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

from src.core.models import Portfolio, Order, OrderAction
from src.core.logic.sso_dip_signals import SsoDipSignals


class SignalLevel(str, Enum):
    IDLE = "IDLE"
    BUY_STAGE_1 = "BUY_STAGE_1"
    BUY_STAGE_2 = "BUY_STAGE_2"
    BUY_STAGE_3 = "BUY_STAGE_3"
    SELL = "SELL"


# IDLE 기본 SSO 비중 (상승장에서도 SSO 수익에 참여)
IDLE_TARGET = 0.20
IDLE_SPEED = 0.10

# 매수 단계 정의: (level, rsi_threshold, deviation_threshold, target_ratio, speed)
BUY_STAGES = [
    (SignalLevel.BUY_STAGE_3, 36.0, -0.26, 0.80, 0.40),
    (SignalLevel.BUY_STAGE_2, 42.0, -0.18, 0.60, 0.20),
    (SignalLevel.BUY_STAGE_1, 48.0, -0.10, 0.40, 0.10),
]

SELL_CONDITION = {"rsi": 72.0, "deviation": 0.13}
SELL_TARGET = 0.20
SELL_SPEED = 0.10

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

    def to_dict(self) -> dict:
        return {"level": self.level.value}

    @classmethod
    def from_dict(cls, data: dict) -> "SsoDipState":
        data = data or {}
        level_str = data.get("level", SignalLevel.IDLE.value)
        try:
            level = SignalLevel(level_str)
        except ValueError:
            level = SignalLevel.IDLE
        return cls(level=level)


class SsoDipPlanner:
    """신호 기반 SSO/SPYI 분할매수/매도 플래너."""

    SSO_TICKER = "SSO"
    SPYI_TICKER = "SPYI"

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

        target_ratio, speed = self._get_target_and_speed(new_level)

        # 매도 완료 체크 (40% 이하 도달 시 IDLE 복귀)
        if new_level == SignalLevel.SELL and current_sso_ratio <= SELL_TARGET + 0.005:
            new_level = SignalLevel.IDLE
            target_ratio, speed = self._get_target_and_speed(new_level)

        delta_ratio = (target_ratio - current_sso_ratio) * speed
        delta_amount = delta_ratio * total

        orders: List[Order] = []
        reasons: List[str] = []

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
                reasons.append(f"{new_level.value} 분할매수 SSO {qty}주")

        elif delta_amount < 0:
            sell_amount = abs(delta_amount)
            qty = min(
                math.ceil(sell_amount / sso_price),
                portfolio.holdings.get(self.SSO_TICKER, 0),
            )
            if qty > 0:
                orders.append(Order(self.SSO_TICKER, OrderAction.SELL, qty, sso_price))
                reasons.append(f"분할매도 SSO {qty}주")
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
                reasons.append(f"SPYI 스윕 {sweep_qty}주")

        reason = " / ".join(reasons) if reasons else f"대기({new_level.value})"
        return orders, reason, SsoDipState(level=new_level)

    def _detect_signal(self, rsi: float, dev: float, current: SignalLevel) -> SignalLevel:
        if current != SignalLevel.SELL and rsi >= SELL_CONDITION["rsi"] and dev >= SELL_CONDITION["deviation"]:
            return SignalLevel.SELL

        current_order = _LEVEL_ORDER.get(current, 0)
        for level, rsi_th, dev_th, _, _ in BUY_STAGES:
            if _LEVEL_ORDER[level] > current_order and rsi <= rsi_th and dev <= dev_th:
                return level

        return current

    def _get_target_and_speed(self, level: SignalLevel) -> Tuple[float, float]:
        if level == SignalLevel.SELL:
            return SELL_TARGET, SELL_SPEED
        for lv, _, _, target, speed in BUY_STAGES:
            if lv == level:
                return target, speed
        return IDLE_TARGET, IDLE_SPEED

    def _sso_ratio(self, pf: Portfolio) -> float:
        total = pf.total_value
        if total <= 0:
            return 0.0
        sso_val = pf.holdings.get(self.SSO_TICKER, 0) * pf.current_prices.get(self.SSO_TICKER, 0.0)
        return sso_val / total
