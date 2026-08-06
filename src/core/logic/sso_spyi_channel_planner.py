"""Stateful order planning for independent SSO and SPYI dip campaigns."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Mapping

from src.core.logic.channel_regime import ChannelSnapshot
from src.core.models import ExecutionStatus, Order, OrderAction, Portfolio, TradeExecution


TICKERS = ("SSO", "SPYI")
CORE_ALLOCATIONS = {"SSO": 0.10, "SPYI": 0.30}
BUY_THRESHOLDS = {
    "SSO": ((48.0, -0.10), (42.0, -0.18), (36.0, -0.26)),
    "SPYI": ((50.0, -0.06), (45.0, -0.10), (40.0, -0.15)),
}
CHANNEL_RULES = {
    "SSO": {
        "stddev_k": 3.0,
        "slope": 16.0,
        "slope_exit_threshold": -6.0,
        "breakdown_margin": 0.03,
        "trailing_drop": 0.08,
    },
    "SPYI": {
        "stddev_k": 2.0,
        "slope": 8.0,
        "slope_exit_threshold": -4.0,
        "breakdown_margin": 0.02,
        "trailing_drop": 0.05,
    },
}
PHASE_WEIGHTS = {1: (0.40, 0.40, 0.20), 2: (0.60, 0.30, 0.10), 3: (0.80, 0.15, 0.05)}


class ExitState(str, Enum):
    NONE = "NONE"
    EXIT_LOCK = "EXIT_LOCK"
    EXIT_SUPPRESSED = "EXIT_SUPPRESSED"


@dataclass(frozen=True)
class AssetInput:
    date: str
    weekly_rsi: float
    ma200_deviation: float
    channel: ChannelSnapshot


@dataclass
class AssetState:
    core_target_quantity: int = 0
    core_quantity: int = 0
    pending_core_quantity: int = 0
    pending_core_date: str = ""
    confirmed_level: int = 0
    daily_signal_date: str = ""
    daily_signal_level: int = 0
    prior_signal_date: str = ""
    prior_signal_level: int = 0
    campaign_level: int = 0
    campaign_cash: float = 0.0
    phase: int = 0
    phase_order_count: int = 0
    last_order_date: str = ""
    trading_days_since_order: int = 0
    last_attempt_date: str = ""
    pending_buy_amount: float = 0.0
    exit_state: ExitState = ExitState.NONE
    exit_origin: str = ""
    lock_price: float = 0.0
    uptrend_active: bool = False
    uptrend_days: int = 0
    breach_days: int = 0
    breach_date: str = ""
    breach_day_date: str = ""
    prior_breach_days: int = 0
    slope_exit_days: int = 0
    slope_exit_day_date: str = ""
    prior_slope_exit_days: int = 0
    slope_exit_latched: bool = False
    slope_release_days: int = 0
    slope_release_day_date: str = ""
    prior_slope_release_days: int = 0
    forced_sale_date: str = ""
    forced_sale_reason: str = ""
    pending_exit_date: str = ""
    pending_exit_quantity: int = 0
    pending_exit_origin: str = ""
    pending_full_exit_date: str = ""
    pending_full_exit_quantity: int = 0
    recovery_quantity: int = 0
    recovery_reserved_cash: float = 0.0
    pending_recovery_quantity: int = 0
    pending_recovery_date: str = ""

    def to_dict(self) -> dict:
        data = self.__dict__.copy()
        data["exit_state"] = self.exit_state.value
        return data

    @classmethod
    def from_dict(cls, data: dict | None) -> "AssetState":
        values = dict(data or {})
        try:
            values["exit_state"] = ExitState(values.get("exit_state", ExitState.NONE.value))
        except ValueError:
            values["exit_state"] = ExitState.NONE
        return cls(**{key: values[key] for key in cls.__dataclass_fields__ if key in values})


@dataclass
class SsoSpyiChannelState:
    assets: dict[str, AssetState] = field(default_factory=dict)
    core_setup_initialized: bool = False

    def asset(self, ticker: str) -> AssetState:
        return self.assets.setdefault(ticker, AssetState())

    def to_dict(self) -> dict:
        return {
            "assets": {ticker: state.to_dict() for ticker, state in self.assets.items()},
            "core_setup_initialized": self.core_setup_initialized,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "SsoSpyiChannelState":
        values = data or {}
        raw = values.get("assets", {})
        return cls(
            assets={ticker: AssetState.from_dict(value) for ticker, value in raw.items()},
            core_setup_initialized=bool(values.get("core_setup_initialized", False)),
        )


class SsoSpyiChannelPlanner:
    """Keeps daily signal confirmation and produces sell-first, cash-limited orders."""

    def plan(
        self,
        inputs: Mapping[str, AssetInput],
        portfolio: Portfolio,
        state: SsoSpyiChannelState,
    ) -> tuple[list[Order], str, SsoSpyiChannelState]:
        state = SsoSpyiChannelState.from_dict(state.to_dict())
        for ticker in TICKERS:
            if ticker in inputs:
                self._update_daily_state(ticker, inputs[ticker], state.asset(ticker))

        forced_orders = self._sso_cap_order(portfolio, state.asset("SSO"), inputs.get("SSO"))
        if forced_orders:
            reason = "SSO hard cap: reduce to 78%"
            if state.asset("SSO").forced_sale_reason:
                reason = f"SSO hard cap: {state.asset('SSO').forced_sale_reason}"
            return forced_orders, reason, state

        sells: list[Order] = []
        for ticker in TICKERS:
            value = inputs.get(ticker)
            if value is not None:
                sells.extend(self._exit_orders(ticker, value, portfolio, state.asset(ticker)))
        if sells:
            return sells, "channel exit protection", state

        recovery_orders = self._recovery_orders(inputs, portfolio, state)
        if recovery_orders:
            return recovery_orders, "channel exit recovery", state

        core_orders = self._core_setup_orders(inputs, portfolio, state)
        if core_orders:
            return core_orders, "core position setup", state
        if not self._cores_established(state):
            return [], "waiting", state

        cash = self._free_cash(portfolio, state)
        orders: list[Order] = []
        ordered = sorted(TICKERS, key=lambda ticker: (-state.asset(ticker).confirmed_level, ticker != "SSO"))
        for ticker in ordered:
            value = inputs.get(ticker)
            if value is None:
                continue
            order = self._buy_order(ticker, value, portfolio, state.asset(ticker), cash)
            if order is not None:
                orders.append(order)
                cash -= order.quantity * order.price
        return orders, "dip-buy campaign" if orders else "waiting", state

    def record_fills(
        self, state: SsoSpyiChannelState, executions: list[TradeExecution]
    ) -> SsoSpyiChannelState:
        state = SsoSpyiChannelState.from_dict(state.to_dict())
        recovery_executions = [
            execution for execution in executions
            if execution.ticker in TICKERS
            and execution.status in (ExecutionStatus.FILLED, ExecutionStatus.PARTIAL)
            and execution.action == OrderAction.BUY
            and state.asset(execution.ticker).pending_recovery_quantity > 0
        ]
        for ticker in {execution.ticker for execution in recovery_executions}:
            asset = state.asset(ticker)
            filled_quantity = sum(
                execution.quantity for execution in recovery_executions if execution.ticker == ticker
            )
            filled_amount = sum(
                execution.quantity * execution.price
                for execution in recovery_executions if execution.ticker == ticker
            )
            asset.recovery_quantity = max(asset.recovery_quantity - filled_quantity, 0)
            asset.recovery_reserved_cash = max(asset.recovery_reserved_cash - filled_amount, 0.0)
            asset.pending_recovery_quantity = 0
            asset.pending_recovery_date = ""
            if not asset.recovery_quantity:
                self._clear_recovery_lot(asset)
                asset.exit_state = ExitState.NONE
                asset.lock_price = 0.0
                asset.exit_origin = ""

        core_executions = [
            execution for execution in executions
            if execution.ticker in TICKERS
            and execution.status in (ExecutionStatus.FILLED, ExecutionStatus.PARTIAL)
            and execution.action == OrderAction.BUY
            and execution not in recovery_executions
            and state.asset(execution.ticker).pending_core_quantity > 0
        ]
        for ticker in {execution.ticker for execution in core_executions}:
            asset = state.asset(ticker)
            filled_quantity = min(
                sum(execution.quantity for execution in core_executions if execution.ticker == ticker),
                asset.pending_core_quantity,
            )
            asset.core_quantity = min(asset.core_quantity + filled_quantity, asset.core_target_quantity)
            asset.pending_core_quantity = max(asset.core_target_quantity - asset.core_quantity, 0)
            if not asset.pending_core_quantity:
                asset.pending_core_date = ""

        buy_executions = [
            execution for execution in executions
            if execution.ticker in TICKERS
            and execution.status in (ExecutionStatus.FILLED, ExecutionStatus.PARTIAL)
            and execution.action == OrderAction.BUY
            and execution not in recovery_executions
            and execution not in core_executions
        ]
        for ticker in {execution.ticker for execution in buy_executions}:
            asset = state.asset(ticker)
            filled_amount = sum(
                execution.quantity * execution.price
                for execution in buy_executions if execution.ticker == ticker
            )
            asset.pending_buy_amount = max(asset.pending_buy_amount - filled_amount, 0.0)
            if asset.pending_buy_amount > 0:
                continue
            asset.last_order_date = asset.daily_signal_date
            asset.trading_days_since_order = 0
            if asset.phase in (1, 2):
                asset.phase_order_count += 1
                if asset.phase_order_count >= 8:
                    if asset.phase == 1 and asset.confirmed_level:
                        asset.phase, asset.phase_order_count = 2, 0
                    elif asset.phase == 2 and asset.confirmed_level:
                        asset.phase, asset.phase_order_count = 3, 0
                    else:
                        self._end_campaign(asset)
        for execution in executions:
            if (
                execution.ticker in TICKERS
                and execution.action == OrderAction.SELL
                and execution.status in (ExecutionStatus.FILLED, ExecutionStatus.PARTIAL)
            ):
                asset = state.asset(execution.ticker)
                if (
                    execution.ticker == "SSO"
                    and asset.forced_sale_date == execution.date[:10]
                ):
                    continue
                if asset.pending_full_exit_date:
                    asset.pending_full_exit_quantity = max(
                        asset.pending_full_exit_quantity - execution.quantity, 0
                    )
                    if not asset.pending_full_exit_quantity:
                        self._clear_pending_full_exit(asset)
                        self._end_campaign(asset)
                        asset.exit_state = ExitState.NONE
                        asset.lock_price = 0.0
                        self._clear_recovery_lot(asset)
                        asset.pending_exit_quantity = 0
                        asset.pending_exit_date = ""
                        asset.pending_exit_origin = ""
                        asset.exit_origin = ""
                        asset.uptrend_active = False
                        asset.uptrend_days = 0
                        asset.breach_days = 0
                        asset.breach_date = ""
                    continue
                if asset.pending_exit_date:
                    asset.exit_state = ExitState.EXIT_LOCK
                    asset.exit_origin = asset.pending_exit_origin
                    asset.lock_price = execution.price
                    asset.pending_exit_quantity = max(
                        asset.pending_exit_quantity - execution.quantity, 0
                    )
                    if not asset.pending_exit_quantity:
                        asset.pending_exit_date = ""
                        asset.pending_exit_origin = ""
                    if asset.exit_origin == "CHANNEL":
                        asset.recovery_quantity += execution.quantity
                        asset.recovery_reserved_cash += execution.quantity * execution.price
                    elif asset.exit_origin == "SLOPE":
                        asset.slope_exit_latched = True
                        asset.slope_release_days = 0
                        asset.prior_slope_release_days = 0
        return state

    def _update_daily_state(self, ticker: str, value: AssetInput, state: AssetState) -> None:
        raw_level = self._signal_level(ticker, value)
        if value.date == state.daily_signal_date:
            state.daily_signal_level = raw_level
            self._update_breach(ticker, value, state)
            self._update_slope_exit(ticker, value, state)
            return
        state.prior_signal_date = state.daily_signal_date
        state.prior_signal_level = state.daily_signal_level
        if state.last_order_date:
            state.trading_days_since_order += 1
        state.daily_signal_date = value.date
        state.daily_signal_level = raw_level
        if state.prior_signal_date:
            proven_level = min(state.prior_signal_level, raw_level)
            if proven_level > state.confirmed_level:
                state.confirmed_level = proven_level
            elif (
                proven_level < state.confirmed_level
                and state.prior_signal_level < state.confirmed_level
                and raw_level < state.confirmed_level
            ):
                state.confirmed_level = proven_level
        self._update_uptrend(value, state, ticker)
        self._update_breach(ticker, value, state)
        self._update_slope_exit(ticker, value, state)

    def _update_uptrend(self, value: AssetInput, state: AssetState, ticker: str) -> None:
        if not value.channel.is_valid:
            return
        if value.channel.slope_pct > CHANNEL_RULES[ticker]["slope"]:
            state.uptrend_days += 1
            if state.uptrend_days >= 2:
                state.uptrend_active = True
        else:
            state.uptrend_days = 0

    def _update_breach(self, ticker: str, value: AssetInput, state: AssetState) -> None:
        if not value.channel.is_valid:
            return
        if value.date != state.breach_day_date:
            state.prior_breach_days = state.breach_days
            state.breach_day_date = value.date
        breakdown_line = value.channel.support * (1 - CHANNEL_RULES[ticker]["breakdown_margin"])
        if value.channel.price < breakdown_line:
            state.breach_days = state.prior_breach_days + 1
            state.breach_date = value.date
        else:
            state.breach_days = 0
            state.breach_date = ""

    def _update_slope_exit(self, ticker: str, value: AssetInput, state: AssetState) -> None:
        if not value.channel.is_valid:
            return
        is_below_threshold = value.channel.slope_pct < CHANNEL_RULES[ticker]["slope_exit_threshold"]
        if value.date != state.slope_exit_day_date:
            state.prior_slope_exit_days = state.slope_exit_days
            state.slope_exit_day_date = value.date
        if is_below_threshold:
            state.slope_exit_days = state.prior_slope_exit_days + 1
        else:
            state.slope_exit_days = 0
        if not state.slope_exit_latched:
            return
        if value.date != state.slope_release_day_date:
            state.prior_slope_release_days = state.slope_release_days
            state.slope_release_day_date = value.date
        if is_below_threshold:
            state.slope_release_days = 0
        else:
            state.slope_release_days = state.prior_slope_release_days + 1
            if state.slope_release_days >= 2:
                state.slope_exit_latched = False
                state.slope_exit_days = 0
                state.prior_slope_exit_days = 0
                state.slope_release_days = 0
                state.prior_slope_release_days = 0

    def _exit_orders(self, ticker: str, value: AssetInput, portfolio: Portfolio, state: AssetState) -> list[Order]:
        holding = portfolio.holdings.get(ticker, 0)
        if holding <= 0 or not value.channel.is_valid:
            return []
        if state.exit_state == ExitState.EXIT_LOCK:
            if (
                self._tactical_quantity(ticker, portfolio, state) <= 0
                and not (state.exit_origin == "CHANNEL" and state.recovery_quantity > 0)
            ):
                self._clear_recovery_lot(state)
                self._clear_pending_exit(state)
                self._clear_pending_full_exit(state)
                state.exit_state = ExitState.NONE
                state.lock_price = 0.0
                state.exit_origin = ""
                return []
            if state.confirmed_level:
                state.exit_state = ExitState.EXIT_SUPPRESSED
                self._clear_recovery_lot(state)
                self._clear_pending_exit(state)
                self._clear_pending_full_exit(state)
                return []
            if value.channel.price >= value.channel.support:
                self._clear_pending_exit(state)
                self._clear_pending_full_exit(state)
                if state.exit_origin == "SLOPE":
                    state.exit_state = ExitState.NONE
                    state.lock_price = 0.0
                    state.exit_origin = ""
                return []
            if state.pending_full_exit_quantity:
                return self._start_full_exit(ticker, portfolio, state)
            if value.channel.price <= state.lock_price * (1 - CHANNEL_RULES[ticker]["trailing_drop"]):
                return self._start_full_exit(ticker, portfolio, state)
            if state.pending_exit_quantity:
                return self._start_exit(ticker, portfolio, state, state.pending_exit_origin)
            return []
        if state.exit_state == ExitState.EXIT_SUPPRESSED:
            if value.channel.price >= value.channel.support:
                state.exit_state = ExitState.NONE
                state.exit_origin = ""
            elif not state.confirmed_level:
                if state.slope_exit_days >= 2 and not state.slope_exit_latched:
                    return self._start_exit(ticker, portfolio, state, "SLOPE")
                if state.breach_days >= 2:
                    return self._start_exit(ticker, portfolio, state, "CHANNEL")
            return []
        if state.slope_exit_days >= 2 and not state.slope_exit_latched:
            if state.confirmed_level:
                state.exit_state = ExitState.EXIT_SUPPRESSED
                self._clear_recovery_lot(state)
                self._clear_pending_exit(state)
                self._clear_pending_full_exit(state)
                return []
            return self._start_exit(ticker, portfolio, state, "SLOPE")
        if state.breach_days >= 2:
            if state.confirmed_level:
                state.exit_state = ExitState.EXIT_SUPPRESSED
                self._clear_recovery_lot(state)
                self._clear_pending_exit(state)
                self._clear_pending_full_exit(state)
                return []
            return self._start_exit(ticker, portfolio, state, "CHANNEL")
        return []

    def _recovery_orders(
        self,
        inputs: Mapping[str, AssetInput],
        portfolio: Portfolio,
        state: SsoSpyiChannelState,
    ) -> list[Order]:
        free_cash = self._free_cash(portfolio, state)
        orders: list[Order] = []
        for ticker in TICKERS:
            asset = state.asset(ticker)
            value = inputs.get(ticker)
            if value is not None and asset.pending_recovery_quantity and asset.pending_recovery_date != value.date:
                asset.pending_recovery_quantity = 0
                asset.pending_recovery_date = ""
            if (
                value is None
                or not value.channel.is_valid
                or asset.exit_state != ExitState.EXIT_LOCK
                or asset.pending_recovery_quantity
                or value.channel.price < value.channel.support
            ):
                continue
            if asset.recovery_quantity <= 0:
                asset.exit_state, asset.lock_price = ExitState.NONE, 0.0
                continue
            price = portfolio.current_prices.get(ticker, 0.0)
            if price <= 0:
                continue
            permitted_cash = asset.recovery_reserved_cash + free_cash
            quantity = min(asset.recovery_quantity, math.floor(permitted_cash / price))
            if quantity <= 0:
                continue
            cost = quantity * price
            free_cash = max(free_cash - max(cost - asset.recovery_reserved_cash, 0.0), 0.0)
            asset.pending_recovery_quantity = quantity
            asset.pending_recovery_date = value.date
            orders.append(Order(ticker, OrderAction.BUY, quantity, price))
        return orders

    @staticmethod
    def _core_setup_orders(
        inputs: Mapping[str, AssetInput],
        portfolio: Portfolio,
        state: SsoSpyiChannelState,
    ) -> list[Order]:
        if not state.core_setup_initialized:
            if not all(ticker in inputs for ticker in TICKERS):
                return []
            prices = {ticker: portfolio.current_prices.get(ticker, 0.0) for ticker in TICKERS}
            if not all(price > 0 for price in prices.values()):
                return []
            portfolio_value = portfolio.total_value
            for ticker, allocation in CORE_ALLOCATIONS.items():
                state.asset(ticker).core_target_quantity = math.floor(
                    portfolio_value * allocation / prices[ticker]
                )
            state.core_setup_initialized = True

        orders: list[Order] = []
        for ticker in TICKERS:
            asset = state.asset(ticker)
            value = inputs.get(ticker)
            price = portfolio.current_prices.get(ticker, 0.0)
            quantity = asset.core_target_quantity - asset.core_quantity
            if quantity <= 0:
                asset.pending_core_quantity = 0
                asset.pending_core_date = ""
                continue
            if value is None or price <= 0 or asset.pending_core_date == value.date:
                continue
            asset.pending_core_quantity = quantity
            asset.pending_core_date = value.date
            orders.append(Order(ticker, OrderAction.BUY, quantity, price))
        return orders

    @staticmethod
    def _cores_established(state: SsoSpyiChannelState) -> bool:
        return state.core_setup_initialized and all(
            state.asset(ticker).core_quantity >= state.asset(ticker).core_target_quantity
            for ticker in TICKERS
        )

    def _start_exit(
        self, ticker: str, portfolio: Portfolio, state: AssetState, origin: str
    ) -> list[Order]:
        if state.pending_exit_date == state.daily_signal_date:
            return []
        tactical_quantity = self._tactical_quantity(ticker, portfolio, state)
        quantity = min(
            state.pending_exit_quantity or math.ceil(tactical_quantity * 0.5),
            tactical_quantity,
        )
        if quantity <= 0:
            return []
        state.pending_exit_date = state.daily_signal_date
        state.pending_exit_quantity = quantity
        state.pending_exit_origin = origin
        return [Order(ticker, OrderAction.SELL, quantity, portfolio.current_prices[ticker])]

    def _start_full_exit(self, ticker: str, portfolio: Portfolio, state: AssetState) -> list[Order]:
        if state.pending_full_exit_date == state.daily_signal_date:
            return []
        tactical_quantity = self._tactical_quantity(ticker, portfolio, state)
        quantity = min(state.pending_full_exit_quantity or tactical_quantity, tactical_quantity)
        if quantity <= 0:
            return []
        state.pending_full_exit_date = state.daily_signal_date
        state.pending_full_exit_quantity = quantity
        return [Order(ticker, OrderAction.SELL, quantity, portfolio.current_prices[ticker])]

    def _buy_order(self, ticker: str, value: AssetInput, portfolio: Portfolio, state: AssetState, cash: float) -> Order | None:
        if not state.confirmed_level or state.exit_state == ExitState.EXIT_LOCK:
            return None
        if ticker == "SSO" and state.forced_sale_date == value.date:
            return None
        if state.phase == 0:
            state.campaign_level = state.confirmed_level
            state.campaign_cash = cash
            state.phase = 1
        state.campaign_level = max(state.campaign_level, state.confirmed_level)
        if state.pending_buy_amount > 0:
            amount = state.pending_buy_amount
        elif state.phase == 3:
            amount = cash
        elif not self._is_due(value.date, state):
            return None
        else:
            amount = state.campaign_cash * PHASE_WEIGHTS[state.campaign_level][state.phase - 1] / 8
        price = portfolio.current_prices.get(ticker, 0.0)
        quantity = math.floor(min(amount, cash) / price) if price > 0 else 0
        if quantity <= 0:
            return None
        state.pending_buy_amount = quantity * price
        state.last_attempt_date = value.date
        return Order(ticker, OrderAction.BUY, quantity, price)

    @staticmethod
    def _is_due(date: str, state: AssetState) -> bool:
        # The engine is called once per trading day in backtests. A nonempty date
        # establishes the 5-trading-day cadence through explicit persisted dates.
        if state.last_attempt_date == date:
            return False
        return not state.last_order_date or state.trading_days_since_order >= 5

    @staticmethod
    def _signal_level(ticker: str, value: AssetInput) -> int:
        if math.isnan(value.weekly_rsi) or math.isnan(value.ma200_deviation):
            return 0
        thresholds = BUY_THRESHOLDS[ticker]
        for level, (rsi, deviation) in reversed(list(enumerate(thresholds[1:], start=2))):
            if value.weekly_rsi <= rsi and value.ma200_deviation <= deviation:
                return level
        rsi, deviation = thresholds[0]
        return int(value.weekly_rsi <= rsi or value.ma200_deviation <= deviation)

    @staticmethod
    def _end_campaign(state: AssetState) -> None:
        state.campaign_level = state.phase = state.phase_order_count = 0
        state.campaign_cash = 0.0
        state.last_order_date = ""
        state.trading_days_since_order = 0
        state.pending_buy_amount = 0.0

    @staticmethod
    def _clear_recovery_lot(state: AssetState) -> None:
        state.recovery_quantity = 0
        state.recovery_reserved_cash = 0.0
        state.pending_recovery_quantity = 0
        state.pending_recovery_date = ""

    @staticmethod
    def _clear_pending_exit(state: AssetState) -> None:
        state.pending_exit_date = ""
        state.pending_exit_quantity = 0
        state.pending_exit_origin = ""

    @staticmethod
    def _clear_pending_full_exit(state: AssetState) -> None:
        state.pending_full_exit_date = ""
        state.pending_full_exit_quantity = 0

    @staticmethod
    def _free_cash(portfolio: Portfolio, state: SsoSpyiChannelState) -> float:
        reserved = sum(asset.recovery_reserved_cash for asset in state.assets.values())
        return max(portfolio.total_cash - reserved, 0.0)

    @staticmethod
    def _tactical_quantity(ticker: str, portfolio: Portfolio, state: AssetState) -> int:
        return max(portfolio.holdings.get(ticker, 0) - state.core_quantity, 0)

    @staticmethod
    def _sso_cap_order(portfolio: Portfolio, state: AssetState, value: AssetInput | None) -> list[Order]:
        if value is None or portfolio.total_value <= 0:
            return []
        price = portfolio.current_prices.get("SSO", 0.0)
        held = portfolio.holdings.get("SSO", 0)
        if price <= 0 or held * price / portfolio.total_value <= 0.80:
            state.forced_sale_reason = ""
            return []
        if state.forced_sale_date == value.date:
            return []
        desired_value = portfolio.total_value * 0.78
        needed_quantity = math.ceil((held * price - desired_value) / price)
        tactical_quantity = SsoSpyiChannelPlanner._tactical_quantity("SSO", portfolio, state)
        quantity = min(tactical_quantity, needed_quantity)
        state.forced_sale_reason = (
            "core floor prevents 78% target" if quantity < needed_quantity else ""
        )
        state.forced_sale_date = value.date
        if quantity <= 0:
            return []
        return [Order("SSO", OrderAction.SELL, quantity, price)]
