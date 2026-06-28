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

    참고: 200일선 부근 휩쏘를 줄이려 히스테리시스 밴드(이중 임계)를 백테스트했으나,
    2x 레버리지에선 '늦은 이탈(lag)'의 손실이 휩쏘 절약분보다 커서 오히려 MDD가
    악화됐다(밴드0 -37% vs 밴드2% -52%). 따라서 단일 임계(밴드 없음)를 채택한다.
    """

    TREND_GATE_MA: int = 200   # DipBuySignals.ma200 사용 (변경 시 지표 추가 필요)
    # risk-off(추세 이탈) 때 보유할 자산. None이면 현금성(SHV)으로 대기.
    # 예: "SPY"로 두면 추세 이탈 구간에 1x 광의시장을 보유(DipBuyGatedSpyEngine).
    RISK_OFF_TICKER: Optional[str] = None

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

        if self.dip_signals is None:
            signal = TradeSignal(0.0, [], "지표 데이터 없음 (dip_signals=None) — 매매 중단")
            self.logger.error("dip_signals is None — 매매 중단")
            return signal, [], portfolio, False

        price = portfolio.current_prices.get(self._ticker, 0.0)
        ma = self.dip_signals.ma200
        risk_on = price > 0 and not math.isnan(ma) and ma > 0 and price >= ma
        r = self.RISK_OFF_TICKER

        # 가격 검증: 이번 사이클에 거래가 필요한 종목의 현재가가 없으면(≤0) 상태 변경 없이 중단.
        # (특히 risk-off 전환 시 r 가격이 없으면 기존 자산만 팔고 r은 못 사 의도치 않게
        #  100% 현금이 되는 문제를 방지 — 베이스 엔진의 zero-price 가드와 동일 철학)
        bad = []
        if portfolio.holdings.get(self._ticker, 0) > 0 and price <= 0:
            bad.append(self._ticker)
        if self._cash_ticker and portfolio.holdings.get(self._cash_ticker, 0) > 0 \
                and portfolio.current_prices.get(self._cash_ticker, 0.0) <= 0:
            bad.append(self._cash_ticker)
        if r and portfolio.current_prices.get(r, 0.0) <= 0 \
                and (not risk_on or portfolio.holdings.get(r, 0) > 0):
            bad.append(r)
        if bad:
            reason = f"가격 조회 실패 — 매매 중단: {', '.join(bad)}"
            self.logger.error(reason)
            return TradeSignal(0.0, [], reason), [], portfolio, False

        if risk_on:
            # risk-off 자산을 보유 중이면 먼저 청산(전환 사이클), 아니면 정상 DipBuy 위임
            if r and portfolio.holdings.get(r, 0) > 0:
                return self._finalize(self._exit_risk_off_asset(portfolio), portfolio,
                                      f"추세 복귀 → {r} 청산 후 DipBuy 재개")
            return super().execute_cycle(market_data, portfolio, regime, exposure,
                                         nan_fields, sim_date, record_date)

        # 추세 이탈(200MA 아래) → risk-off
        if r:
            return self._finalize(self._enter_risk_off_asset(portfolio), portfolio,
                                  f"추세 이탈(200MA 아래) → {r} 100% 보유")
        # 기본: 보유 QLD 전량 청산 후 현금성(SHV)으로 대기
        orders: List[Order] = []
        held = portfolio.holdings.get(self._ticker, 0)
        if held > 0 and price > 0:
            orders.append(Order(self._ticker, OrderAction.SELL, held, price))
        orders = self._apply_cash_reservoir(orders, portfolio)
        return self._finalize(orders, portfolio, "추세 이탈(200MA 아래) → risk-off 현금화")

    # ── risk-off 자산 전환 헬퍼 ─────────────────────────────────────────────
    def _enter_risk_off_asset(self, portfolio: Portfolio) -> List[Order]:
        """QLD·SHV 전량 청산 후 RISK_OFF_TICKER로 가용현금 전액 매수."""
        r = self.RISK_OFF_TICKER
        p_r = portfolio.current_prices.get(r, 0.0)
        price = portfolio.current_prices.get(self._ticker, 0.0)
        orders: List[Order] = []
        cash_avail = portfolio.total_cash

        qld_held = portfolio.holdings.get(self._ticker, 0)
        if qld_held > 0 and price > 0:
            orders.append(Order(self._ticker, OrderAction.SELL, qld_held, price))
            cash_avail += qld_held * price
        shv = self._cash_ticker
        if shv:
            p_shv = portfolio.current_prices.get(shv, 0.0)
            shv_held = portfolio.holdings.get(shv, 0)
            if shv_held > 0 and p_shv > 0:
                orders.append(Order(shv, OrderAction.SELL, shv_held, p_shv))
                cash_avail += shv_held * p_shv
        if p_r > 0:
            qty = math.floor(cash_avail / p_r)
            if qty > 0:
                orders.append(Order(r, OrderAction.BUY, qty, p_r))
        return orders

    def _exit_risk_off_asset(self, portfolio: Portfolio) -> List[Order]:
        """RISK_OFF_TICKER 전량 청산 후 잔여 현금을 SHV로 스윕(다음 사이클 DipBuy 재개)."""
        r = self.RISK_OFF_TICKER
        p_r = portfolio.current_prices.get(r, 0.0)
        orders: List[Order] = []
        cash_avail = portfolio.total_cash
        r_held = portfolio.holdings.get(r, 0)
        if r_held > 0 and p_r > 0:
            orders.append(Order(r, OrderAction.SELL, r_held, p_r))
            cash_avail += r_held * p_r
        shv = self._cash_ticker
        if shv:
            p_shv = portfolio.current_prices.get(shv, 0.0)
            if p_shv > 0:
                qty = math.floor(cash_avail / p_shv)
                if qty > 0:
                    orders.append(Order(shv, OrderAction.BUY, qty, p_shv))
        return orders

    def _finalize(self, orders: List[Order], portfolio: Portfolio, reason: str
                  ) -> Tuple[TradeSignal, List[TradeExecution], Portfolio, bool]:
        """risk-off/전환 주문을 실행하고 결과 튜플 생성 (DipBuy 비활성 → 상태 리셋)."""
        new_state = DipBuyState()
        # 이미 초기화 상태면 디스크 재쓰기를 건너뛴다 (장기 risk-off 구간 불필요 I/O 절감)
        if self.dip_state.to_dict() != new_state.to_dict():
            self.repo.save_strategy_state(self.STATE_KEY, new_state.to_dict())
        self.dip_state = new_state

        signal = TradeSignal(0.0, orders, reason)
        self.logger.info(f">>> Step 5: DipBuyGated ({reason})")

        executions: List[TradeExecution] = []
        final_pf = portfolio
        if orders:
            executions = self.broker.execute_orders(orders)
            try:
                final_pf = self.broker.get_portfolio()
            except RuntimeError as e:
                self.logger.error(f"거래 후 포트폴리오 조회 실패 — 거래 전 포트폴리오로 대체: {e}")
                final_pf = portfolio
        return signal, executions, final_pf, bool(orders)


@register_engine(color="#20c997")
class DipBuyGatedSpyEngine(DipBuyGatedEngine):
    """DipBuyGated 변형 — risk-off(추세 이탈) 때 현금(SHV) 대신 SPY(1x)를 100% 보유.

    QLD가 200일선 위면 눌림목 분할매수(QLD+SHV), 아래로 깨지면 전량 SPY로 전환한다.
    추세 이탈 구간에서도 1x 광의시장 수익을 노리는 변형 — 다만 SPY도 하락장엔 함께
    빠지므로 효과는 국면 의존적(현금 버전 대비 비교는 run-compare-backtest로 검증).
    """

    ASSET_GROUPS: dict = {"A": ["QLD"], "B": ["SPY"], "C": ["SHV"]}
    RISK_OFF_TICKER: str = "SPY"
