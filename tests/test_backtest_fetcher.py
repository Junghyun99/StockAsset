# tests/test_backtest_fetcher.py
import pytest
import pandas as pd
from unittest.mock import MagicMock
from src.backtest.fetcher import download_historical_data


@pytest.fixture
def mock_cache():
    """BacktestDataCache mock 인스턴스 직접 주입"""
    mock = MagicMock()
    return mock


def test_download_historical_data_basic(mock_cache):
    """기본 데이터 다운로드 동작 확인"""
    dates = pd.date_range("2023-01-01", periods=5)
    price_df = pd.DataFrame({'Close': [100, 101, 102, 103, 104]}, index=dates)
    vix_df = pd.DataFrame({'Close': [15, 16, 17, 18, 19]}, index=dates)
    div_df = pd.DataFrame()

    mock_cache.get_data.return_value = (price_df, vix_df, div_df)

    tickers = ['SPY', 'IEF']
    df, vix, divs = download_historical_data(tickers, "2023-01-01", "2023-12-31", cache=mock_cache)

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
    mock_cache.get_data.return_value = (mock_df, mock_df, pd.DataFrame())

    download_historical_data(['SPY'], "2023-06-01", "2023-12-31", cache=mock_cache)

    # cache.get_data의 start_date 인자가 500일 앞인지 확인
    call_args = mock_cache.get_data.call_args
    start_date_str = call_args[0][1]  # real_start_str
    # 2023-06-01에서 500일 전 = 약 2022-01-17
    assert "2022" in start_date_str


def test_download_historical_data_returns_tuple(mock_cache):
    """반환값이 (df, vix, dividends) 3-튜플인지 확인"""
    mock_df = pd.DataFrame({'Close': [100]})
    mock_cache.get_data.return_value = (mock_df, mock_df, pd.DataFrame())

    result = download_historical_data(['SPY'], "2023-01-01", "2023-12-31", cache=mock_cache)

    assert isinstance(result, tuple)
    assert len(result) == 3


def test_download_historical_data_cache_isolation():
    """cache 파라미터를 각각 독립적으로 주입하면 서로 영향을 주지 않는지 확인"""
    mock_a = MagicMock()
    mock_b = MagicMock()

    df_a = pd.DataFrame({'Close': [1]})
    df_b = pd.DataFrame({'Close': [2]})

    mock_a.get_data.return_value = (df_a, df_a, pd.DataFrame())
    mock_b.get_data.return_value = (df_b, df_b, pd.DataFrame())

    result_a, _, _ = download_historical_data(['SPY'], "2023-01-01", "2023-12-31", cache=mock_a)
    result_b, _, _ = download_historical_data(['QLD'], "2023-01-01", "2023-12-31", cache=mock_b)

    # 각 mock은 독립적으로 1번씩 호출
    mock_a.get_data.assert_called_once()
    mock_b.get_data.assert_called_once()

    # 결과값이 서로 다른 mock에서 온 것임을 확인
    assert result_a['Close'].iloc[0] == 1
    assert result_b['Close'].iloc[0] == 2


def test_download_historical_data_default_cache_created(monkeypatch):
    """cache 파라미터 미전달 시 BacktestDataCache가 내부에서 생성되는지 확인"""
    from src.backtest import fetcher
    from src.backtest.cache import BacktestDataCache

    created_instances = []

    class FakeCache:
        def __init__(self, cache_dir=None):
            self.mock = MagicMock()
            created_instances.append(self)

        def get_data(self, *args, **kwargs):
            df = pd.DataFrame({'Close': [100]})
            return df, df, pd.DataFrame()

    monkeypatch.setattr(fetcher, "BacktestDataCache", FakeCache)

    download_historical_data(['SPY'], "2023-01-01", "2023-12-31")

    # 내부에서 BacktestDataCache가 생성되었는지 확인
    assert len(created_instances) == 1
