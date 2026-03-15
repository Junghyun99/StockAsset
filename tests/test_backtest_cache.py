# tests/test_backtest_cache.py
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from src.backtest.cache import BacktestDataCache


@pytest.fixture
def tmp_cache_dir(tmp_path):
    """임시 캐시 디렉토리"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def cache(tmp_cache_dir):
    """임시 디렉토리를 사용하는 캐시 인스턴스"""
    return BacktestDataCache(cache_dir=tmp_cache_dir)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_ohlcv(tickers, start, end):
    """MultiIndex OHLCV DataFrame 생성 헬퍼"""
    dates = pd.bdate_range(start, end)
    columns = pd.MultiIndex.from_product([["Close", "Open", "High", "Low", "Volume"], tickers])
    data = np.random.rand(len(dates), len(columns)) * 100 + 50
    return pd.DataFrame(data, index=dates, columns=columns)


def _make_ohlcv_with_dividends(tickers, start, end):
    """yf.download(auto_adjust=False, actions=True) 형식 mock 데이터"""
    dates = pd.bdate_range(start, end)
    columns = pd.MultiIndex.from_product(
        [["Adj Close", "Close", "Dividends", "High", "Low", "Open", "Stock Splits", "Volume"], tickers]
    )
    data = np.zeros((len(dates), len(columns)))
    df = pd.DataFrame(data, index=dates, columns=columns)
    for pt in ["Close", "Open", "High", "Low", "Adj Close"]:
        for t in tickers:
            df[(pt, t)] = np.random.rand(len(dates)) * 100 + 50
    if len(dates) > 5:
        df.loc[dates[5], ("Dividends", tickers[0])] = 0.5
    if len(dates) > 10:
        df.loc[dates[10], ("Stock Splits", tickers[0])] = 2.0
    return df


def _make_vix(start, end):
    """VIX DataFrame 생성 헬퍼"""
    dates = pd.bdate_range(start, end)
    return pd.DataFrame({"Close": np.random.rand(len(dates)) * 10 + 15}, index=dates)


# ── 항상 전체 재다운로드 ──────────────────────────────────────────────────────

class TestAlwaysRedownloads:
    """get_data() 호출마다 항상 전체 재다운로드"""

    @patch("src.backtest.cache.yf.download")
    def test_first_call_downloads(self, mock_download, cache):
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix]

        df, vix_df, div_df = cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        assert not df.empty
        assert not vix_df.empty
        # OHLCV+배당 통합(1번) + VIX(1번) = 2번 호출
        assert mock_download.call_count == 2

    @patch("src.backtest.cache.yf.download")
    def test_second_call_also_downloads(self, mock_download, cache):
        """기존 캐시가 있어도 항상 재다운로드한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix, combined, vix]

        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        # 두 번 호출 → 각 2번씩 총 4번
        assert mock_download.call_count == 4

    @patch("src.backtest.cache.yf.download")
    def test_saves_parquet_after_download(self, mock_download, cache):
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-03-31")
        vix = _make_vix("2023-01-01", "2023-03-31")
        mock_download.side_effect = [combined, vix]

        cache.get_data(["SPY"], "2023-01-01", "2023-03-31")

        assert cache.ohlcv_path.exists()
        assert cache.vix_path.exists()
        assert cache.dividends_path.exists()

    @patch("src.backtest.cache.yf.download")
    def test_download_uses_auto_adjust_false_with_actions(self, mock_download, cache):
        """비수정주가(auto_adjust=False)와 actions=True로 다운로드해야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix]

        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        first_call = mock_download.call_args_list[0]
        kwargs = first_call.kwargs if first_call.kwargs else {}
        assert kwargs.get("auto_adjust") is False
        assert kwargs.get("actions") is True


# ── 상장일 기준 시작일 조정 ───────────────────────────────────────────────────

class TestIpoTrim:
    """가장 늦은 상장 티커 기준으로 시작일 조정"""

    @patch("src.backtest.cache.yf.download")
    def test_trims_start_to_latest_ipo(self, mock_download, cache):
        """한 티커의 데이터가 늦게 시작하면 해당 날짜부터 잘라낸다"""
        dates = pd.bdate_range("2022-01-01", "2023-12-31")
        columns = pd.MultiIndex.from_product(
            [["Close", "Open", "High", "Low", "Volume"], ["SPY", "NEW"]]
        )
        data = np.random.rand(len(dates), len(columns)) * 100 + 50
        ohlcv = pd.DataFrame(data, index=dates, columns=columns)

        # NEW 티커는 2023-01-01부터만 데이터 있음
        ipo_date = pd.Timestamp("2023-01-02")  # 첫 영업일
        ohlcv.loc[ohlcv.index < ipo_date, ("Close", "NEW")] = np.nan
        ohlcv.loc[ohlcv.index < ipo_date, ("Open", "NEW")] = np.nan

        vix = _make_vix("2022-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, vix]

        df, _, _ = cache.get_data(["SPY", "NEW"], "2022-01-01", "2023-12-31")

        # 결과 시작일은 NEW 첫 유효일 이상이어야 함
        assert df.index.min() >= ipo_date

    @patch("src.backtest.cache.yf.download")
    def test_no_trim_when_all_tickers_have_full_data(self, mock_download, cache):
        """모든 티커에 데이터가 있으면 시작일 그대로 유지"""
        combined = _make_ohlcv_with_dividends(["SPY", "IEF"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix]

        df, _, _ = cache.get_data(["SPY", "IEF"], "2023-01-01", "2023-12-31")

        expected_start = pd.bdate_range("2023-01-01", "2023-01-10")[0]
        assert df.index.min() <= expected_start

    @patch("src.backtest.cache.yf.download")
    def test_trim_logs_warning(self, mock_download, tmp_cache_dir):
        """시작일 조정 시 logger.warning 호출"""
        dates = pd.bdate_range("2022-01-01", "2023-12-31")
        columns = pd.MultiIndex.from_product(
            [["Close", "Open", "High", "Low", "Volume"], ["SPY", "NEW"]]
        )
        ohlcv = pd.DataFrame(
            np.random.rand(len(dates), len(columns)) * 100 + 50,
            index=dates, columns=columns
        )
        ipo_date = pd.Timestamp("2023-01-02")
        ohlcv.loc[ohlcv.index < ipo_date, ("Close", "NEW")] = np.nan

        vix = _make_vix("2022-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, vix]

        logger = MagicMock()
        cache = BacktestDataCache(cache_dir=tmp_cache_dir, logger=logger)
        cache.get_data(["SPY", "NEW"], "2022-01-01", "2023-12-31")

        warning_msgs = [c.args[0] for c in logger.warning.call_args_list]
        assert any("조정" in m for m in warning_msgs)


# ── NaN ffill 처리 ────────────────────────────────────────────────────────────

class TestFfill:
    """남은 NaN을 이전 값으로 채움"""

    @patch("src.backtest.cache.yf.download")
    def test_fills_remaining_nan_with_ffill(self, mock_download, cache):
        """첫 유효일 이후 소규모 NaN은 ffill로 채워야 한다"""
        dates = pd.bdate_range("2023-01-01", "2023-12-31")
        columns = pd.MultiIndex.from_product([["Close", "Open", "High", "Low", "Volume"], ["SPY"]])
        data = np.random.rand(len(dates), len(columns)) * 100 + 50
        ohlcv = pd.DataFrame(data, index=dates, columns=columns)

        # 중간에 NaN 3개 삽입
        ohlcv.iloc[10, 0] = np.nan
        ohlcv.iloc[11, 0] = np.nan
        ohlcv.iloc[12, 0] = np.nan

        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, vix]

        df, _, _ = cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        # ffill 후 NaN 없어야 함
        assert not df["Close"]["SPY"].isna().any()


# ── OHLCV 필드 정리 ───────────────────────────────────────────────────────────

class TestOhlcvFields:
    """OHLCV 필드 외 컬럼 제거"""

    @patch("src.backtest.cache.yf.download")
    def test_ohlcv_does_not_contain_dividends_column(self, mock_download, cache):
        """OHLCV DataFrame에 Dividends 컬럼이 없어야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-06-30")
        vix = _make_vix("2023-01-01", "2023-06-30")
        mock_download.side_effect = [combined, vix]

        df, _, _ = cache.get_data(["SPY"], "2023-01-01", "2023-06-30")

        ohlcv_fields = df.columns.get_level_values(0).unique().tolist()
        assert "Dividends" not in ohlcv_fields

    @patch("src.backtest.cache.yf.download")
    def test_dividends_extracted_correctly(self, mock_download, cache):
        """배당 데이터가 통합 다운로드에서 올바르게 추출되어야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-06-30")
        vix = _make_vix("2023-01-01", "2023-06-30")
        mock_download.side_effect = [combined, vix]

        _, _, div_df = cache.get_data(["SPY"], "2023-01-01", "2023-06-30")

        assert "SPY" in div_df.columns
        assert (div_df["SPY"] > 0).any()

    @patch("src.backtest.cache.yf.download")
    def test_ohlcv_does_not_contain_adj_close(self, mock_download, cache):
        """OHLCV DataFrame에 Adj Close 컬럼이 없어야 한다 (비수정주가)"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-06-30")
        vix = _make_vix("2023-01-01", "2023-06-30")
        mock_download.side_effect = [combined, vix]

        df, _, _ = cache.get_data(["SPY"], "2023-01-01", "2023-06-30")

        ohlcv_fields = df.columns.get_level_values(0).unique().tolist()
        assert "Adj Close" not in ohlcv_fields


# ── 단일 티커 정규화 ──────────────────────────────────────────────────────────

class TestSingleTickerNormalization:
    """단일 티커 다운로드 시 MultiIndex 정규화"""

    @patch("src.backtest.cache.yf.download")
    def test_single_ticker_normalized_to_multiindex(self, mock_download, cache):
        dates = pd.bdate_range("2023-01-01", "2023-03-31")
        single_df = pd.DataFrame(
            {"Close": [100.0] * len(dates), "Open": [99.0] * len(dates)},
            index=dates,
        )
        vix = _make_vix("2023-01-01", "2023-03-31")
        mock_download.side_effect = [single_df, vix]

        df, _, _ = cache.get_data(["SPY"], "2023-01-01", "2023-03-31")

        assert isinstance(df.columns, pd.MultiIndex)
        assert "SPY" in df.columns.get_level_values(1).unique()


# ── 다운로드 실패 처리 ────────────────────────────────────────────────────────

class TestDownloadFailure:
    """다운로드 실패 처리"""

    @patch("src.backtest.cache.yf.download")
    def test_ohlcv_download_failure_raises_valueerror(self, mock_download, cache):
        """OHLCV 다운로드 실패 시 ValueError를 발생시킨다"""
        mock_download.side_effect = Exception("Network error")

        with pytest.raises(ValueError, match="다운로드 실패"):
            cache.get_data(["SPY"], "2023-01-01", "2023-12-31")


# ── 캐시 삭제 ─────────────────────────────────────────────────────────────────

class TestClear:
    """캐시 삭제"""

    @patch("src.backtest.cache.yf.download")
    def test_clear_removes_files(self, mock_download, cache):
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-03-31")
        vix = _make_vix("2023-01-01", "2023-03-31")
        mock_download.side_effect = [combined, vix]
        cache.get_data(["SPY"], "2023-01-01", "2023-03-31")

        assert cache.ohlcv_path.exists()
        cache.clear()
        assert not cache.ohlcv_path.exists()
        assert not cache.vix_path.exists()
        assert not cache.dividends_path.exists()


# ── 로거 ─────────────────────────────────────────────────────────────────────

class TestLogger:
    """ILogger 의존성 주입 테스트"""

    def _make_mock_logger(self):
        logger = MagicMock()
        logger.info = MagicMock()
        logger.warning = MagicMock()
        logger.error = MagicMock()
        return logger

    @patch("src.backtest.cache.yf.download")
    def test_logger_info_called_on_download(self, mock_download, tmp_cache_dir):
        """다운로드 시 logger.info가 호출되어야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix]

        logger = self._make_mock_logger()
        cache = BacktestDataCache(cache_dir=tmp_cache_dir, logger=logger)
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        assert logger.info.called

    @patch("src.backtest.cache.yf.download")
    def test_logger_warning_called_on_download_failure(self, mock_download, tmp_cache_dir):
        """다운로드 실패 시 logger.warning이 호출되어야 한다"""
        mock_download.side_effect = Exception("Network error")

        logger = self._make_mock_logger()
        cache = BacktestDataCache(cache_dir=tmp_cache_dir, logger=logger)

        with pytest.raises(ValueError):
            cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        warning_messages = [c.args[0] for c in logger.warning.call_args_list]
        assert any("다운로드 실패" in m for m in warning_messages)

    @patch("src.backtest.cache.yf.download")
    def test_logger_info_called_on_clear(self, mock_download, tmp_cache_dir):
        """캐시 삭제 시 logger.info가 호출되어야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-03-31")
        vix = _make_vix("2023-01-01", "2023-03-31")
        mock_download.side_effect = [combined, vix]

        logger = self._make_mock_logger()
        cache = BacktestDataCache(cache_dir=tmp_cache_dir, logger=logger)
        cache.get_data(["SPY"], "2023-01-01", "2023-03-31")
        logger.info.reset_mock()

        cache.clear()

        info_messages = [c.args[0] for c in logger.info.call_args_list]
        assert any("삭제" in m for m in info_messages)

    @patch("src.backtest.cache.yf.download")
    def test_no_logger_works_with_null_logger(self, mock_download, tmp_cache_dir):
        """logger 없이도 오류 없이 동작해야 한다 (NullLogger)"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix]

        cache = BacktestDataCache(cache_dir=tmp_cache_dir)
        df, vix_df, _ = cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        assert not df.empty
        assert not vix_df.empty
