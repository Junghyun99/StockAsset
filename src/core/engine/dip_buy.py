# src/core/engine/dip_buy.py
"""오즐웅줍 눌림목 분할매수 엔진.

QLD 단일 종목을 대상으로 이동평균선(MA20/60/120) 눌림목과 RSI 과매도/과열을
트리거로 현금을 분할 투입/회수한다. 트랜치 큐는 strategy_state.json에 영속화되어
백테스트(엔진 재사용)와 라이브(매일 재시작)가 동일한 코드 경로로 동작한다.

현금성 자산(C그룹, 기본 SHV)을 '현금 저수지'로 사용한다: QLD에 들어가지 않은
모든 현금을 SHV로 주차해 단기채 이자를 받고, 눌림 매수 시 SHV를 팔아 자금을
확보한다. 가용현금 = 예수금 + SHV평가액으로 계산한다.
"""
from typing import List

import math

from src.core.engine.base import TradingEngine
from src.core.engine.data_pipeline import CollectedData, DataSetSpec, StrategyDataSpec
from src.core.engine.registry import register_engine
from src.core.logic.dip_buy_indicators import DipBuyIndicatorCalculator
from src.core.logic.dip_buy_planner import DipBuyPlanner, DipBuyState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, Order, OrderAction,
    DecisionFactor, OrderBatchResult, StrategyDecision,
)


@register_engine(color="#e45756")
class DipBuyEngine(TradingEngine):
    """QLD(A그룹) + SHV(C그룹 현금 저수지) 눌림목 분할매수 전략 엔진.

    - 자산군 A: [QLD] (눌림목 분할매수 대상)
    - 자산군 C: [SHV] (현금 저수지 — 유휴 현금을 주차해 단기채 이자 수취)
    - 트리거(종가 ±2% 밴드): MA20 터치 10% / MA60·120 부근 50% 5일 분할 /
      MA120 아래 & RSI<30 100% 40일 분할 / RSI>70 목표 현금비중 20%까지 5일 분할 매도
    - 가용현금 = 예수금 + SHV평가액. QLD 매수 시 SHV 매도로 자금 확보, 잔여 현금은 SHV로 스윕
    - 트랜치 큐/무장 상태는 repo(strategy_state.json)에 영속화
    """

    ASSET_GROUPS: dict = {"A": ["QLD"], "C": ["SHV"]}
    BAND: float = 0.02
    SELL_TARGET_CASH_RATIO: float = 0.20
    STATE_KEY: str = "dip_buy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ticker = self.ASSET_GROUPS["A"][0]
        # 현금 저수지 티커 (C그룹 첫 종목). 없으면 예수금만 사용(cash-only 모드).
        c_group = self.ASSET_GROUPS.get("C", [])
        self._cash_ticker = c_group[0] if c_group else None
        self._dip_calc = DipBuyIndicatorCalculator()
        self._planner = DipBuyPlanner(
            ticker=self._ticker,
            band=self.BAND,
            sell_target_cash_ratio=self.SELL_TARGET_CASH_RATIO,
        )
        # 트랜치 큐/무장 상태 복원 (국면 히스테리시스 복원과 동일 패턴)
        self.dip_state = DipBuyState.from_dict(
            self.restore_strategy_state(self.STATE_KEY)
        )
        self.dip_signals = None

    def data_spec(self) -> StrategyDataSpec:
        return StrategyDataSpec(
            reference=DataSetSpec("reference", (self._ticker,), days=400),
        )

    def calculate_strategy_indicators(self, collected: CollectedData):
        self.dip_signals = self._dip_calc.calculate(collected.reference)
        return self.dip_signals

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
        """전략 훅: 눌림목 트리거와 현금 저수지 주문만 결정한다."""
        previous_state = self.dip_state
        deployable_cash = self._deployable_cash(portfolio)
        orders, reason, new_state = self._planner.plan(
            self.dip_signals, portfolio, self.dip_state, available_cash=deployable_cash
        )
        # 현금 저수지 관리: QLD 매수 자금은 SHV 매도로 확보, 잔여 현금은 SHV로 스윕
        orders = self._apply_cash_reservoir(orders, portfolio)

        signal = TradeSignal(exposure, orders, reason)
        return StrategyDecision(
            signal=signal,
            label=type(self).__name__.removesuffix("Engine"),
            is_rebalancing=bool(orders),
            state_key=self.STATE_KEY,
            proposed_state=new_state,
            metadata={"previous_state": previous_state, "target_ticker": self._ticker},
        )

    def finalize_strategy_state(
        self,
        decision: StrategyDecision,
        order_result: OrderBatchResult,
        record_date: str | None = None,
    ) -> DipBuyState:
        target_ticker = decision.metadata["target_ticker"]
        target_requested = any(
            order.ticker == target_ticker for order in decision.signal.orders
        )
        target_filled = any(
            execution.ticker == target_ticker
            for execution in order_result.actual_executions
        )
        state = (
            decision.metadata["previous_state"]
            if target_requested and not target_filled
            else decision.proposed_state
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
        """눌림목 분할매수: MA 이격·RSI·트리거 무장 상태가 결정요소다."""
        factors: List[DecisionFactor] = []
        s = self.dip_signals
        price = portfolio.current_prices.get(self._ticker, 0.0)
        if s is not None:
            if price <= 0 and not math.isnan(s.price):
                price = s.price
            for key, ma, label in (("ma20", s.ma20, "MA20 이격"),
                                   ("ma60", s.ma60, "MA60 이격"),
                                   ("ma120", s.ma120, "MA120 이격")):
                if price > 0 and not math.isnan(ma) and ma > 0:
                    factors.append(DecisionFactor(f"gap_{key}", label,
                                                  price / ma - 1.0, "percent",
                                                  threshold=self.BAND))
            if not math.isnan(s.rsi):
                factors.append(DecisionFactor("rsi", "RSI(14)", s.rsi, "number",
                                              threshold=70.0))
        armed = self.dip_state.armed
        armed_count = sum(1 for v in armed.values() if v)
        factors.append(DecisionFactor("armed_triggers", "무장 트리거",
                                      f"{armed_count}/{len(armed)}", "text"))
        return factors

    # ── 현금 저수지(SHV) 관리 ──────────────────────────────────────────────
    def _deployable_cash(self, pf: Portfolio) -> float:
        """가용현금 = 예수금 + SHV평가액. C그룹이 없으면 예수금만."""
        if not self._cash_ticker:
            return pf.total_cash
        price = pf.current_prices.get(self._cash_ticker, 0.0)
        if price <= 0:
            return pf.total_cash
        return pf.total_cash + pf.holdings.get(self._cash_ticker, 0) * price

    def _apply_cash_reservoir(self, orders: List[Order], pf: Portfolio) -> List[Order]:
        """QLD 주문 후 잔여 현금을 SHV로 스윕(매수)하거나, 부족분만큼 SHV를 매도한다.

        브로커가 매도→매수 순으로 체결하므로, SHV 매도(자금확보)는 QLD 매수보다,
        QLD 매도(자금유입)는 SHV 매수(스윕)보다 먼저 처리된다.
        """
        if not self._cash_ticker:
            return orders
        shv = self._cash_ticker
        p_shv = pf.current_prices.get(shv, 0.0)
        p_qld = pf.current_prices.get(self._ticker, 0.0)
        if p_shv <= 0 or p_qld <= 0:
            return orders

        buy_cost = sum(o.quantity * p_qld for o in orders
                       if o.ticker == self._ticker and o.action == OrderAction.BUY)
        sell_proc = sum(o.quantity * p_qld for o in orders
                        if o.ticker == self._ticker and o.action == OrderAction.SELL)
        cash_after = pf.total_cash - buy_cost + sell_proc

        if cash_after < 0:
            # QLD 매수 자금 부족 → SHV 매도로 확보 (보유 수량 한도)
            held = pf.holdings.get(shv, 0)
            qty = min(math.ceil(-cash_after / p_shv), held)
            if qty > 0:
                orders.append(Order(shv, OrderAction.SELL, qty, p_shv))
        elif cash_after > 0:
            # 잔여 현금 → SHV 스윕 매수
            qty = math.floor(cash_after / p_shv)
            if qty > 0:
                orders.append(Order(shv, OrderAction.BUY, qty, p_shv))
        return orders


@register_engine(color="#6f42c1")
class DipBuyGatedEngine(DipBuyEngine):
    """DipBuy + 200일선 추세 게이트.

    대상(QLD)이 200일 이동평균 위(risk-on)일 때만 눌림목 분할매수를 가동하고,
    아래로 깨지면(risk-off) 보유 QLD를 전량 청산해 현금성(SHV)으로 대기한다.
    추세가 무너지는 폭락에서 자동으로 빠져 -84% 같은 꼬리 손실을 줄인다
    (백테스트상 MDD -84%→-37%, Sharpe 0.66→0.81; 수익은 연 ~2%p 양보).

    '강세장에만 가동'이라는 직관을 재량 타이밍이 아니라 규칙으로 자동화한 변형.

    참고: 200일선 부근 휩쏘를 줄이려 히스테리시스 밴드(이중 임계)를 백테스트했으나,
    2x 레버리지에선 '늦은 이탈(lag)'의 손실이 휩쏘 절약분보다 커서 오히려 MDD가
    악화됐다(밴드0 -37% vs 밴드2% -52%). 따라서 단일 임계(밴드 없음)를 채택한다.
    """

    TREND_GATE_MA: int = 200   # DipBuySignals.ma200 사용 (변경 시 지표 추가 필요)

    def build_strategy_decision(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
        record_date: str | None = None,
    ) -> StrategyDecision:
        price = portfolio.current_prices.get(self._ticker, 0.0)
        ma = self.dip_signals.ma200 if self.dip_signals is not None else float("nan")
        risk_on = price > 0 and not math.isnan(ma) and ma > 0 and price >= ma

        if risk_on:
            return super().build_strategy_decision(
                market_data, portfolio, regime, exposure, record_date=record_date
            )

        # 추세 이탈(200MA 아래) → risk-off: 보유 QLD 전량 청산 후 SHV로 대기, 상태 리셋
        orders: List[Order] = []
        held = portfolio.holdings.get(self._ticker, 0)
        if held > 0 and price > 0:
            orders.append(Order(self._ticker, OrderAction.SELL, held, price))
        orders = self._apply_cash_reservoir(orders, portfolio)

        new_state = DipBuyState()
        reason = "추세 이탈(200MA 아래) → risk-off 현금화"
        signal = TradeSignal(0.0, orders, reason)
        return StrategyDecision(
            signal=signal,
            label="DipBuyGated",
            is_rebalancing=bool(orders),
            state_key=self.STATE_KEY,
            proposed_state=new_state,
            metadata={
                "previous_state": self.dip_state,
                "target_ticker": self._ticker,
            },
        )
