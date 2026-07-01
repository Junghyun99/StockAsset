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


def test_leverage_sizing_uses_realized_vol_ignores_vix(tmp_path):
    """레버리지 사이징은 실현변동성만 사용하고 VIX는 무시한다(PR #350 롤백).

    저변동성 시계열 + 높은 VIX(80)에서, realized 단독이면 레버리지업(QLD↑)
    되어야 한다. 과거 max(실현,VIX)였다면 VIX=80이 σ=0.80을 강제해 디레버리지
    됐겠지만, 그 방식이 realized 단독보다 성과가 나빠 롤백됐다.
    """
    eng, _, _ = _make(tmp_path)
    res = eng.run_one_cycle(_Loader(_series(step=0.001), vix=80.0),
                            sim_date="2023-10-27")
    assert res is not None
    # 저변동성 → 0.30/작은σ → 상한 2.0 → QLD 100% (VIX 80은 무시)
    assert eng.rebalancer.ratio_a > 0.9
    assert not hasattr(VolTargetLeverageEngine, "_effective_vol")  # 메서드 제거 확인


def test_cycle_runs_and_invests(tmp_path):
    eng, broker, repo = _make(tmp_path)
    res = eng.run_one_cycle(_Loader(_series()), sim_date="2023-10-27")
    assert res.signal is not None
    # 첫 투자 → QLD/QQQ 매수 발생
    assert any(o.ticker in ("QLD", "QQQ") for o in res.signal.orders)
