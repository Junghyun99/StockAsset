import pytest
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from src.infra.data import YFinanceLoader

# 이 테스트들은 실제 네트워크 호출을 하므로 속도가 느릴 수 있습니다.
# CI/CD 환경이나 네트워크가 없는 곳에서는 실패할 수 있습니다.

@pytest.fixture
def live_loader():
    # 로거는 Mock 처리 (파일 생성 방지)하여 로더만 생성
    return YFinanceLoader(logger=MagicMock())

def test_live_connection_basic(live_loader):
    """
    [Live] 기본 연결 테스트: SPY 데이터와 VIX가 응답하는가?
    """
    df = live_loader.fetch_ohlcv(["SPY"], days=10)
    assert not df.empty
    
    vix = live_loader.fetch_vix()
    assert isinstance(vix, float)
    assert 5.0 < vix < 150.0 # VIX의 현실적인 범위 체크

def test_live_data_recency(live_loader):
    """
    [Live] 데이터 최신성: 받아온 데이터의 마지막 날짜가 최근(휴일 고려 5일 이내)인가?
    (Yahoo Finance가 멈춰있지 않은지 확인)
    """
    df = live_loader.fetch_ohlcv(["SPY"], days=10)
    
    last_date = df.index[-1]
    # timezone 정보가 있을 수 있으므로 제거 후 비교
    if last_date.tzinfo:
        last_date = last_date.tz_localize(None)
        
    now = datetime.now()
    diff = now - last_date
    
    # 주말/연휴 고려하여 5일 이내 데이터면 정상으로 간주
    assert diff.days <= 5, f"Data is too old! Last date: {last_date}"

def test_live_data_sufficiency_for_strategy(live_loader):
    """
    [Live] 데이터 충분성: 전략 계산(MA180, Momentum 12M)을 위한 
    최소 데이터(253개 이상)가 확보되는가?
    """
    # 400일 요청
    df = live_loader.fetch_ohlcv(["SPY"], days=400)
    
    # 거래일 기준 253개 이상이어야 함
    assert len(df) >= 253, f"Not enough data rows: {len(df)}"

def test_live_multi_ticker_structure(live_loader):
    """
    [Live] 다중 종목 요청 시 구조 확인
    """
    tickers = ["SPY", "IEF", "GLD"]
    df = live_loader.fetch_ohlcv(tickers, days=10)
    
    # 1. MultiIndex 여부 확인
    assert isinstance(df.columns, pd.MultiIndex)
    
    # 2. 모든 요청 종목이 컬럼에 포함되어 있는지 확인 (Level 1)
    downloaded_tickers = df.columns.get_level_values(1).unique()
    for t in tickers:
        assert t in downloaded_tickers, f"Ticker {t} is missing in response"

def test_live_data_integrity(live_loader):
    """
    [Live] 데이터 무결성: 최근 데이터에 NaN이나 0원이 없는지 확인
    """
    df = live_loader.fetch_ohlcv(["SPY"], days=30)
    
    # 종가(Close) 컬럼 추출
    close_prices = df['Close']
    
    # 1. 결측치(NaN) 확인
    assert not close_prices.isnull().values.any(), "NaN values found in live data"
    
    # 2. 0원 이하 가격 확인
    assert (close_prices > 0).all(), "Zero or negative prices found in live data" 