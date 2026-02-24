import math
from typing import Dict, List, Optional
from src.core.models import MarketRegime, MarketData, Portfolio, TradeSignal, Order, OrderAction
from src.core.interfaces import ILogger

class RegimeAnalyzer:
    # BULL/SIDEWAYS 판정 기본 모멘텀 임계치 (SPY 6개월 수익률 기준)
    DEFAULT_BULL_MOMENTUM_THRESHOLD = 0.05

    def __init__(self, bull_momentum_threshold: float = 0.05):
        self.bull_momentum_threshold = bull_momentum_threshold

    def analyze(self, data: MarketData) -> MarketRegime:
        # 1. Crash Check
        if data.is_risk_condition():
            return MarketRegime.CRASH

        is_bear_momentum = data.spy_momentum < 0
        is_below_ma = data.spy_price < data.spy_ma180

        # 2. Bear Check
        if is_bear_momentum and is_below_ma:
            return MarketRegime.BEAR_STRONG
        elif is_bear_momentum or is_below_ma:
            return MarketRegime.BEAR_WEAK

        # 3. Bull / Sideways Check
        # 이 시점: momentum >= 0 AND price >= MA
        if data.spy_momentum >= self.bull_momentum_threshold:
            return MarketRegime.BULL
        else:
            # momentum이 0 이상 임계치 미만 → 횡보장
            return MarketRegime.SIDEWAYS

class VolatilityTargeter:
    # 변동성이 이 값 이하일 경우 보정하여 0으로 나누기를 방지
    MIN_VOLATILITY_FLOOR = 0.001

    # 국면별 exposure 상한선 기본값
    DEFAULT_REGIME_MAX_EXPOSURES: Dict[MarketRegime, float] = {
        MarketRegime.BEAR_STRONG: 0.4,
        MarketRegime.BEAR_WEAK: 0.6,
    }

    # exposure 하한선 기본값
    DEFAULT_MIN_EXPOSURE = 0.2

    # exposure 상한선 기본값 (regime_max_exposures에 없는 국면에 적용)
    DEFAULT_MAX_EXPOSURE = 1.0

    def __init__(self, target_vol: float = 0.15,
                 min_exposure: float = DEFAULT_MIN_EXPOSURE,
                 regime_max_exposures: Optional[Dict[MarketRegime, float]] = None,
                 max_exposure: float = DEFAULT_MAX_EXPOSURE):
        self.target_vol = target_vol
        self.min_exposure = min_exposure
        self._regime_max_exposures = dict(regime_max_exposures) if regime_max_exposures is not None else dict(self.DEFAULT_REGIME_MAX_EXPOSURES)
        self.max_exposure = max_exposure

    def calculate_exposure(self, regime: MarketRegime, current_vol: float) -> float:
        if regime == MarketRegime.CRASH:
            return 0.0

        # 0으로 나누기 방지: 극소 변동성을 최솟값으로 보정
        vol = current_vol if current_vol > self.MIN_VOLATILITY_FLOOR else self.MIN_VOLATILITY_FLOOR

        # 기본 비율 (Target Vol / Current Vol)
        base_ratio = self.target_vol / vol

        # 국면별 exposure 상한선
        upper = self._regime_max_exposures.get(regime, self.max_exposure)

        # 상한선·하한선 적용
        exposure = min(base_ratio, upper)
        return max(exposure, self.min_exposure)

class Rebalancer:
    """리밸런싱 및 주문 생성기"""

    # 국면별 리밸런싱 임계치 기본값
    DEFAULT_THRESHOLD_MAP: Dict[MarketRegime, float] = {
        MarketRegime.BULL: 0.15,
        MarketRegime.SIDEWAYS: 0.05,
        MarketRegime.BEAR_WEAK: 0.10,
        MarketRegime.BEAR_STRONG: 0.10,
    }

    # 비율 유지 시 미세 주문 필터링 임계치 (총 주문 금액 / 총 자산 비율)
    DEFAULT_MIN_ORDER_PCT = 0.05

    def __init__(self, asset_groups: Dict[str, List[str]],
                 logger: Optional[ILogger] = None,
                 threshold_map: Optional[Dict[MarketRegime, float]] = None,
                 min_order_pct: float = DEFAULT_MIN_ORDER_PCT):
        self.groups = asset_groups
        self._logger = logger
        self._threshold_map = threshold_map if threshold_map is not None else dict(self.DEFAULT_THRESHOLD_MAP)
        self.min_order_pct = min_order_pct

    def generate_signal(self,
                        portfolio: Portfolio,
                        target_exposure: float,
                        regime: MarketRegime) -> TradeSignal:

        # ── 섹션 1: 시작 구분선 + 입력 컨텍스트 ──────────────────────────────
        if self._logger:
            self._logger.info("═" * 48)
            self._logger.info(" Rebalancer.generate_signal 시작")
            self._logger.info("═" * 48)
            self._logger.info(
                f"[입력] Regime={regime.value} | TargetExposure={target_exposure:.2f} "
                f"| TotalValue=${portfolio.total_value:,.2f} | Cash=${portfolio.total_cash:,.2f}"
            )

        # [핵심 수정] CRASH 발생 시 즉시 리턴 (가드 절)
        if regime == MarketRegime.CRASH:
            if self._logger:
                self._logger.info("[CRASH] Emergency Stop. 주문 생성을 건너뜁니다.")
                self._logger.info("═" * 48)
            return TradeSignal(
                target_exposure=target_exposure,
                orders=[],
                reason="CRASH Detected: Emergency Stop. No Action."
            )

        # 1. 국면별 리밸런싱 임계치 설정
        threshold = self._threshold_map.get(regime, 0.10)

        # 2. 가격 누락 종목 경고
        if self._logger:
            for t, q in portfolio.holdings.items():
                if q > 0 and t not in portfolio.current_prices:
                    self._logger.warning(f"보유 종목 {t}의 가격 정보가 누락되어 평가액이 0으로 계산됩니다.")

        # 3. 현재 자산군(A, B) 평가액 및 비중 계산
        val_a = portfolio.get_group_value(self.groups.get('A', []))
        val_b = portfolio.get_group_value(self.groups.get('B', []))
        val_c = portfolio.get_group_value(self.groups.get('C', []))
        val_risky = val_a + val_b

        # ── 섹션 2: 포트폴리오 현황 ───────────────────────────────────────────
        total = portfolio.total_value
        def pct(v): return (v / total * 100) if total > 0 else 0.0
        if self._logger:
            self._logger.info("[포트폴리오 현황]")
            self._logger.info(f"  A그룹(성장): ${val_a:>12,.2f} ({pct(val_a):5.1f}%)")
            self._logger.info(f"  B그룹(안전): ${val_b:>12,.2f} ({pct(val_b):5.1f}%)")
            self._logger.info(f"  C그룹(현금): ${val_c:>12,.2f} ({pct(val_c):5.1f}%)")
            self._logger.info(f"  현금(예수금): ${portfolio.total_cash:>11,.2f} ({pct(portfolio.total_cash):5.1f}%)")

        # 첫 투자 여부 판별 (위험자산 보유액이 0이면 첫 투자)
        is_first_investment = (val_risky == 0)

        # A, B 상대 비중
        if is_first_investment:
            ratio_a = 0.5
            ratio_b = 0.5
            needs_rebalance = True
            current_diff = 0.0
        else:
            ratio_a = val_a / val_risky
            ratio_b = val_b / val_risky

            # 부동소수점 오차 해결
            current_diff = round(abs(ratio_a - ratio_b), 6)

            needs_rebalance = current_diff > threshold

        # ── 섹션 3: 비중 판정 ────────────────────────────────────────────────
        if self._logger:
            if is_first_investment:
                self._logger.info("[비중 판정] 첫 투자 → 50:50 초기 비율 적용")
            else:
                verdict = "임계치 초과 → 50:50 재조정" if needs_rebalance else "비율 유지 (리밸런싱 불필요)"
                self._logger.info(
                    f"[비중 판정] ratio_A={ratio_a:.3f}  ratio_B={ratio_b:.3f}"
                )
                self._logger.info(
                    f"  현재 차이: {current_diff:.1%} | 임계치: {threshold:.1%} → {verdict}"
                )

        # 3. 목표 금액 계산
        if needs_rebalance:
            target_ratio_a = 0.5
            target_ratio_b = 0.5
        else:
            target_ratio_a = ratio_a
            target_ratio_b = ratio_b

        # 최종 목표 금액 = 전체자산 * Exposure * 상대비중
        target_val_a = portfolio.total_value * target_exposure * target_ratio_a
        target_val_b = portfolio.total_value * target_exposure * target_ratio_b

        # C는 나머지 전부 (Total - A - B)
        # 현금으로 두지 않고, C그룹 주식(SHV)으로 꽉 채우는 것을 목표로 함
        target_val_c = max(portfolio.total_value - (target_val_a + target_val_b), 0)

        # ── 섹션 4: 목표 금액 ────────────────────────────────────────────────
        if self._logger:
            self._logger.info("[목표 금액]")
            self._logger.info(
                f"  A그룹: 현재 ${val_a:>10,.2f} → 목표 ${target_val_a:>10,.2f}"
                f"  (exposure {target_exposure:.2f} × ratio {target_ratio_a:.2f})"
            )
            self._logger.info(
                f"  B그룹: 현재 ${val_b:>10,.2f} → 목표 ${target_val_b:>10,.2f}"
                f"  (exposure {target_exposure:.2f} × ratio {target_ratio_b:.2f})"
            )
            self._logger.info(
                f"  C그룹: 현재 ${val_c:>10,.2f} → 목표 ${target_val_c:>10,.2f}  (잔여)"
            )

        # 4. 주문 생성 (섹션 5 로그는 _create_group_orders 내부에서 출력)
        orders = []
        orders.extend(self._create_group_orders(portfolio, self.groups.get('A', []), target_val_a, group_name='A그룹(성장)'))
        orders.extend(self._create_group_orders(portfolio, self.groups.get('B', []), target_val_b, group_name='B그룹(안전)'))
        # 남는 현금을 모두 SHV 매수에 사용하거나, 현금이 부족하면 SHV를 매도함
        orders.extend(self._create_group_orders(portfolio, self.groups.get('C', []), target_val_c, group_name='C그룹(현금)'))

        # 예수금이 없는 상황을 대비하여, 무조건 매도 주문을 먼저 실행해서 현금을 확보해야 함.
        sell_orders = [o for o in orders if o.action == OrderAction.SELL]
        buy_orders = [o for o in orders if o.action == OrderAction.BUY]

        # 정렬된 최종 주문 리스트
        sorted_orders = sell_orders + buy_orders

        # 4-1. 비율 유지 시 미세 주문 필터링
        # needs_rebalance=False인데 소액 주문만 발생하면 노이즈 트레이딩 방지
        if not needs_rebalance and not is_first_investment and sorted_orders:
            total_order_value = sum(o.quantity * o.price for o in sorted_orders)
            min_order_value = portfolio.total_value * self.min_order_pct
            if total_order_value < min_order_value:
                sorted_orders = []

        # 5. reason 결정 (주문 생성 결과를 반영)
        if is_first_investment and sorted_orders:
            reason = "첫 투자: 50:50 비율로 진입"
        elif is_first_investment and not sorted_orders:
            reason = "첫 투자: 주문 단위 미달로 진입 불가"
        elif needs_rebalance and sorted_orders:
            reason = f"비율 재조정: Threshold {threshold:.0%} 초과 (Diff: {current_diff:.1%})"
        elif needs_rebalance and not sorted_orders:
            reason = f"비율 재조정 필요하나 주문 단위 미달 (Diff: {current_diff:.1%})"
        elif not needs_rebalance and sorted_orders:
            reason = "비율 유지, exposure 조정으로 주문 발생"
        else:
            reason = "비율 유지, 추가 주문 없음"

        # ── 섹션 6: 최종 요약 + 종료 구분선 ────────────────────────────────
        if self._logger:
            sell_cnt = len(sell_orders)
            buy_cnt  = len(buy_orders)
            total_order_val = sum(o.quantity * o.price for o in sorted_orders)
            order_pct = (total_order_val / portfolio.total_value * 100) if portfolio.total_value > 0 else 0.0
            if sorted_orders:
                self._logger.info(
                    f"[최종 주문] SELL {sell_cnt}건 + BUY {buy_cnt}건 "
                    f"(총 주문금액: ${total_order_val:,.2f} / 자산대비 {order_pct:.1f}%)"
                )
            else:
                self._logger.info("[최종 주문] 주문 없음")
            self._logger.info(f"[결정 사유] {reason}")
            self._logger.info("═" * 48)

        return TradeSignal(
            target_exposure=target_exposure,
            orders=sorted_orders,
            reason=reason
        )

    def _create_group_orders(self, pf: Portfolio, tickers: List[str], group_target_amt: float, group_name: str = "") -> List[Order]:
        orders = []
        count = len(tickers)
        if count == 0: return orders

        per_stock_target = group_target_amt / count

        if self._logger and group_name:
            self._logger.info(f"[{group_name} 종목별]")

        for ticker in tickers:
            price = pf.current_prices.get(ticker, 0)
            if price <= 0:
                if self._logger:
                    self._logger.warning(f"종목 {ticker}의 가격이 유효하지 않습니다 (price={price}). 주문 생성을 건너뜁니다.")
                continue

            current_qty = pf.holdings.get(ticker, 0)
            current_val = current_qty * price

            diff_val = per_stock_target - current_val

            order_desc = "→ 주문 없음"
            if diff_val > 0:
                qty = math.floor(diff_val / price)
                if qty > 0:
                    orders.append(Order(ticker, OrderAction.BUY, qty, price))
                    order_desc = f"→ BUY {qty}주 @${price:.2f}"
                else:
                    order_desc = "→ 주문 없음 (수량 미달)"
            elif diff_val < 0:
                qty = math.ceil(abs(diff_val) / price)
                qty = min(qty, current_qty)  # 보유 수량 초과 매도 방지
                if qty > 0:
                    orders.append(Order(ticker, OrderAction.SELL, qty, price))
                    order_desc = f"→ SELL {qty}주 @${price:.2f}"
                else:
                    order_desc = "→ 주문 없음 (수량 미달)"

            if self._logger:
                self._logger.info(
                    f"  {ticker}: 보유 {current_qty}주 ${current_val:,.2f} → 목표 ${per_stock_target:,.2f} "
                    f"| diff={diff_val:+,.2f} {order_desc}"
                )

        return orders