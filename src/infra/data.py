# src/infra/data.py
import yfinance as yf
import pandas as pd
from typing import List
from src.core.interfaces import IDataProvider

class YFinanceLoader(IDataProvider):
    def fetch_ohlcv(self, tickers: List[str], days: int = 365) -> pd.DataFrame:
        print(f"[Data] Fetching {tickers} history for {days} days...")
        
        # yfinance로 데이터 다운로드
        # auto_adjust=True: 배당/분할 수정주가 반영
        df = yf.download(tickers, period=f"{days}d", auto_adjust=True, progress=False)
        
        # 데이터가 비어있는지 체크
        if df.empty:
            raise ValueError("No data fetched from Yahoo Finance.")
            
        # 단일 종목일 경우 컬럼 구조 통일 (MultiIndex 처리)
        if len(tickers) == 1:
            # yfinance 최신 버전은 단일 종목도 MultiIndex로 올 수 있음. 처리 필요.
            if isinstance(df.columns, pd.MultiIndex):
                df = df.xs(tickers[0], axis=1, level=1)
                
        # 종가(Close) 컬럼만 리턴하거나, 전체를 리턴
        # 여기서는 지표 계산기가 전체 데이터를 쓸 수 있도록 그대로 둠
        return df

    def fetch_vix(self) -> float:
        print("[Data] Fetching VIX...")
        vix_df = yf.download("^VIX", period="5d", progress=False)
        if vix_df.empty:
            return 20.0 # 실패 시 안전값 반환
            
        # 최신 종가 반환
        return float(vix_df['Close'].iloc[-1])