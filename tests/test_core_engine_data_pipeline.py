"""공통 데이터 수집·지표 계산 파이프라인 계약 테스트."""

from unittest.mock import MagicMock, patch

import pandas as pd

from src.core.engine.base import TradingEngine
from src.core.engine.data_pipeline import DataSetSpec, StrategyDataSpec
from src.core.models import MarketData, Portfolio


def _frame(price: float) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=300, freq="D")
    return pd.DataFrame({"Close": [price] * len(index)}, index=index)


def _engine(engine_type=TradingEngine):
    broker = MagicMock()
    broker.get_portfolio.return_value = Portfolio(1000.0, {}, {})
    repo = MagicMock()
    repo.load_last_regime.return_value = None
    logger = MagicMock()
    return engine_type(
        broker=broker,
        repo=repo,
        logger=logger,
        asset_groups={"A": ["SPY"]},
    )


def test_default_data_spec_declares_reference_dataset():
    engine = _engine()

    assert engine.data_spec() == StrategyDataSpec(
        reference=DataSetSpec("reference", ("SPY",), days=400),
    )


def test_common_collector_fetches_declared_datasets_and_vix_once():
    class TwoDatasetEngine(TradingEngine):
        def data_spec(self) -> StrategyDataSpec:
            return StrategyDataSpec(
                reference=DataSetSpec("reference", ("SPY",), days=400),
                strategy=(DataSetSpec("signal", ("SSO",), days=260),),
            )

    engine = _engine(TwoDatasetEngine)
    provider = MagicMock()
    spy = _frame(500.0)
    sso = _frame(100.0)
    provider.fetch_ohlcv.side_effect = [spy, sso]
    provider.fetch_vix.return_value = 17.5

    collected = engine.collect_data(provider)

    assert collected.frame("reference") is spy
    assert collected.frame("signal") is sso
    assert collected.vix == 17.5
    assert provider.fetch_ohlcv.call_args_list == [
        ((["SPY"],), {"days": 400}),
        ((["SSO"],), {"days": 260}),
    ]
    provider.fetch_vix.assert_called_once_with()


def test_common_indicator_pipeline_uses_reference_and_calls_strategy_hook():
    class HookEngine(TradingEngine):
        def data_spec(self) -> StrategyDataSpec:
            return StrategyDataSpec(
                reference=DataSetSpec("reference", ("QQQ",), days=400),
                strategy=(DataSetSpec("signal", ("QLD",), days=400),),
            )

        def calculate_strategy_indicators(self, collected):
            self.seen_signal = collected.frame("signal")
            return {"kind": "dip"}

    engine = _engine(HookEngine)
    provider = MagicMock()
    qqq = _frame(400.0)
    qld = _frame(90.0)
    provider.fetch_ohlcv.side_effect = [qqq, qld]
    provider.fetch_vix.return_value = 20.0
    market_data = MarketData(
        "2024-10-26", 400.0, 390.0, 0.15, 0.03, -0.05, 20.0,
    )

    with patch.object(engine.calculator, "calculate", return_value=market_data) as calculate:
        result = engine.calculate_indicators(engine.collect_data(provider))

    assert result is market_data
    calculate.assert_called_once_with(qqq, 20.0)
    assert engine.seen_signal is qld
    assert engine.strategy_indicators == {"kind": "dip"}
