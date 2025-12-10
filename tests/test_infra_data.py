import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from src.infra.data import YFinanceLoader

@pytest.fixture
def mock_yf_download():
    """yfinance.download 함수를 Mocking"""
    with patch('src.infra.data.yf.download') as mock:
        yield mock
@pytest.fixture
def mock_logger():
    """가짜 로거 생성"""
    return MagicMock()

def test_fetch_ohlcv_success(mock_yf_download,mock_logger):
    # 1. 정상 데이터 반환 시나리오
    mock_df = pd.DataFrame({'Close': [100, 101, 102]})
    mock_yf_download.return_value = mock_df
    
    loader = YFinanceLoader(mock_logger)
    df = loader.fetch_ohlcv(['SPY'], days=10)
    
    assert not df.empty
    assert len(df) == 3
    # yfinance가 올바른 인자로 호출되었는지 검증
    mock_yf_download.assert_called_once()
    args, kwargs = mock_yf_download.call_args
    assert args[0] == ['SPY']
    assert kwargs['period'] == '10d'

def test_fetch_ohlcv_empty_data(mock_yf_download,mock_logger):
    # 2. 데이터가 비어있을 때 (예외 발생)
    mock_yf_download.return_value = pd.DataFrame() # 빈 DF
    
    loader = YFinanceLoader(mock_logger)
    
    with pytest.raises(ValueError, match="No data fetched"):
        loader.fetch_ohlcv(['SPY'])

def test_fetch_vix_success(mock_yf_download,mock_logger):
    # 3. VIX 조회 성공
    mock_df = pd.DataFrame({'Close': [15.5, 16.0, 17.5]})
    mock_yf_download.return_value = mock_df
    
    loader = YFinanceLoader(mock_logger)
    vix = loader.fetch_vix()
    
    assert vix == 17.5 # 마지막 값

def test_fetch_vix_failure_fallback(mock_yf_download,mock_logger):
    # 4. VIX 조회 실패 시 안전값(20.0) 반환 확인
    mock_yf_download.return_value = pd.DataFrame() # 빈 DF
    
    loader = YFinanceLoader(mock_logger)
    vix = loader.fetch_vix()
    
    assert vix == 20.0

# ... (기존 임포트 및 Fixture 생략) ...

def test_fetch_ohlcv_single_ticker_flattening(mock_yf_download, mock_logger):
    """
    [구조] 단일 종목 요청 시, yfinance가 MultiIndex를 반환하더라도
    Loader가 이를 Single Index로 깔끔하게 펴주는지(Flatten) 확인
    """
    # 1. MultiIndex 구조의 가짜 데이터 생성 (Price, Ticker)
    # yfinance 최신 버전은 단일 종목도 이렇게 줄 때가 있음
    columns = pd.MultiIndex.from_product([['Close', 'Open'], ['SPY']])
    mock_df = pd.DataFrame([[100, 102], [101, 103]], columns=columns)
    
    mock_yf_download.return_value = mock_df
    
    loader = YFinanceLoader(mock_logger)
    df = loader.fetch_ohlcv(['SPY'], days=5)
    
    # 2. 검증
    # 결과는 MultiIndex가 아니어야 함
    assert not isinstance(df.columns, pd.MultiIndex)
    # 컬럼명이 'Close', 'Open' 처럼 단순해야 함 ('SPY' 레벨이 제거됨)
    assert 'Close' in df.columns
    assert 'SPY' not in df.columns 

def test_fetch_ohlcv_multiple_tickers(mock_yf_download, mock_logger):
    """
    [구조] 다중 종목 요청 시에는 MultiIndex 구조가 유지되어야 함
    """
    # 1. MultiIndex 데이터 (SPY, QLD)
    columns = pd.MultiIndex.from_product([['Close'], ['SPY', 'QLD']])
    mock_df = pd.DataFrame([[100, 50], [101, 51]], columns=columns)
    
    mock_yf_download.return_value = mock_df
    
    loader = YFinanceLoader(mock_logger)
    df = loader.fetch_ohlcv(['SPY', 'QLD'], days=5)
    
    # 2. 검증
    # 결과가 여전히 MultiIndex여야 함 (누가 누구 데이터인지 구분 필요)
    assert isinstance(df.columns, pd.MultiIndex)
    # 레벨 1에 티커들이 존재해야 함
    assert 'SPY' in df.columns.get_level_values(1)
    assert 'QLD' in df.columns.get_level_values(1)

def test_fetch_ohlcv_network_error(mock_yf_download, mock_logger):
    """
    [예외] 외부 API 호출 중 에러 발생 시 로그를 남기고 예외를 다시 던지는지 확인
    """
    # 1. 강제 에러 설정
    mock_yf_download.side_effect = Exception("Connection Timeout")
    
    loader = YFinanceLoader(mock_logger)
    
    # 2. 예외가 상위로 전파되어야 함 (봇이 인지해야 하므로)
    with pytest.raises(Exception, match="Connection Timeout"):
        loader.fetch_ohlcv(['SPY'])
        
    # 3. 동시에 에러 로그도 남겨야 함
    mock_logger.error.assert_called_once()

# ... (기존 코드 생략) ...
import numpy as np

def test_fetch_vix_multiindex_structure(mock_yf_download, mock_logger):
    """
    [구조] VIX 데이터가 MultiIndex(Close -> ^VIX) 형태로 들어와도
    로직이 깨지지 않고 값을 추출하는지 확인
    """
    # 1. MultiIndex 구조 생성 (Close, ^VIX)
    columns = pd.MultiIndex.from_product([['Close'], ['^VIX']])
    # 값 25.5
    mock_df = pd.DataFrame([[25.5]], columns=columns)
    
    mock_yf_download.return_value = mock_df
    
    loader = YFinanceLoader(mock_logger)
    vix = loader.fetch_vix()
    
    # 2. 검증
    assert vix == 25.5
    # 성공 로그가 찍혔는지 확인
    mock_logger.info.assert_any_call("[Data] 🔍 Fetching VIX data from Yahoo Finance...")

def test_fetch_vix_return_type_float(mock_yf_download, mock_logger):
    """
    [타입] VIX 결과값이 numpy 타입이 아닌 순수 float인지 확인 (JSON 직렬화 안전성)
    """
    # Numpy float64 타입 데이터 준비
    mock_df = pd.DataFrame({'Close': [np.float64(19.5)]})
    mock_yf_download.return_value = mock_df
    
    loader = YFinanceLoader(mock_logger)
    vix = loader.fetch_vix()
    
    # 값 검증
    assert vix == 19.5
    # 타입 검증 (매우 중요: numpy type은 json dump시 에러 유발 가능)
    assert isinstance(vix, float)
    assert not isinstance(vix, np.float64)

def test_fetch_ohlcv_datetime_index(mock_yf_download, mock_logger):
    """
    [데이터] 반환된 DataFrame의 인덱스가 DatetimeIndex인지 확인
    (IndicatorCalculator에서 날짜 연산을 하려면 필수)
    """
    # 문자열 날짜로 생성해도 yfinance는 보통 datetime 객체로 줌
    dates = pd.date_range("2024-01-01", periods=3)
    mock_df = pd.DataFrame({'Close': [100, 101, 102]}, index=dates)
    mock_yf_download.return_value = mock_df
    
    loader = YFinanceLoader(mock_logger)
    df = loader.fetch_ohlcv(['SPY'], days=5)
    
    # 인덱스 타입 확인
    assert isinstance(df.index, pd.DatetimeIndex)
    assert len(df) == 3