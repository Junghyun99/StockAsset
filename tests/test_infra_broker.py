import pytest
from src.infra.broker import MockBroker
from src.core.models import Order, OrderAction

def test_mock_broker_initialization():
    # 1. 초기 상태 확인
    broker = MockBroker(initial_cash=5000.0, holdings={'SPY': 10})
    pf = broker.get_portfolio()
    
    assert pf.total_cash == 5000.0
    assert pf.holdings['SPY'] == 10

def test_mock_broker_buy_execution():
    # 2. 매수 주문 실행 (슬리피지 1%, 수수료 0.1% 반영)
    broker = MockBroker(initial_cash=1000.0)
    
    # 100원짜리 5주 매수
    orders = [Order(ticker='SPY', action=OrderAction.BUY, quantity=5, price=100.0)]
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    
    # 예상 비용 계산:
    # 체결가: 100 * 1.01 = 101.0
    # 금액: 101 * 5 = 505.0
    # 수수료: 505 * 0.001 = 0.505
    # 총비용: 505.505
    # 잔고: 1000 - 505.505 = 494.495
    
    assert pf.total_cash == pytest.approx(494.495)
    # 보유량 증가: 0 -> 5
    assert pf.holdings['SPY'] == 5

def test_mock_broker_sell_execution():
    # 3. 매도 주문 실행 (슬리피지 -1%, 수수료 0.1% 반영)
    broker = MockBroker(initial_cash=0.0, holdings={'SPY': 10})
    
    # 100원짜리 3주 매도
    orders = [Order(ticker='SPY', action=OrderAction.SELL, quantity=3, price=100.0)]
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    
    # 예상 수익 계산:
    # 체결가: 100 * 0.99 = 99.0
    # 금액: 99 * 3 = 297.0
    # 수수료: 297 * 0.001 = 0.297
    # 입금액: 297 - 0.297 = 296.703
    
    assert pf.total_cash == pytest.approx(296.703)
    # 보유량 감소: 10 - 3 = 7
    assert pf.holdings['SPY'] == 7

def test_mock_broker_mixed_orders():
    # 4. 매수/매도 섞어서 실행
    broker = MockBroker(initial_cash=1000.0, holdings={'OLD': 10})
    
    orders = [
        Order(ticker='NEW', action=OrderAction.BUY, quantity=2, price=100.0), 
        Order(ticker='OLD', action=OrderAction.SELL, quantity=5, price=10.0)
    ]
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    
    # 비용(NEW): (100*1.01*2) + 수수료(0.1%) = 202 + 0.202 = 202.202
    # 수익(OLD): (10*0.99*5) - 수수료(0.1%) = 49.5 - 0.0495 = 49.4505
    # 최종: 1000 - 202.202 + 49.4505 = 847.2485
    
    assert pf.total_cash == pytest.approx(847.2485)
    assert pf.holdings['NEW'] == 2
    assert pf.holdings['OLD'] == 5

def test_mock_broker_sell_more_than_owned():
    """
    [예외 시나리오: 과매도]
    보유 수량보다 더 많이 팔려고 하면 실제 보유량만 체결되어야 함.
    현금은 실제 체결된 수량(5주)만큼만 지급되어야 한다 (10주분 지급 금지).
    """
    broker = MockBroker(initial_cash=0.0, holdings={'SPY': 5})

    # 10주 매도 시도 (보유는 5주)
    orders = [Order('SPY', OrderAction.SELL, 10, 100.0)]
    broker.execute_orders(orders)

    pf = broker.get_portfolio()

    # 보유량은 0으로 감소 (5주 전량 매도)
    assert pf.holdings['SPY'] == 0

    # 현금은 실제 체결 수량(5주)만큼만 지급되어야 함
    # 체결가: 100 * 0.99 = 99.0
    # 금액: 99.0 * 5 = 495.0
    # 수수료: 495.0 * 0.001 = 0.495
    # 입금액: 495.0 - 0.495 = 494.505
    assert pf.total_cash == pytest.approx(494.505)


def test_mock_broker_sell_more_than_owned_execution_qty():
    """
    [예외 시나리오: 과매도 체결 수량]
    보유 수량보다 더 많이 팔려고 할 때 TradeExecution의 quantity가
    실제 체결된 수량(보유량)으로 기록되어야 함.
    """
    broker = MockBroker(initial_cash=0.0, holdings={'SPY': 5})

    orders = [Order('SPY', OrderAction.SELL, 10, 100.0)]
    executions = broker.execute_orders(orders)

    assert len(executions) == 1
    # 실제 체결 수량은 보유량인 5주여야 함 (주문 수량 10주가 아님)
    assert executions[0].quantity == 5

def test_mock_broker_insufficient_funds():
    """
    [예외 시나리오: 잔고 부족]
    현금 부족 시 수량 조정 로직 확인
    """
    broker = MockBroker(initial_cash=100.0)
    
    # 100원짜리 10주 매수 시도 (총 1000원 필요) -> 현금 100원밖에 없음
    # Broker 내부 로직: 
    # Budget = 100 * 0.98 = 98.0
    # Price = 100 * 1.01 = 101.0
    # Max Qty = int(98 / 101) = 0
    
    orders = [Order('SPY', OrderAction.BUY, 10, 100.0)] 
    executions = broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    
    # 수량이 0으로 조정되어 체결되지 않아야 함 (혹은 Log만 찍고 Skip)
    assert len(executions) == 0
    assert pf.total_cash == 100.0 # 현금 그대로
    assert pf.holdings.get('SPY', 0) == 0



def test_mock_broker_order_not_mutated_on_qty_adjustment():
    """
    [버그 방지: #71] 잔고 부족으로 수량 조정 시 원본 Order 객체가 변경되지 않아야 함.
    MockBroker가 order.quantity를 직접 수정하면 호출자가 보유한 동일 객체 참조도 오염된다.
    """
    broker = MockBroker(initial_cash=500.0)

    # 500원으로 100원짜리 10주 매수 시도 -> 잔고 부족으로 수량 조정 필요
    original_order = Order(ticker='SPY', action=OrderAction.BUY, quantity=10, price=100.0)
    original_qty = original_order.quantity  # 수정 전 수량 저장

    broker.execute_orders([original_order])

    # 원본 Order 객체의 quantity는 변하지 않아야 함
    assert original_order.quantity == original_qty, (
        f"원본 Order.quantity가 변경됨: {original_qty} -> {original_order.quantity}"
    )


def test_mock_broker_order_not_mutated_when_sufficient_funds():
    """
    [버그 방지: #71] 잔고가 충분할 때도 원본 Order 객체가 변경되지 않아야 함.
    """
    broker = MockBroker(initial_cash=10000.0)

    original_order = Order(ticker='SPY', action=OrderAction.BUY, quantity=5, price=100.0)
    original_qty = original_order.quantity

    broker.execute_orders([original_order])

    # 정상 체결 후에도 원본 quantity 불변
    assert original_order.quantity == original_qty


def test_mock_broker_tradesignal_orders_integrity():
    """
    [버그 방지: #71] TradeSignal.orders 목록의 Order 객체들이
    execute_orders 호출 후에도 원래 수량을 유지해야 함.
    """
    from src.core.models import TradeSignal

    broker = MockBroker(initial_cash=150.0)

    # 잔고: 150원, 주문: 100원짜리 10주 (총 1000원 필요) -> 수량 조정됨
    order = Order(ticker='SPY', action=OrderAction.BUY, quantity=10, price=100.0)
    signal = TradeSignal(target_exposure=0.8, orders=[order], reason="테스트")

    original_qty_in_signal = signal.orders[0].quantity

    broker.execute_orders(signal.orders)

    # TradeSignal 내 Order 수량이 변하지 않아야 함
    assert signal.orders[0].quantity == original_qty_in_signal


def test_mock_broker_no_print_on_execute(capsys):
    """
    [이슈 #69] logger 미전달 시 MockBroker.execute_orders()가 콘솔에 아무것도 출력하지 않아야 함.
    백테스트 중 수만 건의 주문이 조용히 처리되어야 한다.
    """
    broker = MockBroker(initial_cash=1000.0, holdings={'SPY': 5})
    orders = [
        Order(ticker='SPY', action=OrderAction.SELL, quantity=3, price=100.0),
        Order(ticker='SPY', action=OrderAction.BUY, quantity=2, price=100.0),
    ]
    broker.execute_orders(orders)

    captured = capsys.readouterr()
    assert captured.out == "", f"예상치 못한 stdout 출력: {captured.out!r}"
    assert captured.err == "", f"예상치 못한 stderr 출력: {captured.err!r}"


def test_mock_broker_qty_adjustment_uses_logger_warning():
    """
    [이슈 #69] 잔고 부족으로 수량 조정 시 ILogger.warning()이 호출되어야 함.
    """
    from unittest.mock import MagicMock
    from src.core.interfaces import ILogger

    mock_logger = MagicMock(spec=ILogger)
    broker = MockBroker(initial_cash=100.0, logger=mock_logger)

    # 잔고 부족으로 수량 조정이 필요한 주문
    orders = [Order(ticker='SPY', action=OrderAction.BUY, quantity=10, price=100.0)]
    broker.execute_orders(orders)

    warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
    assert any("Qty Adjusted" in call for call in warning_calls), \
        "수량 조정 시 ILogger.warning()이 호출되어야 함"


def test_mock_broker_cash_recycling_logic():
    """
    [심화] 매도 대금이 즉시 매수 재원으로 활용되는지 검증
    상황: 현금 0원, A주식 100만원어치 보유.
    주문: A 전량 매도 -> B 100만원어치 매수.
    기대: A 매도 후 현금이 100만원이 되고, 그 돈으로 B를 사서 최종 현금은 0원, B 보유량이 늘어야 함.
    """
    # 1. 초기 설정: 현금 0, StockA 10주($100)
    broker = MockBroker(initial_cash=0.0, holdings={'StockA': 10})
    
    # 2. 주문 목록: Sell A -> Buy B
    # (Rebalancer가 정렬해준 순서대로 들어온다고 가정)
    orders = [
        Order('StockA', OrderAction.SELL, 10, 100.0),
        Order('StockB', OrderAction.BUY, 10, 100.0)
    ]
    
    # 3. 실행
    broker.execute_orders(orders)
    pf = broker.get_portfolio()
    
    # 4. 검증
    # StockA는 팔았으니 0
    assert pf.holdings.get('StockA', 0) == 0
    
    # StockB는 샀으니 10 (이게 핵심! 매도 대금이 안 들어왔으면 0일 것임)
    assert pf.holdings.get('StockB', 0) >= 9
    
    # 현금 흐름: 0 -> +1000(매도) -> -1000(매수) -> 0 (수수료/슬리피지 제외 시)
    # 실제로는 MockBroker 수수료 로직 때문에 약간 차감됨, 대략 0 근처인지 확인
    assert pf.total_cash < 100.0 # 잔돈만 남아야 함