import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

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
    ORDERED = "ORDERED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"

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
    # 리밸런싱 진단값 (프론트 이격도 시계열용). 리밸런서를 거치지 않는
    # 신호(NaN/가격조회 실패/모니터링)에서는 None.
    target_ratio_a: float | None = None       # 해당 국면의 목표 A그룹 비율(eff_a)
    rebalance_threshold: float | None = None  # 해당 국면의 리밸런싱 임계치

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


@dataclass(frozen=True)
class OrderOutcome:
    """주문 한 건의 최종 관측 결과.

    ``order``는 전략이 요청한 원본 주문이며, 수량 조정이 있었다면
    ``execution``에 실제 수량이 기록된다.
    """

    order: Order
    status: ExecutionStatus
    execution: Optional[TradeExecution] = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.execution is not None and self.execution.status != self.status:
            raise ValueError("outcome status must match execution status")


@dataclass
class OrderBatchResult:
    """한 번의 브로커 호출에서 요청한 모든 주문의 결과."""

    outcomes: List[OrderOutcome]

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def actual_executions(self) -> List[TradeExecution]:
        """현금·보유수량에 반영 가능한 실제 체결만 반환한다."""
        fill_statuses = {ExecutionStatus.FILLED, ExecutionStatus.PARTIAL}
        return [
            outcome.execution
            for outcome in self.outcomes
            if outcome.status in fill_statuses
            and outcome.execution is not None
            and outcome.execution.quantity > 0
        ]

    @property
    def warning_outcomes(self) -> List[OrderOutcome]:
        warning_statuses = {
            ExecutionStatus.PARTIAL,
            ExecutionStatus.ORDERED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.ERROR,
        }
        return [
            outcome for outcome in self.outcomes
            if outcome.status in warning_statuses
        ]

    @property
    def has_warnings(self) -> bool:
        return bool(self.warning_outcomes)

    def count(self, status: ExecutionStatus) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)

    @property
    def reported_executions(self) -> List[TradeExecution]:
        """브로커가 상세 객체를 돌려준 결과(미체결 상태 포함)."""
        return [
            outcome.execution
            for outcome in self.outcomes
            if outcome.execution is not None
        ]

    # 과도기 호환: 기존 브로커 테스트가 상세 응답 리스트처럼 읽을 수 있게 한다.
    # 도메인 저장·정산 코드는 반드시 actual_executions를 사용한다.
    def __iter__(self):
        return iter(self.reported_executions)

    def __len__(self) -> int:
        return len(self.reported_executions)

    def __getitem__(self, index):
        return self.reported_executions[index]


@dataclass
class StrategyDecision:
    """전략 훅이 공통 실행 흐름에 전달하는 순수 결정."""

    signal: TradeSignal
    label: str = "Rebalancing"
    is_rebalancing: bool = True
    state_key: Optional[str] = None
    proposed_state: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class DecisionFactor:
    """엔진의 의사결정 핵심 요소 한 항목 (자기서술적 — 프론트가 그대로 렌더링).

    key: 안정적 식별자 (summary.json 시계열 키로도 사용)
    label: 표시명
    value: 요소 값 (수치 또는 텍스트)
    format: "number" | "percent" | "text" — 프론트 표시 형식
    threshold: 판단 기준값 (있으면 프론트가 기준 대비 강조 표시)
    """
    key: str
    label: str
    value: float | str
    format: str = "number"
    threshold: Optional[float] = None

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
    expected_dividend: float = 0.0
    order_result: Optional[OrderBatchResult] = None
