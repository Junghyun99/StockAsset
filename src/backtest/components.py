# src/backtest/components.py
import pandas as pd
from dataclasses import replace
from typing import List, Dict, Optional
from src.core.interfaces import IDataProvider, IBrokerAdapter, ILogger, IDividendRateProvider, IDividendSettlement
from src.core.models import Order, OrderBatchResult, Portfolio, TradeExecution
from src.infra.broker import MockBroker # 기능 재사용

class BacktestDataLoader(IDataProvider, IDividendRateProvider):
    def __init__(self, full_df: pd.DataFrame, full_vix: pd.DataFrame,
                 dividends: Optional[pd.DataFrame] = None):
        self.full_df = full_df
        self.full_vix = full_vix
        self.dividends = dividends if dividends is not None else pd.DataFrame()
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
        # VIX 데이터가 아예 없을 때(빈 DF)만 기본값 20.0으로 폴백한다.
        if self.full_vix is None or self.full_vix.empty:
            return 20.0

        # asof: 인덱스에 딱 맞는 값이 없으면 직전 값을 가져옴
        idx = self.full_vix.index.get_indexer([self.current_date], method='pad')[0]
        if idx < 0:
            # current_date가 VIX 데이터 시작 이전 → 직전 값이 없으므로 첫 값 사용
            idx = 0

        close = self.full_vix['Close'].iloc[idx]
        # 포맷 계약 검증: 'Close'는 단일 레벨 스칼라여야 한다.
        # MultiIndex 컬럼(예: ('Close','^VIX'))을 넘기면 close가 Series가 되고,
        # 과거 구현은 이를 bare except로 삼켜 매 사이클 상수 VIX(20.0)를 반환 →
        # VIX≥30 국면 판정이 영영 발동하지 않아 백테스트가 조용히 오염됐다.
        # 조용히 폴백하지 말고 명시적으로 실패시켜 데이터 포맷 오류를 드러낸다.
        if not pd.api.types.is_scalar(close):
            raise TypeError(
                f"VIX 'Close'가 스칼라가 아닙니다: {type(close).__name__}. "
                "full_vix는 단일 레벨 'Close' 컬럼을 가져야 합니다 "
                "(MultiIndex 컬럼이면 xs('^VIX', axis=1, level=1) 등으로 평탄화 필요)."
            )
        return float(close)

    def get_dividend_rates(self, tickers: List[str], date: str) -> Dict[str, float]:
        target_date = pd.Timestamp(date)
        if self.dividends.empty or target_date not in self.dividends.index:
            return {}
        row = self.dividends.loc[target_date]
        return {
            ticker: float(row[ticker])
            for ticker in tickers
            if ticker in row.index and float(row[ticker]) > 0
        }

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

    def execute_orders(self, orders: List[Order]) -> OrderBatchResult:
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

    def _wait_for_completion(self, timeout: int = 60) -> bool:
        # 백테스트에서는 모든 주문이 즉시 체결됨 (폴링 불필요)
        return True

    def _refresh_balance_from_api(self):
        # 백테스트에서는 API 갱신 및 딜레이 불필요
        pass


class BacktestDividendSettlement(IDividendSettlement):
    """Credits an engine-calculated dividend to the simulated broker."""

    def __init__(self, broker: BacktestBroker):
        self.broker = broker

    def receive_dividend(self, amount: float) -> float:
        self.broker.receive_dividends(amount)
        return amount if amount > 0 else 0.0
