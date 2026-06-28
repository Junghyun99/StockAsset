# src/core/engine/dip_buy.py
"""오즐웅줍 눌림목 분할매수 엔진.

QLD 단일 종목을 대상으로 이동평균선(MA20/60/120) 눌림목과 RSI 과매도/과열을
트리거로 현금을 분할 투입/회수한다. 트랜치 큐는 strategy_state.json에 영속화되어
백테스트(엔진 재사용)와 라이브(매일 재시작)가 동일한 코드 경로로 동작한다.

현금성 자산(C그룹, 기본 SHV)을 '현금 저수지'로 사용한다: QLD에 들어가지 않은
모든 현금을 SHV로 주차해 단기채 이자를 받고, 눌림 매수 시 SHV를 팔아 자금을
확보한다. 가용현금 = 예수금 + SHV평가액으로 계산한다.
"""
from typing import List, Optional, Tuple

import math
import pandas as pd

from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.dip_buy_indicators import DipBuyIndicatorCalculator
from src.core.logic.dip_buy_planner import DipBuyPlanner, DipBuyState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution, Order, OrderAction,
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
        self.dip_state = DipBuyState.from_dict(self.repo.load_strategy_state(self.STATE_KEY))
        self.dip_signals = None

    def collect_data(self, data_provider: IDataProvider) -> Tuple[pd.DataFrame, float]:
        """Step 1 오버라이드: SPY 대신 대상 티커(QLD) OHLCV를 수집한다."""
        df = data_provider.fetch_ohlcv([self._ticker], days=400)
        vix = data_provider.fetch_vix()
        return df, vix

    def calculate_indicators(self, spy_df: pd.DataFrame, vix: float) -> MarketData:
        """Step 2 오버라이드: 대시보드/repo 호환 MarketData + 눌림목 지표 동시 계산."""
        self.dip_signals = self._dip_calc.calculate(spy_df)
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
        """Step 5 오버라이드: Rebalancer 대신 DipBuyPlanner로 트리거 기반 매매."""
        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = False

        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}")
            self.logger.error(f"NaN detected: {', '.join(nan_fields)} — 매매 중단")
            return signal, executions, final_pf, is_rebalancing

        deployable_cash = self._deployable_cash(portfolio)
        orders, reason, new_state = self._planner.plan(
            self.dip_signals, portfolio, self.dip_state, available_cash=deployable_cash
        )
        # 현금 저수지 관리: QLD 매수 자금은 SHV 매도로 확보, 잔여 현금은 SHV로 스윕
        orders = self._apply_cash_reservoir(orders, portfolio)

        signal = TradeSignal(exposure, orders, reason)
        self.logger.info(f">>> Step 5: DipBuy ({reason})")

        if orders:
            is_rebalancing = True
            self.logger.info(f"Executing {len(orders)} orders ({reason})")
            executions = self.broker.execute_orders(orders)
            try:
                final_pf = self.broker.get_portfolio()
            except RuntimeError as e:
                self.logger.error(f"거래 후 포트폴리오 조회 실패 — 거래 전 포트폴리오로 대체: {e}")
                final_pf = portfolio

        # 상태 갱신 + 영속화는 주문 실행 시도 이후에 수행한다. execute_orders가
        # 예외로 중단되면 차감된 트랜치 상태가 저장되지 않아, 다음 거래일에 동일
        # 상태로 재시도된다 (주문 미실행 + 상태 차감의 불일치 방지).
        self.dip_state = new_state
        self.repo.save_strategy_state(self.STATE_KEY, new_state.to_dict())

        return signal, executions, final_pf, is_rebalancing

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
    """

    TREND_GATE_MA: int = 200   # DipBuySignals.ma200 사용 (변경 시 지표 추가 필요)

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
        if nan_fields:
            return super().execute_cycle(market_data, portfolio, regime, exposure,
                                         nan_fields, sim_date, record_date)

        price = portfolio.current_prices.get(self._ticker, 0.0)
        ma = self.dip_signals.ma200 if self.dip_signals is not None else float("nan")
        risk_on = price > 0 and not math.isnan(ma) and ma > 0 and price >= ma

        if risk_on:
            # 추세 위 → 정상 DipBuy 위임
            return super().execute_cycle(market_data, portfolio, regime, exposure,
                                         nan_fields, sim_date, record_date)

        # 추세 이탈(200MA 아래) → risk-off: 보유 QLD 전량 청산 후 SHV로 대기, 상태 리셋
        orders: List[Order] = []
        held = portfolio.holdings.get(self._ticker, 0)
        if held > 0 and price > 0:
            orders.append(Order(self._ticker, OrderAction.SELL, held, price))
        orders = self._apply_cash_reservoir(orders, portfolio)

        new_state = DipBuyState()
        self.dip_state = new_state
        self.repo.save_strategy_state(self.STATE_KEY, new_state.to_dict())

        reason = "추세 이탈(200MA 아래) → risk-off 현금화"
        signal = TradeSignal(0.0, orders, reason)
        self.logger.info(f">>> Step 5: DipBuyGated ({reason})")

        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = bool(orders)
        if orders:
            executions = self.broker.execute_orders(orders)
            try:
                final_pf = self.broker.get_portfolio()
            except RuntimeError as e:
                self.logger.error(f"거래 후 포트폴리오 조회 실패 — 거래 전 포트폴리오로 대체: {e}")
                final_pf = portfolio

        return signal, executions, final_pf, is_rebalancing
