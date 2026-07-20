# tests/test_spyi_engine.py
"""SpyiEngine 단위 테스트.

SPYI Buy&Hold 벤치마크:
- A그룹: [SPYI], B그룹: [SHV]
- FullExposureEngine 상속 → 항상 exposure=1.0
- REBALANCE_RATIO_A=0.999 → 사실상 100% SPYI 투자
"""
from unittest.mock import MagicMock, patch

from src.core.engine import SpyiEngine, FullExposureEngine, _ENGINE_REGISTRY, _ENGINE_BACKTEST


def _make_base_deps():
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    return broker, repo, logger


def test_asset_groups_A():
    assert SpyiEngine.ASSET_GROUPS['A'] == ['SPYI']


def test_asset_groups_B():
    assert SpyiEngine.ASSET_GROUPS['B'] == ['SHV']


def test_no_C_group():
    assert 'C' not in SpyiEngine.ASSET_GROUPS


def test_rebalance_ratio_a():
    assert SpyiEngine.REBALANCE_RATIO_A == 0.999


def test_is_full_exposure_subclass():
    assert issubclass(SpyiEngine, FullExposureEngine)


def test_registered_in_registry():
    names = [name for name, _ in _ENGINE_REGISTRY]
    assert "SpyiEngine" in names


def test_backtest_enabled():
    assert _ENGINE_BACKTEST.get("SpyiEngine") is True


def test_rebalancer_groups():
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.base.IndicatorCalculator'), \
         patch('src.core.engine.base.RegimeAnalyzer'), \
         patch('src.core.engine.base.VolatilityTargeter'):
        engine = SpyiEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == SpyiEngine.ASSET_GROUPS


def test_all_tickers():
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.base.IndicatorCalculator'), \
         patch('src.core.engine.base.RegimeAnalyzer'), \
         patch('src.core.engine.base.VolatilityTargeter'):
        engine = SpyiEngine(broker=broker, repo=repo, logger=logger)
    assert set(engine.all_tickers) == {"SPYI", "SHV"}
