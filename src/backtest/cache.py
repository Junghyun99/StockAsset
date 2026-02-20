# src/backtest/cache.py
import pandas as pd
import yfinance as yf
from datetime import timedelta
from pathlib import Path
from typing import List, Tuple, Optional

CACHE_DIR = Path(__file__).parent / "cache"

# 주말/공휴일로 인한 날짜 차이 허용 범위 (캘린더 일수)
_DATE_TOLERANCE = timedelta(days=7)


class BacktestDataCache:
    """
    티커 기준 누적 캐시.
    한번 받은 데이터는 다시 받지 않고, 부족분만 추가 다운로드한다.

    저장 위치: src/backtest/cache/
      - ohlcv.parquet: 전체 티커 OHLCV 데이터
      - vix.parquet: VIX 데이터
    """

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.ohlcv_path = self.cache_dir / "ohlcv.parquet"
        self.vix_path = self.cache_dir / "vix.parquet"

    def get_data(
        self, tickers: List[str], start_date: str, end_date: str
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        캐시를 활용하여 OHLCV + VIX 데이터 반환.
        부족분만 다운로드하고 캐시를 업데이트한다.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        need_start = pd.Timestamp(start_date)
        need_end = pd.Timestamp(end_date)

        ohlcv = self._process_ohlcv(tickers, need_start, need_end)
        vix = self._process_vix(need_start, need_end)

        return ohlcv, vix

    # ── OHLCV ──────────────────────────────────────────────

    def _process_ohlcv(
        self, tickers: List[str], need_start: pd.Timestamp, need_end: pd.Timestamp
    ) -> pd.DataFrame:
        cached = self._load_parquet(self.ohlcv_path)

        if cached is None or cached.empty:
            print(f"📥 캐시 없음. 전체 다운로드: {tickers}")
            ohlcv = self._download_ohlcv(tickers, need_start, need_end)
            self._save_parquet(ohlcv, self.ohlcv_path)
            return ohlcv

        # 캐시된 정보 파악
        cached_tickers = set(self._get_tickers_from_df(cached))
        requested_tickers = set(tickers)
        missing_tickers = requested_tickers - cached_tickers

        cache_start = cached.index.min()
        cache_end = cached.index.max()

        downloads = []  # (tickers, start, end, reason)

        # 1. 앞쪽 날짜 부족 (허용 범위 이내 차이는 무시)
        if need_start < cache_start - _DATE_TOLERANCE:
            all_tickers = list(requested_tickers | cached_tickers)
            downloads.append((
                all_tickers,
                need_start,
                cache_start - timedelta(days=1),
                "앞쪽 날짜 보충",
            ))

        # 2. 뒤쪽 날짜 부족 (허용 범위 이내 차이는 무시)
        if need_end > cache_end + _DATE_TOLERANCE:
            all_tickers = list(requested_tickers | cached_tickers)
            downloads.append((
                all_tickers,
                cache_end + timedelta(days=1),
                need_end,
                "뒤쪽 날짜 보충",
            ))

        # 3. 새 티커 추가
        if missing_tickers:
            effective_start = min(need_start, cache_start)
            effective_end = max(need_end, cache_end)
            downloads.append((
                list(missing_tickers),
                effective_start,
                effective_end,
                "새 티커 추가",
            ))

        if not downloads:
            print("✅ OHLCV 캐시 히트 (다운로드 불필요)")
            return cached

        # 다운로드 및 병합
        result = cached
        for dl_tickers, dl_start, dl_end, reason in downloads:
            print(f"📥 {reason}: {dl_tickers} ({dl_start.date()} ~ {dl_end.date()})")
            new_data = self._download_ohlcv(dl_tickers, dl_start, dl_end)
            if new_data is not None and not new_data.empty:
                result = self._merge_dataframes(result, new_data)

        self._save_parquet(result, self.ohlcv_path)
        return result

    # ── VIX ────────────────────────────────────────────────

    def _process_vix(
        self, need_start: pd.Timestamp, need_end: pd.Timestamp
    ) -> pd.DataFrame:
        cached = self._load_parquet(self.vix_path)

        if cached is None or cached.empty:
            print("📥 VIX 캐시 없음. 전체 다운로드")
            vix = self._download_vix(need_start, need_end)
            self._save_parquet(vix, self.vix_path)
            return vix

        cache_start = cached.index.min()
        cache_end = cached.index.max()

        downloads = []
        if need_start < cache_start - _DATE_TOLERANCE:
            downloads.append((need_start, cache_start - timedelta(days=1)))
        if need_end > cache_end + _DATE_TOLERANCE:
            downloads.append((cache_end + timedelta(days=1), need_end))

        if not downloads:
            print("✅ VIX 캐시 히트 (다운로드 불필요)")
            return cached

        result = cached
        for dl_start, dl_end in downloads:
            print(f"📥 VIX 보충: {dl_start.date()} ~ {dl_end.date()}")
            new_data = self._download_vix(dl_start, dl_end)
            if new_data is not None and not new_data.empty:
                result = pd.concat([result, new_data])
                result = result[~result.index.duplicated(keep="last")]
                result = result.sort_index()

        self._save_parquet(result, self.vix_path)
        return result

    # ── 다운로드 ───────────────────────────────────────────

    def _download_ohlcv(
        self, tickers: List[str], start: pd.Timestamp, end: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        try:
            df = yf.download(
                tickers, start=start, end=end, auto_adjust=True, progress=True
            )
            if df is not None and not df.empty:
                # 단일 티커 + SingleIndex → MultiIndex로 정규화
                if not isinstance(df.columns, pd.MultiIndex) and len(tickers) == 1:
                    df.columns = pd.MultiIndex.from_product([df.columns, tickers])
                return df
            return None
        except Exception as e:
            print(f"❌ OHLCV 다운로드 실패: {e}")
            return None

    def _download_vix(
        self, start: pd.Timestamp, end: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        try:
            df = yf.download("^VIX", start=start, end=end, progress=False)
            return df if df is not None and not df.empty else None
        except Exception as e:
            print(f"❌ VIX 다운로드 실패: {e}")
            return None

    # ── 유틸리티 ───────────────────────────────────────────

    def _merge_dataframes(
        self, cached: pd.DataFrame, new_data: pd.DataFrame
    ) -> pd.DataFrame:
        """두 DataFrame 병합. 겹치는 구간은 new_data 우선."""
        if cached is None or cached.empty:
            return new_data
        if new_data is None or new_data.empty:
            return cached

        combined = new_data.combine_first(cached)
        combined = combined.sort_index()
        return combined

    def _get_tickers_from_df(self, df: pd.DataFrame) -> List[str]:
        """MultiIndex DataFrame에서 티커 목록 추출"""
        if isinstance(df.columns, pd.MultiIndex):
            return list(df.columns.get_level_values(1).unique())
        return []

    def _load_parquet(self, path: Path) -> Optional[pd.DataFrame]:
        if path.exists():
            try:
                return pd.read_parquet(path)
            except Exception as e:
                print(f"⚠️ 캐시 로드 실패 ({path.name}): {e}")
                return None
        return None

    def _save_parquet(self, df: pd.DataFrame, path: Path):
        if df is not None and not df.empty:
            try:
                df.to_parquet(path)
            except Exception as e:
                print(f"⚠️ 캐시 저장 실패 ({path.name}): {e}")

    def clear(self):
        """캐시 파일 삭제"""
        for p in [self.ohlcv_path, self.vix_path]:
            if p.exists():
                p.unlink()
        print("🗑️ 캐시 삭제 완료")
