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