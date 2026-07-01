import numpy as np
import pandas as pd
import pytest

from src.core.engine.volmanaged import VolManagedEngine
from src.infra.broker.mock import MockBroker
from src.infra.repo import JsonRepository
from src.utils.logger import TradeLogger


def _make(tmp_path):
    groups = {"A": ["QLD"], "B": ["QQQ"], "C": ["SHV"]}
    repo = JsonRepository(str(tmp_path), asset_groups=groups)
    broker = MockBroker(initial_cash=10000.0)
    eng = VolManagedEngine(broker=broker, repo=repo,
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
    assert "VolManagedEngine" in [n for n, _ in _ENGINE_REGISTRY]


@pytest.mark.parametrize("vol,exp_exposure,exp_ratio_a", [
    (0.11,  1.0, 1.0),   # 0.22/0.11=2.0 → L=2 → 위험100%, QLD100%
    (0.22,  1.0, 0.0),   # L=1.0 → 위험100%, QQQ100%
    (0.44,  0.5, 0.0),   # 0.22/0.44=0.5 → 위험50%(QQQ)+현금50%
    (0.147, 1.0, 0.5),   # 0.22/0.147≈1.5 → QLD50%+QQQ50%
    (2.0,   0.11, 0.0),  # 0.22/2.0=0.11 → 위험11%(QQQ)+현금89% (거의 현금화)
])
def test_L_to_exposure_ratio_mapping(tmp_path, vol, exp_exposure, exp_ratio_a):
    eng, _, _ = _make(tmp_path)
    exposure, ratio_a = eng._leverage_to_weights(vol)
    assert abs(exposure - exp_exposure) < 1e-2
    assert abs(ratio_a - exp_ratio_a) < 1e-2


def test_low_vol_levers_into_qld(tmp_path):
    eng, broker, repo = _make(tmp_path)
    res = eng.run_one_cycle(_Loader(_series(step=0.001), vix=20.0), sim_date="2023-10-27")
    assert res.signal is not None
    assert eng.rebalancer.ratio_a > 0.9        # 저변동성 → QLD 편입


def test_high_vol_moves_to_cash(tmp_path):
    eng, broker, repo = _make(tmp_path)
    res = eng.run_one_cycle(_Loader(_series(step=0.03), vix=20.0), sim_date="2023-10-27")
    assert res.exposure < 1.0                    # 고변동성 → 현금(SHV) 이탈


def test_leverage_deadband_holds_small_changes(tmp_path):
    """목표 L이 데드밴드(0.15) 이내로 변하면 실효 레버리지를 유지(턴오버 억제)."""
    from src.core.models import MarketData
    eng, _, _ = _make(tmp_path)

    def md(vol):
        return MarketData(date="2023-01-02", spy_price=300.0, spy_ma180=280.0,
                          spy_volatility=vol, spy_momentum=0.1, spy_mdd=-0.02, vix=20.0)

    eng.analyze_strategy(md(0.147))                 # L≈1.50 (init 1.0에서 0.5 이동 → 갱신)
    assert abs(eng._applied_L - 1.50) < 0.05
    eng.analyze_strategy(md(0.142))                 # L≈1.55, Δ0.05<0.15 → 유지
    assert abs(eng._applied_L - 1.50) < 0.05
    eng.analyze_strategy(md(0.110))                 # L=2.00, Δ0.5>0.15 → 갱신
    assert abs(eng._applied_L - 2.00) < 0.05


def test_nan_data_treated_as_crash(tmp_path):
    from src.core.models import MarketData
    eng, _, _ = _make(tmp_path)
    md = MarketData(date="2020-03-16", spy_price=float("nan"), spy_ma180=210.0,
                    spy_volatility=0.2, spy_momentum=-0.1, spy_mdd=-0.3, vix=80.0)
    regime, exposure, nan_fields = eng.analyze_strategy(md)
    assert exposure == 0.0
    assert nan_fields
