# tests/test_sso_spyi_engine.py
"""SsoSpyiEngine 단위 테스트.

SSO(2x S&P500 레버리지) + SPYI(S&P500 커버드콜) Full Exposure 전략:
- A그룹: [SSO], B그룹: [SPYI]
- FullExposureEngine 상속 → 항상 exposure=1.0
- REBALANCE_RATIO_A=0.4 → SSO:SPYI = 4:6
"""
import math
from unittest.mock import MagicMock, patch

from src.core.engine import SsoSpyiEngine, FullExposureEngine, _ENGINE_REGISTRY, _ENGINE_BACKTEST
from src.core.models import MarketData, MarketRegime, Portfolio, TradeSignal


def _make_market_data(nan_vol: bool = False, vix: float = 18.0) -> MarketData:
    return MarketData(
        date="2024-06-01",
        spy_price=520.0,
        spy_ma180=490.0,
        spy_volatility=math.nan if nan_vol else 0.14,
        spy_momentum=0.04,
        spy_mdd=-0.08,
        vix=vix,
    )


def _make_base_deps():
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    return broker, repo, logger


def _build_engine(repo_last_reb=None):
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = repo_last_reb
    repo.load_last_regime.return_value = None
    broker.get_portfolio.return_value = Portfolio(
        total_cash=10000.0,
        holdings={"SSO": 50, "SPYI": 100},
        current_prices={"SSO": 80.0, "SPYI": 55.0},
    )
    broker.fetch_current_prices.return_value = {}

    with patch('src.core.engine.base.IndicatorCalculator') as MockCalc, \
         patch('src.core.engine.base.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.base.VolatilityTargeter') as MockTargeter, \
         patch('src.core.engine.base.Rebalancer') as MockRebalancer:

        calculator = MockCalc.return_value
        analyzer = MockAnalyzer.return_value
        analyzer._prev_regime = None
        targeter = MockTargeter.return_value
        rebalancer = MockRebalancer.return_value
        rebalancer.get_target_params.return_value = (0.4, 0.075)

        engine = SsoSpyiEngine(
            broker=broker,
            repo=repo,
            logger=logger,
            trading_interval_days=5,
        )

    return engine, {
        "calculator": calculator,
        "analyzer": analyzer,
        "targeter": targeter,
        "rebalancer": rebalancer,
        "broker": broker,
        "repo": repo,
        "logger": logger,
        "data_provider": data_provider,
    }


# ── 클래스 상수 검증 ──────────────────────────────────────────────

def test_asset_groups_A():
    assert SsoSpyiEngine.ASSET_GROUPS['A'] == ['SSO']


def test_asset_groups_B():
    assert SsoSpyiEngine.ASSET_GROUPS['B'] == ['SPYI']


def test_no_C_group():
    assert 'C' not in SsoSpyiEngine.ASSET_GROUPS


def test_rebalance_ratio_a():
    assert SsoSpyiEngine.REBALANCE_RATIO_A == 0.4


def test_is_full_exposure_subclass():
    assert issubclass(SsoSpyiEngine, FullExposureEngine)


# ── 레지스트리 등록 검증 ──────────────────────────────────────────

def test_registered_in_registry():
    names = [name for name, _ in _ENGINE_REGISTRY]
    assert "SsoSpyiEngine" in names


def test_backtest_enabled():
    assert _ENGINE_BACKTEST.get("SsoSpyiEngine") is True


# ── Rebalancer 생성 검증 ──────────────────────────────────────────

def test_rebalancer_groups():
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.base.IndicatorCalculator'), \
         patch('src.core.engine.base.RegimeAnalyzer'), \
         patch('src.core.engine.base.VolatilityTargeter'):
        engine = SsoSpyiEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == SsoSpyiEngine.ASSET_GROUPS


def test_rebalancer_ratio_a():
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.base.IndicatorCalculator'), \
         patch('src.core.engine.base.RegimeAnalyzer'), \
         patch('src.core.engine.base.VolatilityTargeter'):
        engine = SsoSpyiEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.ratio_a == 0.4


def test_all_tickers():
    engine, _ = _build_engine()
    assert set(engine.all_tickers) == {"SSO", "SPYI"}


# ── analyze_strategy (FullExposureEngine 동작) ────────────────────

def test_bull_exposure_1():
    engine, mocks = _build_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0
    assert nan_fields == []


def test_crash_exposure_1():
    engine, mocks = _build_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    _, exposure, _ = engine.analyze_strategy(_make_market_data(vix=40.0))
    assert exposure == 1.0


def test_nan_exposure_zero():
    engine, mocks = _build_engine()
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data(nan_vol=True))
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields


# ── End-to-end 사이클 ─────────────────────────────────────────────

def test_end_to_end_rebalancing():
    engine, mocks = _build_engine(repo_last_reb=None)
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    engine.rebalancer = MagicMock()
    engine.rebalancer.generate_signal.return_value = TradeSignal(1.0, [], "Hold")
    engine.rebalancer.get_target_params.return_value = (0.4, 0.075)

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 1.0
