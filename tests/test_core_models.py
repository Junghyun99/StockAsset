# tests/test_models.py
import pytest
from src.core.models import MarketData, Portfolio

def test_market_data_risk_detection():
    # 1. 정상 상황
    normal = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.10, vix=20.0 # MDD > -20%, VIX < 30
    )
    assert normal.is_risk_condition() is False

    # 2. MDD 위험 (-20% 미만)
    mdd_risk = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.25, vix=20.0
    )
    assert mdd_risk.is_risk_condition() is True

    # 3. VIX 위험 (30 초과)
    vix_risk = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.10, vix=35.0
    )
    assert vix_risk.is_risk_condition() is True

def test_portfolio_calculation():
    # 상황: 현금 1000원 + 주식 A 10주(100원) + 주식 B 5주(200원)
    pf = Portfolio(
        total_cash=1000.0,
        holdings={'A': 10, 'B': 5},
        current_prices={'A': 100.0, 'B': 200.0}
    )

    # 1. 총 자산 가치 검증
    # 1000 + (10*100) + (5*200) = 3000
    assert pf.total_value == 3000.0

    # 2. 그룹별 가치 계산 검증
    # 그룹 A(종목 A)의 가치 = 1000
    assert pf.get_group_value(['A']) == 1000.0
    # 없는 종목 C의 가치 = 0
    assert pf.get_group_value(['C']) == 0.0