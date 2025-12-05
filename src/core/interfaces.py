from abc import ABC, abstractmethod
from typing import List, Dict
import pandas as pd
from src.core.models import Portfolio, Order, MarketData, TradeSignal, MarketRegime, TradeExecution

class IDataProvider(ABC):
    @abstractmethod
    def fetch_ohlcv(self, tickers: List[str], days: int = 365) -> pd.DataFrame: ...
    @abstractmethod
    def fetch_vix(self) -> float: ...

class IBrokerAdapter(ABC):
    @abstractmethod
    def get_portfolio(self) -> Portfolio: ...
    @abstractmethod
    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]: ...
    @abstractmethod
    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]: ...

class INotifier(ABC):
    @abstractmethod
    def send_message(self, message: str) -> None: ...
    @abstractmethod
    def send_alert(self, message: str) -> None: ...