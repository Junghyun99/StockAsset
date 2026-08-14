# tests/test_core_engine_domestic_qld_dip_buy.py
"""DomesticQldDipBuyEngine 단위 테스트."""
from unittest.mock import MagicMock, patch

import pandas as pd

from src.core.engine.domestic_qld_dip_buy import (
    DomesticQldDipBuyEngine, DomesticQldDipPlanner,
    LEVER_TICKER, INCOME_TICKER,
)
from src.core.engine import TradingEngine, _ENGINE_REGISTRY, _ENGINE_BACKTEST, _ENGINE_MARKET_TYPES
from src.core.engine.data_pipeline import CollectedData
from src.core.logic.sso_dip_planner import SsoDipPlanner
from src.core.logic.sso_dip_planner import SignalLevel, SsoDipState
from src.core.logic.sso_dip_signals import SsoDipSignals
from src.core.models import (
    ExecutionStatus,
    MarketData,
    MarketRegime,
    Order,
    OrderAction,
    OrderBatchResult,
    OrderOutcome,
    Portfolio,
    StrategyDecision,
    TradeSignal,
    TradeExecution,
)


def _build_engine(notifier=None):
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = None
    repo.load_last_regime.return_value = None
    repo.load_strategy_state.return_value = {}
    broker.get_portfolio.return_value = Portfolio(
        total_cash=1_000_000.0,
        holdings={LEVER_TICKER: 0, INCOME_TICKER: 0},
        current_prices={LEVER_TICKER: 15000.0, INCOME_TICKER: 10000.0},
    )
    broker.fetch_current_prices.return_value = {}

    with patch('src.core.engine.base.IndicatorCalculator') as MockCalc, \
         patch('src.core.engine.base.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.base.VolatilityTargeter') as MockTargeter, \
         patch('src.core.engine.base.Rebalancer') as MockRebalancer:

        analyzer = MockAnalyzer.return_value
        analyzer._prev_regime = None
        rebalancer = MockRebalancer.return_value
        rebalancer.get_target_params.return_value = (0.4, 0.075)

        engine = DomesticQldDipBuyEngine(
            broker=broker, repo=repo, logger=logger,
            notifier=notifier,
            trading_interval_days=1,
        )

    return engine, {
        "broker": broker, "repo": repo, "logger": logger,
        "data_provider": data_provider,
    }


class TestClassStructure:
    def test_is_trading_engine_subclass(self):
        assert issubclass(DomesticQldDipBuyEngine, TradingEngine)

    def test_registered_in_registry(self):
        names = [name for name, _ in _ENGINE_REGISTRY]
        assert "DomesticQldDipBuyEngine" in names

    def test_backtest_disabled(self):
        assert _ENGINE_BACKTEST.get("DomesticQldDipBuyEngine") is False

    def test_market_type_domestic(self):
        assert _ENGINE_MARKET_TYPES.get("DomesticQldDipBuyEngine") == "domestic"

    def test_asset_groups(self):
        assert DomesticQldDipBuyEngine.ASSET_GROUPS == {
            "A": [LEVER_TICKER], "B": [INCOME_TICKER],
        }

    def test_all_tickers(self):
        engine, _ = _build_engine()
        assert set(engine.all_tickers) == {LEVER_TICKER, INCOME_TICKER}


class TestDomesticQldDipPlanner:
    def test_is_sso_planner_subclass(self):
        assert issubclass(DomesticQldDipPlanner, SsoDipPlanner)

    def test_ticker_names(self):
        planner = DomesticQldDipPlanner()
        assert planner.SSO_TICKER == LEVER_TICKER
        assert planner.SPYI_TICKER == INCOME_TICKER

    def test_sell_condition_overridden(self):
        planner = DomesticQldDipPlanner()
        assert planner._sell_condition == {"rsi": 80.0, "deviation": 0.35}

    def test_sell_condition_differs_from_base(self):
        base = SsoDipPlanner()
        domestic = DomesticQldDipPlanner()
        assert domestic._sell_condition["rsi"] > base._sell_condition["rsi"]
        assert domestic._sell_condition["deviation"] > base._sell_condition["deviation"]


class TestStateManagement:
    def test_loads_state_on_init(self):
        engine, mocks = _build_engine()
        mocks["repo"].load_strategy_state.assert_called_with("domestic_qld_dip_buy")

    def test_rejected_buy_alerts_and_does_not_consume_tranche(self):
        notifier = MagicMock()
        engine, mocks = _build_engine(notifier)
        order = Order(LEVER_TICKER, OrderAction.BUY, 15, 43930.0)
        proposed_state = SsoDipState(
            level=SignalLevel.BUY_STAGE_1,
            tranche_total=10,
            tranche_completed=0,
            tranche_amount=700_000.0,
        )
        engine.build_strategy_decision = MagicMock(return_value=StrategyDecision(
            signal=TradeSignal(1.0, [order], "BUY_STAGE_1 분할매수"),
            label="DomesticQldDipBuy",
            is_rebalancing=True,
            state_key=engine.STATE_KEY,
            proposed_state=proposed_state,
        ))
        mocks["broker"].execute_orders.return_value = OrderBatchResult([
            OrderOutcome(
                order,
                ExecutionStatus.REJECTED,
                reason="해당종목은 기본예탁금 충족한 계좌만 매수주문가능합니다",
            )
        ])

        _, executions, _, _ = engine.execute_cycle(
            MarketData(
                "2026-07-23", 747.41, 700.0, 0.1, 0.1, -0.016, 16.64,
            ),
            mocks["broker"].get_portfolio.return_value,
            MarketRegime.BULL,
            1.0,
            [],
            "2026-07-23",
            "2026-07-23",
        )

        assert executions == []
        assert engine.dip_state.tranche_completed == 0
        mocks["repo"].save_strategy_state.assert_called_once()
        saved_state = mocks["repo"].save_strategy_state.call_args.args[1]
        assert saved_state["tranche_completed"] == 0
        notifier.send_alert.assert_called_once()
        assert "기본예탁금" in notifier.send_alert.call_args.args[0]


class TestForcedStage:
    def test_forced_stage_filled_order_commits_first_tranche(self):
        engine, mocks = _build_engine()
        engine.dip_signals = SsoDipSignals(
            date="2026-08-14", weekly_rsi=55.0, ma200_deviation=0.02,
            price=43_000.0, ma200=42_000.0, mdd_200=0.0,
        )
        engine.force_buy_stage(1, "2026-07-30 missed entry")

        def fill_all(orders):
            return [
                TradeExecution(
                    ticker=order.ticker, action=order.action,
                    quantity=order.quantity, price=order.price, fee=0.0,
                    date="2026-08-14 10:00:00", status=ExecutionStatus.FILLED,
                )
                for order in orders
            ]

        mocks["broker"].execute_orders.side_effect = fill_all
        signal, executions, _, _ = engine.execute_cycle(
            MarketData("2026-08-14", 1, 1, 1, 1, 1, 1),
            mocks["broker"].get_portfolio.return_value,
            MarketRegime.BULL,
            1.0,
            [],
            "2026-08-14",
            "2026-08-14",
        )

        assert "수동 강제 Stage 1 진입" in signal.reason
        assert any(execution.ticker == LEVER_TICKER for execution in executions)
        assert engine.dip_state.level == SignalLevel.BUY_STAGE_1
        assert engine.dip_state.tranche_completed == 1
        saved_state = mocks["repo"].save_strategy_state.call_args.args[1]
        assert saved_state["tranche_completed"] == 1

    def test_forced_stage_overrides_raw_signal_once(self):
        engine, mocks = _build_engine()
        engine.dip_signals = SsoDipSignals(
            date="2026-08-14", weekly_rsi=55.0, ma200_deviation=0.02,
            price=43_000.0, ma200=42_000.0, mdd_200=0.0,
        )
        engine.force_buy_stage(1, "2026-07-30 missed entry")

        decision = engine.build_strategy_decision(
            MarketData("2026-08-14", 1, 1, 1, 1, 1, 1),
            mocks["broker"].get_portfolio.return_value,
            MarketRegime.BULL,
            1.0,
        )

        assert decision.proposed_state.level == SignalLevel.BUY_STAGE_1
        assert "수동 강제 Stage 1 진입: 2026-07-30 missed entry" in decision.signal.reason

        engine.dip_state = decision.proposed_state
        next_decision = engine.build_strategy_decision(
            MarketData("2026-08-15", 1, 1, 1, 1, 1, 1),
            mocks["broker"].get_portfolio.return_value,
            MarketRegime.BULL,
            1.0,
        )

        assert next_decision.proposed_state.level == SignalLevel.BUY_STAGE_1
        assert "수동 강제" not in next_decision.signal.reason


class TestDecisionFactors:
    def test_includes_trailing_mdd(self):
        engine, mocks = _build_engine()
        engine.dip_signals = SsoDipSignals(
            date="2026-08-13", weekly_rsi=45.0, ma200_deviation=0.0,
            price=43_200.0, ma200=39_215.0, mdd_200=-0.21,
        )

        factors = engine.decision_factors(
            MarketData("2026-08-13", 1, 1, 1, 1, 1, 1),
            MarketRegime.BULL,
            1.0,
            TradeSignal(1.0, [], "test"),
            mocks["broker"].get_portfolio.return_value,
        )

        mdd = next(factor for factor in factors if factor.key == "mdd_200")
        assert mdd.value == -0.21
        assert mdd.threshold == -0.20


class TestCollectData:
    def test_fetches_lever_and_spy_ohlcv(self):
        engine, mocks = _build_engine()
        engine.collect_data(mocks["data_provider"])
        calls = mocks["data_provider"].fetch_ohlcv.call_args_list
        tickers_called = [c[0][0] for c in calls]
        assert ["SPY"] in tickers_called
        assert [LEVER_TICKER] in tickers_called
        assert len(calls) == 2

    def test_logs_invalid_indicator_data_diagnostics(self):
        engine, mocks = _build_engine()
        frame = pd.DataFrame(
            {"Close": [100.0] * 199},
            index=pd.date_range("2026-01-01", periods=199, freq="D"),
        )
        collected = CollectedData(
            frames={"signal": frame}, vix=20.0, spec=engine.data_spec(),
        )

        engine.calculate_strategy_indicators(collected)

        mocks["logger"].warning.assert_called_once()
        message, fields, rows, last_date = mocks["logger"].warning.call_args.args
        assert "Invalid strategy indicators" in message
        assert "mdd_200" in fields
        assert rows == 199
        assert last_date.startswith("2026-07-18")
