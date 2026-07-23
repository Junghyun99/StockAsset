"""공통 execute_cycle의 주문 결과·알림 정책 테스트."""

from unittest.mock import MagicMock

from src.core.engine.base import TradingEngine
from src.core.models import (
    ExecutionStatus,
    MarketData,
    MarketRegime,
    Order,
    OrderAction,
    OrderBatchResult,
    OrderOutcome,
    Portfolio,
    TradeExecution,
    TradeSignal,
)


def _engine(notifier=None):
    broker = MagicMock()
    broker.get_portfolio.return_value = _portfolio()
    repo = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    logger = MagicMock()
    engine = TradingEngine(
        broker=broker,
        repo=repo,
        logger=logger,
        notifier=notifier,
        asset_groups={"A": ["418660.KS"]},
        trading_interval_days=1,
    )
    engine.rebalancer.get_target_params = MagicMock(return_value=(1.0, 0.075))
    return engine, broker, repo, logger


def _market_data():
    return MarketData(
        "2026-07-23", 44000.0, 42000.0, 0.15, 0.05, -0.05, 16.0,
    )


def _portfolio():
    return Portfolio(1_000_000.0, {}, {"418660.KS": 44000.0})


def _execute(engine, signal):
    engine.rebalancer.generate_signal = MagicMock(return_value=signal)
    return engine.execute_cycle(
        _market_data(),
        _portfolio(),
        MarketRegime.BULL,
        1.0,
        [],
        "2026-07-23",
        "2026-07-23",
    )


def test_rejected_order_sends_alert_with_broker_reason_and_no_execution():
    notifier = MagicMock()
    engine, broker, _, _ = _engine(notifier)
    order = Order("418660.KS", OrderAction.BUY, 15, 43930.0)
    broker.execute_orders.return_value = OrderBatchResult([
        OrderOutcome(
            order,
            ExecutionStatus.REJECTED,
            reason="해당종목은 기본예탁금 충족한 계좌만 매수주문가능합니다",
        )
    ])

    _, executions, _, _ = _execute(
        engine, TradeSignal(1.0, [order], "분할매수"),
    )

    assert executions == []
    notifier.send_alert.assert_called_once()
    assert "기본예탁금" in notifier.send_alert.call_args.args[0]


def test_all_intentionally_skipped_orders_do_not_send_alert():
    notifier = MagicMock()
    engine, broker, _, _ = _engine(notifier)
    order = Order("418660.KS", OrderAction.BUY, 15, 43930.0)
    broker.execute_orders.return_value = OrderBatchResult([
        OrderOutcome(order, ExecutionStatus.SKIPPED, reason="spread guard")
    ])

    _, executions, _, _ = _execute(
        engine, TradeSignal(1.0, [order], "분할매수"),
    )

    assert executions == []
    notifier.send_alert.assert_not_called()


def test_only_actual_fills_are_returned_from_execute_cycle():
    notifier = MagicMock()
    engine, broker, _, _ = _engine(notifier)
    filled_order = Order("418660.KS", OrderAction.BUY, 3, 43930.0)
    ordered_order = Order("486290.KS", OrderAction.BUY, 2, 10000.0)
    fill = TradeExecution(
        filled_order.ticker,
        filled_order.action,
        3,
        43930.0,
        0.0,
        "2026-07-23",
        ExecutionStatus.FILLED,
    )
    pending = TradeExecution(
        ordered_order.ticker,
        ordered_order.action,
        2,
        10000.0,
        0.0,
        "2026-07-23",
        ExecutionStatus.ORDERED,
    )
    broker.execute_orders.return_value = OrderBatchResult([
        OrderOutcome(filled_order, ExecutionStatus.FILLED, fill),
        OrderOutcome(ordered_order, ExecutionStatus.ORDERED, pending),
    ])

    _, executions, _, _ = _execute(
        engine,
        TradeSignal(1.0, [filled_order, ordered_order], "mixed"),
    )

    assert executions == [fill]
    notifier.send_alert.assert_called_once()


def test_run_one_cycle_persists_only_actual_fills():
    engine, broker, _, _ = _engine()
    filled_order = Order("418660.KS", OrderAction.BUY, 3, 43930.0)
    pending_order = Order("486290.KS", OrderAction.BUY, 2, 10000.0)
    fill = TradeExecution(
        filled_order.ticker,
        filled_order.action,
        3,
        43930.0,
        0.0,
        "2026-07-23",
        ExecutionStatus.FILLED,
    )
    pending = TradeExecution(
        pending_order.ticker,
        pending_order.action,
        2,
        10000.0,
        0.0,
        "2026-07-23",
        ExecutionStatus.ORDERED,
    )
    engine.collect_data = MagicMock(return_value=MagicMock())
    engine.calculate_indicators = MagicMock(return_value=_market_data())
    engine.analyze_strategy = MagicMock(
        return_value=(MarketRegime.BULL, 1.0, [])
    )
    engine.get_portfolio = MagicMock(return_value=_portfolio())
    engine.rebalancer.generate_signal = MagicMock(return_value=TradeSignal(
        1.0, [filled_order, pending_order], "mixed",
    ))
    broker.execute_orders.return_value = OrderBatchResult([
        OrderOutcome(filled_order, ExecutionStatus.FILLED, fill),
        OrderOutcome(pending_order, ExecutionStatus.ORDERED, pending),
    ])
    engine.persist = MagicMock()

    result = engine.run_one_cycle(MagicMock(), sim_date="2026-07-23")

    assert result.executions == [fill]
    assert result.order_result.outcomes[1].status == ExecutionStatus.ORDERED
    assert engine.persist.call_args.args[2] == [fill]
