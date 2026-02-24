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
        
        # [핵심 수정] CRASH 발생 시 즉시 리턴 (가드 절)
        if regime == MarketRegime.CRASH:
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
        val_risky = val_a + val_b

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

        # 4. 주문 생성
        orders = []
        orders.extend(self._create_group_orders(portfolio, self.groups.get('A', []), target_val_a))
        orders.extend(self._create_group_orders(portfolio, self.groups.get('B', []), target_val_b))
        # 남는 현금을 모두 SHV 매수에 사용하거나, 현금이 부족하면 SHV를 매도함
        orders.extend(self._create_group_orders(portfolio, self.groups.get('C', []), target_val_c))

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

        return TradeSignal(
            target_exposure=target_exposure,
            orders=sorted_orders,
            reason=reason
        )

    def _create_group_orders(self, pf: Portfolio, tickers: List[str], group_target_amt: float) -> List[Order]:
        orders = []
        count = len(tickers)
        if count == 0: return orders
        
        per_stock_target = group_target_amt / count
        
        for ticker in tickers:
            price = pf.current_prices.get(ticker, 0)
            if price <= 0:
                if self._logger:
                    self._logger.warning(f"종목 {ticker}의 가격이 유효하지 않습니다 (price={price}). 주문 생성을 건너뜁니다.")
                continue
            
            current_qty = pf.holdings.get(ticker, 0)
            current_val = current_qty * price
            
            diff_val = per_stock_target - current_val

            if diff_val > 0:
                qty = math.floor(diff_val / price)
                if qty > 0:
                    orders.append(Order(ticker, OrderAction.BUY, qty, price))
            elif diff_val < 0:
                qty = math.ceil(abs(diff_val) / price)
                qty = min(qty, current_qty)  # 보유 수량 초과 매도 방지
                if qty > 0:
                    orders.append(Order(ticker, OrderAction.SELL, qty, price))
                
        return orders