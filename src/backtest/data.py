# src/backtest/data.py
import pandas as pd
from typing import List
from src.core.interfaces import IDataProvider

class HistoricalDataLoader(IDataProvider):
    def __init__(self, full_data: pd.DataFrame, full_vix: pd.DataFrame):
        self.full_data = full_data  # 전체 10년치 데이터 (MultiIndex)
        self.full_vix = full_vix    # 전체 VIX 데이터
        self.current_date = None    # 시뮬레이션 현재 날짜

    def set_date(self, date):
        self.current_date = date

    def fetch_ohlcv(self, tickers: List[str], days: int = 400) -> pd.DataFrame:
        # [핵심] 전체 데이터에서 current_date 이전 days 만큼만 잘라서 리턴
        end_idx = self.full_data.index.get_loc(self.current_date)
        start_idx = max(0, end_idx - days)

        sliced_df = self.full_data.iloc[start_idx : end_idx + 1]

        # 계약 준수: 단일 종목이면 SingleIndex로 변환
        if len(tickers) == 1 and isinstance(sliced_df.columns, pd.MultiIndex):
            try:
                return sliced_df.xs(tickers[0], axis=1, level=1)
            except KeyError:
                return sliced_df

        return sliced_df

    def fetch_vix(self) -> float:
        # current_date 시점의 VIX 값 리턴
        return self.full_vix.loc[self.current_date]['Close']