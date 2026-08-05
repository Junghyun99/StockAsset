"""Independent SSO/SPYI dip buying with channel-protected exits."""
from typing import List

from src.core.engine.base import TradingEngine
from src.core.engine.data_pipeline import CollectedData, DataSetSpec, StrategyDataSpec
from src.core.engine.registry import register_engine
from src.core.logic.channel_regime import classify_channel
from src.core.logic.sso_dip_signals import SsoDipIndicatorCalculator
from src.core.logic.sso_spyi_channel_planner import (
    AssetInput,
    CHANNEL_RULES,
    SsoSpyiChannelPlanner,
    SsoSpyiChannelState,
)
from src.core.models import (
    DecisionFactor, MarketData, MarketRegime, OrderBatchResult, Portfolio,
    StrategyDecision, TradeSignal,
)


@register_engine(color="#c0392b")
class SsoSpyiChannelDipEngine(TradingEngine):
    """Run SSO and SPYI campaigns from one cash pool without global interval gating."""

    ASSET_GROUPS = {"A": ["SSO"], "B": ["SPYI"]}
    STATE_KEY = "sso_spyi_channel_dip"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._calculator = SsoDipIndicatorCalculator()
        self._planner = SsoSpyiChannelPlanner()
        self.channel_state = SsoSpyiChannelState.from_dict(
            self.restore_strategy_state(self.STATE_KEY)
        )
        self.asset_inputs: dict[str, AssetInput] = {}

    def data_spec(self) -> StrategyDataSpec:
        return StrategyDataSpec(
            reference=DataSetSpec("reference", ("SPY",), days=400),
            strategy=(
                DataSetSpec("sso_signal", ("SSO",), days=400),
                DataSetSpec("spyi_signal", ("SPYI",), days=400),
            ),
        )

    def uses_trading_interval(self) -> bool:
        return False

    def calculate_strategy_indicators(self, collected: CollectedData):
        self.asset_inputs = {}
        for ticker, dataset in (("SSO", "sso_signal"), ("SPYI", "spyi_signal")):
            frame = collected.frame(dataset)
            signal = self._calculator.calculate(frame)
            self.asset_inputs[ticker] = AssetInput(
                date=signal.date,
                weekly_rsi=signal.weekly_rsi,
                ma200_deviation=signal.ma200_deviation,
                channel=classify_channel(
                    frame, lookback=63, stddev_k=CHANNEL_RULES[ticker]["stddev_k"]
                ),
            )
        return self.asset_inputs

    def build_strategy_decision(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
    ) -> StrategyDecision:
        orders, reason, state = self._planner.plan(self.asset_inputs, portfolio, self.channel_state)
        return StrategyDecision(
            signal=TradeSignal(exposure, orders, reason),
            label="SsoSpyiChannelDip",
            is_rebalancing=bool(orders),
            state_key=self.STATE_KEY,
            proposed_state=state,
        )

    def finalize_strategy_state(
        self, decision: StrategyDecision, order_result: OrderBatchResult
    ) -> SsoSpyiChannelState:
        self.channel_state = self._planner.record_fills(
            decision.proposed_state, order_result.actual_executions
        )
        return self.channel_state

    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        factors: List[DecisionFactor] = []
        for ticker in ("SSO", "SPYI"):
            value = self.asset_inputs.get(ticker)
            if value is None:
                continue
            state = self.channel_state.asset(ticker)
            factors.extend([
                DecisionFactor(f"{ticker.lower()}_buy_level", f"{ticker} buy level", state.confirmed_level, "number"),
                DecisionFactor(f"{ticker.lower()}_channel_slope", f"{ticker} channel slope", value.channel.slope_pct, "percent"),
                DecisionFactor(f"{ticker.lower()}_exit_state", f"{ticker} exit state", state.exit_state.value, "text"),
            ])
        return factors
