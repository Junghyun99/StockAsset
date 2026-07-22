# src/core/engine/qld_dip_buy.py
"""QLD/QQQI 신호 기반 분할매수 엔진.

QLD 주봉 RSI + 200일선 괴리율로 매수/매도 신호를 감지하고,
QLD(NASDAQ 2x 레버리지)를 단계적으로 분할매수/매도한다.
나머지 자산은 QQQI(NASDAQ 커버드콜)에 배분하여 인컴을 확보한다.

SsoDipBuyEngine의 NASDAQ 버전. 신호 임계값과 플래너 로직은 동일하다.
"""
from typing import List, Optional, Tuple

import math
import pandas as pd

from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.sso_dip_signals import SsoDipIndicatorCalculator
from src.core.logic.sso_dip_planner import SsoDipPlanner, SsoDipState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution,
    DecisionFactor,
)


class QldDipPlanner(SsoDipPlanner):
    """QLD/QQQI 티커를 사용하는 DipBuy 플래너."""

    SSO_TICKER = "QLD"
    SPYI_TICKER = "QQQI"


@register_engine(color="#9b59b6", backtest=False)
class QldDipBuyEngine(TradingEngine):
    """QLD/QQQI 신호 기반 분할매수 전략 엔진."""

    ASSET_GROUPS: dict = {"A": ["QLD"], "B": ["QQQI"]}
    STATE_KEY: str = "qld_dip_buy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._signal_calc = SsoDipIndicatorCalculator()
        self._planner = QldDipPlanner()
        self.dip_state = SsoDipState.from_dict(
            self.repo.load_strategy_state(self.STATE_KEY)
        )
        self._signal_df = None
        self.dip_signals = None

    def collect_data(
        self, data_provider: IDataProvider
    ) -> Tuple[pd.DataFrame, float]:
        spy_df = data_provider.fetch_ohlcv(["SPY"], days=400)
        self._signal_df = data_provider.fetch_ohlcv(["QLD"], days=400)
        vix = data_provider.fetch_vix()
        return spy_df, vix

    def calculate_indicators(
        self, spy_df: pd.DataFrame, vix: float
    ) -> MarketData:
        self.dip_signals = self._signal_calc.calculate(self._signal_df)
        return self.calculator.calculate(spy_df, vix)

    def execute_cycle(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
        nan_fields: List[str],
        sim_date: Optional[str],
        record_date: str,
    ) -> Tuple[TradeSignal, List[TradeExecution], Portfolio, bool]:
        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = False

        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}")
            self.logger.error(f"NaN detected: {', '.join(nan_fields)} — 매매 중단")
            return signal, executions, final_pf, is_rebalancing

        orders, reason, new_state = self._planner.plan(
            self.dip_signals, portfolio, self.dip_state,
        )

        signal = TradeSignal(exposure, orders, reason)
        self.logger.info(f">>> Step 5: QldDipBuy ({reason})")

        if orders:
            is_rebalancing = True
            self.logger.info(f"Executing {len(orders)} orders ({reason})")
            executions = self.broker.execute_orders(orders)
            try:
                final_pf = self.broker.get_portfolio()
            except RuntimeError as e:
                self.logger.error(
                    f"거래 후 포트폴리오 조회 실패 — 거래 전 포트폴리오로 대체: {e}"
                )
                final_pf = portfolio

        new_state = self._planner.record_filled_tranche(new_state, executions)
        self.dip_state = new_state
        self.repo.save_strategy_state(self.STATE_KEY, new_state.to_dict())

        return signal, executions, final_pf, is_rebalancing

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

        factors.append(DecisionFactor(
            "signal_level", "신호 단계", self.dip_state.level.value, "text",
        ))

        total = portfolio.total_value
        if total > 0:
            qld_val = (portfolio.holdings.get("QLD", 0)
                       * portfolio.current_prices.get("QLD", 0.0))
            factors.append(DecisionFactor(
                "qld_ratio", "QLD 비중", qld_val / total, "percent",
            ))

        return factors
