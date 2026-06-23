import math
from typing import Dict, List, Optional, Tuple
from src.core.models import MarketRegime, Portfolio, TradeSignal, Order, OrderAction
from src.core.interfaces import ILogger
from src.config import ticker_display


class Rebalancer:
    """리밸런싱 및 주문 생성기"""

    # 국면별 리밸런싱 임계치 기본값 (각 그룹의 상대이탈 기준)
    DEFAULT_THRESHOLD_MAP: Dict[MarketRegime, float] = {
        MarketRegime.BULL: 0.075,
        MarketRegime.SIDEWAYS: 0.025,
        MarketRegime.BEAR_WEAK: 0.05,
        MarketRegime.BEAR_STRONG: 0.05,
        MarketRegime.CRASH: 0.05,
    }

    # 비율 유지 시 미세 주문 필터링 임계치 (총 주문 금액 / 총 자산 비율)
    DEFAULT_MIN_ORDER_PCT = 0.05

    # A:B 기본 비율 (A그룹 비율, B = 1 - A)
    DEFAULT_RATIO_A = 0.5

    def __init__(self, asset_groups: Dict[str, List[str]],
                 logger: Optional[ILogger] = None,
                 threshold_map: Optional[Dict[MarketRegime, float]] = None,
                 min_order_pct: float = DEFAULT_MIN_ORDER_PCT,
                 ratio_a: float = DEFAULT_RATIO_A,
                 regime_ratio_a_map: Optional[Dict[MarketRegime, float]] = None):
        if not (0.0 < ratio_a < 1.0):
            raise ValueError(f"ratio_a must be between 0 and 1 exclusive, got {ratio_a}")
        if regime_ratio_a_map is not None:
            for regime, val in regime_ratio_a_map.items():
                if not (0.0 <= val < 1.0):
                    raise ValueError(f"regime_ratio_a_map[{regime.value}] must be in [0, 1), got {val}")
        self.groups = asset_groups
        self._logger = logger
        self._threshold_map = threshold_map if threshold_map is not None else dict(self.DEFAULT_THRESHOLD_MAP)
        self.min_order_pct = min_order_pct
        self.ratio_a = ratio_a
        self.ratio_b = round(1.0 - ratio_a, 10)
        self._regime_ratio_a_map = regime_ratio_a_map

    # ===================================================================
    # Public API
    # ===================================================================

    def generate_signal(self,
                        portfolio: Portfolio,
                        target_exposure: float,
                        regime: MarketRegime) -> TradeSignal:
        eff_a, eff_b = self._resolve_ratios(regime)
        threshold = self._threshold_map.get(regime, 0.05)

        self._log_header(regime, target_exposure, portfolio, eff_a)
        self._warn_missing_prices(portfolio)

        val_a, val_b, val_c, val_risky = self._compute_group_values(portfolio)
        self._log_portfolio(val_a, val_b, val_c, portfolio)

        is_first, ratio_a, ratio_b, rel_dev_a, rel_dev_b, needs_rebalance = \
            self._determine_rebalance(val_a, val_b, val_risky, eff_a, eff_b, threshold)

        ratio_str = f"{eff_a*100:.0f}:{eff_b*100:.0f}"
        self._log_verdict(is_first, ratio_str, ratio_a, ratio_b, rel_dev_a, rel_dev_b, threshold, needs_rebalance)

        target_ratio_a = eff_a if needs_rebalance else ratio_a
        target_ratio_b = eff_b if needs_rebalance else ratio_b
        target_val_a, target_val_b, target_val_c = self._compute_targets(
            portfolio, target_exposure, target_ratio_a, target_ratio_b
        )
        self._log_targets(val_a, val_b, val_c, target_val_a, target_val_b, target_val_c,
                          target_exposure, target_ratio_a, target_ratio_b)

        # 주문 생성 (섹션 5 로그는 _create_group_orders 내부에서 출력)
        orders = []
        orders.extend(self._create_group_orders(portfolio, self.groups.get('A', []), target_val_a, group_name='A그룹(성장)'))
        orders.extend(self._create_group_orders(portfolio, self.groups.get('B', []), target_val_b, group_name='B그룹(안전)'))
        # 남는 현금을 모두 SHV 매수에 사용하거나, 현금이 부족하면 SHV를 매도함
        orders.extend(self._create_group_orders(portfolio, self.groups.get('C', []), target_val_c, group_name='C그룹(현금)'))

        sorted_orders, sell_cnt, buy_cnt = self._sort_and_filter_orders(
            orders, portfolio, needs_rebalance, is_first
        )

        # 리밸런싱 불필요 & 주문 없음 → 현금 소진 매수 시도
        is_cash_deployment = False
        if not needs_rebalance and not is_first and not sorted_orders:
            raw_buy_orders = [o for o in orders if o.action == OrderAction.BUY]
            if raw_buy_orders and portfolio.total_cash > 0:
                cash_orders = self._create_cash_deployment_orders(raw_buy_orders, portfolio.total_cash)
                if cash_orders:
                    sorted_orders = cash_orders
                    sell_cnt = 0
                    buy_cnt = len(cash_orders)
                    is_cash_deployment = True

        reason = self._build_reason(is_first, needs_rebalance, sorted_orders,
                                    rel_dev_a, rel_dev_b, threshold, ratio_str,
                                    is_cash_deployment=is_cash_deployment)

        self._log_summary(sorted_orders, sell_cnt, buy_cnt, portfolio, reason)

        return TradeSignal(
            target_exposure=target_exposure,
            orders=sorted_orders,
            reason=reason,
            target_ratio_a=eff_a,
            rebalance_threshold=threshold,
        )

    # ===================================================================
    # Domain helpers
    # ===================================================================

    def get_target_params(self, regime: MarketRegime) -> Tuple[float, float]:
        """국면에 따른 (target_ratio_a, rebalance_threshold) 반환."""
        eff_a, _ = self._resolve_ratios(regime)
        threshold = self._threshold_map.get(regime, 0.05)
        return eff_a, threshold

    def _resolve_ratios(self, regime: MarketRegime) -> Tuple[float, float]:
        """국면별 ratio_a 조회 (맵이 없으면 고정값 사용)"""
        if self._regime_ratio_a_map is not None:
            eff_a = self._regime_ratio_a_map.get(regime, self.ratio_a)
        else:
            eff_a = self.ratio_a
        eff_b = round(1.0 - eff_a, 10)
        return eff_a, eff_b

    def _compute_group_values(self, portfolio: Portfolio) -> Tuple[float, float, float, float]:
        val_a = portfolio.get_group_value(self.groups.get('A', []))
        val_b = portfolio.get_group_value(self.groups.get('B', []))
        val_c = portfolio.get_group_value(self.groups.get('C', []))
        return val_a, val_b, val_c, val_a + val_b

    def _determine_rebalance(self, val_a: float, val_b: float, val_risky: float,
                             eff_a: float, eff_b: float, threshold: float
                             ) -> Tuple[bool, float, float, float, float, bool]:
        """리밸런싱 필요 여부와 현재 비중·이탈도를 계산한다."""
        is_first = (val_risky == 0)
        if is_first:
            return True, eff_a, eff_b, 0.0, 0.0, True

        ratio_a = val_a / val_risky
        ratio_b = val_b / val_risky
        rel_dev_a = round(abs(ratio_a - eff_a) / eff_a, 6) if eff_a > 0 else 0.0
        rel_dev_b = round(abs(ratio_b - eff_b) / eff_b, 6) if eff_b > 0 else 0.0
        needs_rebalance = (rel_dev_a > threshold) or (rel_dev_b > threshold)
        return False, ratio_a, ratio_b, rel_dev_a, rel_dev_b, needs_rebalance

    def _compute_targets(self, portfolio: Portfolio, target_exposure: float,
                         target_ratio_a: float, target_ratio_b: float
                         ) -> Tuple[float, float, float]:
        target_val_a = portfolio.total_value * target_exposure * target_ratio_a
        target_val_b = portfolio.total_value * target_exposure * target_ratio_b
        # C는 나머지 전부 (Total - A - B)
        # 현금으로 두지 않고, C그룹 주식(SHV)으로 꽉 채우는 것을 목표로 함
        target_val_c = max(portfolio.total_value - (target_val_a + target_val_b), 0)
        return target_val_a, target_val_b, target_val_c

    def _sort_and_filter_orders(self, orders: List[Order], portfolio: Portfolio,
                                needs_rebalance: bool, is_first: bool
                                ) -> Tuple[List[Order], int, int]:
        # 예수금이 없는 상황을 대비하여, 무조건 매도 주문을 먼저 실행해서 현금을 확보해야 함.
        sell_orders = [o for o in orders if o.action == OrderAction.SELL]
        buy_orders = [o for o in orders if o.action == OrderAction.BUY]
        sorted_orders = sell_orders + buy_orders

        # 비율 유지 시 미세 주문 필터링: 노이즈 트레이딩 방지
        if not needs_rebalance and not is_first and sorted_orders:
            total_order_value = sum(o.quantity * o.price for o in sorted_orders)
            min_order_value = portfolio.total_value * self.min_order_pct
            if total_order_value < min_order_value:
                sorted_orders = []

        return sorted_orders, len(sell_orders), len(buy_orders)

    def _create_cash_deployment_orders(
        self,
        buy_orders: List[Order],
        available_cash: float,
    ) -> List[Order]:
        """리밸런싱 불필요 시 남은 현금으로 BUY 주문 생성. 현금 부족 시 부분 매수."""
        result = []
        remaining = available_cash
        for order in buy_orders:
            if remaining <= 0:
                break
            if order.price <= 0:
                continue
            max_qty = int(remaining / order.price)
            actual_qty = min(order.quantity, max_qty)
            if actual_qty > 0:
                result.append(Order(order.ticker, OrderAction.BUY, actual_qty, order.price))
                remaining -= actual_qty * order.price
        return result

    def _build_reason(self, is_first: bool, needs_rebalance: bool, sorted_orders: List[Order],
                      rel_dev_a: float, rel_dev_b: float, threshold: float, ratio_str: str,
                      is_cash_deployment: bool = False) -> str:
        if is_first and sorted_orders:
            return f"첫 투자: {ratio_str} 비율로 진입"
        if is_first and not sorted_orders:
            return "첫 투자: 주문 단위 미달로 진입 불가"
        if needs_rebalance and sorted_orders:
            max_dev = max(rel_dev_a, rel_dev_b)
            return f"비율 재조정: 상대이탈 {max_dev:.1%} > 임계치 {threshold:.1%}"
        if needs_rebalance and not sorted_orders:
            max_dev = max(rel_dev_a, rel_dev_b)
            return f"비율 재조정 필요하나 주문 단위 미달 (상대이탈: {max_dev:.1%})"
        if not needs_rebalance and sorted_orders:
            if is_cash_deployment:
                return "비율 유지, 현금 소진 매수"
            return "비율 유지, exposure 조정으로 주문 발생"
        return "비율 유지, 추가 주문 없음"

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
                    self._logger.warning(f"종목 {ticker_display(ticker)}의 가격이 유효하지 않습니다 (price={price}). 주문 생성을 건너뜁니다.")
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
                    f"  {ticker_display(ticker)}: 보유 {current_qty}주 ${current_val:,.2f} → 목표 ${per_stock_target:,.2f} "
                    f"| diff={diff_val:+,.2f} {order_desc}"
                )

        return orders

    # ===================================================================
    # Logging helpers
    # ===================================================================

    def _warn_missing_prices(self, portfolio: Portfolio) -> None:
        if not self._logger:
            return
        for t, q in portfolio.holdings.items():
            if q > 0 and t not in portfolio.current_prices:
                self._logger.warning(f"보유 종목 {ticker_display(t)}의 가격 정보가 누락되어 평가액이 0으로 계산됩니다.")

    def _log_header(self, regime: MarketRegime, target_exposure: float,
                    portfolio: Portfolio, eff_a: float) -> None:
        if not self._logger:
            return
        self._logger.info(
            f"[입력] Regime={regime.value} | TargetExposure={target_exposure:.2f} "
            f"| TotalValue=${portfolio.total_value:,.2f} | Cash=${portfolio.total_cash:,.2f}"
        )
        if self._regime_ratio_a_map is not None:
            self._logger.info(
                f"[국면별 ratio_a] {regime.value} → ratio_a={eff_a:.2f}"
            )

    def _log_portfolio(self, val_a: float, val_b: float, val_c: float, portfolio: Portfolio) -> None:
        if not self._logger:
            return
        total = portfolio.total_value
        def pct(v): return (v / total * 100) if total > 0 else 0.0
        self._logger.info("[포트폴리오 현황]")
        self._logger.info(f"  A그룹(성장): ${val_a:>12,.2f} ({pct(val_a):5.1f}%)")
        self._logger.info(f"  B그룹(안전): ${val_b:>12,.2f} ({pct(val_b):5.1f}%)")
        self._logger.info(f"  C그룹(현금): ${val_c:>12,.2f} ({pct(val_c):5.1f}%)")
        self._logger.info(f"  현금(예수금): ${portfolio.total_cash:>11,.2f} ({pct(portfolio.total_cash):5.1f}%)")

    def _log_verdict(self, is_first: bool, ratio_str: str, ratio_a: float, ratio_b: float,
                     rel_dev_a: float, rel_dev_b: float, threshold: float, needs_rebalance: bool) -> None:
        if not self._logger:
            return
        if is_first:
            self._logger.info(f"[비중 판정] 첫 투자 → {ratio_str} 초기 비율 적용")
        else:
            verdict = f"임계치 초과 → {ratio_str} 재조정" if needs_rebalance else "비율 유지 (리밸런싱 불필요)"
            self._logger.info(
                f"[비중 판정] ratio_A={ratio_a:.3f}  ratio_B={ratio_b:.3f}"
            )
            self._logger.info(
                f"  A 상대이탈: {rel_dev_a:.1%} | B 상대이탈: {rel_dev_b:.1%}"
                f" | 임계치: {threshold:.1%} → {verdict}"
            )

    def _log_targets(self, val_a: float, val_b: float, val_c: float,
                     target_val_a: float, target_val_b: float, target_val_c: float,
                     target_exposure: float, target_ratio_a: float, target_ratio_b: float) -> None:
        if not self._logger:
            return
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

    def _log_summary(self, sorted_orders: List[Order], sell_cnt: int, buy_cnt: int,
                     portfolio: Portfolio, reason: str) -> None:
        if not self._logger:
            return
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
