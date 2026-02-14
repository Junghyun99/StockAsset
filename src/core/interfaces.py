from abc import ABC, abstractmethod
from typing import Any, List, Dict
from src.core.models import Portfolio, Order, MarketData, TradeSignal, MarketRegime, TradeExecution

class IDataProvider(ABC):
    @abstractmethod
    def fetch_ohlcv(self, tickers: List[str], days: int = 365) -> Any:
        """OHLCV 데이터를 반환한다.

        Args:
            tickers: 조회할 종목 코드 리스트 (예: ["SPY"], ["SPY", "IEF"])
            days: 조회할 과거 일수 (기본 365)

        Returns:
            DatetimeIndex를 가진 DataFrame. 반환 구조는 tickers 개수에 따라 다름:

            단일 종목 (len(tickers) == 1):
                SingleIndex 컬럼 ['Open', 'High', 'Low', 'Close', 'Volume'].
                예) df['Close'] → Series

            복수 종목 (len(tickers) > 1):
                MultiIndex 컬럼 (Price, Ticker).
                예) df['Close']['SPY'] → Series

        Raises:
            ValueError: 데이터가 비어있거나 조회 실패 시
        """
        ...
    @abstractmethod
    def fetch_vix(self) -> float: ...

class IBrokerAdapter(ABC):
    @abstractmethod
    def get_portfolio(self) -> Portfolio: ...
    @abstractmethod
    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]: ...
    @abstractmethod
    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]: ...

class ILogger(ABC):
    @abstractmethod
    def info(self, msg: str) -> None: ...
    @abstractmethod
    def warning(self, msg: str) -> None: ...
    @abstractmethod
    def error(self, msg: str) -> None: ...

class INotifier(ABC):
    @abstractmethod
    def send_message(self, message: str) -> None: ...
    @abstractmethod
    def send_alert(self, message: str) -> None: ...