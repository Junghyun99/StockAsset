# tests/test_backtest_components.py
import pytest
import pandas as pd
import numpy as np
from src.backtest.components import BacktestDataLoader, BacktestBroker
from src.core.models import Order

@pytest.fixture
def mock_full_data():
    """10일치 가짜 데이터 생성"""
    dates = pd.date_range(start="2024-01-01", periods=10)
    # 가격: 100, 110, ... 190
    prices = np.linspace(100, 190, 10).reshape(-1, 1) 
    
    # MultiIndex 구조 흉내 (Close, SPY)
    columns = pd.MultiIndex.from_product([['Close'], ['SPY']])
    df = pd.DataFrame(prices, index=dates, columns=columns)
    
    # VIX 데이터 (단일 인덱스)
    vix_df = pd.DataFrame({'Close': [20.0]*10}, index=dates)
    
    return df, vix_df

def test_loader_time_travel_slicing(mock_full_data):
    """
    [Loader] 특정 날짜로 설정했을 때, 그 이전 데이터만 가져오는지 확인
    """
    full_df, full_vix = mock_full_data
    loader = BacktestDataLoader(full_df, full_vix)
    
    # 1. 2024-01-05 (5번째 날)로 시점 설정
    target_date = pd.Timestamp("2024-01-05")
    loader.set_date(target_date)
    
    # 2. 과거 3일치 데이터 요청
    df = loader.fetch_ohlcv(["SPY"], days=3)
    
    # 3. 검증
    # 1월 5일 포함, 그 전 3개 행이 나와야 함 (3, 4, 5일)
    assert len(df) == 3
    assert df.index[-1] == target_date
    assert df.iloc[-1].item() == 140.0 # 5번째 값 (100, 110, 120, 130, 140)

def test_broker_price_injection():
    """
    [Broker] 외부에서 주입한 가격이 체결에 반영되는지 확인
    """
    broker = BacktestBroker(initial_cash=10000.0)
    
    # 1. 가격 주입 (SPY = 200달러)
    broker.set_prices({'SPY': 200.0})
    
    # 2. 현재가 조회 확인
    prices = broker.fetch_current_prices(['SPY'])
    assert prices['SPY'] == 200.0
    
    # 3. 매수 주문 실행
    # Order 객체의 price는 '예상가'일 뿐, Broker는 주입된 '200.0'으로 체결해야 함
    order = Order('SPY', 'BUY', 10, 150.0) # 주문서엔 150이라 적혀있어도
    executions = broker.execute_orders([order])
    
    # 4. 체결 가격 검증 (MockBroker 로직상 슬리피지 1% 적용됨 -> 202.0)
    exec_price = executions[0].price
    assert exec_price == pytest.approx(202.0) 
    
    # 잔고 차감 확인: 10000 - (202 * 10 + 수수료)
    assert broker.get_portfolio().total_cash < 8000.0