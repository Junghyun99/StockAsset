# src/core/engine/sso_dip_buy.py
"""SSO/SPYI 신호 기반 분할매수 엔진.

SSO 주봉 RSI + 200일선 괴리율로 매수/매도 신호를 감지하고,
SSO(S&P500 2x 레버리지)를 단계적으로 분할매수/매도한다.
나머지 자산은 SPYI(S&P500 커버드콜)에 배분하여 인컴을 확보한다.

리밸런서를 사용하지 않는 신호 기반 엔진이다.
"""
from typing import List

import math

from src.core.engine.base import TradingEngine
from src.core.engine.data_pipeline import CollectedData, DataSetSpec, StrategyDataSpec
from src.core.engine.registry import register_engine
from src.core.logic.sso_dip_signals import SsoDipIndicatorCalculator
from src.core.logic.sso_dip_planner import SsoDipPlanner, SsoDipState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, DecisionFactor,
    OrderBatchResult, StrategyDecision,
)


@register_engine(color="#ff6b6b")
class SsoDipBuyEngine(TradingEngine):
    """SSO/SPYI 신호 기반 분할매수 전략 엔진."""

    ASSET_GROUPS: dict = {"A": ["SSO"], "B": ["SPYI"]}
    STATE_KEY: str = "sso_dip_buy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sso_calc = SsoDipIndicatorCalculator()
        self._planner = SsoDipPlanner()
        self.dip_state = SsoDipState.from_dict(
            self.restore_strategy_state(self.STATE_KEY)
        )
        self.sso_signals = None

    def data_spec(self) -> StrategyDataSpec:
        return StrategyDataSpec(
            reference=DataSetSpec("reference", ("SPY",), days=400),
            strategy=(DataSetSpec("signal", ("SSO",), days=400),),
        )

    def calculate_strategy_indicators(self, collected: CollectedData):
        self.sso_signals = self._sso_calc.calculate(collected.frame("signal"))
        return self.sso_signals

    def uses_trading_interval(self) -> bool:
        return False

    def build_strategy_decision(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
        record_date: str | None = None,
    ) -> StrategyDecision:
        orders, reason, new_state = self._planner.plan(
            self.sso_signals, portfolio, self.dip_state, record_date=record_date,
        )

        signal = TradeSignal(exposure, orders, reason)
        return StrategyDecision(
            signal=signal,
            label="SsoDipBuy",
            is_rebalancing=bool(orders),
            state_key=self.STATE_KEY,
            proposed_state=new_state,
        )

    def finalize_strategy_state(
        self,
        decision: StrategyDecision,
        order_result: OrderBatchResult,
        record_date: str | None = None,
    ) -> SsoDipState:
        state = self._planner.record_filled_tranche(
            decision.proposed_state, order_result.actual_executions, record_date=record_date,
        )
        self.dip_state = state
        return state

    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        factors: List[DecisionFactor] = []
        s = self.sso_signals

        if s is not None:
            if not math.isnan(s.weekly_rsi):
                factors.append(DecisionFactor(
                    "weekly_rsi", "주봉 RSI(14)", s.weekly_rsi, "number", threshold=48.0,
                ))
            if not math.isnan(s.ma200_deviation):
                factors.append(DecisionFactor(
                    "ma200_deviation", "200일선 괴리율", s.ma200_deviation, "percent",
                    threshold=-0.10,
                ))

        factors.append(DecisionFactor(
            "signal_level", "신호 단계", self.dip_state.level.value, "text",
        ))

        total = portfolio.total_value
        if total > 0:
            sso_val = (portfolio.holdings.get("SSO", 0)
                       * portfolio.current_prices.get("SSO", 0.0))
            factors.append(DecisionFactor(
                "sso_ratio", "SSO 비중", sso_val / total, "percent",
            ))

        return factors
