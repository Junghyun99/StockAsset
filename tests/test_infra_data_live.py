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

# ... (기존 코드 생략) ...

def test_live_invalid_ticker_handling(live_loader):
    """
    [Live] 존재하지 않는 티커 요청 시 ValueError가 발생하는지 확인
    (yfinance는 에러를 내지 않고 빈 df를 주는 경우가 많음 -> 로더가 이를 잡아야 함)
    """
    invalid_ticker = "THIS_IS_FAKE_TICKER_123"
    
    # 로더 코드에서 if df.empty: raise ValueError(...) 로직이 동작하는지 검증
    with pytest.raises(ValueError, match="No data fetched"):
        live_loader.fetch_ohlcv([invalid_ticker], days=5)

def test_live_diverse_asset_classes(live_loader):
    """
    [Live] 주식 외에 채권, 원자재, 현금성 자산 데이터도 잘 가져오는지 확인
    전략 구성 종목: IEF(채권), PDBC(원자재), SHV(단기채)
    """
    diverse_tickers = ["IEF", "PDBC", "SHV"]
    
    df = live_loader.fetch_ohlcv(diverse_tickers, days=5)
    
    # 1. 데이터가 비어있지 않아야 함
    assert not df.empty
    
    # 2. 모든 티커가 컬럼에 존재해야 함
    downloaded = df.columns.get_level_values(1).unique()
    for t in diverse_tickers:
        assert t in downloaded, f"Failed to fetch asset class ticker: {t}"

def test_live_column_schema(live_loader):
    """
    [Live] 데이터프레임이 표준 OHLCV 컬럼을 모두 가지고 있는지 확인
    """
    df = live_loader.fetch_ohlcv(["SPY"], days=5)
    
    # 1. 단일 인덱스 변환 확인 (fetch_ohlcv 내부 로직)
    # 로더가 단일 종목일 때 level 1을 날려버리는지 확인
    assert "Close" in df.columns
    
    # 2. 필수 컬럼 확인
    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in required_cols:
        assert col in df.columns, f"Missing required column: {col}"

def test_live_vix_sanity_check(live_loader):
    """
    [Live] VIX 지수가 현실적인 범위 내의 값인지 확인 (데이터 오염 방지)
    """
    vix = live_loader.fetch_vix()
    
    print(f"Current Live VIX: {vix}")
    
    # 1. 타입 확인
    assert isinstance(vix, float)
    
    # 2. 범위 확인 (역대 최저 ~9, 역대 최고 ~80)
    # 안전하게 5 ~ 150 사이인지 확인
    assert 5.0 < vix < 150.0, f"VIX value {vix} seems abnormal!"