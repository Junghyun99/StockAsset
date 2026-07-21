# tests/test_core_engine_domestic_qld_dip_buy.py
"""DomesticQldDipBuyEngine 단위 테스트."""
from unittest.mock import MagicMock, patch

from src.core.engine.domestic_qld_dip_buy import (
    DomesticQldDipBuyEngine, DomesticQldDipPlanner,
    LEVER_TICKER, INCOME_TICKER,
)
from src.core.engine import TradingEngine, _ENGINE_REGISTRY, _ENGINE_BACKTEST, _ENGINE_MARKET_TYPES
from src.core.logic.sso_dip_planner import SsoDipPlanner
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
        total_cash=1_000_000.0,
        holdings={LEVER_TICKER: 0, INCOME_TICKER: 0},
        current_prices={LEVER_TICKER: 15000.0, INCOME_TICKER: 10000.0},
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

        engine = DomesticQldDipBuyEngine(
            broker=broker, repo=repo, logger=logger,
            trading_interval_days=1,
        )

    return engine, {
        "broker": broker, "repo": repo, "logger": logger,
        "data_provider": data_provider,
    }


class TestClassStructure:
    def test_is_trading_engine_subclass(self):
        assert issubclass(DomesticQldDipBuyEngine, TradingEngine)

    def test_registered_in_registry(self):
        names = [name for name, _ in _ENGINE_REGISTRY]
        assert "DomesticQldDipBuyEngine" in names

    def test_backtest_disabled(self):
        assert _ENGINE_BACKTEST.get("DomesticQldDipBuyEngine") is False

    def test_market_type_domestic(self):
        assert _ENGINE_MARKET_TYPES.get("DomesticQldDipBuyEngine") == "domestic"

    def test_asset_groups(self):
        assert DomesticQldDipBuyEngine.ASSET_GROUPS == {
            "A": [LEVER_TICKER], "B": [INCOME_TICKER],
        }

    def test_all_tickers(self):
        engine, _ = _build_engine()
        assert set(engine.all_tickers) == {LEVER_TICKER, INCOME_TICKER}


class TestDomesticQldDipPlanner:
    def test_is_sso_planner_subclass(self):
        assert issubclass(DomesticQldDipPlanner, SsoDipPlanner)

    def test_ticker_names(self):
        planner = DomesticQldDipPlanner()
        assert planner.SSO_TICKER == LEVER_TICKER
        assert planner.SPYI_TICKER == INCOME_TICKER


class TestStateManagement:
    def test_loads_state_on_init(self):
        engine, mocks = _build_engine()
        mocks["repo"].load_strategy_state.assert_called_with("domestic_qld_dip_buy")


class TestCollectData:
    def test_fetches_lever_and_spy_ohlcv(self):
        engine, mocks = _build_engine()
        engine.collect_data(mocks["data_provider"])
        calls = mocks["data_provider"].fetch_ohlcv.call_args_list
        tickers_called = [c[0][0] for c in calls]
        assert ["SPY"] in tickers_called
        assert [LEVER_TICKER] in tickers_called
        assert len(calls) == 2
