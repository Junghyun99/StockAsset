# tests/test_backtest_cache.py
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock
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


def _make_ohlcv(tickers, start, end):
    """MultiIndex OHLCV DataFrame 생성 헬퍼 (날짜 범위 기반)"""
    dates = pd.bdate_range(start, end)
    price_types = ["Close", "Open", "High", "Low", "Volume"]
    columns = pd.MultiIndex.from_product([price_types, tickers])
    data = np.random.rand(len(dates), len(columns)) * 100 + 50
    return pd.DataFrame(data, index=dates, columns=columns)


def _make_vix(start, end):
    """VIX DataFrame 생성 헬퍼 (날짜 범위 기반)"""
    dates = pd.bdate_range(start, end)
    return pd.DataFrame(
        {"Close": np.random.rand(len(dates)) * 10 + 15}, index=dates
    )


def _make_dividends_raw(tickers, start, end):
    """yf.download(actions=True) 형식의 배당 raw 데이터 mock.
    MultiIndex columns (('Dividends', ticker)) 형태로 반환.
    """
    dates = pd.bdate_range(start, end)
    columns = pd.MultiIndex.from_product([["Dividends"], tickers])
    return pd.DataFrame(0.0, index=dates, columns=columns)


class TestCacheMiss:
    """캐시가 없을 때 전체 다운로드"""

    @patch("src.backtest.cache.yf.download")
    def test_no_cache_downloads_all(self, mock_download, cache):
        combined = _make_ohlcv_with_dividends(["SPY", "IEF"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix]

        df, vix_df, div_df = cache.get_data(["SPY", "IEF"], "2023-01-01", "2023-12-31")

        assert not df.empty
        assert not vix_df.empty
        # OHLCV+배당 통합(1번) + VIX(1번) = 2번 호출
        assert mock_download.call_count == 2
        # parquet 파일 생성 확인
        assert cache.ohlcv_path.exists()
        assert cache.vix_path.exists()
        assert cache.dividends_path.exists()

    @patch("src.backtest.cache.yf.download")
    def test_saves_and_loads_parquet(self, mock_download, cache):
        ohlcv = _make_ohlcv(["SPY"], "2023-01-01", "2023-03-31")
        vix = _make_vix("2023-01-01", "2023-03-31")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-03-31")
        mock_download.side_effect = [ohlcv, vix, divs]

        cache.get_data(["SPY"], "2023-01-01", "2023-03-31")

        # 저장된 파일을 다시 읽어서 확인
        loaded = pd.read_parquet(cache.ohlcv_path)
        assert len(loaded) == len(ohlcv)


class TestCacheHit:
    """캐시가 요청 범위를 완전히 포함할 때"""

    @patch("src.backtest.cache.yf.download")
    def test_full_hit_no_download(self, mock_download, cache):
        # 1차: 넓은 범위로 캐시 생성
        ohlcv = _make_ohlcv(["SPY", "IEF"], "2022-01-01", "2023-12-31")
        vix = _make_vix("2022-01-01", "2023-12-31")
        divs = _make_dividends_raw(["SPY", "IEF"], "2022-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, vix, divs]
        cache.get_data(["SPY", "IEF"], "2022-01-01", "2023-12-31")

        # 2차: 더 좁은 범위로 요청 → 다운로드 없어야 함
        mock_download.reset_mock()
        df, vix_df, _ = cache.get_data(["SPY", "IEF"], "2022-06-01", "2023-06-30")

        assert not df.empty
        mock_download.assert_not_called()

    @patch("src.backtest.cache.yf.download")
    def test_same_range_no_download(self, mock_download, cache):
        # 동일 범위 두 번 요청
        ohlcv = _make_ohlcv(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, vix, divs]
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        mock_download.reset_mock()
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")
        mock_download.assert_not_called()

    @patch("src.backtest.cache.yf.download")
    def test_tolerance_no_download_for_small_gap(self, mock_download, cache):
        """주말/공휴일로 인한 미세한 날짜 차이는 다운로드 안 함"""
        # 캐시: 2023-01-02 (월) ~ 2023-12-29 (금)
        ohlcv = _make_ohlcv(["SPY"], "2023-01-02", "2023-12-29")
        vix = _make_vix("2023-01-02", "2023-12-29")
        divs = _make_dividends_raw(["SPY"], "2023-01-02", "2023-12-29")
        mock_download.side_effect = [ohlcv, vix, divs]
        cache.get_data(["SPY"], "2023-01-02", "2023-12-29")

        # 요청: 2023-01-01 (일) ~ 2023-12-31 (일)
        # → 차이가 tolerance(7일) 이내이므로 다운로드 없어야 함
        mock_download.reset_mock()
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")
        mock_download.assert_not_called()


class TestDateExtension:
    """날짜 범위 확장 시 부족분만 다운로드"""

    @patch("src.backtest.cache.yf.download")
    def test_extend_earlier_dates(self, mock_download, cache):
        # 1차: 2023년 데이터 캐시
        combined_2023 = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-12-31")
        vix_2023 = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined_2023, vix_2023]
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        # 2차: 2022년부터 요청 → 앞쪽 부족분만 다운로드
        mock_download.reset_mock()
        combined_gap = _make_ohlcv_with_dividends(["SPY"], "2022-01-01", "2022-12-31")
        vix_gap = _make_vix("2022-01-01", "2022-12-31")
        mock_download.side_effect = [combined_gap, vix_gap]

        df, vix_df, _ = cache.get_data(["SPY"], "2022-01-01", "2023-12-31")

        # OHLCV+배당 통합(1번) + VIX(1번) = 2번 (앞쪽 부족분만)
        assert mock_download.call_count == 2
        assert not df.empty

    @patch("src.backtest.cache.yf.download")
    def test_extend_later_dates(self, mock_download, cache):
        # 1차: 2023년 전반기 캐시
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-06-30")
        vix = _make_vix("2023-01-01", "2023-06-30")
        mock_download.side_effect = [combined, vix]
        cache.get_data(["SPY"], "2023-01-01", "2023-06-30")

        # 2차: 2023년 전체 요청 → 뒤쪽 부족분만 다운로드
        mock_download.reset_mock()
        combined_gap = _make_ohlcv_with_dividends(["SPY"], "2023-07-01", "2023-12-31")
        vix_gap = _make_vix("2023-07-01", "2023-12-31")
        mock_download.side_effect = [combined_gap, vix_gap]

        df, vix_df, _ = cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        # OHLCV+배당 통합(1번) + VIX(1번) = 2번 (뒤쪽 부족분만)
        assert mock_download.call_count == 2
        assert not df.empty


class TestNewTicker:
    """새 티커 추가 시 해당 티커만 다운로드"""

    @patch("src.backtest.cache.yf.download")
    def test_add_new_ticker(self, mock_download, cache):
        # 1차: SPY만 캐시
        ohlcv_spy = _make_ohlcv(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv_spy, vix, divs]
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        # 2차: SPY + IEF 요청 → IEF OHLCV만 추가 다운로드 (VIX + 배당은 캐시 히트)
        mock_download.reset_mock()
        ohlcv_ief = _make_ohlcv(["IEF"], "2023-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv_ief]

        df, vix_df, _ = cache.get_data(["SPY", "IEF"], "2023-01-01", "2023-12-31")

        # IEF OHLCV만 다운로드 (VIX + 배당은 캐시 히트)
        assert mock_download.call_count == 1
        # 병합 결과에 두 티커 모두 있어야 함
        result_tickers = set(df.columns.get_level_values(1).unique())
        assert "SPY" in result_tickers
        assert "IEF" in result_tickers


class TestSingleTickerNormalization:
    """단일 티커 다운로드 시 MultiIndex 정규화"""

    @patch("src.backtest.cache.yf.download")
    def test_single_ticker_normalized_to_multiindex(self, mock_download, cache):
        # yfinance가 SingleIndex를 반환하는 경우 시뮬레이션
        dates = pd.bdate_range("2023-01-01", "2023-03-31")
        single_df = pd.DataFrame(
            {"Close": [100] * len(dates), "Open": [99] * len(dates)},
            index=dates,
        )
        vix = _make_vix("2023-01-01", "2023-03-31")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-03-31")
        mock_download.side_effect = [single_df, vix, divs]

        df, _, _ = cache.get_data(["SPY"], "2023-01-01", "2023-03-31")

        # MultiIndex로 정규화되어야 함
        assert isinstance(df.columns, pd.MultiIndex)
        tickers = list(df.columns.get_level_values(1).unique())
        assert "SPY" in tickers


class TestClear:
    """캐시 삭제"""

    @patch("src.backtest.cache.yf.download")
    def test_clear_removes_files(self, mock_download, cache):
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-03-31")
        vix = _make_vix("2023-01-01", "2023-03-31")
        mock_download.side_effect = [combined, vix]
        cache.get_data(["SPY"], "2023-01-01", "2023-03-31")

        assert cache.ohlcv_path.exists()
        assert cache.vix_path.exists()
        assert cache.dividends_path.exists()

        cache.clear()

        assert not cache.ohlcv_path.exists()
        assert not cache.vix_path.exists()
        assert not cache.dividends_path.exists()


class TestVixMergeConsistency:
    """VIX 병합이 _merge_dataframes()와 동일하게 동작하는지 검증"""

    @patch("src.backtest.cache.yf.download")
    def test_vix_merge_fills_nan_from_cached(self, mock_download, cache):
        """VIX 신규 데이터에 NaN이 포함된 경우 캐시 값으로 채워져야 한다."""
        # 1차: 정상 VIX 데이터 캐시
        cached_vix = _make_vix("2023-01-01", "2023-06-30")
        ohlcv = _make_ohlcv(["SPY"], "2023-01-01", "2023-06-30")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-06-30")
        mock_download.side_effect = [ohlcv, cached_vix, divs]
        cache.get_data(["SPY"], "2023-01-01", "2023-06-30")

        # 2차: 새 구간 + 겹치는 날짜에 NaN이 포함된 VIX
        mock_download.reset_mock()
        ohlcv_new = _make_ohlcv(["SPY"], "2023-07-01", "2023-12-31")
        vix_new = _make_vix("2023-07-01", "2023-12-31")
        divs_new = _make_dividends_raw(["SPY"], "2023-07-01", "2023-12-31")
        mock_download.side_effect = [ohlcv_new, vix_new, divs_new]

        _, result_vix, _ = cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        # 병합 결과에 NaN이 없어야 함 (캐시 값이 올바르게 유지)
        assert not result_vix["Close"].isna().any(), "VIX 결과에 NaN이 포함되어 있습니다"

    @patch("src.backtest.cache.yf.download")
    def test_vix_merge_new_data_takes_priority(self, mock_download, cache):
        """겹치는 날짜에서 신규 데이터가 우선 적용되어야 한다."""
        # 1차: 2023년 전체 캐시 (Close=15.0 고정)
        dates_full = pd.bdate_range("2023-01-01", "2023-12-31")
        cached_vix = pd.DataFrame({"Close": [15.0] * len(dates_full)}, index=dates_full)
        ohlcv = _make_ohlcv(["SPY"], "2023-01-01", "2023-12-31")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, cached_vix, divs]
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        # 2차: 뒤쪽 날짜 추가 + 겹치는 구간에 다른 값 (Close=30.0)
        mock_download.reset_mock()
        dates_new = pd.bdate_range("2023-10-01", "2024-03-31")
        vix_new = pd.DataFrame({"Close": [30.0] * len(dates_new)}, index=dates_new)
        ohlcv_new = _make_ohlcv(["SPY"], "2024-01-01", "2024-03-31")
        divs_new = _make_dividends_raw(["SPY"], "2023-10-01", "2024-03-31")
        mock_download.side_effect = [ohlcv_new, vix_new, divs_new]

        _, result_vix, _ = cache.get_data(["SPY"], "2023-01-01", "2024-03-31")

        # 겹치는 구간(2023-10-01 ~ 2023-12-31): 신규 데이터(30.0)가 우선
        overlap_start = pd.Timestamp("2023-10-02")  # 첫 영업일
        overlap_mask = result_vix.index >= overlap_start
        overlap_values = result_vix.loc[overlap_mask, "Close"]
        assert (overlap_values == 30.0).all(), "겹치는 구간에서 신규 VIX 값이 적용되지 않았습니다"


class TestDownloadFailure:
    """다운로드 실패 처리"""

    @patch("src.backtest.cache.yf.download")
    def test_ohlcv_download_failure_returns_none(self, mock_download, cache):
        mock_download.side_effect = Exception("Network error")

        df, vix, _ = cache.get_data(["SPY"], "2023-01-01", "2023-12-31")
        assert df is None
        assert vix is None


class TestLogger:
    """ILogger 의존성 주입 테스트"""

    def _make_mock_logger(self):
        from unittest.mock import MagicMock
        logger = MagicMock()
        logger.info = MagicMock()
        logger.warning = MagicMock()
        logger.error = MagicMock()
        return logger

    @patch("src.backtest.cache.yf.download")
    def test_logger_info_called_on_cache_miss(self, mock_download, tmp_cache_dir):
        """캐시 미스 시 logger.info가 호출되어야 한다"""
        ohlcv = _make_ohlcv(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, vix, divs]

        logger = self._make_mock_logger()
        cache = BacktestDataCache(cache_dir=tmp_cache_dir, logger=logger)
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        assert logger.info.called

    @patch("src.backtest.cache.yf.download")
    def test_logger_info_called_on_cache_hit(self, mock_download, tmp_cache_dir):
        """캐시 히트 시 logger.info가 호출되어야 한다"""
        ohlcv = _make_ohlcv(["SPY"], "2022-01-01", "2023-12-31")
        vix = _make_vix("2022-01-01", "2023-12-31")
        divs = _make_dividends_raw(["SPY"], "2022-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, vix, divs]

        logger = self._make_mock_logger()
        cache = BacktestDataCache(cache_dir=tmp_cache_dir, logger=logger)

        # 1차: 넓은 범위로 캐시 생성
        cache.get_data(["SPY"], "2022-01-01", "2023-12-31")
        logger.info.reset_mock()

        # 2차: 더 좁은 범위 요청 → 캐시 히트
        cache.get_data(["SPY"], "2022-06-01", "2023-06-30")

        # "캐시 히트" 메시지가 포함된 info 호출이 있어야 함
        info_messages = [call.args[0] for call in logger.info.call_args_list]
        assert any("히트" in msg for msg in info_messages)

    @patch("src.backtest.cache.yf.download")
    def test_logger_warning_called_on_download_failure(self, mock_download, tmp_cache_dir):
        """다운로드 실패 시 logger.warning이 호출되어야 한다"""
        mock_download.side_effect = Exception("Network error")

        logger = self._make_mock_logger()
        cache = BacktestDataCache(cache_dir=tmp_cache_dir, logger=logger)
        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        assert logger.warning.called
        warning_messages = [call.args[0] for call in logger.warning.call_args_list]
        assert any("다운로드 실패" in msg for msg in warning_messages)

    @patch("src.backtest.cache.yf.download")
    def test_logger_info_called_on_clear(self, mock_download, tmp_cache_dir):
        """캐시 삭제 시 logger.info가 호출되어야 한다"""
        ohlcv = _make_ohlcv(["SPY"], "2023-01-01", "2023-03-31")
        vix = _make_vix("2023-01-01", "2023-03-31")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-03-31")
        mock_download.side_effect = [ohlcv, vix, divs]

        logger = self._make_mock_logger()
        cache = BacktestDataCache(cache_dir=tmp_cache_dir, logger=logger)
        cache.get_data(["SPY"], "2023-01-01", "2023-03-31")
        logger.info.reset_mock()

        cache.clear()

        info_messages = [call.args[0] for call in logger.info.call_args_list]
        assert any("삭제" in msg for msg in info_messages)

    @patch("src.backtest.cache.yf.download")
    def test_no_logger_works_with_null_logger(self, mock_download, tmp_cache_dir):
        """logger를 전달하지 않아도 오류 없이 동작해야 한다 (NullLogger 사용)"""
        ohlcv = _make_ohlcv(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        divs = _make_dividends_raw(["SPY"], "2023-01-01", "2023-12-31")
        mock_download.side_effect = [ohlcv, vix, divs]

        cache = BacktestDataCache(cache_dir=tmp_cache_dir)  # logger=None
        df, vix_df, _ = cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        assert not df.empty
        assert not vix_df.empty


def _make_ohlcv_with_dividends(tickers, start, end):
    """yf.download(auto_adjust=True, actions=True) 형식의 mock 데이터.
    MultiIndex columns: [Close, Dividends, High, Low, Open, Volume] x tickers
    6번째 영업일에 첫 번째 티커의 배당금 0.5 포함.
    """
    dates = pd.bdate_range(start, end)
    price_types = ["Close", "Dividends", "High", "Low", "Open", "Volume"]
    columns = pd.MultiIndex.from_product([price_types, tickers])
    data = np.zeros((len(dates), len(columns)))
    df = pd.DataFrame(data, index=dates, columns=columns)
    for pt in ["Close", "Open", "High", "Low"]:
        for t in tickers:
            df[(pt, t)] = np.random.rand(len(dates)) * 100 + 50
    if len(dates) > 5:
        df.loc[dates[5], ("Dividends", tickers[0])] = 0.5
    return df


class TestUnifiedDownload:
    """OHLCV와 배당을 단일 yf.download 호출로 처리 (auto_adjust=True, actions=True)"""

    @patch("src.backtest.cache.yf.download")
    def test_cache_miss_calls_download_twice_not_thrice(self, mock_download, cache):
        """캐시 없을 때 yf.download를 2번(OHLCV+배당 통합, VIX)만 호출해야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix]

        df, vix_df, div_df = cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        assert mock_download.call_count == 2
        assert not df.empty
        assert not div_df.empty

    @patch("src.backtest.cache.yf.download")
    def test_ohlcv_download_uses_auto_adjust_true_with_actions(self, mock_download, cache):
        """OHLCV 다운로드 시 auto_adjust=True, actions=True를 사용해야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-12-31")
        vix = _make_vix("2023-01-01", "2023-12-31")
        mock_download.side_effect = [combined, vix]

        cache.get_data(["SPY"], "2023-01-01", "2023-12-31")

        # 첫 번째 호출(OHLCV)에 auto_adjust=True, actions=True 확인
        first_call = mock_download.call_args_list[0]
        kwargs = first_call.kwargs if first_call.kwargs else {}
        assert kwargs.get("auto_adjust") is True
        assert kwargs.get("actions") is True

    @patch("src.backtest.cache.yf.download")
    def test_dividends_extracted_from_combined_download(self, mock_download, cache):
        """배당 데이터가 통합 다운로드에서 올바르게 추출되어야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-06-30")
        vix = _make_vix("2023-01-01", "2023-06-30")
        mock_download.side_effect = [combined, vix]

        _, _, div_df = cache.get_data(["SPY"], "2023-01-01", "2023-06-30")

        assert "SPY" in div_df.columns
        assert (div_df["SPY"] > 0).any(), "배당금 0.5인 날이 존재해야 한다"

    @patch("src.backtest.cache.yf.download")
    def test_ohlcv_does_not_contain_dividends_column(self, mock_download, cache):
        """OHLCV DataFrame에 Dividends 컬럼이 포함되지 않아야 한다"""
        combined = _make_ohlcv_with_dividends(["SPY"], "2023-01-01", "2023-06-30")
        vix = _make_vix("2023-01-01", "2023-06-30")
        mock_download.side_effect = [combined, vix]

        df, _, _ = cache.get_data(["SPY"], "2023-01-01", "2023-06-30")

        ohlcv_fields = df.columns.get_level_values(0).unique().tolist()
        assert "Dividends" not in ohlcv_fields
