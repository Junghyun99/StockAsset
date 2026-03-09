# tests/test_backtest_runner.py
import pytest
import pandas as pd
import numpy as np
import math
from unittest.mock import patch, MagicMock
from src.backtest.runner import run_backtest, BacktestResult, _validate_tickers
from src.core.engine import QldSchdEngine, QldSHVEngine
from src.core.models import MarketRegime, TradeExecution, OrderAction, ExecutionStatus, Order


ALL_TICKERS = ["SPY", "SSO", "QLD", "IEF", "GLD", "PDBC", "SHV"]
ENGINE_TICKERS_SCHD = ["SPY", "QLD", "SCHD"]
ENGINE_TICKERS_SHV = ["SPY", "QLD", "SHV"]


@pytest.fixture
def mock_fetcher_return():
    """fetcher가 반환할 가짜 대량 데이터 (253일 이상 필요).
    ASSET_GROUPS 전체 티커 + SPY를 포함해야 _validate_tickers를 통과한다.
    """
    dates = pd.date_range(start="2022-01-01", end="2023-02-15")  # 400+일

    n = len(dates)
    price_data = {
        ticker: np.linspace(100, 200, n)
        for ticker in ALL_TICKERS
    }
    columns = pd.MultiIndex.from_product([["Close"], ALL_TICKERS])
    df = pd.DataFrame(
        np.column_stack(list(price_data.values())),
        index=dates,
        columns=columns,
    )

    vix = pd.DataFrame({"Close": [15.0] * n}, index=dates)
    dividends = pd.DataFrame()  # 배당 없음 (테스트용 빈 DataFrame)
    return df, vix, dividends


@pytest.fixture
def mock_fetcher_spy_only():
    """SPY만 있는 데이터 — _validate_tickers 실패를 재현하기 위한 fixture."""
    dates = pd.date_range(start="2022-01-01", end="2023-02-15")
    columns = pd.MultiIndex.from_product([["Close"], ["SPY"]])
    df = pd.DataFrame(
        np.linspace(100, 200, len(dates)).reshape(-1, 1),
        index=dates,
        columns=columns,
    )
    vix = pd.DataFrame({"Close": [15.0] * len(dates)}, index=dates)
    dividends = pd.DataFrame()
    return df, vix, dividends


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

    with patch("src.core.engine.IndicatorCalculator.calculate", return_value=nan_market_data), \
         patch("src.core.engine.Rebalancer.generate_signal") as mock_signal:
        run_backtest(start_date="2023-01-02", end_date="2023-01-03", initial_cash=10000.0)
        # NaN으로 인해 CRASH 처리 → generate_signal이 호출되지 않아야 함
        mock_signal.assert_not_called()


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_crash_regime_executes_rebalancing(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Runner] analyzer가 CRASH를 반환하면 exposure=0으로 리밸런싱을 실행하고
    history에 exposure=0으로 기록해야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    with patch("src.core.engine.RegimeAnalyzer.analyze", return_value=MarketRegime.CRASH):
        result = run_backtest(start_date="2023-01-02", end_date="2023-01-03", initial_cash=10000.0)
        # CRASH regime → generate_signal이 호출되어야 함 (exposure=0으로 리밸런싱)
        assert result is not None
        assert (result.history["target_exposure"] == 0.0).all(), "CRASH 시 exposure=0으로 기록되어야 함"
        assert not result.history["reason"].str.contains("데이터 이상").any(), "NaN 없는 CRASH에서 데이터 이상 사유가 없어야 함"


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


def test_validate_tickers_all_present():
    """
    [Validate] 요청 티커가 full_df에 모두 있으면 빈 리스트를 반환해야 한다.
    """
    dates = pd.date_range("2023-01-01", periods=5)
    cols = pd.MultiIndex.from_product([["Close"], ["SPY", "SSO"]])
    df = pd.DataFrame([[100.0, 200.0]] * 5, index=dates, columns=cols)

    mock_logger = MagicMock()
    missing = _validate_tickers(df, ["SPY", "SSO"], mock_logger)

    assert missing == []
    mock_logger.warning.assert_not_called()


def test_validate_tickers_some_missing():
    """
    [Validate] 일부 티커가 full_df에 없으면 누락 목록을 반환하고 경고를 출력해야 한다.
    """
    dates = pd.date_range("2023-01-01", periods=5)
    cols = pd.MultiIndex.from_product([["Close"], ["SPY"]])
    df = pd.DataFrame([[100.0]] * 5, index=dates, columns=cols)

    mock_logger = MagicMock()
    missing = _validate_tickers(df, ["SPY", "SSO", "QLD"], mock_logger)

    assert "SSO" in missing
    assert "QLD" in missing
    assert "SPY" not in missing
    mock_logger.warning.assert_called_once()
    assert "⚠️" in mock_logger.warning.call_args[0][0]


@patch("src.backtest.runner.download_historical_data")
def test_run_backtest_aborts_when_tickers_missing(mock_download, mock_fetcher_spy_only, caplog):
    """
    [Validate] full_df에 ASSET_GROUPS 티커가 일부 누락되면
    경고를 출력하고 None을 반환해 백테스트를 중단해야 한다.
    """
    import logging
    mock_download.return_value = mock_fetcher_spy_only  # SPY만 포함

    with caplog.at_level(logging.WARNING, logger="SolidQuant"):
        result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is None, "티커 누락 시 None을 반환해 백테스트를 중단해야 함"
    assert "⚠️" in caplog.text, "누락 티커에 대한 경고가 출력되어야 함"


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
    mock_download.return_value = (df, vix, pd.DataFrame())

    result = run_backtest(start_date="2099-01-01", end_date="2099-01-05", initial_cash=10000.0)

    assert result is None


@patch("src.backtest.runner.download_historical_data")
def test_empty_history_returns_none_when_all_prices_fail(mock_download, mock_fetcher_return):
    """
    [Runner] 모든 날 가격 데이터 추출이 실패하면 history가 비어 None을 반환해야 한다 (#43).
    full_df['Close'] 접근 시 항상 KeyError를 발생시켜 continue 분기를 재현한다.
    """
    mock_df, mock_vix, _ = mock_fetcher_return

    # full_df['Close'] 접근 시 항상 KeyError 발생 → 매일 except → continue
    bad_df = MagicMock()
    bad_df.index = mock_df.index
    bad_df.__getitem__ = MagicMock(side_effect=KeyError("Close"))
    mock_download.return_value = (bad_df, mock_vix, pd.DataFrame())

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is None


@patch("src.backtest.runner.download_historical_data")
def test_price_extraction_failure_logs_warning(mock_download, mock_fetcher_return, caplog):
    """
    [Issue #90] 종가 추출 실패 시 로그 없이 건너뛰지 않고
    logger.warning으로 실패한 날짜와 원인을 기록해야 한다.
    """
    import logging
    mock_df, mock_vix, _ = mock_fetcher_return

    # _validate_tickers 통과를 위해 columns을 실제 MultiIndex로 설정
    bad_df = MagicMock()
    bad_df.index = mock_df.index
    bad_df.columns = mock_df.columns  # 실제 MultiIndex → _validate_tickers 통과
    # full_df['Close'] 접근 시 KeyError 발생 → 종가 추출 실패 경로 재현
    bad_df.__getitem__ = MagicMock(side_effect=KeyError("Close"))
    mock_download.return_value = (bad_df, mock_vix, pd.DataFrame())

    with caplog.at_level(logging.WARNING, logger="SolidQuant"):
        run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert "종가 추출 실패" in caplog.text, (
        f"종가 추출 실패 경고가 로그에 기록되어야 함. 실제 로그: {caplog.text}"
    )


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
    n = len(dates)
    columns = pd.MultiIndex.from_product([["Close"], ALL_TICKERS])
    df = pd.DataFrame(
        np.column_stack([np.linspace(100, 200, n) for _ in ALL_TICKERS]),
        index=dates,
        columns=columns,
    )
    vix = pd.DataFrame({"Close": [15.0] * n}, index=dates)
    mock_download.return_value = (df, vix, pd.DataFrame())

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
@patch("src.backtest.runner.Path")
def test_docs_directory_created_if_missing(mock_path_cls, mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #52] run_backtest가 차트 저장 전에 docs/ 디렉토리를 자동 생성해야 한다.
    docs/ 가 없어도 FileNotFoundError 없이 plt.savefig가 호출되어야 한다.
    """
    mock_download.return_value = mock_fetcher_return
    mock_path_instance = MagicMock()
    mock_path_cls.return_value = mock_path_instance

    run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    mock_path_cls.assert_called_with("docs")
    mock_path_instance.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_savefig.assert_called_once()


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_nan_triggered_flag_true_when_nan_occurs(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #68] NaN 데이터 발생 시 reason에 '데이터 이상'이 기록되어야 한다.
    이를 통해 실제 CRASH와 데이터 품질 오류(NaN)를 사후 분석에서 구분할 수 있다.
    """
    mock_download.return_value = mock_fetcher_return

    nan_market_data = MagicMock()
    nan_market_data.nan_fields.return_value = ['spy_volatility']
    nan_market_data.date = "2023-01-02"
    nan_market_data.spy_price = 189.27
    nan_market_data.spy_ma180 = 167.44
    nan_market_data.spy_volatility = math.nan
    nan_market_data.spy_momentum = 0.1977
    nan_market_data.spy_mdd = 0.0
    nan_market_data.vix = 15.0

    with patch("src.core.engine.IndicatorCalculator.calculate", return_value=nan_market_data):
        result = run_backtest(start_date="2023-01-02", end_date="2023-01-03", initial_cash=10000.0)

    assert result is not None
    # NaN 발생일은 reason에 "데이터 이상" 포함
    assert result.history["reason"].str.contains("데이터 이상").any(), "NaN 발생 시 reason에 '데이터 이상'이 기록되어야 함"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_nan_triggered_flag_false_for_real_crash(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #68] 실제 CRASH 국면(NaN 없음)에서는 reason에 '데이터 이상'이 없어야 한다.
    NaN 원인 없는 CRASH와 NaN으로 인한 CRASH를 구분할 수 있어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    with patch("src.core.engine.RegimeAnalyzer.analyze", return_value=MarketRegime.CRASH):
        result = run_backtest(start_date="2023-01-02", end_date="2023-01-03", initial_cash=10000.0)

    assert result is not None
    # 실제 CRASH(NaN 없음)는 reason에 "데이터 이상" 미포함
    assert not result.history["reason"].str.contains("데이터 이상").any(), "NaN 없는 CRASH에서 reason에 데이터 이상이 없어야 함"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_exception_during_execution_records_error_in_history(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #91] 주문 실행 중 예외 발생 시에도 봇이 멈추지 않고 다음 거래일로 넘어가야 한다.
    일부 날에 예외가 발생해도 나머지 날의 기록이 남아 result는 None이 아니어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    mock_signal_obj = MagicMock()
    mock_signal_obj.has_orders = True
    mock_signal_obj.orders = [Order(ticker="SSO", action=OrderAction.BUY, quantity=5, price=100.0)]
    mock_signal_obj.reason = "test_signal"
    mock_signal_obj.target_exposure = 1.0

    # 첫 날만 예외, 이후엔 빈 체결 목록으로 성공
    with patch("src.backtest.components.BacktestBroker.execute_orders",
               side_effect=[RuntimeError("주문 실행 오류"), [], [], []]), \
         patch("src.core.engine.Rebalancer.generate_signal", return_value=mock_signal_obj):
        result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    # 예외가 발생해도 봇이 멈추지 않고 나머지 날의 결과가 반환되어야 함
    assert result is not None


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_exception_during_execution_preserves_portfolio_value(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Issue #91] 주문 실행 중 예외 발생 시에도 전체 total_value 기록이 양수로 유지되어야 한다.
    예외가 발생하지 않은 날의 포트폴리오 가치는 정상적으로 기록되어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    mock_signal_obj = MagicMock()
    mock_signal_obj.has_orders = True
    mock_signal_obj.orders = [Order(ticker="SSO", action=OrderAction.BUY, quantity=5, price=100.0)]
    mock_signal_obj.reason = "test_signal"
    mock_signal_obj.target_exposure = 1.0

    # 첫 날만 예외, 이후엔 성공
    with patch("src.backtest.components.BacktestBroker.execute_orders",
               side_effect=[ValueError("가격 계산 오류"), [], [], []]), \
         patch("src.core.engine.Rebalancer.generate_signal", return_value=mock_signal_obj):
        result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is not None
    # 기록된 모든 행의 total_value는 양수여야 함
    assert (result.history["total_value"] > 0).all(), "모든 기록 행의 total_value는 양수여야 함"


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
         patch("src.core.engine.Rebalancer.generate_signal") as mock_signal:

        mock_signal_obj = MagicMock()
        mock_signal_obj.has_orders = True
        mock_signal_obj.orders = [Order(ticker="SSO", action=OrderAction.BUY, quantity=5, price=100.0)]
        mock_signal_obj.reason = "test"
        mock_signal_obj.target_exposure = 1.0
        mock_signal.return_value = mock_signal_obj

        result = run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    assert result is not None
    # execute_orders가 최소 1회 호출되어야 함
    assert mock_exec.call_count >= 1, "execute_orders가 최소 1회 호출되어야 함"
    # 반환된 실행 기록이 누적되어야 함
    assert len(result.trade_executions) >= 1, "trade_executions에 체결 기록이 누적되어야 함"


# === execution_interval 테스트 ===

def test_execution_interval_invalid_raises_error():
    """
    [Interval] execution_interval이 1 미만이면 ValueError를 발생시켜야 한다.
    """
    with pytest.raises(ValueError, match="execution_interval은 1 이상"):
        run_backtest("2023-01-02", "2023-01-05", execution_interval=0)

    with pytest.raises(ValueError, match="execution_interval은 1 이상"):
        run_backtest("2023-01-02", "2023-01-05", execution_interval=-1)


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_execution_interval_default_executes_every_day(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Interval] execution_interval 미지정(기본값 1)이면 매 거래일마다 실행해야 한다.
    모니터링 날(리밸런싱 미실행)이 없어야 한다 (기존 동작 유지).
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(start_date="2023-01-02", end_date="2023-01-10", initial_cash=10000.0)

    assert result is not None
    # 기본값(1)이면 모니터링 날이 없어야 함
    skip_rows = result.history[result.history["reason"].str.contains("모니터링")]
    assert len(skip_rows) == 0, "interval=1이면 모니터링 날이 없어야 함"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_execution_interval_skips_non_execution_days(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Interval] execution_interval=3이면 3거래일에 1번만 리밸런싱을 실행하고,
    나머지 날은 지표 계산 후 모니터링(저장만)으로 처리해야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(
        start_date="2023-01-02", end_date="2023-01-31",
        initial_cash=10000.0, execution_interval=3,
    )

    assert result is not None
    skip_rows = result.history[result.history["reason"].str.contains("모니터링")]
    exec_rows = result.history[~result.history["reason"].str.contains("모니터링")]
    # 모니터링 날이 존재해야 함
    assert len(skip_rows) > 0, "interval=3이면 모니터링 날이 있어야 함"
    # 실행일도 존재해야 함
    assert len(exec_rows) > 0, "interval=3이면 실행일도 있어야 함"
    # 모니터링 날의 trade_count는 0이어야 함
    assert (skip_rows["trade_count"] == 0).all(), "모니터링 날의 trade_count는 0이어야 함"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_execution_interval_first_day_always_executes(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Interval] execution_interval 값과 무관하게 첫 거래일에는 반드시 봇 로직을 실행해야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(
        start_date="2023-01-02", end_date="2023-01-10",
        initial_cash=10000.0, execution_interval=5,
    )

    assert result is not None
    # 첫 번째 행은 모니터링 날이 아니어야 함
    first_reason = result.history.iloc[0]["reason"]
    assert "모니터링" not in first_reason, f"첫날은 반드시 실행일이어야 함: {first_reason}"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_execution_interval_portfolio_value_tracked_on_skip_days(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Interval] 모니터링 날에도 포트폴리오 가치(total_value)가 기록되어야 한다.
    가격 변동이 반영된 가치가 매일 history에 남아야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    result = run_backtest(
        start_date="2023-01-02", end_date="2023-01-20",
        initial_cash=10000.0, execution_interval=5,
    )

    assert result is not None
    # 모든 행에 total_value가 양수로 기록되어야 함
    assert (result.history["total_value"] > 0).all(), "모니터링 날 포함 모든 날의 total_value가 양수여야 함"
    # 모니터링 날의 exposure가 NaN이 아닌 숫자여야 함
    skip_rows = result.history[result.history["reason"].str.contains("모니터링")]
    if len(skip_rows) > 0:
        assert skip_rows["target_exposure"].notna().all(), "모니터링 날의 target_exposure가 NaN이 아니어야 함"


# === 엔진 고유 자산군 일관성 테스트 ===

def _make_engine_price_df(tickers, n=400):
    """지정된 티커 목록으로 가짜 가격 DataFrame 생성."""
    dates = pd.date_range(start="2022-01-01", periods=n)
    price_data = {t: np.linspace(100, 200, n) for t in tickers}
    columns = pd.MultiIndex.from_product([["Close"], tickers])
    df = pd.DataFrame(
        np.column_stack(list(price_data.values())),
        index=dates,
        columns=columns,
    )
    vix = pd.DataFrame({"Close": [15.0] * n}, index=dates)
    dividends = pd.DataFrame()
    return df, vix, dividends


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_engine_asset_groups_used_for_rebalancer(mock_savefig, mock_download):
    """
    [Asset Consistency] QldSchdEngine을 engine_class로 사용하면
    runner가 생성하는 rebalancer의 groups가 QldSchdEngine.ASSET_GROUPS여야 한다.
    strategy_config.py의 기본 자산군(SSO/IEF 등)이 아닌 엔진 자산군(QLD/SCHD)이
    rebalancer에 주입되어야 한다.
    """
    mock_download.return_value = _make_engine_price_df(ENGINE_TICKERS_SCHD)

    captured_groups = {}

    original_init = __import__('src.core.logic', fromlist=['Rebalancer']).Rebalancer.__init__

    def capture_init(self, asset_groups, *args, **kwargs):
        captured_groups['groups'] = asset_groups
        original_init(self, asset_groups, *args, **kwargs)

    with patch("src.core.engine.Rebalancer.__init__", capture_init):
        run_backtest(
            start_date="2023-01-02", end_date="2023-01-05",
            initial_cash=10000.0,
            engine_class=QldSchdEngine,
        )

    assert captured_groups.get('groups') == QldSchdEngine.ASSET_GROUPS, (
        f"rebalancer가 QldSchdEngine.ASSET_GROUPS를 사용해야 함. "
        f"실제: {captured_groups.get('groups')}"
    )


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_engine_asset_groups_used_for_tickers(mock_savefig, mock_download):
    """
    [Asset Consistency] QldSchdEngine 사용 시 download_historical_data에
    엔진 자산군(QLD, SCHD) 티커가 전달되어야 한다.
    기본 전략 자산군(SSO, IEF 등)이 포함되어서는 안 된다.
    """
    mock_download.return_value = _make_engine_price_df(ENGINE_TICKERS_SCHD)

    run_backtest(
        start_date="2023-01-02", end_date="2023-01-05",
        initial_cash=10000.0,
        engine_class=QldSchdEngine,
    )

    tickers_called = set(mock_download.call_args[0][0])
    assert "QLD" in tickers_called, "QLD가 다운로드 티커에 포함되어야 함"
    assert "SCHD" in tickers_called, "SCHD가 다운로드 티커에 포함되어야 함"
    assert "SSO" not in tickers_called, "SSO는 QldSchdEngine 자산군이 아님"
    assert "IEF" not in tickers_called, "IEF는 QldSchdEngine 자산군이 아님"


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_qld_schd_engine_ratio_a_used(mock_savefig, mock_download):
    """
    [Asset Consistency] QldSchdEngine의 REBALANCE_RATIO_A(0.3)가
    runner의 기본 ratio_a(0.5) 대신 rebalancer에 적용되어야 한다.
    """
    mock_download.return_value = _make_engine_price_df(ENGINE_TICKERS_SCHD)

    captured_ratio = {}

    original_init = __import__('src.core.logic', fromlist=['Rebalancer']).Rebalancer.__init__

    def capture_init(self, asset_groups, logger=None, ratio_a=0.5):
        captured_ratio['ratio_a'] = ratio_a
        original_init(self, asset_groups, logger=logger, ratio_a=ratio_a)

    with patch("src.core.engine.Rebalancer.__init__", capture_init):
        run_backtest(
            start_date="2023-01-02", end_date="2023-01-05",
            initial_cash=10000.0,
            engine_class=QldSchdEngine,
        )

    assert captured_ratio.get('ratio_a') == QldSchdEngine.REBALANCE_RATIO_A, (
        f"QldSchdEngine의 REBALANCE_RATIO_A({QldSchdEngine.REBALANCE_RATIO_A})가 "
        f"rebalancer에 적용되어야 함. 실제: {captured_ratio.get('ratio_a')}"
    )


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_default_engine_uses_strategy_asset_groups(mock_savefig, mock_download, mock_fetcher_return):
    """
    [Asset Consistency] engine_class 미지정(기본 TradingEngine) 시
    strategy_config.py의 기본 자산군이 그대로 사용되어야 한다.
    """
    mock_download.return_value = mock_fetcher_return

    run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)

    tickers_called = set(mock_download.call_args[0][0])
    # 기본 자산군 티커가 모두 포함되어야 함
    for ticker in ["SSO", "QLD", "IEF", "GLD", "PDBC", "SHV"]:
        assert ticker in tickers_called, f"{ticker}가 기본 엔진 다운로드 티커에 포함되어야 함"
