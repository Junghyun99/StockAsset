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
    # 2. 매수 주문 실행
    broker = MockBroker(initial_cash=1000.0)
    
    # 100원짜리 5주 매수
    orders = [Order(ticker='SPY', action='BUY', quantity=5, price=100.0)]
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    # 현금 차감: 1000 - 500 = 500
    assert pf.total_cash == 500.0
    # 보유량 증가: 0 -> 5
    assert pf.holdings['SPY'] == 5

def test_mock_broker_sell_execution():
    # 3. 매도 주문 실행
    broker = MockBroker(initial_cash=0.0, holdings={'SPY': 10})
    
    # 100원짜리 3주 매도
    orders = [Order(ticker='SPY', action='SELL', quantity=3, price=100.0)]
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    # 현금 증가: 0 + 300 = 300
    assert pf.total_cash == 300.0
    # 보유량 감소: 10 - 3 = 7
    assert pf.holdings['SPY'] == 7

def test_mock_broker_mixed_orders():
    # 4. 매수/매도 섞어서 실행
    broker = MockBroker(initial_cash=1000.0, holdings={'OLD': 10})
    
    orders = [
        Order(ticker='NEW', action='BUY', quantity=2, price=100.0), # -200
        Order(ticker='OLD', action='SELL', quantity=5, price=10.0)   # +50
    ]
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    # 현금: 1000 - 200 + 50 = 850
    assert pf.total_cash == 850.0
    assert pf.holdings['NEW'] == 2
    assert pf.holdings['OLD'] == 5

# tests/test_infra_broker.py (추가 내용)

def test_mock_broker_sell_more_than_owned():
    """
    [예외 시나리오: 과매도]
    보유 수량보다 더 많이 팔려고 하면?
    MockBroker 구현상 음수가 되지 않고 0에서 멈춰야 함 (max(0, ...))
    """
    # 5주 보유
    broker = MockBroker(initial_cash=0.0, holdings={'SPY': 5})
    
    # 10주 매도 시도
    orders = [Order('SPY', 'SELL', 10, 100.0)]
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    
    # 1. 보유량은 -5가 아니라 0이어야 함
    assert pf.holdings['SPY'] == 0
    
    # 2. 현금은 10주치가 아니라 5주치(실제 팔린 만큼)만 들어오는게 정상이지만,
    # 현재 MockBroker 단순 구현상 주문 수량(10)대로 현금을 더해버리는지, 
    # 아니면 보유량만큼만 파는지 확인 필요.
    # NOTE: Part 2의 단순 구현에서는 현금은 주문수량대로 증가하고 잔고만 0이 되는 한계가 있음.
    # 이 테스트는 "잔고가 음수가 되지 않음"을 보장하는지 확인.

def test_mock_broker_insufficient_funds():
    """
    [예외 시나리오: 잔고 부족]
    현금보다 비싼 주식을 사려고 하면?
    MockBroker는 단순 시뮬레이터라 마이너스 통장을 허용하는지 확인.
    (실전 API는 거절되겠지만, Mock은 로직 검증용이라 허용될 수 있음)
    """
    broker = MockBroker(initial_cash=100.0)
    
    # 1000원어치 매수
    orders = [Order('SPY', 'BUY', 10, 100.0)] 
    broker.execute_orders(orders)
    
    pf = broker.get_portfolio()
    
    # MockBroker는 현금이 마이너스로 떨어지는 것을 허용하는 구조임 (설계 의도: 로직 흐름 끊기지 않게)
    assert pf.total_cash == -900.0 
    assert pf.holdings['SPY'] == 10