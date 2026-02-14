import logging
import math
from typing import Dict, List
from src.core.models import MarketRegime, MarketData, Portfolio, TradeSignal, Order, OrderAction

logger = logging.getLogger(__name__)

class RegimeAnalyzer:
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
        if data.spy_momentum >= 0.05:
            return MarketRegime.BULL
        else:
            # momentum이 0 이상 0.05 미만 → 횡보장
            return MarketRegime.SIDEWAYS

class VolatilityTargeter:
    def __init__(self, target_vol: float = 0.15):
        self.target_vol = target_vol

    def calculate_exposure(self, regime: MarketRegime, current_vol: float) -> float:
        if regime == MarketRegime.CRASH:
            return 0.0
            
        # 0으로 나누기 방지
        vol = current_vol if current_vol > 0.001 else 0.001
        
        # 기본 비율 (Target Vol / Current Vol)
        base_ratio = self.target_vol / vol
        
        # 국면별 상한선(Cap)
        max_cap = 1.0
        if regime == MarketRegime.BEAR_STRONG:
            max_cap = 0.4
        elif regime == MarketRegime.BEAR_WEAK:
            max_cap = 0.6
            
        # Cap 적용 및 하한선(Floor, 0.2) 적용
        exposure = min(base_ratio, max_cap)
        return max(exposure, 0.2)

class Rebalancer:
    """리밸런싱 및 주문 생성기"""
    def __init__(self, asset_groups: Dict[str, List[str]]):
        self.groups = asset_groups

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
        threshold_map = {
            MarketRegime.BULL: 0.15,
            MarketRegime.SIDEWAYS: 0.05,
            MarketRegime.BEAR_WEAK: 0.10,
            MarketRegime.BEAR_STRONG: 0.10,
        }
        threshold = threshold_map.get(regime, 0.10)
        
        # 2. 현재 자산군(A, B) 평가액 및 비중 계산
        val_a = portfolio.get_group_value(self.groups.get('A', []))
        val_b = portfolio.get_group_value(self.groups.get('B', []))
        val_risky = val_a + val_b

        # A, B 상대 비중
        if val_risky == 0:
            ratio_a = 0.5
            ratio_b = 0.5
            needs_rebalance = True # 첫 투자
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

        # 5. reason 결정 (주문 생성 결과를 반영)
        if needs_rebalance and sorted_orders:
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
                logger.warning("종목 %s의 가격이 유효하지 않습니다 (price=%s). 주문 생성을 건너뜁니다.", ticker, price)
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