import pytest
from src.infra.broker import MockBroker
from src.core.models import Order

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
    orders = [Order(ticker='SPY', action='BUY', quantity=5, price=100.0)]
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
    orders = [Order(ticker='SPY', action='SELL', quantity=3, price=100.0)]
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
        Order(ticker='NEW', action='BUY', quantity=2, price=100.0), 
        Order(ticker='OLD', action='SELL', quantity=5, price=10.0)
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
    보유 수량보다 더 많이 팔려고 하면 0에서 멈추는지 확인
    """
    broker = MockBroker(initial_cash=0.0, holdings={'SPY': 5})
    
    # 10주 매도 시도
    orders = [Order('SPY', 'SELL', 10, 100.0)]
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    
    assert pf.holdings['SPY'] == 0

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
    
    orders = [Order('SPY', 'BUY', 10, 100.0)] 
    executions = broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    
    # 수량이 0으로 조정되어 체결되지 않아야 함 (혹은 Log만 찍고 Skip)
    assert len(executions) == 0
    assert pf.total_cash == 100.0 # 현금 그대로
    assert pf.holdings.get('SPY', 0) == 0



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
        Order('StockA', 'SELL', 10, 100.0),
        Order('StockB', 'BUY', 10, 100.0)
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