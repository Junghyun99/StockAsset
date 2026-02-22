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


@patch("src.backtest.runner.download_historical_data")
def test_empty_history_returns_none_when_no_trading_days(mock_download):
    """
    [Runner] 날짜 범위에 거래일이 없으면 history가 비어 None을 반환해야 한다 (#43).
    다운로드된 데이터의 날짜 범위가 요청 기간과 겹치지 않는 경우를 재현한다.
    """
    # 요청 기간(2099년)과 전혀 겹치지 않는 데이터 반환
    dates = pd.date_range(start="2020-01-01", end="2020-01-10")
    columns = pd.MultiIndex.from_product([['Close'], ['SPY']])
    df = pd.DataFrame([[100.0]] * len(dates), index=dates, columns=columns)
    vix = pd.DataFrame({'Close': [15.0] * len(dates)}, index=dates)
    mock_download.return_value = (df, vix)

    result = run_backtest(start_date="2099-01-01", end_date="2099-01-05", initial_cash=10000.0)

    assert result is None


@patch("src.backtest.runner.download_historical_data")
def test_empty_history_returns_none_when_all_prices_fail(mock_download, mock_fetcher_return):
    """
    [Runner] 모든 날 가격 데이터 추출이 실패하면 history가 비어 None을 반환해야 한다 (#43).
    full_df['Close'] 접근 시 항상 KeyError를 발생시켜 continue 분기를 재현한다.
    """
    mock_df, mock_vix = mock_fetcher_return

    # full_df['Close'] 접근 시 항상 KeyError 발생 → 매일 except → continue
    bad_df = MagicMock()
    bad_df.index = mock_df.index
    bad_df.__getitem__ = MagicMock(side_effect=KeyError("Close"))
    mock_download.return_value = (bad_df, mock_vix)

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is None


def test_cagr_formula_actual_dates_vs_data_points():
    """
    [Bug #44] CAGR 공식이 데이터 포인트 수가 아닌 실제 날짜 기간을 사용하는지 검증한다.

    시나리오: 정확히 1년 기간(2022-01-03 ~ 2023-01-03)에 포트폴리오가 2배(100% 수익).
    단, 중간 데이터 포인트가 3개뿐인 희소 데이터를 사용.

    - 구 공식 (252 / len(res_df)): 252/3 = 84 → 비현실적 CAGR (수백만%)
    - 신 공식 (실제 날짜 기반): 약 1년 → CAGR ≈ 100%
    """
    # 1년 기간에 3개 포인트만 있는 희소 데이터 (누락일이 많은 상황 재현)
    index = pd.DatetimeIndex(["2022-01-03", "2022-07-01", "2023-01-03"])
    initial_cash = 10000.0
    final_value = 20000.0  # 2배 수익

    # 신 공식: 실제 날짜 기간 기반
    years = (index[-1] - index[0]).days / 365.25
    cagr_new = (final_value / initial_cash) ** (1 / years) - 1 if years > 0 else 0.0

    # 구 공식: 데이터 포인트 수 기반
    cagr_old = (final_value / initial_cash) ** (252 / len(index)) - 1

    # 신 공식: 1년 2배 → CAGR ≈ 100% (±5% 허용)
    assert abs(cagr_new - 1.0) < 0.05, (
        f"신 공식 CAGR이 100%에 근접해야 함: {cagr_new:.2%}"
    )
    # 구 공식: 3포인트로 84배 연환산 → 심각한 과대 추정 (100배 이상)
    assert cagr_old > 100.0, (
        f"구 공식은 데이터 누락 시 CAGR을 과대 추정함: {cagr_old:.2%}"
    )


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.show")
def test_cagr_single_day_does_not_raise(mock_show, mock_download):
    """
    [Bug #44] history가 1개 행(같은 날)이면 years=0이 되는 엣지 케이스에서
    ZeroDivisionError 없이 CAGR=0.0을 반환해야 한다.
    """
    # 데이터가 딱 1일치만 있어서 start == end
    dates = pd.date_range(start="2021-06-01", end="2023-06-30")
    prices = np.linspace(100, 200, len(dates)).reshape(-1, 1)
    columns = pd.MultiIndex.from_product([['Close'], ['SPY']])
    df = pd.DataFrame(prices, index=dates, columns=columns)
    vix = pd.DataFrame({'Close': [15.0] * len(dates)}, index=dates)
    mock_download.return_value = (df, vix)

    # 단 하루만 실행
    with patch("builtins.print") as mock_print:
        run_backtest(start_date="2023-01-03", end_date="2023-01-03", initial_cash=10000.0)

        # CAGR 출력에서 0.00% 확인 (단 하루 → years=0 → cagr=0.0)
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "0.00%" in printed, f"단일 날짜 시 CAGR=0.00%이어야 함. 출력: {printed}"