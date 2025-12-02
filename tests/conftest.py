# tests/conftest.py
import pytest
from src.core.models import MarketData, Portfolio

@pytest.fixture
def mock_market_bear():
    """강한 하락장 데이터"""
    return MarketData(
        date="2024-05-20",
        spy_price=400.0,
        spy_ma180=450.0,      # 가격 < 이평선
        spy_volatility=0.20,
        spy_momentum=-0.05,   # 모멘텀 음수
        spy_mdd=-0.10,
        vix=25.0
    )

@pytest.fixture
def mock_market_bull():
    """상승장 데이터"""
    return MarketData(
        date="2024-05-20",
        spy_price=500.0,
        spy_ma180=480.0,
        spy_volatility=0.10,
        spy_momentum=0.10,    # 모멘텀 5% 이상
        spy_mdd=-0.02,
        vix=15.0
    )

@pytest.fixture
def mock_portfolio():
    """현금만 있는 초기 상태"""
    return Portfolio(
        total_cash=10000.0,
        holdings={},
        current_prices={"SSO": 100.0, "IEF": 100.0}
    )