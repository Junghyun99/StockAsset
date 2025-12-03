import yfinance as yf
import pandas as pd
from typing import List
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
            df = yf.download(tickers, period=f"{days}d", auto_adjust=True, progress=False)
            
            if df.empty:
                raise ValueError("No data fetched from Yahoo Finance.")
                
            if len(tickers) == 1:
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.xs(tickers[0], axis=1, level=1)
            
            return df
        except Exception as e:
            self.logger.error(f"[Data] ❌ Error fetching OHLCV: {e}")
            raise e

    def fetch_vix(self) -> float:
        """
        VIX 지수 조회 (안전장치 포함)
        """
        self.logger.info("[Data] 🔍 Fetching VIX data from Yahoo Finance...")

        try:
            vix_df = yf.download("^VIX", period="5d", progress=False)
            
            # 1. 데이터가 비어있는 경우
            if vix_df.empty:
                self.logger.warning("[Data] ⚠️ VIX DataFrame is empty! Returning safety default: 20.0")
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
            self.logger.info(f"[Data] ✅ VIX successfully fetched: {vix_value:.2f}")
            return vix_value

        except Exception as e:
            # 3. 에러 발생 시
            self.logger.error(f"[Data] ❌ Error fetching VIX: {e}. Returning safety default: 20.0")
            return 20.0
        print("[Data] Fetching VIX...")
        vix_df = yf.download("^VIX", period="5d", progress=False)
        if vix_df.empty:
            return 20.0 # 실패 시 안전값 반환
            
        # 최신 종가 반환
        return float(vix_df['Close'].iloc[-1])   