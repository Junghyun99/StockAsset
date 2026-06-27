# src/core/logic/dip_buy_planner.py
"""눌림목 분할매수 플래너 (순수, 무상태).

이동평균선 눌림목·RSI 과매도/과열 트리거를 평가해 트랜치(분할 주문)를 큐에
적재하고, 매 거래일 활성 트랜치의 당일 슬라이스를 합산해 주문을 생성한다.

상태(DipBuyState)는 플래너 내부 필드가 아니라 호출자가 보관·영속화한다.
이로써 백테스트(엔진 재사용)와 라이브(매일 프로세스 재시작)가 동일한 코드 경로를
쓰며, 진실의 원천(source of truth)은 repo의 strategy_state.json이 된다.
"""
import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple

from src.core.models import Portfolio, Order, OrderAction
from src.core.logic.dip_buy_indicators import DipBuySignals

TRIGGERS = ("ma20", "ma60", "ma120", "dip", "sell")


@dataclass
class Tranche:
    """분할 트랜치: 트리거 시점에 고정된 1일 슬라이스 금액과 남은 일수."""
    side: str            # "BUY" | "SELL"
    per_day_amount: float
    remaining_days: int


@dataclass
class DipBuyState:
    """플래너의 영속 상태 (큐 + 트리거 무장 플래그)."""
    queue: List[Tranche] = field(default_factory=list)
    armed: Dict[str, bool] = field(default_factory=lambda: {t: True for t in TRIGGERS})

    def to_dict(self) -> dict:
        return {
            "queue": [asdict(t) for t in self.queue],
            "armed": dict(self.armed),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DipBuyState":
        data = data or {}
        queue = [Tranche(**t) for t in data.get("queue", [])]
        armed = {t: True for t in TRIGGERS}
        armed.update(data.get("armed", {}))
        return cls(queue=queue, armed=armed)


class DipBuyPlanner:
    """눌림목 트리거 → 트랜치 적재 → 당일 슬라이스 주문 (순수, 무상태)."""

    def __init__(self, ticker: str, band: float = 0.02,
                 sell_target_cash_ratio: float = 0.20):
        self.ticker = ticker
        self.band = band
        self.sell_target_cash_ratio = sell_target_cash_ratio

    def plan(self, signals: DipBuySignals, portfolio: Portfolio,
             state: DipBuyState) -> Tuple[List[Order], str, DipBuyState]:
        armed = dict(state.armed)
        queue = list(state.queue)

        # 1. 트리거 평가 + 적재 + 무장/재무장 (엣지 트리거)
        for key, active, make_tranche in self._evaluate_conditions(signals, portfolio):
            if active and armed.get(key, True):
                tranche = make_tranche()
                if tranche is not None:
                    queue.append(tranche)
                armed[key] = False
            elif not active:
                armed[key] = True

        # 2. 당일 슬라이스 합산
        buy_amount = sum(t.per_day_amount for t in queue if t.side == "BUY")
        sell_amount = sum(t.per_day_amount for t in queue if t.side == "SELL")

        # 3. 트랜치 소진 (remaining_days 감소, 0이면 제거)
        next_queue: List[Tranche] = []
        for t in queue:
            t.remaining_days -= 1
            if t.remaining_days > 0:
                next_queue.append(t)
        new_state = DipBuyState(queue=next_queue, armed=armed)

        # 4. 주문 생성 (매도 우선 → 자금 확보 후 매수)
        price = portfolio.current_prices.get(self.ticker, 0.0)
        orders: List[Order] = []
        reasons: List[str] = []

        if price > 0 and sell_amount > 0:
            held = portfolio.holdings.get(self.ticker, 0)
            qty = min(math.ceil(sell_amount / price), held)
            if qty > 0:
                orders.append(Order(self.ticker, OrderAction.SELL, qty, price))
                reasons.append(f"분할매도 {qty}주")

        if price > 0 and buy_amount > 0:
            capped = min(buy_amount, portfolio.total_cash)
            qty = math.floor(capped / price)
            if qty > 0:
                orders.append(Order(self.ticker, OrderAction.BUY, qty, price))
                reasons.append(f"분할매수 {qty}주")

        reason = " / ".join(reasons) if reasons else "대기(트리거 없음)"
        return orders, reason, new_state

    # ── 트리거 조건 평가 ────────────────────────────────────────────
    def _in_band(self, price: float, ma: float) -> bool:
        if ma is None or math.isnan(ma) or ma <= 0:
            return False
        return abs(price / ma - 1.0) <= self.band

    def _evaluate_conditions(self, sig: DipBuySignals, pf: Portfolio):
        cash = pf.total_cash
        rsi_ok = not math.isnan(sig.rsi)

        def buy(ratio: float, days: int):
            return lambda: (
                Tranche("BUY", (cash * ratio) / days, days) if cash > 0 else None
            )

        ma120_valid = not math.isnan(sig.ma120) and sig.ma120 > 0
        dip_active = ma120_valid and sig.price < sig.ma120 and rsi_ok and sig.rsi < 30
        sell_active = rsi_ok and sig.rsi > 70

        return [
            ("ma20", self._in_band(sig.price, sig.ma20), buy(0.10, 1)),
            ("ma60", self._in_band(sig.price, sig.ma60), buy(0.50, 5)),
            ("ma120", self._in_band(sig.price, sig.ma120), buy(0.50, 5)),
            ("dip", dip_active, buy(1.00, 40)),
            ("sell", sell_active, self._make_sell_tranche(sig, pf)),
        ]

    def _make_sell_tranche(self, sig: DipBuySignals, pf: Portfolio):
        """RSI 과열 시 목표 현금비중까지 부족분을 5일 분할 매도하는 트랜치."""
        def factory():
            price = pf.current_prices.get(self.ticker, 0.0)
            holdings_val = pf.holdings.get(self.ticker, 0) * price
            total = pf.total_cash + holdings_val
            if total <= 0 or holdings_val <= 0:
                return None
            target_cash = total * self.sell_target_cash_ratio
            shortfall = target_cash - pf.total_cash
            if shortfall <= 0:
                return None
            sell_amt = min(shortfall, holdings_val)
            return Tranche("SELL", sell_amt / 5, 5)
        return factory
