# tests/test_core_engine_qld_dip_buy.py
"""QldDipBuyEngine 단위 테스트."""
from unittest.mock import MagicMock, patch

from src.core.engine.qld_dip_buy import QldDipBuyEngine, QldDipPlanner
from src.core.engine import TradingEngine, _ENGINE_REGISTRY, _ENGINE_BACKTEST
from src.core.logic.sso_dip_planner import SignalLevel, SsoDipState, SsoDipPlanner
from src.core.models import Portfolio


def _build_engine():
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = None
    repo.load_last_regime.return_value = None
    repo.load_strategy_state.return_value = {}
    broker.get_portfolio.return_value = Portfolio(
        total_cash=10000.0,
        holdings={"QLD": 0, "QQQI": 0},
        current_prices={"QLD": 90.0, "QQQI": 25.0},
    )
    broker.fetch_current_prices.return_value = {}

    with patch('src.core.engine.base.IndicatorCalculator') as MockCalc, \
         patch('src.core.engine.base.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.base.VolatilityTargeter') as MockTargeter, \
         patch('src.core.engine.base.Rebalancer') as MockRebalancer:

        analyzer = MockAnalyzer.return_value
        analyzer._prev_regime = None
        rebalancer = MockRebalancer.return_value
        rebalancer.get_target_params.return_value = (0.4, 0.075)

        engine = QldDipBuyEngine(
            broker=broker, repo=repo, logger=logger,
            trading_interval_days=1,
        )

    return engine, {
        "broker": broker, "repo": repo, "logger": logger,
        "data_provider": data_provider,
    }


class TestClassStructure:
    def test_is_trading_engine_subclass(self):
        assert issubclass(QldDipBuyEngine, TradingEngine)

    def test_registered_in_registry(self):
        names = [name for name, _ in _ENGINE_REGISTRY]
        assert "QldDipBuyEngine" in names

    def test_backtest_disabled(self):
        assert _ENGINE_BACKTEST.get("QldDipBuyEngine") is False

    def test_asset_groups(self):
        assert QldDipBuyEngine.ASSET_GROUPS == {"A": ["QLD"], "B": ["QQQI"]}

    def test_all_tickers(self):
        engine, _ = _build_engine()
        assert set(engine.all_tickers) == {"QLD", "QQQI"}


class TestQldDipPlanner:
    def test_is_sso_planner_subclass(self):
        assert issubclass(QldDipPlanner, SsoDipPlanner)

    def test_ticker_names(self):
        planner = QldDipPlanner()
        assert planner.SSO_TICKER == "QLD"
        assert planner.SPYI_TICKER == "QQQI"


class TestStateManagement:
    def test_loads_state_on_init(self):
        engine, mocks = _build_engine()
        mocks["repo"].load_strategy_state.assert_called_with("qld_dip_buy")


class TestCollectData:
    def test_fetches_qld_and_spy_ohlcv(self):
        engine, mocks = _build_engine()
        engine.collect_data(mocks["data_provider"])
        calls = mocks["data_provider"].fetch_ohlcv.call_args_list
        tickers_called = [c[0][0] for c in calls]
        assert ["SPY"] in tickers_called
        assert ["QLD"] in tickers_called
        assert len(calls) == 2
