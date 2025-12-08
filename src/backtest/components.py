# src/backtest/components.py
import pandas as pd
from typing import List, Dict
from src.core.interfaces import IDataProvider, IBrokerAdapter
from src.core.models import Portfolio, Order, TradeExecution
from src.infra.broker import MockBroker # 기능 재사용

class BacktestDataLoader(IDataProvider):
    def __init__(self, full_df: pd.DataFrame, full_vix: pd.DataFrame):
        self.full_df = full_df
        self.full_vix = full_vix
        self.current_date = None # 시뮬레이션 상의 '오늘'

    def set_date(self, date):
        self.current_date = date

    def fetch_ohlcv(self, tickers: List[str], days: int = 365) -> pd.DataFrame:
        # [Time Travel] current_date 기준 과거 days 만큼 Slicing
        # full_df의 인덱스는 DatetimeIndex여야 함
        
        # 데이터가 없는 날짜(휴장일 등) 처리
        if self.current_date not in self.full_df.index:
            # 해당 날짜가 없으면 가장 가까운 과거 데이터 사용 (ffill 개념)
            # 여기서는 로직 단순화를 위해 해당 날짜까지의 데이터를 자름
            cutoff_df = self.full_df.loc[:self.current_date]
        else:
            cutoff_df = self.full_df.loc[:self.current_date]
            
        # 최근 days 만큼 자르기
        sliced = cutoff_df.tail(days)
        
        # yfinance 포맷 맞추기 (단일/멀티 인덱스 처리)
        if len(tickers) == 1 and isinstance(sliced.columns, pd.MultiIndex):
             # 단일 종목 요청 시 해당 종목 레벨만 추출
             try:
                 return sliced.xs(tickers[0], axis=1, level=1)
             except KeyError:
                 return sliced # 이미 처리된 경우
                 
        return sliced

    def fetch_vix(self) -> float:
        # current_date 시점의 VIX (없으면 직전 값)
        try:
            # asof: 인덱스에 딱 맞는 값이 없으면 직전 값을 가져옴
            idx = self.full_vix.index.get_indexer([self.current_date], method='pad')[0]
            return float(self.full_vix.iloc[idx]['Close'])
        except:
            return 20.0

class BacktestBroker(MockBroker):
    """
    MockBroker를 상속받되, '현재가'를 API가 아닌 
    백테스터가 주입해준 가격(simulation_prices)으로 처리
    """
    def __init__(self, initial_cash: float):
        super().__init__(initial_cash=initial_cash)
        self.simulation_prices = {} # {ticker: price}

    def set_prices(self, prices: Dict[str, float]):
        self.simulation_prices = prices

    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        # 백테스터가 설정해준 가격 리턴
        return {t: self.simulation_prices.get(t, 0.0) for t in tickers}

    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]:
        # 주문 객체의 price는 '예상가'일 뿐이므로, 
        # 체결은 'simulation_prices'(실제 종가)로 이루어져야 함.
        
        updated_orders = []
        for order in orders:
            real_price = self.simulation_prices.get(order.ticker, order.price)
            # 주문 객체의 가격을 그 날의 실제 종가로 강제 수정 (시장가 체결 시뮬레이션)
            order.price = real_price 
            updated_orders.append(order)
            
        return super().execute_orders(updated_orders)