# tests/conftest.py
import sys
import types
import pytest
import os

# yfinance가 설치되지 않은 환경을 위한 mock 모듈 등록
try:
    import yfinance  # noqa: F401 - 설치 여부만 확인
except ImportError:
    yf_mock = types.ModuleType('yfinance')
    yf_mock.download = lambda *a, **kw: None
    sys.modules['yfinance'] = yf_mock

from src.core.models import MarketData, Portfolio


@pytest.fixture(autouse=True)
def isolate_backtest_filesystem(tmp_path, monkeypatch):
    """테스트 시 backtest 파일 시스템 작업을 임시 경로로 자동 격리한다.

    - shutil.rmtree: 실제 docs/data/backtest 삭제 방지
    - JsonRepository: backtest 경로 요청 시 임시 경로(tmp_path)로 리다이렉트
    """
    try:
        import src.backtest.runner as runner_mod
        from src.infra.repo import JsonRepository
    except ImportError:
        return  # backtest 모듈이 없는 환경에서는 건너뜀

    # 1. shutil.rmtree no-op → 실제 backtest 데이터 보호
    monkeypatch.setattr(runner_mod.shutil, "rmtree", lambda *a, **kw: None)

    # 2. JsonRepository가 backtest 경로 요청 시 임시 경로로 리다이렉트
    backtest_tmp = str(tmp_path / "backtest")

    class _TmpBacktestRepo(JsonRepository):
        def __init__(self, root_path=None, **kwargs):
            if root_path is None or root_path == "docs/data/backtest":
                root_path = backtest_tmp
            super().__init__(root_path, **kwargs)

    monkeypatch.setattr(runner_mod, "JsonRepository", _TmpBacktestRepo)

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