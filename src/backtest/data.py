# src/backtest/data.py
import pandas as pd
from src.core.interfaces import IDataProvider

class HistoricalDataLoader(IDataProvider):
    def __init__(self, full_data: pd.DataFrame, full_vix: pd.DataFrame):
        self.full_data = full_data  # 전체 10년치 데이터 (MultiIndex)
        self.full_vix = full_vix    # 전체 VIX 데이터
        self.current_date = None    # 시뮬레이션 현재 날짜

    def set_date(self, date):
        self.current_date = date

    def fetch_ohlcv(self, tickers, days=400):
        # [핵심] 전체 데이터에서 current_date 이전 days 만큼만 잘라서 리턴
        # 마치 그 날짜에 API를 호출한 것처럼 속임
        end_idx = self.full_data.index.get_loc(self.current_date)
        start_idx = max(0, end_idx - days)
        
        # Slicing
        sliced_df = self.full_data.iloc[start_idx : end_idx + 1]
        
        # 필요한 종목만 필터링해서 리턴
        return sliced_df # (구조에 맞게 가공 필요)

    def fetch_vix(self):
        # current_date 시점의 VIX 값 리턴
        return self.full_vix.loc[self.current_date]['Close']