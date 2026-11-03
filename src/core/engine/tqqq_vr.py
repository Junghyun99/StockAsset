"""TQQQ VR adapter using the shared data/order/persistence template."""
import math
from zoneinfo import ZoneInfo

import pandas as pd

from src.core.engine.base import TradingEngine
from src.core.engine.data_pipeline import DataSetSpec, StrategyDataSpec
from src.core.engine.registry import register_engine
from src.core.logic.tqqq_vr import TqqqVrPlanner, VrState
from src.core.models import DecisionFactor, MarketRegime, StrategyDecision, TradeSignal


@register_engine(color="#d97706", backtest=False)
class TqqqVrEngine(TradingEngine):
    """Daily cap sales and weekly V/budget updates; dedicated TQQQ/cash account."""
    ASSET_GROUPS = {"A": ["TQQQ"], "B": []}
    STATE_KEY = "tqqq_vr"
    SESSION_TIMEZONE = ZoneInfo("America/New_York")

    def __init__(self, *args, fee_rate: float = 0.0025, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner = TqqqVrPlanner(fee_rate)
        self.vr_state = VrState.from_dict(self.restore_strategy_state(self.STATE_KEY))
        self.realized_vol = float("nan")
        self.weight_cap = float("nan")

    def data_spec(self):
        return StrategyDataSpec(reference=DataSetSpec("reference", ("QQQ",), days=400))

    def calculate_strategy_indicators(self, collected):
        frame = collected.reference
        if isinstance(frame.columns, pd.MultiIndex):
            frame = frame.xs("QQQ", axis=1, level=1)
        # Strictly prior session, whether the provider includes today's unfinished bar or not.
        prior = frame.loc[frame.index.strftime("%Y-%m-%d") < self.cycle_date]
        close = prior["Close"].tail(21) if "Close" in prior else pd.Series(dtype=float)
        if len(close) != 21 or not close.gt(0).all() or not close.map(math.isfinite).all():
            self.realized_vol = self.weight_cap = float("nan")
        else:
            self.realized_vol = float(close.pct_change(fill_method=None).dropna().std(ddof=1)*math.sqrt(252))
            self.weight_cap = min(1.0, .30/(3*self.realized_vol)) if self.realized_vol > 0 else 1.0
        return self.weight_cap

    def analyze_strategy(self, market_data):
        # Other regimes are diagnostics, not an additional crash liquidation rule.
        invalid = [] if math.isfinite(self.weight_cap) else ["qqq_volatility_20d"]
        return MarketRegime.SIDEWAYS, self.weight_cap if not invalid else 0.0, invalid

    def uses_trading_interval(self):
        return False

    def build_strategy_decision(self, market_data, portfolio, regime, exposure):
        orders, reason, state = self.planner.plan(
            self.cycle_date or market_data.date, self.weight_cap, portfolio, self.vr_state)
        return StrategyDecision(
            signal=TradeSignal(exposure, orders, reason), label="TQQQ VR",
            is_rebalancing=bool(orders), state_key=self.STATE_KEY, proposed_state=state)

    def finalize_strategy_state(self, decision, order_result):
        self.vr_state = self.planner.settle(decision.proposed_state, order_result)
        return self.vr_state

    def decision_factors(self, market_data, regime, exposure, signal, portfolio):
        factors = [DecisionFactor("vr_value", "VR 기준 V", self.vr_state.value),
                   DecisionFactor("vr_budget_left", "사이클 잔여 예산",
                                  max(0, self.vr_state.budget-self.vr_state.spent))]
        if math.isfinite(self.weight_cap):
            factors.append(DecisionFactor("tqqq_cap", "TQQQ 비중 상한", self.weight_cap, "percent"))
            factors.append(DecisionFactor("qqq_vol20", "QQQ 변동성(20d)", self.realized_vol, "percent"))
        factors.append(DecisionFactor("vr_reconcile", "체결 확인 필요",
                                      str(self.vr_state.reconciliation_required), "text"))
        return factors
