# tests/test_core_engine_sso_dip_buy.py
"""SsoDipBuyEngine 단위 테스트."""
import math
from unittest.mock import MagicMock, patch

from src.core.engine.sso_dip_buy import SsoDipBuyEngine
from src.core.engine import TradingEngine, _ENGINE_REGISTRY, _ENGINE_BACKTEST
from src.core.logic.sso_dip_planner import SignalLevel, SsoDipState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, Order, OrderAction,
)


def _make_market_data(vix: float = 18.0) -> MarketData:
    return MarketData(
        date="2024-06-01", spy_price=520.0, spy_ma180=490.0,
        spy_volatility=0.14, spy_momentum=0.04, spy_mdd=-0.08, vix=vix,
    )


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
        holdings={"SSO": 0, "SPYI": 0},
        current_prices={"SSO": 80.0, "SPYI": 55.0},
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

        engine = SsoDipBuyEngine(
            broker=broker, repo=repo, logger=logger,
            trading_interval_days=1,
        )

    return engine, {
        "broker": broker, "repo": repo, "logger": logger,
        "data_provider": data_provider,
    }


class TestClassStructure:
    def test_is_trading_engine_subclass(self):
        assert issubclass(SsoDipBuyEngine, TradingEngine)

    def test_registered_in_registry(self):
        names = [name for name, _ in _ENGINE_REGISTRY]
        assert "SsoDipBuyEngine" in names

    def test_backtest_enabled(self):
        assert _ENGINE_BACKTEST.get("SsoDipBuyEngine") is True

    def test_asset_groups(self):
        assert SsoDipBuyEngine.ASSET_GROUPS == {"A": ["SSO"], "B": ["SPYI"]}

    def test_all_tickers(self):
        engine, _ = _build_engine()
        assert set(engine.all_tickers) == {"SSO", "SPYI"}


class TestStateManagement:
    def test_loads_state_on_init(self):
        engine, mocks = _build_engine()
        mocks["repo"].load_strategy_state.assert_called_with("sso_dip_buy")

    def test_saves_state_after_cycle(self):
        engine, mocks = _build_engine()
        engine.dip_state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        mocks["repo"].save_strategy_state.assert_not_called()


class TestCollectData:
    def test_fetches_sso_and_spy_ohlcv(self):
        """SSO OHLCV(신호용)와 SPY OHLCV(국면분석용)를 모두 수집한다."""
        engine, mocks = _build_engine()
        engine.collect_data(mocks["data_provider"])
        calls = mocks["data_provider"].fetch_ohlcv.call_args_list
        tickers_called = [c[0][0] for c in calls]
        assert ["SPY"] in tickers_called
        assert ["SSO"] in tickers_called
        assert len(calls) == 2
