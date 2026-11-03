from dataclasses import replace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from src.core.engine import TqqqVrEngine, TradingEngine
from src.core.engine.data_pipeline import CollectedData
from src.core.logic.tqqq_vr import TqqqVrPlanner, VrState
from src.core.models import (Portfolio, OrderAction, OrderBatchResult, OrderOutcome,
                             TradeExecution, ExecutionStatus, MarketData, MarketRegime)


def state(**kwargs):
    return replace(VrState(anchor="2026-01-05", value=8000, budget=1000,
                          closing_pool=2000, initialized=True), **kwargs)


def pf(cash=2000, qty=80, price=100):
    return Portfolio(cash, {"TQQQ": qty}, {"TQQQ": price})


def result(order, status=ExecutionStatus.FILLED, qty=None, fee=5):
    fill = TradeExecution(order.ticker, order.action, order.quantity if qty is None else qty,
                          order.price, fee, "2026-01-06", status)
    return OrderBatchResult([OrderOutcome(order, status, fill)])


def test_initial_cost_and_pool_budget():
    p = TqqqVrPlanner(.0025)
    orders, _, s = p.plan("2026-01-05", 1, pf(10000, 0), VrState())
    assert orders[0].quantity == 79
    assert s.initialized is False
    s = p.settle(s, result(orders[0], fee=19.75))
    assert s.value == 8000
    assert s.closing_pool == 2080.25
    assert s.budget == 1040.125
    assert s.spent == 0
    assert s.initialized


def test_initial_allocation_obeys_known_cap():
    orders, _, _ = TqqqVrPlanner().plan("2026-01-05", .4, pf(10000, 0), VrState())
    assert orders[0].quantity == 39


def test_weekly_rollover_uses_previous_pool_and_does_not_repeat():
    p = TqqqVrPlanner()
    _, _, s = p.plan("2026-01-13", 1, pf(2500), state(spent=900))
    assert (s.value, s.budget, s.spent, s.cycle) == (8200, 1000, 0, 1)
    _, _, again = p.plan("2026-01-14", 1, pf(3000), s)
    assert again.value == 8200
    assert again.budget == 1000


def test_cap_sell_is_daily_and_post_fee_safe():
    p = TqqqVrPlanner()
    orders, _, s = p.plan("2026-01-06", .4, pf(), state())
    o = orders[0]
    assert o.action == OrderAction.SELL
    assert (80-o.quantity)*100 <= .4*(10000-o.quantity*100*.0025)
    after = p.settle(s, result(o))
    assert after.budget == 1000 and after.spent == 0


def test_sell_uses_max_not_sum_and_never_buys_same_day():
    orders, _, _ = TqqqVrPlanner(0).plan("2026-01-06", .4, pf(price=150), state())
    assert len(orders) == 1
    assert orders[0].quantity == 43


def test_buy_capped_by_budget_and_filled_cost_only():
    p = TqqqVrPlanner(.0025)
    orders, _, s = p.plan("2026-01-06", 1, pf(price=50), state())
    assert orders[0].quantity == 19
    partial = p.settle(s, result(orders[0], ExecutionStatus.PARTIAL, qty=3, fee=.375))
    assert partial.spent == 150.375
    assert partial.reconciliation_required
    assert p.plan("2026-01-07", 1, pf(price=50), partial)[0] == []


@pytest.mark.parametrize('status', [ExecutionStatus.ORDERED, ExecutionStatus.ERROR])
def test_unresolved_orders_block_future_days_without_consuming_budget(status):
    p = TqqqVrPlanner()
    orders, _, s = p.plan("2026-01-06", 1, pf(price=50), state())
    s = p.settle(s, result(orders[0], status))
    assert s.spent == 0
    assert s.reconciliation_required


@pytest.mark.parametrize('status', [ExecutionStatus.REJECTED, ExecutionStatus.CANCELLED,
                                    ExecutionStatus.SKIPPED])
def test_no_fill_does_not_spend(status):
    p = TqqqVrPlanner()
    orders, _, s = p.plan("2026-01-06", 1, pf(price=50), state())
    s = p.settle(s, result(orders[0], status))
    assert s.spent == 0 and not s.reconciliation_required


def test_release_does_not_force_rebuy_and_repeat_is_idempotent():
    p = TqqqVrPlanner()
    orders, _, s = p.plan("2026-01-06", 1, pf(6000, 70), state())
    assert not orders
    assert not p.plan("2026-01-06", 1, pf(price=50), s)[0]
    assert not p.plan("2026-01-05", 1, pf(price=50), s)[0]


@pytest.mark.parametrize('portfolio,cap', [(pf(price=0), 1), (pf(cash=-1), 1),
                                         (pf(), float('nan')), (pf(), 0)])
def test_invalid_inputs_do_not_change_state(portfolio, cap):
    old = state()
    orders, _, new = TqqqVrPlanner().plan("2026-01-06", cap, portfolio, old)
    assert not orders and old == new


def test_uninitialized_existing_holdings_require_state():
    assert not TqqqVrPlanner().plan("2026-01-05", 1, pf(), VrState())[0]


def engine(repo=None):
    repo = repo or Mock()
    repo.load_last_regime.return_value = None
    repo.load_strategy_state.return_value = {}
    logger = Mock()
    logger.get_captured_logs.return_value = []
    return TqqqVrEngine(broker=Mock(), repo=repo, logger=logger)


def test_volatility_uses_close_prior_20_returns_only():
    e = engine()
    e.cycle_date = "2026-02-04"
    idx = pd.bdate_range(end=e.cycle_date, periods=30)
    prices = 100*np.cumprod(1+np.tile([.01, -.02], 15))
    df = pd.DataFrame({'Close': prices*2, 'Adj Close': np.full(30, 100.0)}, index=idx)
    data = CollectedData({'reference': df}, 20, e.data_spec())
    e.calculate_strategy_indicators(data)
    expected = df['Close'].iloc[:-1].tail(21).pct_change().dropna().std()*np.sqrt(252)
    assert e.realized_vol == pytest.approx(expected)
    df.iloc[-1] = 1000000
    assert e.calculate_strategy_indicators(data) == pytest.approx(min(1, .3/(3*expected)))
    # A provider already excluding today must yield exactly the same cap.
    old = CollectedData({'reference': df.iloc[:-1]}, 20, e.data_spec())
    assert e.calculate_strategy_indicators(old) == pytest.approx(e.weight_cap)


def test_missing_close_blocks_instead_of_using_adjusted_prices():
    e = engine(); e.cycle_date = '2026-02-04'
    data = CollectedData({'reference': pd.DataFrame({'Adj Close': [100]*30},
                          index=pd.bdate_range(end=e.cycle_date, periods=30))},20,e.data_spec())
    e.calculate_strategy_indicators(data)
    assert e.analyze_strategy(None)[2] == ['qqq_volatility_20d']


def test_template_execution_persists_state_and_restores_for_next_day():
    e = engine(); e.weight_cap=1; e.realized_vol=.1
    e.broker.execute_orders.side_effect = lambda orders: result(orders[0], fee=19.75)
    e.broker.get_portfolio.return_value = pf(2080.25,79)
    m = MarketData('2026-01-02',100,100,.1,0,0,20)
    e.execute_cycle(m,pf(10000,0),MarketRegime.SIDEWAYS,1,[], '2026-01-05','2026-01-05')
    key,saved=e.repo.save_strategy_state.call_args.args
    assert key == 'tqqq_vr'
    assert saved['anchor']=='2026-01-05'  # execution date, not indicator date
    assert saved['initialized']
    assert VrState.from_dict(saved) == e.vr_state
    e.broker.execute_orders.reset_mock()
    e.execute_cycle(m,pf(2080.25,79),MarketRegime.SIDEWAYS,1,[], '2026-01-05','2026-01-05')
    e.broker.execute_orders.assert_not_called()
    assert TqqqVrEngine.run_one_cycle is TradingEngine.run_one_cycle


def test_close_only_cache_is_supported():
    e = engine()
    e.cycle_date = '2026-02-04'
    frame = pd.DataFrame({'Close': [100.0]*30},
                         index=pd.bdate_range(end=e.cycle_date, periods=30))
    data = CollectedData({'reference': frame}, 20, e.data_spec())
    assert e.calculate_strategy_indicators(data) == 1.0
    assert e.analyze_strategy(None)[2] == []
