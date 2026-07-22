# src/core/logic/sso_dip_planner.py
"""SSO DipBuy 분할매수/매도 플래너 (순수, 무상태).

주봉 RSI + 200일선 괴리율 신호에 따라 SSO 목표 비중을 결정하고,
갭 비율 방식으로 분할매수/매도 주문을 생성한다.

상태(SsoDipState)는 호출자가 보관·영속화한다 (DipBuyPlanner 패턴 동일).
"""
import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple

from src.core.models import ExecutionStatus, Portfolio, Order, OrderAction, TradeExecution
from src.core.logic.sso_dip_signals import SsoDipSignals


class SignalLevel(str, Enum):
    IDLE = "IDLE"
    BUY_STAGE_1 = "BUY_STAGE_1"
    BUY_STAGE_2 = "BUY_STAGE_2"
    BUY_STAGE_3 = "BUY_STAGE_3"
    SELL = "SELL"


# IDLE 기본 SSO 비중 (상승장에서도 SSO 수익에 참여)
IDLE_TARGET = 0.20

# 매수 단계 정의: (level, rsi_threshold, deviation_threshold, target_ratio, tranche_count)
BUY_STAGES = [
    (SignalLevel.BUY_STAGE_3, 36.0, -0.26, 0.80, 3),
    (SignalLevel.BUY_STAGE_2, 42.0, -0.18, 0.60, 5),
    (SignalLevel.BUY_STAGE_1, 48.0, -0.10, 0.40, 10),
]

SELL_CONDITION = {"rsi": 75.0, "deviation": 0.15}
SELL_TARGET = 0.20
SELL_TRANCHE_COUNT = 10

_LEVEL_ORDER = {
    SignalLevel.IDLE: 0,
    SignalLevel.BUY_STAGE_1: 1,
    SignalLevel.BUY_STAGE_2: 2,
    SignalLevel.BUY_STAGE_3: 3,
    SignalLevel.SELL: -1,
}


@dataclass
class SsoDipState:
    """플래너의 영속 상태."""
    level: SignalLevel = SignalLevel.IDLE
    tranche_total: int = 0
    tranche_completed: int = 0
    tranche_amount: float = 0.0

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "tranche_total": self.tranche_total,
            "tranche_completed": self.tranche_completed,
            "tranche_amount": self.tranche_amount,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SsoDipState":
        data = data or {}
        level_str = data.get("level", SignalLevel.IDLE.value)
        try:
            level = SignalLevel(level_str)
        except ValueError:
            level = SignalLevel.IDLE
        return cls(
            level=level,
            tranche_total=int(data.get("tranche_total", 0)),
            tranche_completed=int(data.get("tranche_completed", 0)),
            tranche_amount=float(data.get("tranche_amount", 0.0)),
        )


class SsoDipPlanner:
    """신호 기반 SSO/SPYI 분할매수/매도 플래너."""

    SSO_TICKER = "SSO"
    SPYI_TICKER = "SPYI"
    _buy_stages = BUY_STAGES
    _sell_condition = SELL_CONDITION
    _sell_target = SELL_TARGET
    _sell_tranche_count = SELL_TRANCHE_COUNT

    def plan(
        self,
        signals: SsoDipSignals,
        portfolio: Portfolio,
        state: SsoDipState,
    ) -> Tuple[List[Order], str, SsoDipState]:
        rsi = signals.weekly_rsi
        dev = signals.ma200_deviation

        if math.isnan(rsi) or math.isnan(dev):
            return [], "대기(지표 불가)", state

        sso_price = portfolio.current_prices.get(self.SSO_TICKER, 0.0)
        spyi_price = portfolio.current_prices.get(self.SPYI_TICKER, 0.0)
        if sso_price <= 0 or spyi_price <= 0:
            return [], "대기(가격 정보 없음)", state

        total = portfolio.total_value
        if total <= 0:
            return [], "대기(자산 없음)", state

        current_sso_ratio = self._sso_ratio(portfolio)
        new_level = self._detect_signal(rsi, dev, state.level)

        target_ratio, tranche_total = self._get_target_and_tranche_count(new_level)

        # 매도 완료 체크 (40% 이하 도달 시 IDLE 복귀)
        if new_level == SignalLevel.SELL and current_sso_ratio <= self._sell_target + 0.005:
            new_level = SignalLevel.IDLE
            target_ratio, tranche_total = self._get_target_and_tranche_count(new_level)

        if new_level == SignalLevel.IDLE:
            new_state = SsoDipState(level=new_level)
            delta_amount = (target_ratio - current_sso_ratio) * total
        else:
            needs_new_tranche = (
                new_level != state.level
                or state.tranche_total == 0
            )
            if needs_new_tranche:
                if new_level == SignalLevel.SELL:
                    remaining_amount = max(current_sso_ratio - target_ratio, 0.0) * total
                else:
                    remaining_amount = max(target_ratio - current_sso_ratio, 0.0) * total
                tranche_amount = remaining_amount / tranche_total if tranche_total else 0.0
                new_state = SsoDipState(
                    level=new_level,
                    tranche_total=tranche_total,
                    tranche_amount=tranche_amount,
                )
            else:
                new_state = state

            if new_state.tranche_completed >= new_state.tranche_total:
                delta_amount = 0.0
            elif new_level == SignalLevel.SELL:
                remaining_amount = max(current_sso_ratio - target_ratio, 0.0) * total
                delta_amount = -min(new_state.tranche_amount, remaining_amount)
            else:
                remaining_amount = max(target_ratio - current_sso_ratio, 0.0) * total
                delta_amount = min(new_state.tranche_amount, remaining_amount)

        orders: List[Order] = []
        reasons: List[str] = []
        tranche_progress = (
            f"{new_state.tranche_completed + 1}/{new_state.tranche_total}"
            if new_state.tranche_total else ""
        )

        if delta_amount > 0:
            qty = math.floor(delta_amount / sso_price)
            if qty > 0:
                cost = qty * sso_price
                cash_shortfall = cost - portfolio.total_cash
                if cash_shortfall > 0:
                    spyi_sell_qty = min(
                        math.ceil(cash_shortfall / spyi_price),
                        portfolio.holdings.get(self.SPYI_TICKER, 0),
                    )
                    if spyi_sell_qty > 0:
                        orders.append(Order(self.SPYI_TICKER, OrderAction.SELL, spyi_sell_qty, spyi_price))
                orders.append(Order(self.SSO_TICKER, OrderAction.BUY, qty, sso_price))
                reasons.append(
                    f"{new_level.value} {tranche_progress} 분할매수 {self.SSO_TICKER} {qty}주"
                )

        elif delta_amount < 0:
            sell_amount = abs(delta_amount)
            qty = min(
                math.ceil(sell_amount / sso_price),
                portfolio.holdings.get(self.SSO_TICKER, 0),
            )
            if qty > 0:
                orders.append(Order(self.SSO_TICKER, OrderAction.SELL, qty, sso_price))
                reasons.append(f"{tranche_progress} 분할매도 {self.SSO_TICKER} {qty}주")
                proceeds = qty * sso_price
                spyi_qty = math.floor(proceeds / spyi_price)
                if spyi_qty > 0:
                    orders.append(Order(self.SPYI_TICKER, OrderAction.BUY, spyi_qty, spyi_price))

        # SPYI 스윕: SSO 주문 후 잔여 현금 전액을 SPYI로 투입
        estimated_cash = portfolio.total_cash
        for o in orders:
            if o.action == OrderAction.SELL:
                estimated_cash += o.quantity * o.price
            else:
                estimated_cash -= o.quantity * o.price
        if estimated_cash >= spyi_price:
            sweep_qty = math.floor(estimated_cash / spyi_price)
            if sweep_qty > 0:
                existing = next(
                    (o for o in orders if o.ticker == self.SPYI_TICKER and o.action == OrderAction.BUY),
                    None,
                )
                if existing:
                    existing.quantity += sweep_qty
                else:
                    orders.append(Order(self.SPYI_TICKER, OrderAction.BUY, sweep_qty, spyi_price))
                reasons.append(f"{self.SPYI_TICKER} 스윕 {sweep_qty}주")

        reason = " / ".join(reasons) if reasons else f"대기({new_level.value})"
        return orders, reason, new_state

    def _detect_signal(self, rsi: float, dev: float, current: SignalLevel) -> SignalLevel:
        if current != SignalLevel.SELL and rsi >= self._sell_condition["rsi"] and dev >= self._sell_condition["deviation"]:
            return SignalLevel.SELL

        current_order = _LEVEL_ORDER.get(current, 0)
        for level, rsi_th, dev_th, _, _ in self._buy_stages:
            if _LEVEL_ORDER[level] > current_order and rsi <= rsi_th and dev <= dev_th:
                return level

        return current

    def _get_target_and_tranche_count(self, level: SignalLevel) -> Tuple[float, int]:
        if level == SignalLevel.SELL:
            return self._sell_target, self._sell_tranche_count
        for lv, _, _, target, tranche_count in self._buy_stages:
            if lv == level:
                return target, tranche_count
        return IDLE_TARGET, 0

    def record_filled_tranche(
        self, state: SsoDipState, executions: List[TradeExecution],
    ) -> SsoDipState:
        """레버리지 ETF의 실제 체결 한 건만 현재 트랜치에 반영한다."""
        if state.tranche_completed >= state.tranche_total:
            return state
        for execution in executions:
            if (
                execution.ticker == self.SSO_TICKER
                and execution.status == ExecutionStatus.FILLED
                and execution.action in (OrderAction.BUY, OrderAction.SELL)
            ):
                return SsoDipState(
                    level=state.level,
                    tranche_total=state.tranche_total,
                    tranche_completed=state.tranche_completed + 1,
                    tranche_amount=state.tranche_amount,
                )
        return state

    def _sso_ratio(self, pf: Portfolio) -> float:
        total = pf.total_value
        if total <= 0:
            return 0.0
        sso_val = pf.holdings.get(self.SSO_TICKER, 0) * pf.current_prices.get(self.SSO_TICKER, 0.0)
        return sso_val / total
