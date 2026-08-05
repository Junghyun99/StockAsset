"""Stateful order planning for independent SSO and SPYI dip campaigns."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Mapping

from src.core.logic.channel_regime import ChannelSnapshot
from src.core.models import ExecutionStatus, Order, OrderAction, Portfolio, TradeExecution


TICKERS = ("SSO", "SPYI")
BUY_THRESHOLDS = {
    "SSO": ((48.0, -0.10), (42.0, -0.18), (36.0, -0.26)),
    "SPYI": ((50.0, -0.06), (45.0, -0.10), (40.0, -0.15)),
}
CHANNEL_RULES = {
    "SSO": {"stddev_k": 3.0, "slope": 16.0, "trailing_drop": 0.05},
    "SPYI": {"stddev_k": 2.0, "slope": 8.0, "trailing_drop": 0.03},
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
    lock_price: float = 0.0
    uptrend_active: bool = False
    uptrend_days: int = 0
    breach_days: int = 0
    breach_date: str = ""
    breach_day_date: str = ""
    prior_breach_days: int = 0
    forced_sale_date: str = ""
    pending_exit_date: str = ""
    pending_full_exit_date: str = ""

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

    def asset(self, ticker: str) -> AssetState:
        return self.assets.setdefault(ticker, AssetState())

    def to_dict(self) -> dict:
        return {"assets": {ticker: state.to_dict() for ticker, state in self.assets.items()}}

    @classmethod
    def from_dict(cls, data: dict | None) -> "SsoSpyiChannelState":
        raw = (data or {}).get("assets", {})
        return cls(assets={ticker: AssetState.from_dict(value) for ticker, value in raw.items()})


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
            return forced_orders, "SSO hard cap: reduce to 78%", state

        sells: list[Order] = []
        for ticker in TICKERS:
            value = inputs.get(ticker)
            if value is not None:
                sells.extend(self._exit_orders(ticker, value, portfolio, state.asset(ticker)))
        if sells:
            return sells, "channel exit protection", state

        cash = portfolio.total_cash
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
        buy_executions = [
            execution for execution in executions
            if execution.ticker in TICKERS
            and execution.status in (ExecutionStatus.FILLED, ExecutionStatus.PARTIAL)
            and execution.action == OrderAction.BUY
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
                if asset.pending_full_exit_date:
                    asset.pending_full_exit_date = ""
                    if execution.status == ExecutionStatus.FILLED:
                        self._end_campaign(asset)
                        asset.exit_state = ExitState.NONE
                        asset.lock_price = 0.0
                        asset.uptrend_active = False
                        asset.uptrend_days = 0
                        asset.breach_days = 0
                        asset.breach_date = ""
                    continue
                if asset.pending_exit_date:
                    asset.exit_state = ExitState.EXIT_LOCK
                    asset.lock_price = execution.price
                    asset.pending_exit_date = ""
        return state

    def _update_daily_state(self, ticker: str, value: AssetInput, state: AssetState) -> None:
        raw_level = self._signal_level(ticker, value)
        if value.date == state.daily_signal_date:
            state.daily_signal_level = raw_level
            self._update_breach(value, state)
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
        self._update_breach(value, state)

    def _update_uptrend(self, value: AssetInput, state: AssetState, ticker: str) -> None:
        if not value.channel.is_valid:
            return
        if value.channel.slope_pct > CHANNEL_RULES[ticker]["slope"]:
            state.uptrend_days += 1
            if state.uptrend_days >= 2:
                state.uptrend_active = True
        else:
            state.uptrend_days = 0

    def _update_breach(self, value: AssetInput, state: AssetState) -> None:
        if not value.channel.is_valid:
            return
        if value.date != state.breach_day_date:
            state.prior_breach_days = state.breach_days
            state.breach_day_date = value.date
        if value.channel.price < value.channel.support:
            state.breach_days = state.prior_breach_days + 1
            state.breach_date = value.date
        else:
            state.breach_days = 0
            state.breach_date = ""

    def _exit_orders(self, ticker: str, value: AssetInput, portfolio: Portfolio, state: AssetState) -> list[Order]:
        holding = portfolio.holdings.get(ticker, 0)
        if holding <= 0 or not value.channel.is_valid:
            return []
        if state.exit_state == ExitState.EXIT_LOCK:
            if state.confirmed_level:
                state.exit_state = ExitState.EXIT_SUPPRESSED
                return []
            if value.channel.price >= value.channel.support:
                state.exit_state, state.lock_price = ExitState.NONE, 0.0
                return []
            if value.channel.price <= state.lock_price * (1 - CHANNEL_RULES[ticker]["trailing_drop"]):
                state.pending_full_exit_date = state.daily_signal_date
                return [Order(ticker, OrderAction.SELL, holding, portfolio.current_prices[ticker])]
            return []
        if state.exit_state == ExitState.EXIT_SUPPRESSED:
            if value.channel.price >= value.channel.support:
                state.exit_state = ExitState.NONE
            elif not state.confirmed_level and state.breach_days >= 2:
                return self._start_exit(ticker, portfolio, state)
            return []
        if state.uptrend_active and state.breach_days >= 2:
            if state.confirmed_level:
                state.exit_state = ExitState.EXIT_SUPPRESSED
                return []
            return self._start_exit(ticker, portfolio, state)
        return []

    def _start_exit(self, ticker: str, portfolio: Portfolio, state: AssetState) -> list[Order]:
        if state.pending_exit_date == state.daily_signal_date:
            return []
        quantity = math.ceil(portfolio.holdings.get(ticker, 0) * 0.5)
        if quantity <= 0:
            return []
        state.pending_exit_date = state.daily_signal_date
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
        for level, (rsi, deviation) in reversed(list(enumerate(BUY_THRESHOLDS[ticker], start=1))):
            if value.weekly_rsi <= rsi and value.ma200_deviation <= deviation:
                return level
        return 0

    @staticmethod
    def _end_campaign(state: AssetState) -> None:
        state.campaign_level = state.phase = state.phase_order_count = 0
        state.campaign_cash = 0.0
        state.last_order_date = ""
        state.trading_days_since_order = 0
        state.pending_buy_amount = 0.0

    @staticmethod
    def _sso_cap_order(portfolio: Portfolio, state: AssetState, value: AssetInput | None) -> list[Order]:
        if value is None or portfolio.total_value <= 0:
            return []
        price = portfolio.current_prices.get("SSO", 0.0)
        held = portfolio.holdings.get("SSO", 0)
        if price <= 0 or held * price / portfolio.total_value <= 0.80:
            return []
        desired_value = portfolio.total_value * 0.78
        quantity = min(held, math.ceil((held * price - desired_value) / price))
        if quantity <= 0:
            return []
        state.forced_sale_date = value.date
        return [Order("SSO", OrderAction.SELL, quantity, price)]
