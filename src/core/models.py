import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

class MarketRegime(Enum):
    BULL = "Bull"
    BEAR_WEAK = "Bear_Weak"   # 조건 1개 충족
    BEAR_STRONG = "Bear_Strong" # 조건 2개 충족
    SIDEWAYS = "Sideways"
    CRASH = "Crash"

class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    def __str__(self):
        return self.value

class ExecutionStatus(str, Enum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    ORDERED = "ORDERED"

    def __str__(self):
        return self.value

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

    def nan_fields(self) -> List[str]:
        """NaN인 필드명 리스트 반환"""
        fields = ['spy_price', 'spy_ma180', 'spy_volatility', 'spy_momentum', 'spy_mdd', 'vix']
        return [f for f in fields if math.isnan(getattr(self, f))]

    def is_risk_condition(self) -> bool:
        """MDD -20% 이하 OR (VIX 30 이상 AND MDD -10% 이하)
        VIX 단독 스파이크(MDD 미미)는 CRASH 제외 — 과민 반응 방지"""
        return self.spy_mdd <= -0.20 or (self.vix >= 30 and self.spy_mdd <= -0.10)

@dataclass
class Portfolio:
    """현재 계좌 상태"""
    total_cash: float
    holdings: Dict[str, int]          # {ticker: quantity}
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
    action: OrderAction
    quantity: int
    price: float # 예상가

@dataclass
class TradeSignal:
    """전략 판단 결과"""
    target_exposure: float
    orders: List[Order]
    reason: str

    @property
    def has_orders(self) -> bool:
        return len(self.orders) > 0

@dataclass
class TradeExecution:
    """실제 체결된 매매 결과 (영수증)"""
    ticker: str
    action: OrderAction
    quantity: int # 실제 체결 수량
    price: float  # 실제 체결 단가 (평균단가)
    fee: float    # 수수료
    date: str     # 체결 시간
    status: ExecutionStatus
    reason: str = "" # 거부 사유 등

@dataclass
class DayResult:
    """하루치 트레이딩 사이클 실행 결과"""
    market_data: MarketData
    regime: MarketRegime
    exposure: float
    signal: TradeSignal
    executions: List[TradeExecution]
    final_pf: Portfolio
    is_rebalancing: bool
    nan_fields: List[str]
    daily_dividend: float = 0.0