"""주문 요청과 체결을 분리하는 공통 결과 계약 테스트."""

from src.core.models import (
    ExecutionStatus,
    Order,
    OrderAction,
    OrderBatchResult,
    OrderOutcome,
    TradeExecution,
)
from src.infra.broker.kis_base import KisBrokerCommon
from src.infra.broker.mock import MockBroker


def _order(ticker: str = "418660.KS") -> Order:
    return Order(ticker, OrderAction.BUY, 10, 43000.0)


def _execution(order: Order, status: ExecutionStatus, quantity: int = 10):
    return TradeExecution(
        order.ticker,
        order.action,
        quantity,
        order.price,
        0.0,
        "2026-07-23",
        status,
        reason="broker response",
    )


def test_batch_keeps_one_outcome_per_requested_order():
    first = _order("A")
    second = _order("B")
    batch = OrderBatchResult(
        outcomes=[
            OrderOutcome(first, ExecutionStatus.FILLED, _execution(first, ExecutionStatus.FILLED)),
            OrderOutcome(second, ExecutionStatus.REJECTED, reason="deposit required"),
        ],
    )

    assert [outcome.order for outcome in batch.outcomes] == [first, second]
    assert batch.total == 2


def test_actual_executions_include_only_filled_and_partial():
    orders = [_order(status) for status in ("FILLED", "PARTIAL", "ORDERED", "REJECTED")]
    statuses = [
        ExecutionStatus.FILLED,
        ExecutionStatus.PARTIAL,
        ExecutionStatus.ORDERED,
        ExecutionStatus.REJECTED,
    ]
    batch = OrderBatchResult(
        [
            OrderOutcome(order, status, _execution(order, status, quantity=index + 1))
            for index, (order, status) in enumerate(zip(orders, statuses))
        ]
    )

    assert [execution.status for execution in batch.actual_executions] == [
        ExecutionStatus.FILLED,
        ExecutionStatus.PARTIAL,
    ]


def test_warning_outcomes_exclude_intentional_skips():
    statuses = [
        ExecutionStatus.SKIPPED,
        ExecutionStatus.ORDERED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.REJECTED,
        ExecutionStatus.ERROR,
    ]
    batch = OrderBatchResult(
        [OrderOutcome(_order(status.value), status, reason=status.value) for status in statuses]
    )

    assert [outcome.status for outcome in batch.warning_outcomes] == statuses[1:]
    assert batch.has_warnings is True


def test_all_skipped_batch_is_not_warning():
    batch = OrderBatchResult(
        [OrderOutcome(_order("A"), ExecutionStatus.SKIPPED, reason="spread guard")]
    )

    assert batch.actual_executions == []
    assert batch.warning_outcomes == []
    assert batch.has_warnings is False


def test_mock_broker_reports_zero_affordable_quantity_as_skipped():
    broker = MockBroker(initial_cash=10.0)
    order = Order("SPY", OrderAction.BUY, 5, 100.0)

    result = broker.execute_orders([order])

    assert result.total == 1
    assert result.outcomes[0].status == ExecutionStatus.SKIPPED
    assert result.actual_executions == []
    assert result.has_warnings is False


def test_mock_broker_reports_adjusted_quantity_as_partial():
    broker = MockBroker(initial_cash=250.0)
    order = Order("SPY", OrderAction.BUY, 5, 100.0)

    result = broker.execute_orders([order])

    assert result.total == 1
    assert result.outcomes[0].status == ExecutionStatus.PARTIAL
    assert result.actual_executions[0].quantity < order.quantity
    assert result.has_warnings is True


def test_kis_common_converts_missing_adapter_result_to_error(monkeypatch):
    broker = object.__new__(KisBrokerCommon)
    broker.logger = __import__("unittest.mock").mock.MagicMock()
    broker._send_order_and_wait = __import__("unittest.mock").mock.MagicMock(
        return_value=None
    )
    order = Order("418660.KS", OrderAction.SELL, 3, 43000.0)
    monkeypatch.setattr("src.infra.broker.kis_base.time.sleep", lambda _: None)

    result = broker.execute_orders([order])

    assert result.total == 1
    assert result.outcomes[0].status == ExecutionStatus.ERROR
    assert result.has_warnings is True
