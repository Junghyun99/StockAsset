# tests/test_backtest_runner.py
import pytest
import pandas as pd
import numpy as np
import math
from unittest.mock import patch, MagicMock
from src.backtest.runner import run_backtest
from src.core.models import MarketRegime


@pytest.fixture
def mock_fetcher_return():
    """fetcher가 반환할 가짜 대량 데이터 (253일 이상 필요)"""
    # [수정] 10일 -> 400일로 증가
    dates = pd.date_range(start="2022-01-01", end="2023-02-15") # 400+일
    
    # 가격 데이터 생성 (서서히 오르는 추세)
    prices = np.linspace(100, 200, len(dates)).reshape(-1, 1)
    
    # 주가 데이터
    columns = pd.MultiIndex.from_product([['Close'], ['SPY']])
    df = pd.DataFrame(prices, index=dates, columns=columns)
    
    # VIX 데이터
    vix = pd.DataFrame({'Close': [15.0]*len(dates)}, index=dates)
    
    return df, vix


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.show") # 그래프 팝업 차단
def test_run_backtest_flow(mock_show, mock_download, mock_fetcher_return):
    """
    [Runner] 전체 백테스팅 루프가 에러 없이 돌아가는지 확인
    """
    # 1. Mock 데이터 연결
    mock_download.return_value = mock_fetcher_return
    
    # 2. 백테스트 실행 (1월 2일부터 1월 5일까지)
    # 실제로는 download_historical_data가 호출되지 않고 mock 데이터를 씀
    run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)
    
    # 3. 검증
    # 다운로드가 호출되었는가?
    mock_download.assert_called_once()
    # 그래프가 그려졌는가? (plt.show 호출 여부)
    mock_show.assert_called_once()
    
    # 로그 등을 통해 루프가 돌았는지 간접 확인할 수 있지만,
    # 에러 없이 여기까지 왔다면 로직 흐름은 정상임.


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.show")
def test_nan_data_skips_rebalancing(mock_show, mock_download, mock_fetcher_return):
    """
    [Runner] NaN 데이터가 감지되면 regime을 CRASH로 강제하고 리밸런싱을 실행하지 않아야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    nan_market_data = MagicMock()
    nan_market_data.nan_fields.return_value = ['spy_volatility']
    nan_market_data.spy_volatility = math.nan

    with patch("src.backtest.runner.IndicatorCalculator.calculate", return_value=nan_market_data), \
         patch("src.backtest.runner.Rebalancer.generate_signal") as mock_signal:
        run_backtest(start_date="2023-01-02", end_date="2023-01-03", initial_cash=10000.0)
        # NaN으로 인해 CRASH 처리 → generate_signal이 호출되지 않아야 함
        mock_signal.assert_not_called()


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.show")
def test_crash_regime_skips_rebalancing(mock_show, mock_download, mock_fetcher_return):
    """
    [Runner] analyzer가 CRASH를 반환하면 리밸런싱을 실행하지 않고 history에 exposure=0으로 기록해야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    with patch("src.backtest.runner.RegimeAnalyzer.analyze", return_value=MarketRegime.CRASH), \
         patch("src.backtest.runner.Rebalancer.generate_signal") as mock_signal:
        run_backtest(start_date="2023-01-02", end_date="2023-01-03", initial_cash=10000.0)
        # CRASH regime → generate_signal이 호출되지 않아야 함
        mock_signal.assert_not_called()