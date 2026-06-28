# tests/test_backtest_compare.py
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from src.backtest.runner import (
    run_compare_backtest, CompareBacktestResult, BacktestResult, ENGINE_REGISTRY,
    _ENGINE_BACKTEST,
)


# 모든 엔진의 티커 합집합 + SPY + 벤치마크 티커(EWY, 360750.KS, 133690.KS)
ALL_COMPARE_TICKERS = ["SPY", "SSO", "QLD", "IEF", "GLD", "DBC", "SHV", "SDY", "QQQ", "EEM", "TLT", "EMB",
                        "069500.KS", "143850.KS", "132030.KS", "305080.KS", "148070.KS",
                        "EWY", "360750.KS", "133690.KS"]


@pytest.fixture
def mock_compare_fetcher():
    """모든 엔진 티커를 포함하는 가짜 데이터 (400+일)."""
    dates = pd.date_range(start="2022-01-01", end="2023-02-15")
    n = len(dates)
    price_data = {
        ticker: np.linspace(100, 200, n)
        for ticker in ALL_COMPARE_TICKERS
    }
    columns = pd.MultiIndex.from_product([["Close"], ALL_COMPARE_TICKERS])
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
def test_run_compare_backtest_returns_all_engines(mock_savefig, mock_download, mock_compare_fetcher):
    """[Compare] 비교 백테스트가 4개 엔진 모두의 결과를 반환해야 한다."""
    mock_download.return_value = mock_compare_fetcher

    result = run_compare_backtest(
        start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0,
    )

    assert result is not None
    assert isinstance(result, CompareBacktestResult)
    expected_names = {name for name, _ in ENGINE_REGISTRY if _ENGINE_BACKTEST.get(name, True)}
    assert set(result.engine_results.keys()) == expected_names


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_run_compare_single_data_download(mock_savefig, mock_download, mock_compare_fetcher):
    """[Compare] 데이터 다운로드가 정확히 1회만 호출되어야 한다."""
    mock_download.return_value = mock_compare_fetcher

    run_compare_backtest(
        start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0,
    )

    mock_download.assert_called_once()
    # 호출된 티커에 backtest=True 엔진의 티커가 포함되어야 함
    # (SDY는 backtest=False 엔진만 사용하므로 제외)
    tickers_called = set(mock_download.call_args[0][0])
    assert "SPY" in tickers_called
    assert "QLD" in tickers_called
    assert "SSO" in tickers_called
    assert "SHV" in tickers_called


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_run_compare_independent_portfolios(mock_savefig, mock_download, mock_compare_fetcher):
    """[Compare] 각 엔진의 BacktestResult가 독립적이어야 한다."""
    mock_download.return_value = mock_compare_fetcher

    result = run_compare_backtest(
        start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0,
    )

    assert result is not None
    for name, br in result.engine_results.items():
        assert isinstance(br, BacktestResult), f"{name}의 결과가 BacktestResult여야 함"
        assert br.initial_cash == 10000.0
        assert isinstance(br.final_value, float)
        assert isinstance(br.cagr, float)
        assert isinstance(br.mdd, float)


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_run_compare_chart_saved(mock_savefig, mock_download, mock_compare_fetcher):
    """[Compare] 비교 차트가 저장되어야 한다."""
    mock_download.return_value = mock_compare_fetcher

    result = run_compare_backtest(
        start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0,
    )

    assert result is not None
    mock_savefig.assert_called_once()
    assert result.chart_path is not None
    assert "compare" in result.chart_path


@patch("src.backtest.runner.download_historical_data")
def test_run_compare_returns_none_on_missing_tickers(mock_download):
    """[Compare] 티커 누락 시 None을 반환해야 한다."""
    # SPY만 있는 데이터 → 다른 티커 누락
    dates = pd.date_range(start="2022-01-01", end="2023-02-15")
    columns = pd.MultiIndex.from_product([["Close"], ["SPY"]])
    df = pd.DataFrame(
        np.linspace(100, 200, len(dates)).reshape(-1, 1),
        index=dates,
        columns=columns,
    )
    vix = pd.DataFrame({"Close": [15.0] * len(dates)}, index=dates)
    mock_download.return_value = (df, vix, pd.DataFrame())

    result = run_compare_backtest(
        start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0,
    )

    assert result is None


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_run_compare_spy_cagr_present(mock_savefig, mock_download, mock_compare_fetcher):
    """[Compare] SPY 데이터가 있으면 spy_cagr이 계산되어야 한다."""
    mock_download.return_value = mock_compare_fetcher

    result = run_compare_backtest(
        start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0,
    )

    assert result is not None
    assert result.spy_cagr is not None


def test_compare_execution_interval_invalid_raises_error():
    """[Compare] execution_interval이 1 미만이면 ValueError를 발생시켜야 한다."""
    with pytest.raises(ValueError, match="execution_interval은 1 이상"):
        run_compare_backtest("2023-01-02", "2023-01-05", execution_interval=0)


@patch("src.backtest.runner.download_historical_data")
@patch("src.backtest.runner.plt.savefig")
def test_stale_status_json_does_not_block_rebalancing(mock_savefig, mock_download, mock_compare_fetcher, tmp_path):
    """[Compare] 이전 실행의 stale status.json이 남아있어도 리밸런싱이 정상 실행되어야 한다."""
    import json, os
    mock_download.return_value = mock_compare_fetcher

    output_dir = str(tmp_path / "compare")

    # 엔진별 디렉토리에 stale status.json 미리 생성 (backtest 대상 엔진만)
    for name, _ in ENGINE_REGISTRY:
        if not _ENGINE_BACKTEST.get(name, True):
            continue
        eng_dir = os.path.join(output_dir, name)
        os.makedirs(eng_dir, exist_ok=True)
        stale_status = {
            "last_rebalancing_date": "2025-12-30",
            "last_updated": "2025-12-30",
            "strategy": {"regime": "Bull"},
            "portfolio": {"total_value": 10000.0},
        }
        with open(os.path.join(eng_dir, "status.json"), "w") as f:
            json.dump(stale_status, f)

    result = run_compare_backtest(
        start_date="2023-01-02",
        end_date="2023-01-05",
        initial_cash=10000.0,
        output_dir=output_dir,
    )

    assert result is not None
    for name, br in result.engine_results.items():
        # 가격이 선형 증가(100->200)하므로 total_value는 10000과 달라야 함
        assert br.final_value != br.initial_cash, (
            f"{name}: final_value가 initial_cash와 같음 — 리밸런싱이 실행되지 않았음"
        )
