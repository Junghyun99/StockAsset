# src/backtest/cache.py
import pandas as pd
import yfinance as yf
from datetime import timedelta
from pathlib import Path
from typing import List, Tuple, Optional
from src.core.interfaces import ILogger

CACHE_DIR = Path(__file__).parent / "cache"

# 주말/공휴일로 인한 날짜 차이 허용 범위 (캘린더 일수)
_DATE_TOLERANCE = timedelta(days=7)

# OHLCV에 포함할 필드 (Dividends, Stock Splits 제외)
_OHLCV_FIELDS = ["Close", "Open", "High", "Low", "Volume"]


# 중간 hole로 간주하는 최소 연속 NaN 거래일 수
_HOLE_MIN_DAYS = 10


def _strip_extra_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    OHLCV 필드 외 컬럼(Adj Close 등)을 제거한다.
    yfinance 버전에 따라 auto_adjust=True 여도 Adj Close가 포함될 수 있다.
    """
    if df is None or df.empty or not isinstance(df.columns, pd.MultiIndex):
        return df
    valid = set(_OHLCV_FIELDS)
    keep = [c for c in df.columns if c[0] in valid]
    return df[keep] if keep else df


def _find_data_holes(
    df: pd.DataFrame, tickers: List[str]
) -> List[Tuple]:
    """
    캐시된 DataFrame에서 각 ticker의 첫 유효일 이후 연속 NaN 구간(hole)을 찾는다.
    _HOLE_MIN_DAYS 이상 연속된 경우만 재다운로드 대상으로 반환한다.

    Returns:
        list of (tickers, start, end, reason) — _process_ohlcv_and_dividends의 downloads 포맷
    """
    if df is None or df.empty or not isinstance(df.columns, pd.MultiIndex):
        return []

    holes = []
    for ticker in tickers:
        if ("Close", ticker) not in df.columns:
            continue
        close = df["Close"][ticker]
        first_valid = close.first_valid_index()
        if first_valid is None:
            continue

        # 첫 유효일 이후 NaN만 검사
        post = close.loc[first_valid:]
        nan_idx = post[post.isna()].index
        if nan_idx.empty:
            continue

        # 연속 구간 묶기
        gap_start = nan_idx[0]
        gap_prev = nan_idx[0]
        for d in nan_idx[1:]:
            if (d - gap_prev).days > 5:  # 5일 이상 끊기면 새 구간
                if len(post.loc[gap_start:gap_prev][post.loc[gap_start:gap_prev].isna()]) >= _HOLE_MIN_DAYS:
                    holes.append(([ticker], gap_start, gap_prev, f"중간 데이터 공백 복구: {ticker}"))
                gap_start = d
            gap_prev = d
        # 마지막 구간
        if len(post.loc[gap_start:gap_prev][post.loc[gap_start:gap_prev].isna()]) >= _HOLE_MIN_DAYS:
            holes.append(([ticker], gap_start, gap_prev, f"중간 데이터 공백 복구: {ticker}"))

    return holes


def _ffill_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    다운로드된 데이터에서 공휴일·거래정지 등 소규모 NaN(≤5 거래일)을 채운다.
    대규모 hole은 채우지 않는다(_find_data_holes 로 별도 처리).
    """
    if df is None or df.empty:
        return df
    return df.ffill(limit=5)


class _NullLogger:
    """로거가 없을 때 사용하는 아무것도 하지 않는 로거"""
    def info(self, msg: str) -> None: pass
    def warning(self, msg: str) -> None: pass
    def error(self, msg: str) -> None: pass


class BacktestDataCache:
    """
    티커 기준 누적 캐시.
    한번 받은 데이터는 다시 받지 않고, 부족분만 추가 다운로드한다.

    저장 위치: src/backtest/cache/
      - ohlcv.parquet: 전체 티커 OHLCV 데이터
      - vix.parquet: VIX 데이터
      - dividends.parquet: 배당 데이터 (ticker별 배당금/주)
    """

    def __init__(self, cache_dir: Path = CACHE_DIR, logger: Optional[ILogger] = None):
        self.cache_dir = Path(cache_dir)
        self.ohlcv_path = self.cache_dir / "ohlcv.parquet"
        self.vix_path = self.cache_dir / "vix.parquet"
        self.dividends_path = self.cache_dir / "dividends.parquet"
        self._logger: ILogger = logger if logger is not None else _NullLogger()

    def get_data(
        self, tickers: List[str], start_date: str, end_date: str
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        캐시를 활용하여 OHLCV + VIX + 배당 데이터 반환.
        부족분만 다운로드하고 캐시를 업데이트한다.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        need_start = pd.Timestamp(start_date)
        need_end = pd.Timestamp(end_date)

        ohlcv, dividends = self._process_ohlcv_and_dividends(tickers, need_start, need_end)
        vix = self._process_vix(need_start, need_end)

        return ohlcv, vix, dividends

    # ── OHLCV + 배당 (통합) ────────────────────────────────

    def _process_ohlcv_and_dividends(
        self, tickers: List[str], need_start: pd.Timestamp, need_end: pd.Timestamp
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        cached_ohlcv = self._load_parquet(self.ohlcv_path)
        cached_divs = self._load_parquet(self.dividends_path)

        if cached_ohlcv is None or cached_ohlcv.empty:
            self._logger.info(f"캐시 없음. 전체 다운로드: {tickers}")
            ohlcv, divs = self._download_ohlcv_and_dividends(tickers, need_start, need_end)
            self._save_parquet(ohlcv, self.ohlcv_path)
            self._save_parquet(divs, self.dividends_path)
            return ohlcv, divs if divs is not None else pd.DataFrame()

        # 비OHLCV 컬럼(Adj Close 등) 제거
        cached_ohlcv = _strip_extra_columns(cached_ohlcv)

        # 캐시된 정보 파악
        cached_tickers = set(self._get_tickers_from_df(cached_ohlcv))
        requested_tickers = set(tickers)
        missing_tickers = requested_tickers - cached_tickers

        cache_start = cached_ohlcv.index.min()
        cache_end = cached_ohlcv.index.max()

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

        # 4. 중간 데이터 공백(hole) 감지 — 기존 캐시에서 누락된 구간 재다운로드
        hole_downloads = _find_data_holes(cached_ohlcv, list(requested_tickers))
        if hole_downloads:
            for h in hole_downloads:
                self._logger.warning(
                    f"⚠️ 캐시 hole 감지: {h[0]} {h[1].date()} ~ {h[2].date()} → 재다운로드"
                )
            downloads.extend(hole_downloads)

        if not downloads:
            self._logger.info("OHLCV 캐시 히트 (다운로드 불필요)")
            return cached_ohlcv, cached_divs if cached_divs is not None else pd.DataFrame()

        # 다운로드 및 병합
        result_ohlcv = cached_ohlcv
        result_divs = cached_divs if cached_divs is not None else pd.DataFrame()

        for dl_tickers, dl_start, dl_end, reason in downloads:
            self._logger.info(f"{reason}: {dl_tickers} ({dl_start.date()} ~ {dl_end.date()})")
            new_ohlcv, new_divs = self._download_ohlcv_and_dividends(dl_tickers, dl_start, dl_end)
            if new_ohlcv is not None and not new_ohlcv.empty:
                result_ohlcv = self._merge_dataframes(result_ohlcv, new_ohlcv)
            if new_divs is not None and not new_divs.empty:
                result_divs = self._merge_dataframes(result_divs, new_divs)

        result_ohlcv = _ffill_ohlcv(result_ohlcv)
        self._save_parquet(result_ohlcv, self.ohlcv_path)
        self._save_parquet(result_divs, self.dividends_path)
        return result_ohlcv, result_divs

    # ── VIX ────────────────────────────────────────────────

    def _process_vix(
        self, need_start: pd.Timestamp, need_end: pd.Timestamp
    ) -> pd.DataFrame:
        cached = self._load_parquet(self.vix_path)

        if cached is None or cached.empty:
            self._logger.info("VIX 캐시 없음. 전체 다운로드")
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
            self._logger.info("VIX 캐시 히트 (다운로드 불필요)")
            return cached

        result = cached
        for dl_start, dl_end in downloads:
            self._logger.info(f"VIX 보충: {dl_start.date()} ~ {dl_end.date()}")
            new_data = self._download_vix(dl_start, dl_end)
            if new_data is not None and not new_data.empty:
                result = self._merge_dataframes(result, new_data)

        self._save_parquet(result, self.vix_path)
        return result

    # ── 다운로드 ───────────────────────────────────────────

    def _download_ohlcv_and_dividends(
        self, tickers: List[str], start: pd.Timestamp, end: pd.Timestamp
    ) -> Tuple[Optional[pd.DataFrame], pd.DataFrame]:
        """
        단일 yf.download(auto_adjust=True, actions=True) 호출로
        조정가 OHLCV와 실제 배당금액을 함께 다운로드한다.
        """
        try:
            df = yf.download(
                tickers, start=start, end=end,
                auto_adjust=True, actions=True, progress=True
            )
            if df is None or df.empty:
                return None, pd.DataFrame()

            # 단일 티커 + SingleIndex → MultiIndex로 정규화
            if not isinstance(df.columns, pd.MultiIndex) and len(tickers) == 1:
                df.columns = pd.MultiIndex.from_product([df.columns, tickers])

            level0 = df.columns.get_level_values(0)

            # OHLCV 추출 (Dividends, Stock Splits 제외)
            available_fields = [f for f in _OHLCV_FIELDS if f in level0]
            ohlcv = df[available_fields]

            # 배당 추출
            if "Dividends" in level0:
                divs = df["Dividends"]
                if isinstance(divs, pd.Series):
                    divs = divs.to_frame(name=tickers[0])
            else:
                divs = pd.DataFrame()

            return ohlcv, divs
        except Exception as e:
            self._logger.warning(f"OHLCV 다운로드 실패: {e}")
            return None, pd.DataFrame()

    def _download_vix(
        self, start: pd.Timestamp, end: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        try:
            df = yf.download("^VIX", start=start, end=end, progress=False)
            return df if df is not None and not df.empty else None
        except Exception as e:
            self._logger.warning(f"VIX 다운로드 실패: {e}")
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
                self._logger.warning(f"캐시 로드 실패 ({path.name}): {e}")
                return None
        return None

    def _save_parquet(self, df: pd.DataFrame, path: Path):
        if df is not None and not df.empty:
            try:
                df.to_parquet(path)
            except Exception as e:
                self._logger.warning(f"캐시 저장 실패 ({path.name}): {e}")

    def clear(self):
        """캐시 파일 삭제"""
        for p in [self.ohlcv_path, self.vix_path, self.dividends_path]:
            if p.exists():
                p.unlink()
        self._logger.info("캐시 삭제 완료")
