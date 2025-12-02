from src.core.models import MarketRegime, MarketData, Portfolio, TradeSignal, Order
from typing import Dict, List

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
        if data.spy_momentum >= 0.05:
            return MarketRegime.BULL
        elif 0 < data.spy_momentum < 0.05:
            return MarketRegime.SIDEWAYS
            
        return MarketRegime.BEAR_WEAK # Fallback

class VolatilityTargeter:
    def calculate_exposure(self, regime: MarketRegime, volatility: float) -> float:
        if regime == MarketRegime.CRASH:
            return 0.0
            
        # 타겟 변동성 15%
        if volatility == 0: volatility = 0.001 # 0 나누기 방지
        base_ratio = 0.15 / volatility
        
        # 국면별 상한선(Cap)
        max_cap = 1.0
        if regime == MarketRegime.BEAR_STRONG:
            max_cap = 0.4
        elif regime == MarketRegime.BEAR_WEAK:
            max_cap = 0.6
            
        # Cap 적용
        exposure = min(base_ratio, max_cap)
        
        # 하한선(Floor) 적용 (최소 0.2배)
        return max(exposure, 0.2)

class Rebalancer:
    """리밸런싱 및 주문 생성기"""
    def __init__(self, asset_groups: Dict[str, List[str]]):
        self.groups = asset_groups # {'A': ['SSO',...], 'B': [...], 'C': [...]}

    def generate_signal(self, 
                        portfolio: Portfolio, 
                        target_exposure: float, 
                        regime: MarketRegime) -> TradeSignal:
        
        # 1. 국면별 리밸런싱 임계치 설정
        threshold_map = {
            MarketRegime.BULL: 0.15,
            MarketRegime.SIDEWAYS: 0.05,
            MarketRegime.BEAR_WEAK: 0.10,
            MarketRegime.BEAR_STRONG: 0.10,
            MarketRegime.CRASH: 0.00
        }
        threshold = threshold_map.get(regime, 0.10)
        
        # 2. 현재 자산군(A, B) 비중 계산
        val_a = portfolio.total_value * portfolio.get_allocation_ratio(self.groups['A']) if hasattr(portfolio, 'get_allocation_ratio') else \
                sum(portfolio.holdings.get(t, 0) * portfolio.current_prices.get(t, 0) for t in self.groups['A'])
        
        val_b = sum(portfolio.holdings.get(t, 0) * portfolio.current_prices.get(t, 0) for t in self.groups['B'])
        val_risky = val_a + val_b
        
        # A, B 상대 비중 (A+B=0일 땐 50:50 가정)
        if val_risky == 0:
            ratio_a = 0.5
            ratio_b = 0.5
            needs_rebalance = True # 첫 시작
        else:
            ratio_a = val_a / val_risky
            ratio_b = val_b / val_risky
            diff = abs(ratio_a - ratio_b)
            needs_rebalance = diff > threshold
            
        # 3. 목표 금액 계산
        # 리밸런싱 필요하면 5:5 리셋, 아니면 현재 비율 유지
        if needs_rebalance:
            target_ratio_a = 0.5
            target_ratio_b = 0.5
            reason = f"Threshold {threshold:.2%} 초과 (Diff: {abs(ratio_a - ratio_b):.2%})"
        else:
            target_ratio_a = ratio_a
            target_ratio_b = ratio_b
            reason = "Threshold 미만, 비율 유지"

        # 최종 목표 금액 (전체 자산 * Exposure * 상대비중)
        # 현금(C)은 남는 비중 (1 - Exposure)
        target_val_a = portfolio.total_value * target_exposure * target_ratio_a
        target_val_b = portfolio.total_value * target_exposure * target_ratio_b
        # C그룹(현금)은 주문 대상 아님 (자동으로 남음)

        # 4. 종목별 주문 생성 (동일가중)
        orders = []
        
        # Group A 주문
        cnt_a = len(self.groups['A'])
        if cnt_a > 0:
            per_stock_target = target_val_a / cnt_a
            orders.extend(self._create_orders(portfolio, self.groups['A'], per_stock_target))
            
        # Group B 주문
        cnt_b = len(self.groups['B'])
        if cnt_b > 0:
            per_stock_target = target_val_b / cnt_b
            orders.extend(self._create_orders(portfolio, self.groups['B'], per_stock_target))
            
        return TradeSignal(
            target_exposure=target_exposure,
            rebalance_needed=needs_rebalance,
            orders=orders,
            reason=reason
        )

    def _create_orders(self, pf: Portfolio, tickers: List[str], target_amount: float) -> List[Order]:
        orders = []
        for ticker in tickers:
            price = pf.current_prices.get(ticker, 0)
            if price == 0: continue
            
            current_qty = pf.holdings.get(ticker, 0)
            current_amt = current_qty * price
            
            diff_amt = target_amount - current_amt
            qty_diff = int(diff_amt / price)
            
            if qty_diff > 0:
                orders.append(Order(ticker, "BUY", abs(qty_diff), price))
            elif qty_diff < 0:
                orders.append(Order(ticker, "SELL", abs(qty_diff), price))
                
        return orders