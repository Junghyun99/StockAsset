"""Signal-driven fixed-amount DCA planner for leveraged ETF dip buying."""
import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple

from src.core.logic.sso_dip_signals import SsoDipSignals
from src.core.models import ExecutionStatus, Order, OrderAction, Portfolio, TradeExecution


class SignalLevel(str, Enum):
    IDLE = "IDLE"
    BUY_STAGE_1 = "BUY_STAGE_1"
    BUY_STAGE_2 = "BUY_STAGE_2"
    BUY_STAGE_3 = "BUY_STAGE_3"
    SELL = "SELL"


IDLE_TARGET = 0.20
BUY_STAGES = [
    (SignalLevel.BUY_STAGE_3, 36.0, -0.26, 0.80, 3),
    (SignalLevel.BUY_STAGE_2, 42.0, -0.18, 0.60, 5),
    (SignalLevel.BUY_STAGE_1, 48.0, -0.10, 0.40, 10),
]
SELL_CONDITION = {"rsi": 75.0, "deviation": 0.15}
SELL_TARGET = IDLE_TARGET
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
    """Persisted active tranche and, during sales, its return level."""

    level: SignalLevel = SignalLevel.IDLE
    tranche_total: int = 0
    tranche_completed: int = 0
    tranche_amount: float = 0.0
    sell_target_level: SignalLevel | None = None
    forced_at: str | None = None
    forced_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "tranche_total": self.tranche_total,
            "tranche_completed": self.tranche_completed,
            "tranche_amount": self.tranche_amount,
            "sell_target_level": (
                self.sell_target_level.value if self.sell_target_level else None
            ),
            "forced_at": self.forced_at,
            "forced_reason": self.forced_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SsoDipState":
        data = data or {}
        try:
            level = SignalLevel(data.get("level", SignalLevel.IDLE.value))
        except ValueError:
            level = SignalLevel.IDLE
        try:
            sell_target = SignalLevel(data["sell_target_level"])
        except (KeyError, TypeError, ValueError):
            sell_target = None
        return cls(
            level=level,
            tranche_total=int(data.get("tranche_total", 0)),
            tranche_completed=int(data.get("tranche_completed", 0)),
            tranche_amount=float(data.get("tranche_amount", 0.0)),
            sell_target_level=sell_target,
            forced_at=data.get("forced_at"),
            forced_reason=data.get("forced_reason"),
        )


class SsoDipPlanner:
    """Plans fixed-amount tranches and applies the signal transition table."""

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
            return [], "waiting (invalid signal)", state

        lever_price = portfolio.current_prices.get(self.SSO_TICKER, 0.0)
        income_price = portfolio.current_prices.get(self.SPYI_TICKER, 0.0)
        total = portfolio.total_value
        if lever_price <= 0 or income_price <= 0 or total <= 0:
            return [], "waiting (missing portfolio data)", state

        current_ratio = self._sso_ratio(portfolio)
        raw_signal = self._detect_signal(rsi, dev)
        new_state, delta_amount = self._transition(
            raw_signal, current_ratio, total, state,
        )

        orders: List[Order] = []
        reasons: List[str] = []
        progress = (
            f"{new_state.tranche_completed + 1}/{new_state.tranche_total}"
            if new_state.tranche_total else ""
        )

        if delta_amount > 0:
            qty = math.floor(delta_amount / lever_price)
            if qty > 0:
                cost = qty * lever_price
                cash_shortfall = cost - portfolio.total_cash
                if cash_shortfall > 0:
                    income_sell_qty = min(
                        math.ceil(cash_shortfall / income_price),
                        portfolio.holdings.get(self.SPYI_TICKER, 0),
                    )
                    if income_sell_qty > 0:
                        orders.append(Order(
                            self.SPYI_TICKER, OrderAction.SELL, income_sell_qty, income_price,
                        ))
                orders.append(Order(self.SSO_TICKER, OrderAction.BUY, qty, lever_price))
                reasons.append(
                    f"{new_state.level.value} {progress} 분할매수 "
                    f"{self.SSO_TICKER} {qty}주"
                )

        elif delta_amount < 0:
            qty = min(
                math.ceil(abs(delta_amount) / lever_price),
                portfolio.holdings.get(self.SSO_TICKER, 0),
            )
            if qty > 0:
                orders.append(Order(self.SSO_TICKER, OrderAction.SELL, qty, lever_price))
                reasons.append(f"{progress} 분할매도 {self.SSO_TICKER} {qty}주")
                income_qty = math.floor((qty * lever_price) / income_price)
                if income_qty > 0:
                    orders.append(Order(self.SPYI_TICKER, OrderAction.BUY, income_qty, income_price))

        estimated_cash = portfolio.total_cash
        for order in orders:
            if order.action == OrderAction.SELL:
                estimated_cash += order.quantity * order.price
            else:
                estimated_cash -= order.quantity * order.price
        if estimated_cash >= income_price:
            sweep_qty = math.floor(estimated_cash / income_price)
            existing_buy = next(
                (order for order in orders
                 if order.ticker == self.SPYI_TICKER and order.action == OrderAction.BUY),
                None,
            )
            if existing_buy:
                existing_buy.quantity += sweep_qty
            elif sweep_qty > 0:
                orders.append(Order(self.SPYI_TICKER, OrderAction.BUY, sweep_qty, income_price))
            if sweep_qty > 0:
                reasons.append(f"{self.SPYI_TICKER} 스윕 {sweep_qty}주")

        reason = " / ".join(reasons) if reasons else f"대기({new_state.level.value})"
        return orders, reason, new_state

    def _transition(
        self,
        raw_signal: SignalLevel,
        current_ratio: float,
        total: float,
        state: SsoDipState,
    ) -> Tuple[SsoDipState, float]:
        if state.level == SignalLevel.SELL:
            target_level = state.sell_target_level or SignalLevel.IDLE
            target_ratio, _ = self._get_target_and_tranche_count(target_level)
            if self._is_buy_level(raw_signal):
                buy_target, _ = self._get_target_and_tranche_count(raw_signal)
                if buy_target > current_ratio:
                    new_state = self._new_buy_state(
                        raw_signal, current_ratio, total, state.forced_at, state.forced_reason,
                    )
                    return new_state, self._buy_delta(new_state, current_ratio, total)
            if current_ratio <= target_ratio + 0.005:
                return SsoDipState(level=target_level), 0.0
            if state.tranche_total == 0:
                new_state = self._new_sell_state(target_level, current_ratio, total)
                return new_state, self._sell_delta(new_state, current_ratio, total)
            return state, self._sell_delta(state, current_ratio, total)

        if raw_signal == SignalLevel.SELL:
            if state.level == SignalLevel.IDLE:
                idle_state = SsoDipState(level=SignalLevel.IDLE)
                return idle_state, self._idle_delta(current_ratio, total)
            target_level = self._lower_level(state.level)
            target_ratio, _ = self._get_target_and_tranche_count(target_level)
            if current_ratio <= target_ratio + 0.005:
                return SsoDipState(level=target_level), 0.0
            new_state = self._new_sell_state(target_level, current_ratio, total)
            return new_state, self._sell_delta(new_state, current_ratio, total)

        if self._is_buy_level(raw_signal) and raw_signal != state.level:
            buy_target, _ = self._get_target_and_tranche_count(raw_signal)
            if buy_target > current_ratio:
                new_state = self._new_buy_state(
                    raw_signal, current_ratio, total, state.forced_at, state.forced_reason,
                )
                return new_state, self._buy_delta(new_state, current_ratio, total)

        if state.level == SignalLevel.IDLE:
            idle_state = SsoDipState(level=SignalLevel.IDLE)
            return idle_state, self._idle_delta(current_ratio, total)
        if state.tranche_total == 0:
            new_state = self._new_buy_state(
                state.level, current_ratio, total, state.forced_at, state.forced_reason,
            )
            return new_state, self._buy_delta(new_state, current_ratio, total)
        return state, self._buy_delta(state, current_ratio, total)

    def _new_buy_state(
        self,
        level: SignalLevel,
        current_ratio: float,
        total: float,
        forced_at: str | None = None,
        forced_reason: str | None = None,
    ) -> SsoDipState:
        target_ratio, tranche_total = self._get_target_and_tranche_count(level)
        amount = max(target_ratio - current_ratio, 0.0) * total / tranche_total
        return SsoDipState(
            level=level,
            tranche_total=tranche_total,
            tranche_amount=amount,
            forced_at=forced_at,
            forced_reason=forced_reason,
        )

    def _new_sell_state(
        self, target_level: SignalLevel, current_ratio: float, total: float,
    ) -> SsoDipState:
        target_ratio, _ = self._get_target_and_tranche_count(target_level)
        amount = max(current_ratio - target_ratio, 0.0) * total / self._sell_tranche_count
        return SsoDipState(
            level=SignalLevel.SELL,
            tranche_total=self._sell_tranche_count,
            tranche_amount=amount,
            sell_target_level=target_level,
        )

    def _buy_delta(self, state: SsoDipState, current_ratio: float, total: float) -> float:
        if state.tranche_completed >= state.tranche_total:
            return 0.0
        target_ratio, _ = self._get_target_and_tranche_count(state.level)
        remaining = max(target_ratio - current_ratio, 0.0) * total
        return min(state.tranche_amount, remaining)

    def _sell_delta(self, state: SsoDipState, current_ratio: float, total: float) -> float:
        if state.tranche_completed >= state.tranche_total:
            return 0.0
        target_level = state.sell_target_level or SignalLevel.IDLE
        target_ratio, _ = self._get_target_and_tranche_count(target_level)
        remaining = max(current_ratio - target_ratio, 0.0) * total
        return -min(state.tranche_amount, remaining)

    def _idle_delta(self, current_ratio: float, total: float) -> float:
        return (IDLE_TARGET - current_ratio) * total

    def _detect_signal(self, rsi: float, dev: float) -> SignalLevel:
        if rsi >= self._sell_condition["rsi"] and dev >= self._sell_condition["deviation"]:
            return SignalLevel.SELL
        for level, rsi_threshold, dev_threshold, _, _ in self._buy_stages:
            if rsi <= rsi_threshold and dev <= dev_threshold:
                return level
        return SignalLevel.IDLE

    def _get_target_and_tranche_count(self, level: SignalLevel) -> Tuple[float, int]:
        for stage_level, _, _, target, tranche_count in self._buy_stages:
            if stage_level == level:
                return target, tranche_count
        return IDLE_TARGET, 0

    def _lower_level(self, level: SignalLevel) -> SignalLevel:
        if level == SignalLevel.BUY_STAGE_3:
            return SignalLevel.BUY_STAGE_2
        if level == SignalLevel.BUY_STAGE_2:
            return SignalLevel.BUY_STAGE_1
        return SignalLevel.IDLE

    def _is_buy_level(self, level: SignalLevel) -> bool:
        return level in {
            SignalLevel.BUY_STAGE_1,
            SignalLevel.BUY_STAGE_2,
            SignalLevel.BUY_STAGE_3,
        }

    def record_filled_tranche(
        self, state: SsoDipState, executions: List[TradeExecution],
    ) -> SsoDipState:
        if state.tranche_completed >= state.tranche_total:
            return state
        for execution in executions:
            if (
                execution.ticker == self.SSO_TICKER
                and execution.status in (
                    ExecutionStatus.FILLED,
                    ExecutionStatus.PARTIAL,
                )
                and execution.action in (OrderAction.BUY, OrderAction.SELL)
            ):
                return SsoDipState(
                    level=state.level,
                    tranche_total=state.tranche_total,
                    tranche_completed=state.tranche_completed + 1,
                    tranche_amount=state.tranche_amount,
                    sell_target_level=state.sell_target_level,
                    forced_at=state.forced_at,
                    forced_reason=state.forced_reason,
                )
        return state

    def _sso_ratio(self, portfolio: Portfolio) -> float:
        if portfolio.total_value <= 0:
            return 0.0
        value = (
            portfolio.holdings.get(self.SSO_TICKER, 0)
            * portfolio.current_prices.get(self.SSO_TICKER, 0.0)
        )
        return value / portfolio.total_value
