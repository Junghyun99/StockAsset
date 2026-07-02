import numpy as np
import pandas as pd
import pytest

from src.core.engine.volmanaged import DomesticVolManagedEngine
from src.infra.broker.mock import MockBroker
from src.infra.repo import JsonRepository
from src.utils.logger import TradeLogger


def _make(tmp_path):
    groups = {"A": ["418660.KS"], "B": ["133690.KS"], "C": ["459580.KS"]}
    repo = JsonRepository(str(tmp_path), asset_groups=groups)
    broker = MockBroker(initial_cash=10000.0)
    eng = DomesticVolManagedEngine(broker=broker, repo=repo,
                                   logger=TradeLogger(log_dir=str(tmp_path / "l")),
                                   asset_groups=groups, trading_interval_days=1)
    return eng, broker, repo


class _Loader:
    def __init__(self, df, vix=20.0):
        self.df, self._vix = df, vix

    def fetch_ohlcv(self, tickers, days=365):
        return self.df.tail(days)

    def fetch_vix(self):
        return self._vix


def _series(n=300, step=0.005):
    rng = np.random.default_rng(0)
    closes = 100 * np.cumprod(1 + rng.normal(0.0004, step, n))
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [1] * n}, index=idx)


def test_registered():
    from src.core.engine import _ENGINE_REGISTRY
    assert "DomesticVolManagedEngine" in [n for n, _ in _ENGINE_REGISTRY]


def test_registered_as_domestic_market_type():
    from src.core.engine import _ENGINE_MARKET_TYPES
    assert _ENGINE_MARKET_TYPES["DomesticVolManagedEngine"] == "domestic"


def test_excluded_from_backtest():
    from src.core.engine import _ENGINE_BACKTEST
    assert _ENGINE_BACKTEST["DomesticVolManagedEngine"] is False


def test_asset_groups_use_domestic_tickers():
    assert DomesticVolManagedEngine.ASSET_GROUPS == {
        "A": ["418660.KS"], "B": ["133690.KS"], "C": ["459580.KS"],
    }


def test_signal_ticker_is_domestic_qqq():
    assert DomesticVolManagedEngine.SIGNAL_TICKER == "133690.KS"


def test_collect_data_fetches_signal_ticker(tmp_path):
    eng, _, _ = _make(tmp_path)
    loader = _Loader(_series())
    calls = {}

    def fetch_ohlcv(tickers, days=400):
        calls["tickers"] = tickers
        return loader.df.tail(days)
    loader.fetch_ohlcv = fetch_ohlcv

    eng.collect_data(loader)
    assert calls["tickers"] == ["133690.KS"]


@pytest.mark.parametrize("vol,exp_exposure,exp_ratio_a", [
    (0.11,  1.0, 1.0),   # 0.22/0.11=2.0 → L=2 → 위험100%, 418660.KS100%
    (0.22,  1.0, 0.0),   # L=1.0 → 위험100%, 133690.KS100%
    (0.44,  0.5, 0.0),   # 0.22/0.44=0.5 → 위험50%(133690.KS)+현금50%
])
def test_L_to_exposure_ratio_mapping(tmp_path, vol, exp_exposure, exp_ratio_a):
    eng, _, _ = _make(tmp_path)
    exposure, ratio_a = eng._leverage_to_weights(vol)
    assert abs(exposure - exp_exposure) < 1e-2
    assert abs(ratio_a - exp_ratio_a) < 1e-2


def test_low_vol_levers_into_leveraged_etf(tmp_path):
    eng, broker, repo = _make(tmp_path)
    res = eng.run_one_cycle(_Loader(_series(step=0.001), vix=20.0), sim_date="2023-10-27")
    assert res.signal is not None
    assert eng.rebalancer.ratio_a > 0.9        # 저변동성 → 418660.KS 편입


def test_high_vol_moves_to_cash(tmp_path):
    eng, broker, repo = _make(tmp_path)
    res = eng.run_one_cycle(_Loader(_series(step=0.03), vix=20.0), sim_date="2023-10-27")
    assert res.exposure < 1.0                    # 고변동성 → 현금(459580.KS) 이탈


def test_nan_data_treated_as_crash(tmp_path):
    from src.core.models import MarketData
    eng, _, _ = _make(tmp_path)
    md = MarketData(date="2020-03-16", spy_price=float("nan"), spy_ma180=210.0,
                    spy_volatility=0.2, spy_momentum=-0.1, spy_mdd=-0.3, vix=80.0)
    regime, exposure, nan_fields = eng.analyze_strategy(md)
    assert exposure == 0.0
    assert nan_fields
