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

def test_fetch_ohlcv_success(mock_yf_download):
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

def test_fetch_ohlcv_empty_data(mock_yf_download):
    # 2. 데이터가 비어있을 때 (예외 발생)
    mock_yf_download.return_value = pd.DataFrame() # 빈 DF
    
    loader = YFinanceLoader(mock_logger)
    
    with pytest.raises(ValueError, match="No data fetched"):
        loader.fetch_ohlcv(['SPY'])

def test_fetch_vix_success(mock_yf_download):
    # 3. VIX 조회 성공
    mock_df = pd.DataFrame({'Close': [15.5, 16.0, 17.5]})
    mock_yf_download.return_value = mock_df
    
    loader = YFinanceLoader(mock_logger)
    vix = loader.fetch_vix()
    
    assert vix == 17.5 # 마지막 값

def test_fetch_vix_failure_fallback(mock_yf_download):
    # 4. VIX 조회 실패 시 안전값(20.0) 반환 확인
    mock_yf_download.return_value = pd.DataFrame() # 빈 DF
    
    loader = YFinanceLoader(mock_logger)
    vix = loader.fetch_vix()
    
    assert vix == 20.0