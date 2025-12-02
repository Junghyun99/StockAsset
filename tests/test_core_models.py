import pytest
from src.core.models import MarketData, Portfolio

# ==========================================
# 1. MarketData 테스트 (경계값 검증)
# ==========================================

def test_market_data_boundary_conditions():
    """
    [경계값 테스트]
    MDD가 정확히 -20%이거나, VIX가 정확히 30일 때는 위험으로 간주하는가?
    로직: mdd < -0.20 OR vix > 30
    """
    # Case 1: MDD -20% (Safe)
    # -0.20 < -0.20 은 False이므로 안전함
    data_boundary_mdd = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.20, vix=20.0 
    )
    assert data_boundary_mdd.is_risk_condition() is False

    # Case 2: MDD -20.1% (Risk)
    data_risk_mdd = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.200001, vix=20.0 
    )
    assert data_risk_mdd.is_risk_condition() is True

    # Case 3: VIX 30.0 (Safe)
    # 30 > 30 은 False이므로 안전함
    data_boundary_vix = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.10, vix=30.0
    )
    assert data_boundary_vix.is_risk_condition() is False

    # Case 4: VIX 30.1 (Risk)
    data_risk_vix = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.10, vix=30.1
    )
    assert data_risk_vix.is_risk_condition() is True


# ==========================================
# 2. Portfolio 테스트 (예외 상황 검증)
# ==========================================

def test_portfolio_missing_price_safety():
    """
    [누락 데이터 테스트]
    보유 종목은 있는데, 현재가 정보(Prices)가 딕셔너리에 없다면?
    -> 에러가 나지 않고 가치를 0으로 계산해야 한다. (.get(t, 0) 동작 확인)
    """
    pf = Portfolio(
        total_cash=1000.0,
        holdings={'SPY': 10, 'UNKNOWN_STOCK': 5}, # 알 수 없는 주식 보유
        current_prices={'SPY': 100.0} # UNKNOWN_STOCK 가격 정보 없음
    )
    
    # 총 가치 = 현금(1000) + SPY(10*100) + UNKNOWN(5*0) = 2000
    assert pf.total_value == 2000.0
    
    # 그룹 가치 계산 시에도 에러가 안 나야 함
    val = pf.get_group_value(['UNKNOWN_STOCK'])
    assert val == 0.0

def test_portfolio_empty_state():
    """
    [빈 껍데기 테스트]
    보유 종목도 없고 현금도 없으면?
    """
    pf = Portfolio(
        total_cash=0.0,
        holdings={},
        current_prices={}
    )
    
    assert pf.total_value == 0.0
    assert pf.get_group_value(['SPY']) == 0.0

def test_portfolio_query_non_existent_ticker():
    """
    [존재하지 않는 종목 조회]
    내 포트폴리오에 없는 종목의 그룹 가치를 물어보면?
    """
    pf = Portfolio(
        total_cash=1000.0,
        holdings={'SPY': 10},
        current_prices={'SPY': 100.0, 'GLD': 50.0}
    )
    
    # GLD는 가격 정보는 있지만, 내 holdings에는 없음 -> 가치는 0이어야 함
    assert pf.get_group_value(['GLD']) == 0.0