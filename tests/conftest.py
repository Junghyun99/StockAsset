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

@pytest.fixture
def create_market_data():
    """원하는 값만 바꿔서 MarketData를 만드는 팩토리 함수"""
    def _create(price=100, ma=100, vol=0.15, mom=0.0, mdd=0.0, vix=20.0, date="2024-01-01"):
        return MarketData(
            date=date,
            spy_price=float(price),
            spy_ma180=float(ma),
            spy_volatility=float(vol),
            spy_momentum=float(mom),
            spy_mdd=float(mdd),
            vix=float(vix)
        )
    return _create

@pytest.fixture
def create_portfolio():
    """원하는 종목 구성으로 포트폴리오 생성"""
    def _create(cash=0.0, holdings=None, prices=None):
        if holdings is None: holdings = {}
        if prices is None: prices = {"SPY": 100.0, "IEF": 100.0}
        return Portfolio(
            total_cash=float(cash),
            holdings=holdings,
            current_prices=prices
        )
    return _create