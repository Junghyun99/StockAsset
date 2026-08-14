# src/core/engine/domestic_qld_dip_buy.py
"""국내상장 QLD/QQQI 신호 기반 분할매수 엔진.

QldDipBuyEngine의 국내상장 ETF 버전.
- 418660.KS (TIGER 미국나스닥100레버리지(합성)) = QLD 대응
- 486290.KS (TIGER 미국나스닥100타겟데일리커버드콜) = QQQI 대응
- 신호 평가: 418660.KS 일봉 OHLCV 기반 주봉RSI + 200일선 괴리율
"""
from typing import List

import math

from src.core.engine.base import TradingEngine
from src.core.engine.data_pipeline import CollectedData, DataSetSpec, StrategyDataSpec
from src.core.engine.registry import register_engine
from src.core.logic.sso_dip_signals import SsoDipIndicatorCalculator
from src.core.logic.sso_dip_planner import SignalLevel, SsoDipPlanner, SsoDipState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, DecisionFactor,
    OrderBatchResult, StrategyDecision,
)

LEVER_TICKER = "418660.KS"
INCOME_TICKER = "486290.KS"


class DomesticQldDipPlanner(SsoDipPlanner):
    """국내상장 레버리지/커버드콜 티커를 사용하는 DipBuy 플래너."""

    SSO_TICKER = LEVER_TICKER
    SPYI_TICKER = INCOME_TICKER
    _sell_condition = {"rsi": 80.0, "deviation": 0.35}


@register_engine(color="#8e44ad", market_type="domestic", backtest=False)
class DomesticQldDipBuyEngine(TradingEngine):
    """국내상장 QLD/QQQI 신호 기반 분할매수 전략 엔진."""

    ASSET_GROUPS: dict = {"A": [LEVER_TICKER], "B": [INCOME_TICKER]}
    STATE_KEY: str = "domestic_qld_dip_buy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._signal_calc = SsoDipIndicatorCalculator()
        self._planner = DomesticQldDipPlanner()
        self.dip_state = SsoDipState.from_dict(
            self.restore_strategy_state(self.STATE_KEY)
        )
        self.dip_signals = None
        self._forced_buy_stage: tuple[SignalLevel, str] | None = None

    def force_buy_stage(self, stage: int, reason: str) -> None:
        if stage not in (1, 2, 3):
            raise ValueError("stage must be one of: 1, 2, 3")
        if not reason.strip():
            raise ValueError("reason is required")
        self._forced_buy_stage = (SignalLevel[f"BUY_STAGE_{stage}"], reason.strip())

    def data_spec(self) -> StrategyDataSpec:
        return StrategyDataSpec(
            reference=DataSetSpec("reference", ("SPY",), days=400),
            strategy=(DataSetSpec("signal", (LEVER_TICKER,), days=400),),
        )

    def calculate_strategy_indicators(self, collected: CollectedData):
        frame = collected.frame("signal")
        self.dip_signals = self._signal_calc.calculate(frame)
        invalid_fields = [
            name for name, value in (
                ("weekly_rsi", self.dip_signals.weekly_rsi),
                ("ma200_deviation", self.dip_signals.ma200_deviation),
                ("mdd_200", self.dip_signals.mdd_200),
            ) if not math.isfinite(value)
        ]
        if invalid_fields:
            last_date = str(frame.index[-1]) if not frame.empty else "none"
            self.logger.warning(
                "[DomesticQldDipBuy] Invalid strategy indicators: "
                f"{', '.join(invalid_fields)} "
                f"(rows={len(frame)}, last_date={last_date})"
            )
        return self.dip_signals

    def uses_trading_interval(self) -> bool:
        return False

    def build_strategy_decision(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
    ) -> StrategyDecision:
        forced_stage = self._forced_buy_stage
        self._forced_buy_stage = None
        resolution = self._planner.resolve_signal(
            self.dip_signals,
            self.dip_state,
            forced_stage[0] if forced_stage else None,
        )
        orders, reason, new_state = self._planner.plan(
            self.dip_signals, portfolio, self.dip_state,
            raw_signal_override=resolution.selected_signal,
        )
        if forced_stage:
            stage = forced_stage[0].value.removeprefix("BUY_STAGE_")
            if resolution.forced_applied:
                reason = f"수동 강제 Stage {stage} 진입: {forced_stage[1]} / {reason}"
            else:
                reason = (
                    f"수동 강제 Stage {stage} 미적용 "
                    f"({resolution.forced_status}): {forced_stage[1]} / {reason}"
                )

        signal = TradeSignal(exposure, orders, reason)
        return StrategyDecision(
            signal=signal,
            label="DomesticQldDipBuy",
            is_rebalancing=bool(orders),
            state_key=self.STATE_KEY,
            proposed_state=new_state,
        )

    def finalize_strategy_state(
        self,
        decision: StrategyDecision,
        order_result: OrderBatchResult,
    ) -> SsoDipState:
        state = self._planner.record_filled_tranche(
            decision.proposed_state, order_result.actual_executions
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
        s = self.dip_signals

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
            if not math.isnan(s.mdd_200):
                factors.append(DecisionFactor(
                    "mdd_200", "200거래일 MDD", s.mdd_200, "percent",
                    threshold=-0.20,
                ))

        factors.append(DecisionFactor(
            "signal_level", "신호 단계", self.dip_state.level.value, "text",
        ))

        total = portfolio.total_value
        if total > 0:
            lever_val = (portfolio.holdings.get(LEVER_TICKER, 0)
                         * portfolio.current_prices.get(LEVER_TICKER, 0.0))
            factors.append(DecisionFactor(
                "lever_ratio", "레버리지 비중", lever_val / total, "percent",
            ))

        return factors
