"""Basic value rebalancing with a daily volatility cap; no I/O or simulated cash."""
from dataclasses import asdict, dataclass, replace
from datetime import date
import math

from src.core.models import Order, OrderAction, OrderBatchResult, ExecutionStatus, Portfolio


@dataclass(frozen=True)
class VrState:
    anchor: str = ""
    cycle: int = 0
    value: float = 0.0
    budget: float = 0.0
    spent: float = 0.0
    last_date: str = ""
    closing_pool: float = 0.0
    initialized: bool = False
    reconciliation_required: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "VrState":
        return cls(**data) if data else cls()


class TqqqVrPlanner:
    """Finalist: pool20%, cycle budget50%, G10, 7 calendar days, bands ±15%."""
    TICKER = "TQQQ"
    INITIAL_POOL = 0.20
    CYCLE_LIMIT = 0.50
    G = 10.0
    CYCLE_DAYS = 7

    def __init__(self, fee_rate: float = 0.0025):
        if not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
            raise ValueError("fee_rate must be finite and in [0, 1)")
        self.fee_rate = fee_rate

    def plan(self, day: str, cap: float, portfolio: Portfolio,
             state: VrState) -> tuple[list[Order], str, VrState]:
        date.fromisoformat(day)
        if state.reconciliation_required:
            return [], "VR: unresolved execution; reconcile broker and state", state
        if state.last_date and day <= state.last_date:
            return [], "VR: already evaluated or stale session", state
        cash = portfolio.total_cash
        price = portfolio.current_prices.get(self.TICKER, 0.0)
        qty = portfolio.holdings.get(self.TICKER, 0)
        if (not all(math.isfinite(x) for x in (cash, price, cap))
                or price <= 0 or cash < 0 or not 0 < cap <= 1):
            return [], "VR: invalid cash, price or cap", state
        if any(q > 0 for t, q in portfolio.holdings.items() if t != self.TICKER):
            return [], "VR: requires a dedicated TQQQ/cash portfolio", state
        if not state.anchor:
            if qty:
                return [], "VR: existing holdings require an explicit initial state", state
            state = replace(state, anchor=day, value=cash * (1-self.INITIAL_POOL))
        if not state.initialized:
            # First allocation is also bounded by the known volatility cap.
            n = math.floor(min(state.value / (price*(1+self.fee_rate)),
                               cap*cash / (price*(1+cap*self.fee_rate))) + 1e-10)
            orders = [Order(self.TICKER, OrderAction.BUY, n, price)] if n else []
            return orders, "VR: initial allocation", replace(
                state, last_date=day, closing_pool=cash)
        cycle = (date.fromisoformat(day)-date.fromisoformat(state.anchor)).days // self.CYCLE_DAYS
        if cycle > state.cycle:
            # One update on the first observed session; no fictitious skipped-week compounding.
            state = replace(state, cycle=cycle, value=state.value+state.closing_pool/self.G,
                            budget=state.closing_pool*self.CYCLE_LIMIT, spent=0.0)
        state = replace(state, last_date=day, closing_pool=cash)
        equity = cash + qty*price
        vr_sell = max(0, math.ceil(qty-1.15*state.value/price-1e-10))
        cap_sell = max(0, math.ceil((qty*price-cap*equity) /
                                   (price*(1-cap*self.fee_rate))-1e-10))
        sell = min(qty, max(vr_sell, cap_sell))
        if sell:
            reason = "VR: volatility cap sell" if cap_sell > vr_sell else "VR: upper band sell"
            return [Order(self.TICKER, OrderAction.SELL, sell, price)], reason, state
        need = max(0, math.ceil(.85*state.value/price-qty-1e-10))
        unit_cost = price*(1+self.fee_rate)
        affordable = math.floor(cash/unit_cost+1e-10)
        permitted = max(0, math.floor((state.budget-state.spent)/unit_cost+1e-10))
        room = max(0, math.floor((cap*equity-qty*price) /
                                (price*(1+cap*self.fee_rate))+1e-10))
        buy = min(need, affordable, permitted, room)
        if buy:
            return [Order(self.TICKER, OrderAction.BUY, buy, price)], "VR: lower band buy", state
        reason = "VR: within bands"
        if need:
            reason = f"VR: buy blocked (pool={affordable}, budget={permitted}, cap={room})"
        return [], reason, state

    def settle(self, state: VrState, result: OrderBatchResult) -> VrState:
        cash = state.closing_pool
        spent = state.spent
        initialized = state.initialized
        for fill in result.actual_executions:
            if fill.ticker != self.TICKER:
                continue
            if fill.action == OrderAction.BUY:
                amount = fill.quantity*fill.price+fill.fee
                cash -= amount
                if initialized:
                    spent += amount
            else:
                cash += fill.quantity*fill.price-fill.fee
        if not initialized and any(f.action == OrderAction.BUY for f in result.actual_executions):
            initialized = True
            state = replace(state, budget=max(0, cash)*self.CYCLE_LIMIT)
        # ORDERED, PARTIAL and transport errors may leave working orders. Never guess fills.
        unresolved = any(o.status in {ExecutionStatus.ORDERED, ExecutionStatus.PARTIAL,
                                      ExecutionStatus.ERROR} for o in result.outcomes)
        return replace(state, initialized=initialized, spent=spent, closing_pool=cash,
                       reconciliation_required=state.reconciliation_required or unresolved)
