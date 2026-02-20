# tests/test_backtest_fetcher.py
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from src.backtest.fetcher import download_historical_data


@pytest.fixture
def mock_cache():
    """BacktestDataCache.get_data를 Mock"""
    with patch('src.backtest.fetcher._cache') as mock:
        yield mock


def test_download_historical_data_basic(mock_cache):
    """기본 데이터 다운로드 동작 확인"""
    dates = pd.date_range("2023-01-01", periods=5)
    price_df = pd.DataFrame({'Close': [100, 101, 102, 103, 104]}, index=dates)
    vix_df = pd.DataFrame({'Close': [15, 16, 17, 18, 19]}, index=dates)

    mock_cache.get_data.return_value = (price_df, vix_df)

    tickers = ['SPY', 'IEF']
    df, vix = download_historical_data(tickers, "2023-01-01", "2023-12-31")

    # 반환값 확인
    assert not df.empty
    assert not vix.empty
    assert len(df) == 5

    # cache.get_data가 1번 호출되었는지 확인
    mock_cache.get_data.assert_called_once()

    # 호출 인자 확인
    call_args = mock_cache.get_data.call_args
    assert call_args[0][0] == ['SPY', 'IEF']  # tickers
    assert call_args[0][2] == "2023-12-31"     # end_date


def test_download_historical_data_start_offset(mock_cache):
    """시작 날짜가 500일 앞으로 당겨지는지 확인"""
    mock_df = pd.DataFrame({'Close': [100]})
    mock_cache.get_data.return_value = (mock_df, mock_df)

    download_historical_data(['SPY'], "2023-06-01", "2023-12-31")

    # cache.get_data의 start_date 인자가 500일 앞인지 확인
    call_args = mock_cache.get_data.call_args
    start_date_str = call_args[0][1]  # real_start_str
    # 2023-06-01에서 500일 전 = 약 2022-01-17
    assert "2022" in start_date_str


def test_download_historical_data_returns_tuple(mock_cache):
    """반환값이 (df, vix) 튜플인지 확인"""
    mock_df = pd.DataFrame({'Close': [100]})
    mock_cache.get_data.return_value = (mock_df, mock_df)

    result = download_historical_data(['SPY'], "2023-01-01", "2023-12-31")

    assert isinstance(result, tuple)
    assert len(result) == 2
