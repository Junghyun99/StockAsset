# tests/test_core_logic.py
import pytest
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.core.models import MarketRegime

def test_regime_analyzer_bear_strong(mock_market_bear):
    analyzer = RegimeAnalyzer()
    regime = analyzer.analyze(mock_market_bear)
    assert regime == MarketRegime.BEAR_STRONG

def test_volatility_targeter_caps(mock_market_bear):
    targeter = VolatilityTargeter()
    # Bear Strong일 때, 변동성이 낮더라도 Max 0.4 제한 확인
    # 계산상: 0.15 / 0.10 = 1.5배여야 하지만 -> 0.4로 캡
    exposure = targeter.calculate_exposure(MarketRegime.BEAR_STRONG, volatility=0.10)
    assert exposure == 0.4

def test_rebalancer_initial_buy(mock_portfolio):
    groups = {'A': ['SSO'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 하락장(0.4배 투자), A:B 50:50 목표
    signal = rebalancer.generate_signal(mock_portfolio, target_exposure=0.4, regime=MarketRegime.BEAR_STRONG)
    
    assert signal.rebalance_needed is True
    # 총자산 10000 -> 투자분 4000 -> A: 2000, B: 2000
    # 가격 100 -> 각 20주 매수
    assert len(signal.orders) == 2
    assert signal.orders[0].action == "BUY"
    assert signal.orders[0].quantity == 20