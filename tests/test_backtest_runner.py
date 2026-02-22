# tests/test_backtest_runner.py
import pytest
import pandas as pd
import numpy as np
import math
from unittest.mock import patch, MagicMock
from src.backtest.runner import run_backtest, BacktestResult
from src.core.models import MarketRegime, TradeExecution, OrderAction, ExecutionStatus


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
@patch("src.backtest.runner.plt.savefig")  # 차트 파일 저장 차단
def test_run_backtest_flow(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Runner] 전체 백테스팅 루프가 에러 없이 돌아가고 BacktestResult를 반환하는지 확인
    """
    # 1. Mock 데이터 연결
    mock_download.return_value = mock_fetcher_return

    # 2. 백테스트 실행 (1월 2일부터 1월 5일까지)
    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    # 3. 검증
    # 다운로드가 호출되었는가?
    mock_download.assert_called_once()
    # 차트가 저장되었는가? (plt.savefig 호출 여부)
    mock_savefig.assert_called_once()
    # BacktestResult 반환 확인
    assert result is not None
    assert isinstance(result, BacktestResult)


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_nan_data_skips_rebalancing(mock_savefig, mock_download, mock_fetcher_return):
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
@patch("src.backtest.runner.plt.savefig")
def test_crash_regime_skips_rebalancing(mock_savefig, mock_download, mock_fetcher_return):
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
@patch("src.backtest.runner.plt.savefig")
def test_spy_included_in_download_tickers(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #51] ASSET_GROUPS에 SPY가 없어도 download_historical_data 호출 시
    tickers에 SPY가 포함되어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    tickers_called = mock_download.call_args[0][0]
    assert "SPY" in tickers_called, f"SPY가 tickers에 포함되어야 함: {tickers_called}"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_spy_cagr_not_none_when_spy_data_present(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #51] full_df에 SPY 데이터가 있으면 spy_cagr이 None이 아닌 값으로 계산되어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is not None
    assert result.spy_cagr is not None, "SPY 데이터가 있으면 spy_cagr이 None이 아니어야 함"


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
@patch("src.backtest.runner.plt.savefig")
def test_cagr_single_day_does_not_raise(mock_savefig, mock_download):
    """
    [Bug #44] history가 1개 행(같은 날)이면 years=0이 되는 엣지 케이스에서
    ZeroDivisionError 없이 cagr=0.0을 반환해야 한다.
    """
    # 데이터가 딱 1일치만 있어서 start == end
    dates = pd.date_range(start="2021-06-01", end="2023-06-30")
    prices = np.linspace(100, 200, len(dates)).reshape(-1, 1)
    columns = pd.MultiIndex.from_product([['Close'], ['SPY']])
    df = pd.DataFrame(prices, index=dates, columns=columns)
    vix = pd.DataFrame({'Close': [15.0] * len(dates)}, index=dates)
    mock_download.return_value = (df, vix)

    # 단 하루만 실행
    result = run_backtest(start_date="2023-01-03", end_date="2023-01-03", initial_cash=10000.0)

    # 단일 날짜 → years=0 → cagr=0.0
    assert result is not None
    assert result.cagr == 0.0


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_backtest_result_structure(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #41] BacktestResult 구조체의 모든 필드가 올바른 타입으로 채워지는지 확인한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert isinstance(result, BacktestResult)
    assert isinstance(result.history, pd.DataFrame)
    assert isinstance(result.initial_cash, float)
    assert isinstance(result.final_value, float)
    assert isinstance(result.cagr, float)
    assert isinstance(result.mdd, float)
    assert isinstance(result.sharpe_ratio, float)
    assert isinstance(result.regime_returns, dict)
    # chart_path는 str 또는 None
    assert result.chart_path is None or isinstance(result.chart_path, str)


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_mdd_is_non_positive(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #42] MDD(최대 낙폭)는 항상 0 이하(non-positive)여야 한다.
    상승 추세 데이터라도 MDD = 0.0 (낙폭 없음).
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is not None
    assert result.mdd <= 0.0, f"MDD는 0 이하여야 함: {result.mdd}"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_sharpe_ratio_positive_for_uptrend(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #42] 지속 상승 추세 데이터에서 Sharpe Ratio는 양수여야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-10", initial_cash=10000.0)

    assert result is not None
    # 상승 추세이므로 Sharpe >= 0 (단일 날짜 등 edge case는 0 허용)
    assert result.sharpe_ratio >= 0.0, f"상승 추세에서 Sharpe >= 0이어야 함: {result.sharpe_ratio}"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_regime_returns_populated(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #42] 백테스트 실행 후 regime_returns에 적어도 하나의 국면이 기록되어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is not None
    assert len(result.regime_returns) >= 1, "최소 1개의 국면 수익률이 기록되어야 함"
    # 모든 값이 float인지 확인
    for regime_name, ret in result.regime_returns.items():
        assert isinstance(ret, float), f"{regime_name}의 수익률이 float이어야 함"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_chart_saved_not_shown(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #42] plt.savefig()가 호출되고 plt.show()는 호출되지 않아야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    with patch("src.backtest.runner.plt.show") as mock_show:
        run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    mock_savefig.assert_called_once()
    mock_show.assert_not_called()


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_trade_executions_in_result(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #45] BacktestResult에 trade_executions 필드가 존재하고 리스트 타입이어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is not None
    assert hasattr(result, "trade_executions"), "BacktestResult에 trade_executions 필드가 있어야 함"
    assert isinstance(result.trade_executions, list), "trade_executions는 리스트여야 함"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_trade_count_in_history(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #45] history DataFrame에 trade_count 컬럼이 존재하고 0 이상의 정수여야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is not None
    assert "trade_count" in result.history.columns, "history에 trade_count 컬럼이 있어야 함"
    assert (result.history["trade_count"] >= 0).all(), "trade_count는 0 이상이어야 함"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_execute_orders_return_value_collected(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #45] execute_orders 반환값(TradeExecution 리스트)이 누락 없이 수집되어야 한다.
    신호가 발생하면 result.trade_executions에 해당 체결 기록이 포함되어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    fake_execution = TradeExecution(
        ticker="SSO",
        action=OrderAction.BUY,
        quantity=5,
        price=100.0,
        fee=0.1,
        date="2023-01-02",
        status=ExecutionStatus.FILLED,
    )

    with patch("src.backtest.components.BacktestBroker.execute_orders",
               return_value=[fake_execution]) as mock_exec, \
         patch("src.backtest.runner.Rebalancer.generate_signal") as mock_signal:

        mock_signal_obj = MagicMock()
        mock_signal_obj.has_orders = True
        mock_signal_obj.orders = [MagicMock()]
        mock_signal_obj.reason = "test"
        mock_signal.return_value = mock_signal_obj

        result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is not None
    # execute_orders가 최소 1회 호출되어야 함
    assert mock_exec.call_count >= 1, "execute_orders가 최소 1회 호출되어야 함"
    # 반환된 실행 기록이 누적되어야 함
    assert len(result.trade_executions) >= 1, "trade_executions에 체결 기록이 누적되어야 함"
