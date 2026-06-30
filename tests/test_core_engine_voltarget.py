import numpy as np
import pandas as pd

from src.core.engine.voltarget import VolTargetLeverageEngine
from src.core.models import MarketRegime
from src.infra.broker.mock import MockBroker
from src.infra.repo import JsonRepository
from src.utils.logger import TradeLogger


def _make(tmp_path):
    groups = {"A": ["QLD"], "B": ["QQQ"]}
    repo = JsonRepository(str(tmp_path), asset_groups=groups)
    broker = MockBroker(initial_cash=10000.0)
    eng = VolTargetLeverageEngine(broker=broker, repo=repo,
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
    assert "VolTargetLeverageEngine" in [n for n, _ in _ENGINE_REGISTRY]


def test_low_vol_levers_up(tmp_path):
    eng, _, _ = _make(tmp_path)
    eng._set_leverage_ratio(MarketRegime.BULL, 0.15)   # 0.30/0.15=2.0 → QLD 100%
    assert abs(eng.rebalancer.ratio_a - 1.0) < 1e-9


def test_high_vol_delevers(tmp_path):
    eng, _, _ = _make(tmp_path)
    eng._set_leverage_ratio(MarketRegime.BULL, 0.60)   # 0.5 → 하한 1.0 → QLD 0%
    assert abs(eng.rebalancer.ratio_a - 0.0) < 1e-9


def test_mid_vol_blend(tmp_path):
    eng, _, _ = _make(tmp_path)
    eng._set_leverage_ratio(MarketRegime.BULL, 0.20)   # 0.30/0.20=1.5 → QLD 50%
    assert abs(eng.rebalancer.ratio_a - 0.5) < 1e-9


def test_crash_delevers_to_1x_not_cash(tmp_path):
    eng, _, _ = _make(tmp_path)
    eng._set_leverage_ratio(MarketRegime.CRASH, 0.80)  # CRASH → 1x → QLD 0% (전부 QQQ, 현금화 아님)
    assert abs(eng.rebalancer.ratio_a - 0.0) < 1e-9
    assert abs(eng.rebalancer.ratio_b - 1.0) < 1e-9


def test_effective_vol_takes_max_of_realized_and_vix(tmp_path):
    from src.core.models import MarketData
    # VIX(내재)가 실현보다 클 때 → VIX 채택 (선행 패닉 신호)
    md = MarketData(date="2020-03-16", spy_price=200.0, spy_ma180=210.0,
                    spy_volatility=0.18, spy_momentum=-0.1, spy_mdd=-0.3, vix=80.0)
    assert abs(VolTargetLeverageEngine._effective_vol(md) - 0.80) < 1e-9
    # 실현이 VIX보다 클 때 → 실현 채택 (그라인드 약세장, VIX 잠잠)
    md2 = MarketData(date="2022-06-16", spy_price=280.0, spy_ma180=320.0,
                     spy_volatility=0.35, spy_momentum=-0.2, spy_mdd=-0.25, vix=28.0)
    assert abs(VolTargetLeverageEngine._effective_vol(md2) - 0.35) < 1e-9


def test_vix_panic_delevers_even_when_realized_low(tmp_path):
    # 실현은 낮아 2x를 가리키지만 VIX 급등 시 디레버리지되어야 함
    from src.core.models import MarketData
    eng, _, _ = _make(tmp_path)
    md = MarketData(date="2020-02-28", spy_price=300.0, spy_ma180=290.0,
                    spy_volatility=0.10, spy_momentum=0.05, spy_mdd=-0.05, vix=40.0)
    sigma = eng._effective_vol(md)                      # max(0.10, 0.40)=0.40
    eng._set_leverage_ratio(MarketRegime.BULL, sigma)  # 0.30/0.40=0.75 → 하한 1.0
    assert abs(eng.rebalancer.ratio_a - 0.0) < 1e-9    # 레버리지 끔(전부 QQQ)


def test_cycle_runs_and_invests(tmp_path):
    eng, broker, repo = _make(tmp_path)
    res = eng.run_one_cycle(_Loader(_series()), sim_date="2023-10-27")
    assert res.signal is not None
    # 첫 투자 → QLD/QQQ 매수 발생
    assert any(o.ticker in ("QLD", "QQQ") for o in res.signal.orders)
