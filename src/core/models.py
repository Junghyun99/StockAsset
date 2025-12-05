from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

class MarketRegime(Enum):
    BULL = "Bull"
    BEAR_WEAK = "Bear_Weak"   # 조건 1개 충족
    BEAR_STRONG = "Bear_Strong" # 조건 2개 충족
    SIDEWAYS = "Sideways"
    CRASH = "Crash"

@dataclass(frozen=True)
class MarketData:
    """오늘의 시장 지표 스냅샷"""
    date: str
    spy_price: float
    spy_ma180: float
    spy_volatility: float
    spy_momentum: float
    spy_mdd: float
    vix: float

    def is_risk_condition(self) -> bool:
        """MDD -20% 이하 or VIX 30 이상"""
        return self.spy_mdd < -0.20 or self.vix > 30

@dataclass
class Portfolio:
    """현재 계좌 상태"""
    total_cash: float
    holdings: Dict[str, float]       # {ticker: quantity}
    current_prices: Dict[str, float] # {ticker: price}

    @property
    def total_value(self) -> float:
        stock_val = sum(q * self.current_prices.get(t, 0) for t, q in self.holdings.items())
        return self.total_cash + stock_val

    def get_group_value(self, tickers: List[str]) -> float:
        """특정 종목 그룹의 평가액 합계"""
        return sum(self.holdings.get(t, 0) * self.current_prices.get(t, 0) for t in tickers)

@dataclass
class Order:
    ticker: str
    action: str  # "BUY" or "SELL"
    quantity: int
    price: float # 예상가

@dataclass
class TradeSignal:
    """전략 판단 결과"""
    target_exposure: float
    rebalance_needed: bool
    orders: List[Order]
    reason: str

@dataclass
class TradeExecution:
    """실제 체결된 매매 결과 (영수증)"""
    ticker: str
    action: str   # "BUY" or "SELL"
    quantity: int # 실제 체결 수량
    price: float  # 실제 체결 단가 (평균단가)
    fee: float    # 수수료
    date: str     # 체결 시간
    status: str   # "FILLED" (체결), "PARTIAL" (부분체결), "REJECTED" (거부)
    reason: str = "" # 거부 사유 등