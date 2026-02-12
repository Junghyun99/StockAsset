# tests/test_backtest_fetcher.py
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from src.backtest.fetcher import download_historical_data


@pytest.fixture
def mock_yf_download():
    """yfinance.download를 Mock"""
    with patch('src.backtest.fetcher.yf.download') as mock:
        yield mock


def test_download_historical_data_basic(mock_yf_download):
    """기본 데이터 다운로드 동작 확인"""
    # Mock 데이터 준비
    dates = pd.date_range("2023-01-01", periods=5)
    price_df = pd.DataFrame({'Close': [100, 101, 102, 103, 104]}, index=dates)
    vix_df = pd.DataFrame({'Close': [15, 16, 17, 18, 19]}, index=dates)

    # 첫 번째 호출: 주가, 두 번째 호출: VIX
    mock_yf_download.side_effect = [price_df, vix_df]

    tickers = ['SPY', 'IEF']
    df, vix = download_historical_data(tickers, "2023-01-01", "2023-12-31")

    # 반환값 확인
    assert not df.empty
    assert not vix.empty
    assert len(df) == 5

    # yf.download가 2번 호출되었는지 확인 (주가 + VIX)
    assert mock_yf_download.call_count == 2

    # 첫 번째 호출: 주가 데이터
    first_call_args = mock_yf_download.call_args_list[0]
    assert first_call_args[0][0] == ['SPY', 'IEF']

    # 두 번째 호출: VIX 데이터
    second_call_args = mock_yf_download.call_args_list[1]
    assert second_call_args[0][0] == "^VIX"


def test_download_historical_data_start_offset(mock_yf_download):
    """시작 날짜가 500일 앞으로 당겨지는지 확인"""
    dates = pd.date_range("2022-01-01", periods=3)
    mock_df = pd.DataFrame({'Close': [100, 101, 102]}, index=dates)
    mock_yf_download.side_effect = [mock_df, mock_df]

    download_historical_data(['SPY'], "2023-06-01", "2023-12-31")

    # start 인자가 500일 앞인지 확인
    first_call = mock_yf_download.call_args_list[0]
    start_date = first_call[1]['start']
    # 2023-06-01에서 500일 전 = 약 2022-01-17
    assert start_date.year == 2022


def test_download_historical_data_returns_tuple(mock_yf_download):
    """반환값이 (df, vix) 튜플인지 확인"""
    mock_df = pd.DataFrame({'Close': [100]})
    mock_yf_download.side_effect = [mock_df, mock_df]

    result = download_historical_data(['SPY'], "2023-01-01", "2023-12-31")

    assert isinstance(result, tuple)
    assert len(result) == 2
