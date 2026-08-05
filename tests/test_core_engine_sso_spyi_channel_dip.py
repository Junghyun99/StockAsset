from unittest.mock import MagicMock, patch

from src.core.engine import TradingEngine, _ENGINE_BACKTEST, _ENGINE_REGISTRY
from src.core.engine.sso_spyi_channel_dip import SsoSpyiChannelDipEngine


def _engine():
    broker, repo, logger = MagicMock(), MagicMock(), MagicMock()
    repo.load_last_regime.return_value = None
    repo.load_strategy_state.return_value = {}
    with patch("src.core.engine.base.IndicatorCalculator"), \
         patch("src.core.engine.base.RegimeAnalyzer") as analyzer, \
         patch("src.core.engine.base.VolatilityTargeter"), \
         patch("src.core.engine.base.Rebalancer"):
        analyzer.return_value._prev_regime = None
        engine = SsoSpyiChannelDipEngine(broker=broker, repo=repo, logger=logger)
    return engine, repo


def test_channel_dip_engine_is_registered_for_compare_backtest():
    assert issubclass(SsoSpyiChannelDipEngine, TradingEngine)
    assert "SsoSpyiChannelDipEngine" in [name for name, _ in _ENGINE_REGISTRY]
    assert _ENGINE_BACKTEST["SsoSpyiChannelDipEngine"] is True


def test_channel_dip_engine_collects_independent_sso_and_spyi_data_without_interval():
    engine, repo = _engine()

    assert engine.uses_trading_interval() is False
    assert [dataset.key for dataset in engine.data_spec().strategy] == ["sso_signal", "spyi_signal"]
    repo.load_strategy_state.assert_called_with("sso_spyi_channel_dip")
