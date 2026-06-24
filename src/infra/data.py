import yfinance as yf
import pandas as pd
from typing import List, Dict
from src.core.interfaces import IDataProvider
# TradeLogger 타입 힌팅을 위해 (선택 사항, TYPE_CHECKING 이용 가능)
# from src.utils.logger import TradeLogger 

class YFinanceLoader(IDataProvider):
    def __init__(self, logger):
        """
        Logger를 주입받아 초기화
        :param logger: src.utils.logger.TradeLogger 인스턴스
        """
        self.logger = logger

    def fetch_ohlcv(self, tickers: List[str], days: int = 365) -> pd.DataFrame:
        self.logger.info(f"[Data] Fetching {tickers} history for {days} days...")
        try:
            df = yf.download(tickers, period=f"{days}d", auto_adjust=False, progress=False)

            if df is None or df.empty:
                raise ValueError("No data fetched from Yahoo Finance.")
                
            if len(tickers) == 1:
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.xs(tickers[0], axis=1, level=1)
            
            return df
        except Exception as e:
            self.logger.error(f"[Data] Error fetching OHLCV: {e}")
            raise e

    def fetch_vix(self) -> float:
        """
        VIX 지수 조회 (안전장치 포함)
        """
        try:
            vix_df = yf.download("^VIX", period="5d", auto_adjust=False, progress=False)

            # 1. 데이터가 비어있는 경우
            if vix_df is None or vix_df.empty:
                self.logger.warning("[Data] VIX DataFrame is empty — fallback to 20.0")
                return 20.0

            # 2. 값 추출 (MultiIndex 대응)
            if isinstance(vix_df.columns, pd.MultiIndex):
                close_series = vix_df.xs('Close', axis=1, level=0)
                if isinstance(close_series, pd.DataFrame):
                    val = close_series.iloc[-1, 0]
                else:
                    val = close_series.iloc[-1]
            else:
                val = vix_df['Close'].iloc[-1]

            vix_value = float(val)
            self.logger.info(f"[Data] VIX fetched: {vix_value:.2f}")
            return vix_value

        except Exception as e:
            # 3. 에러 발생 시
            self.logger.error(f"[Data] Error fetching VIX: {e} — fallback to 20.0")
            return 20.0

    def fetch_daily_dividends(self, tickers: List[str]) -> Dict[str, float]:
        """오늘 날짜의 티커별 주당 배당금 조회. {ticker: div_per_share}.
        배당락일이 아니거나 오류 시 {} 반환.
        """
        from datetime import datetime, timezone, timedelta
        _KST = timezone(timedelta(hours=9))
        try:
            df = yf.download(tickers, period="5d", auto_adjust=False, actions=True, progress=False)
            if df is None or df.empty:
                return {}
            if not isinstance(df.columns, pd.MultiIndex) and len(tickers) == 1:
                df.columns = pd.MultiIndex.from_product([df.columns, tickers])
            level0 = df.columns.get_level_values(0)
            if "Dividends" not in level0:
                return {}
            divs = df["Dividends"]
            if isinstance(divs, pd.Series):
                divs = divs.to_frame(name=tickers[0])
            today_ts = pd.Timestamp(datetime.now(_KST).strftime("%Y-%m-%d"))
            if today_ts not in divs.index:
                return {}
            row = divs.loc[today_ts]
            return {t: float(v) for t, v in row.items() if float(v) > 0}
        except Exception as e:
            self.logger.error(f"[Data] Error fetching dividends: {e} — returning empty")
            return {}

    def fetch_latest_prices(self, tickers: List[str]) -> Dict[str, float]:
        """티커별 최신 종가를 조회한다. {ticker: last_close}.

        벤치마크 등 부가 지표용. 일부 티커만 실패해도 나머지는 반환하며,
        전체 실패 시 {} 반환(호출부에서 매매 로직을 막지 않도록 한다).
        """
        if not tickers:
            return {}
        try:
            df = yf.download(tickers, period="7d", auto_adjust=False, progress=False)
            if df is None or df.empty:
                return {}
            # MultiIndex(field, ticker) → 'Close' 레벨 선택
            if isinstance(df.columns, pd.MultiIndex):
                close = df["Close"]
            else:
                # 단일 티커: 컬럼이 평탄화된 경우
                close = df[["Close"]]
                close.columns = [tickers[0]]
            prices: Dict[str, float] = {}
            for ticker in tickers:
                try:
                    series = close[ticker].dropna()
                    if not series.empty:
                        prices[ticker] = float(series.iloc[-1])
                except (KeyError, IndexError, ValueError):
                    continue
            return prices
        except Exception as e:
            self.logger.error(f"[Data] Error fetching latest prices: {e} — returning empty")
            return {}