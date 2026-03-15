# src/backtest/components.py
import pandas as pd
from dataclasses import replace
from typing import List, Dict, Optional
from src.core.interfaces import IDataProvider, IBrokerAdapter, ILogger
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

        # current_date 이하의 행 전체 선택
        # loc[:date] 슬라이싱은 날짜가 인덱스에 없는 경우(휴장일 등)에도
        # 해당 날짜 이전의 마지막 데이터까지 올바르게 반환 (ffill 효과)
        cutoff_df = self.full_df.loc[:self.current_date]
            
        # 최근 days 만큼 자르기
        sliced = cutoff_df.tail(days)
        
        # yfinance 포맷 맞추기 (단일/멀티 인덱스 처리)
        if len(tickers) == 1 and isinstance(sliced.columns, pd.MultiIndex):
             # 단일 종목 요청 시 해당 종목 레벨만 추출
             try:
                 return sliced.xs(tickers[0], axis=1, level=1)
             except KeyError:
                 available = list(sliced.columns.get_level_values(1).unique())
                 raise ValueError(
                     f"Ticker '{tickers[0]}' not found in DataFrame. "
                     f"Available tickers: {available}"
                 )
                 
        return sliced

    def fetch_vix(self) -> float:
        # current_date 시점의 VIX (없으면 직전 값)
        try:
            # asof: 인덱스에 딱 맞는 값이 없으면 직전 값을 가져옴
            idx = self.full_vix.index.get_indexer([self.current_date], method='pad')[0]
            return float(self.full_vix.iloc[idx]['Close'])
        except (IndexError, KeyError, TypeError, ValueError):
            return 20.0

class BacktestBroker(MockBroker):
    """
    MockBroker를 상속받되, '현재가'를 API가 아닌
    백테스터가 주입해준 가격(simulation_prices)으로 처리
    """
    def __init__(self, initial_cash: float, logger: Optional[ILogger] = None):
        super().__init__(initial_cash=initial_cash, logger=logger)
        self.simulation_prices = {} # {ticker: price}
        self.current_date = None    # 시뮬레이션 상의 '오늘'

    def set_date(self, date):
        """시뮬레이션 날짜를 설정한다. runner가 매 거래일마다 호출해야 한다."""
        self.current_date = date

    def set_prices(self, prices: Dict[str, float]):
        self.simulation_prices = prices

    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        # 백테스터가 설정해준 가격 리턴
        return {t: self.simulation_prices.get(t, 0.0) for t in tickers}

    def get_portfolio(self) -> Portfolio:
        # 백테스터가 주입한 simulation_prices를 current_prices로 반영
        return Portfolio(
            total_cash=self.cash,
            holdings=self.holdings,
            current_prices=self.simulation_prices
        )

    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]:
        # 주문 객체의 price는 '예상가'일 뿐이므로,
        # 체결은 'simulation_prices'(실제 종가)로 이루어져야 함.

        updated_orders = [
            replace(order, price=self.simulation_prices.get(order.ticker, order.price))
            for order in orders
        ]
        return super().execute_orders(updated_orders)

    def _process_order_internal(self, order: Order) -> TradeExecution:
        """체결 날짜를 실제 현재 시각이 아닌 시뮬레이션 날짜로 기록한다."""
        result = super()._process_order_internal(order)
        if self.current_date is not None:
            sim_date = self.current_date.strftime("%Y-%m-%d")
            return replace(result, date=sim_date)
        return result

    def receive_dividends(self, amount: float) -> None:
        """배당금을 현금으로 수령한다. amount > 0인 경우만 처리."""
        if amount > 0:
            self.cash += amount
            if self.logger:
                self.logger.info(f"[Dividend] +${amount:.2f} 배당금 수령")

    def apply_stock_split(self, ticker: str, ratio: float) -> None:
        """주식분할을 보유 주수에 반영한다. ratio > 1이면 정분할, 0 < ratio < 1이면 역분할."""
        if ratio <= 0 or ratio == 1.0:
            return
        current_shares = self.holdings.get(ticker, 0)
        if current_shares == 0:
            return
        new_shares = int(round(current_shares * ratio))
        self.holdings[ticker] = new_shares
        if self.logger:
            self.logger.info(f"[Split] {ticker}: {current_shares}주 → {new_shares}주 (ratio: {ratio})")

    def _wait_for_completion(self, timeout: int = 60) -> bool:
        # 백테스트에서는 모든 주문이 즉시 체결됨 (폴링 불필요)
        return True

    def _refresh_balance_from_api(self):
        # 백테스트에서는 API 갱신 및 딜레이 불필요
        pass