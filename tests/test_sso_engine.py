# tests/test_sso_engine.py
"""SsoEngine 단위 테스트.

SSO Buy&Hold 벤치마크:
- A그룹: [SSO], B그룹: [SHV]
- FullExposureEngine 상속 → 항상 exposure=1.0
- REBALANCE_RATIO_A=0.999 → 사실상 100% SSO 투자
"""
from unittest.mock import MagicMock, patch

from src.core.engine import SsoEngine, FullExposureEngine, _ENGINE_REGISTRY, _ENGINE_BACKTEST


def _make_base_deps():
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    return broker, repo, logger


def test_asset_groups_A():
    assert SsoEngine.ASSET_GROUPS['A'] == ['SSO']


def test_asset_groups_B():
    assert SsoEngine.ASSET_GROUPS['B'] == ['SHV']


def test_no_C_group():
    assert 'C' not in SsoEngine.ASSET_GROUPS


def test_rebalance_ratio_a():
    assert SsoEngine.REBALANCE_RATIO_A == 0.999


def test_is_full_exposure_subclass():
    assert issubclass(SsoEngine, FullExposureEngine)


def test_registered_in_registry():
    names = [name for name, _ in _ENGINE_REGISTRY]
    assert "SsoEngine" in names


def test_backtest_enabled():
    assert _ENGINE_BACKTEST.get("SsoEngine") is True


def test_rebalancer_groups():
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.base.IndicatorCalculator'), \
         patch('src.core.engine.base.RegimeAnalyzer'), \
         patch('src.core.engine.base.VolatilityTargeter'):
        engine = SsoEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == SsoEngine.ASSET_GROUPS


def test_all_tickers():
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.base.IndicatorCalculator'), \
         patch('src.core.engine.base.RegimeAnalyzer'), \
         patch('src.core.engine.base.VolatilityTargeter'):
        engine = SsoEngine(broker=broker, repo=repo, logger=logger)
    assert set(engine.all_tickers) == {"SSO", "SHV"}
