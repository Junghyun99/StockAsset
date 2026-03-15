# src/backtest/cache.py
import pandas as pd
import yfinance as yf
from pathlib import Path
from typing import List, Tuple, Optional
from src.core.interfaces import ILogger

CACHE_DIR = Path(__file__).parent / "cache"

# OHLCV에 포함할 필드 (Adj Close, Dividends, Stock Splits 제외)
# auto_adjust=False: Close는 분할 소급 반영(split-adjusted), 배당 미반영(not dividend-adjusted)
_OHLCV_FIELDS = ["Close", "Open", "High", "Low", "Volume"]


class _NullLogger:
    """로거가 없을 때 사용하는 아무것도 하지 않는 로거"""
    def info(self, msg: str) -> None: pass
    def warning(self, msg: str) -> None: pass
    def error(self, msg: str) -> None: pass


class BacktestDataCache:
    """
    요청할 때마다 기존 캐시를 삭제하고 전체 재다운로드한다.
    증분 merge 없이 항상 깨끗한 데이터를 보장한다.

    저장 위치: src/backtest/cache/
      - ohlcv.parquet
      - vix.parquet
      - dividends.parquet
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
        기존 캐시를 삭제하고 전체 티커를 새로 다운로드한다.
        Close(분할 소급 반영, 배당 미반영)를 사용하며 배당 정보를 별도 저장한다.

        1. 기존 캐시 삭제
        2. 전 티커 일괄 다운로드 (auto_adjust=False)
        3. 가장 늦은 상장 티커 기준으로 시작일 조정 (로그 출력)
        4. 남은 NaN을 이전 값으로 채움 (ffill)
        5. 저장 후 반환

        Returns:
            (ohlcv, vix, dividends)
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        need_start = pd.Timestamp(start_date)
        need_end = pd.Timestamp(end_date)

        # 1. 기존 캐시 삭제
        self.clear()

        # 2. 전체 다운로드
        self._logger.info(f"전체 다운로드 시작: {tickers} ({start_date} ~ {end_date})")
        ohlcv, divs = self._download_ohlcv_and_actions(tickers, need_start, need_end)
        vix = self._download_vix(need_start, need_end)

        if ohlcv is None or ohlcv.empty:
            raise ValueError(f"OHLCV 다운로드 실패: {tickers} ({start_date} ~ {end_date})")

        # 3. 상장일 기준 시작일 조정
        ohlcv = self._trim_to_latest_ipo(ohlcv, tickers)

        # 4. 남은 NaN → 이전 값으로 채움
        nan_before = int(ohlcv.isna().sum().sum())
        if nan_before > 0:
            ohlcv = ohlcv.ffill()
            nan_after = int(ohlcv.isna().sum().sum())
            filled = nan_before - nan_after
            self._logger.info(f"NaN ffill 처리: {filled}개 채움, 잔여 {nan_after}개")

        # 5. 저장
        self._save_parquet(ohlcv, self.ohlcv_path)
        self._save_parquet(divs if divs is not None else pd.DataFrame(), self.dividends_path)
        if vix is not None and not vix.empty:
            self._save_parquet(vix, self.vix_path)

        return (
            ohlcv,
            vix if vix is not None else pd.DataFrame(),
            divs if divs is not None else pd.DataFrame(),
        )

    # ── 상장일 조정 ────────────────────────────────────────

    def _trim_to_latest_ipo(self, ohlcv: pd.DataFrame, tickers: List[str]) -> pd.DataFrame:
        """
        가장 늦은 상장 티커의 첫 유효일을 기준으로 DataFrame 시작일을 조정한다.
        조정이 발생하면 원래 요청 시작일과 조정된 시작일을 로그에 출력한다.
        """
        if not isinstance(ohlcv.columns, pd.MultiIndex):
            return ohlcv

        latest_ipo: Optional[pd.Timestamp] = None
        latest_ticker: Optional[str] = None

        for ticker in tickers:
            if ("Close", ticker) not in ohlcv.columns:
                continue
            first_valid = ohlcv["Close"][ticker].first_valid_index()
            if first_valid is not None and (latest_ipo is None or first_valid > latest_ipo):
                latest_ipo = first_valid
                latest_ticker = ticker

        if latest_ipo is None:
            return ohlcv

        original_start = ohlcv.index.min()
        if latest_ipo > original_start:
            self._logger.warning(
                f"⚠️ 상장일 조정: {latest_ticker} 첫 거래일 {latest_ipo.date()} "
                f"(요청 시작일 {original_start.date()} → 조정 후 시작일 {latest_ipo.date()})"
            )
            ohlcv = ohlcv.loc[latest_ipo:]
        else:
            self._logger.info(f"모든 티커 데이터 정상 (시작일: {original_start.date()})")

        return ohlcv

    # ── 다운로드 ───────────────────────────────────────────

    def _download_ohlcv_and_actions(
        self, tickers: List[str], start: pd.Timestamp, end: pd.Timestamp
    ) -> Tuple[Optional[pd.DataFrame], pd.DataFrame]:
        """
        단일 yf.download(auto_adjust=False, actions=True) 호출로
        OHLCV와 실제 배당금액을 함께 다운로드한다.

        auto_adjust=False: Close는 분할 소급 반영(split-adjusted), 배당 미반영
        actions=True: Dividends 컬럼 포함
        """
        try:
            df = yf.download(
                tickers, start=start, end=end,
                auto_adjust=False, back_adjust=False, actions=True, progress=True
            )
            if df is None or df.empty:
                return None, pd.DataFrame()

            # 단일 티커 + SingleIndex → MultiIndex로 정규화
            if not isinstance(df.columns, pd.MultiIndex) and len(tickers) == 1:
                df.columns = pd.MultiIndex.from_product([df.columns, tickers])

            level0 = df.columns.get_level_values(0)

            # OHLCV 추출 (Adj Close, Dividends, Stock Splits 제외)
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
        self._logger.info("기존 캐시 삭제 완료")
