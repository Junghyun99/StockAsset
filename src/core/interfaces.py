from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import pandas as pd
from src.core.models import Portfolio, Order, MarketData, TradeSignal, MarketRegime, TradeExecution

class IDataProvider(ABC):
    @abstractmethod
    def fetch_ohlcv(self, tickers: List[str], days: int = 365) -> pd.DataFrame:
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
    def debug(self, msg: str) -> None: ...
    @abstractmethod
    def info(self, msg: str) -> None: ...
    @abstractmethod
    def warning(self, msg: str) -> None: ...
    @abstractmethod
    def error(self, msg: str) -> None: ...

    # ── 슬랙 댓글용 로그 캡처 (선택적 기능, 기본 no-op) ──────────────
    # 엔진은 이 계약에만 의존한다. 캡처를 지원하지 않는 로거가 주입되어도
    # 기본 구현이 안전하게 degrade하여 AttributeError 없이 동작한다.
    def set_ticker_context(self, ticker: Optional[str]) -> None:
        """이후 캡처되는 로그의 소유 종목을 태깅한다 (기본 no-op)."""
        return None

    def get_captured_logs(self, ticker: Optional[str] = None) -> List[str]:
        """캡처된 로그 메시지 목록을 반환한다 (기본: 빈 리스트)."""
        return []

    def clear_captured_logs(self) -> None:
        """캡처 버퍼를 비운다 (기본 no-op)."""
        return None

class INotifier(ABC):
    @abstractmethod
    def send_message(self, message: str, detail: Optional[str] = None) -> None: ...
    @abstractmethod
    def send_alert(self, message: str, detail: Optional[str] = None) -> None: ...

class IRepository(ABC):
    @abstractmethod
    def get_last_rebalancing_date(self) -> Optional[str]: ...
    @abstractmethod
    def load_last_regime(self) -> Optional[MarketRegime]: ...
    @abstractmethod
    def save_daily_summary(self, market_data: MarketData, signal: TradeSignal,
                           portfolio: Portfolio, regime: MarketRegime,
                           daily_dividend: float = 0.0,
                           date_override: Optional[str] = None) -> None: ...
    @abstractmethod
    def save_trade_history(self, executions: List[TradeExecution], portfolio: Portfolio,
                           reason: str, sim_date: Optional[str] = None) -> None: ...
    @abstractmethod
    def update_status(self, regime: MarketRegime, exposure: float, portfolio: Portfolio,
                      market_data: MarketData, reason: str,
                      sim_date: Optional[str] = None,
                      rebalancing_date: Optional[str] = None) -> None: ...

    # ── 전략 상태 영속화 (선택적 기능, 기본 안전 degrade) ──────────────
    # 상태형 엔진(예: DipBuyEngine의 트랜치 큐)이 프로세스 수명을 넘는 상태를
    # 저장/복원하는 데 사용한다. 미지원 구현체(테스트 더블 등)도 AttributeError
    # 없이 동작하도록 기본 구현을 제공한다 (국면 히스테리시스와 동일 패턴).
    def load_strategy_state(self, key: str) -> dict:
        """저장된 전략 상태를 반환한다 (기본: 빈 dict)."""
        return {}

    def save_strategy_state(self, key: str, state: dict) -> None:
        """전략 상태를 저장한다 (기본 no-op)."""
        return None
