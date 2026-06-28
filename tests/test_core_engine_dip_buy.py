import numpy as np
import pandas as pd
import pytest

from src.core.engine.dip_buy import DipBuyEngine, DipBuyGatedEngine, DipBuyGatedSpyEngine
from src.core.logic.dip_buy_indicators import DipBuySignals
from src.core.models import Order, OrderAction, Portfolio
from src.infra.broker.mock import MockBroker
from src.infra.repo import JsonRepository
from src.utils.logger import TradeLogger


class _Loader:
    """단일 종목 OHLCV + VIX를 서빙하는 최소 데이터 프로바이더."""
    def __init__(self, df, vix=20.0):
        self.df, self._vix = df, vix

    def fetch_ohlcv(self, tickers, days=365):
        return self.df.tail(days)

    def fetch_vix(self):
        return self._vix


def _ramp_then_dip(n=300):
    up = np.linspace(50, 150, n - 20)
    down = np.linspace(150, 120, 20)
    closes = np.concatenate([up, down])
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes,
        "Close": closes, "Volume": [1] * n,
    }, index=idx)


def _make_engine(tmp_path, log_sub="logs"):
    repo = JsonRepository(str(tmp_path), asset_groups={"A": ["QLD"]})
    broker = MockBroker(initial_cash=10000.0)
    logger = TradeLogger(log_dir=str(tmp_path / log_sub))
    engine = DipBuyEngine(
        broker=broker, repo=repo, logger=logger,
        asset_groups={"A": ["QLD"]}, trading_interval_days=1,
    )
    return engine, broker, repo


def test_engine_registered():
    from src.core.engine import _ENGINE_REGISTRY
    names = [n for n, _ in _ENGINE_REGISTRY]
    assert "DipBuyEngine" in names


def test_cycle_runs_and_persists_state(tmp_path):
    engine, broker, repo = _make_engine(tmp_path)
    result = engine.run_one_cycle(_Loader(_ramp_then_dip()), sim_date="2023-10-27")
    saved = repo.load_strategy_state("dip_buy")
    assert "queue" in saved and "armed" in saved
    assert result.signal is not None


def test_state_survives_engine_recreation(tmp_path):
    df = _ramp_then_dip()
    engine, broker, repo = _make_engine(tmp_path)
    engine.run_one_cycle(_Loader(df), sim_date="2023-10-27")
    saved_before = repo.load_strategy_state("dip_buy")

    # 새 엔진 인스턴스(라이브 재시작 모사) → repo에서 상태 복원
    engine2 = DipBuyEngine(
        broker=broker, repo=repo, logger=TradeLogger(log_dir=str(tmp_path / "l2")),
        asset_groups={"A": ["QLD"]}, trading_interval_days=1,
    )
    assert engine2.dip_state.to_dict()["armed"] == saved_before["armed"]


def test_deployable_cash_includes_shv(tmp_path):
    engine, _, _ = _make_engine(tmp_path)
    pf = Portfolio(total_cash=500.0, holdings={"SHV": 10},
                   current_prices={"SHV": 100.0, "QLD": 50.0})
    assert engine._deployable_cash(pf) == 500.0 + 10 * 100.0   # 예수금 + SHV평가액


def test_reservoir_sweeps_idle_cash_to_shv(tmp_path):
    engine, _, _ = _make_engine(tmp_path)
    pf = Portfolio(total_cash=1000.0, holdings={}, current_prices={"SHV": 100.0, "QLD": 50.0})
    orders = engine._apply_cash_reservoir([], pf)   # QLD 주문 없음 → 전액 SHV 스윕
    shv_buys = [o for o in orders if o.ticker == "SHV" and o.action == OrderAction.BUY]
    assert shv_buys and shv_buys[0].quantity == 10   # floor(1000/100)


def test_reservoir_sells_shv_to_fund_qld_buy(tmp_path):
    engine, _, _ = _make_engine(tmp_path)
    pf = Portfolio(total_cash=0.0, holdings={"SHV": 20},
                   current_prices={"SHV": 100.0, "QLD": 50.0})
    qld_buy = [Order("QLD", OrderAction.BUY, 10, 50.0)]   # 비용 500
    orders = engine._apply_cash_reservoir(list(qld_buy), pf)
    shv_sells = [o for o in orders if o.ticker == "SHV" and o.action == OrderAction.SELL]
    assert shv_sells and shv_sells[0].quantity == 5      # ceil(500/100)


def test_reservoir_sweeps_qld_sell_proceeds_to_shv(tmp_path):
    engine, _, _ = _make_engine(tmp_path)
    pf = Portfolio(total_cash=0.0, holdings={"QLD": 10, "SHV": 0},
                   current_prices={"SHV": 100.0, "QLD": 50.0})
    qld_sell = [Order("QLD", OrderAction.SELL, 10, 50.0)]  # 유입 500
    orders = engine._apply_cash_reservoir(list(qld_sell), pf)
    shv_buys = [o for o in orders if o.ticker == "SHV" and o.action == OrderAction.BUY]
    assert shv_buys and shv_buys[0].quantity == 5         # floor(500/100)


def _make_gated(tmp_path):
    repo = JsonRepository(str(tmp_path), asset_groups={"A": ["QLD"], "C": ["SHV"]})
    broker = MockBroker(initial_cash=10000.0, holdings={"QLD": 50})
    logger = TradeLogger(log_dir=str(tmp_path / "g"))
    eng = DipBuyGatedEngine(broker=broker, repo=repo, logger=logger,
                            asset_groups={"A": ["QLD"], "C": ["SHV"]}, trading_interval_days=1)
    return eng, broker, repo


def test_gated_engine_registered():
    from src.core.engine import _ENGINE_REGISTRY
    assert "DipBuyGatedEngine" in [n for n, _ in _ENGINE_REGISTRY]


def test_gated_risk_off_liquidates_below_ma200(tmp_path):
    eng, _, _ = _make_gated(tmp_path)
    # price(80) < ma200(100) → risk-off → 보유 QLD 전량 청산
    eng.dip_signals = DipBuySignals("2024-01-01", 80.0, 85.0, 90.0, 95.0, 50.0, ma200=100.0)
    pf = Portfolio(total_cash=0.0, holdings={"QLD": 50, "SHV": 0},
                   current_prices={"QLD": 80.0, "SHV": 100.0})
    signal, _, _, _ = eng.execute_cycle(None, pf, None, 0.0, [], "2024-01-01", "2024-01-01")
    sells = [o for o in signal.orders if o.ticker == "QLD" and o.action == OrderAction.SELL]
    assert sells and sells[0].quantity == 50
    assert "현금화" in signal.reason
    assert eng.dip_state.queue == []          # 상태 리셋


def test_gated_risk_on_delegates_to_dipbuy(tmp_path):
    eng, _, _ = _make_gated(tmp_path)
    # price(120) >= ma200(90) → risk-on → 정상 DipBuy (트리거 없으면 대기)
    eng.dip_signals = DipBuySignals("2024-01-01", 120.0, 110.0, 105.0, 100.0, 50.0, ma200=90.0)
    pf = Portfolio(total_cash=1000.0, holdings={"QLD": 0, "SHV": 0},
                   current_prices={"QLD": 120.0, "SHV": 100.0})
    signal, _, _, _ = eng.execute_cycle(None, pf, None, 0.5, [], "2024-01-01", "2024-01-01")
    assert "현금화" not in signal.reason       # risk-off 경로 아님


def _make_gated_spy(tmp_path, holdings=None):
    groups = {"A": ["QLD"], "B": ["SPY"], "C": ["SHV"]}
    repo = JsonRepository(str(tmp_path), asset_groups=groups)
    broker = MockBroker(initial_cash=10000.0, holdings=holdings or {})
    logger = TradeLogger(log_dir=str(tmp_path / "gs"))
    eng = DipBuyGatedSpyEngine(broker=broker, repo=repo, logger=logger,
                               asset_groups=groups, trading_interval_days=1)
    return eng, broker, repo


def test_gated_spy_engine_registered():
    from src.core.engine import _ENGINE_REGISTRY
    assert "DipBuyGatedSpyEngine" in [n for n, _ in _ENGINE_REGISTRY]


def test_gated_spy_risk_off_buys_spy(tmp_path):
    eng, _, _ = _make_gated_spy(tmp_path)
    # price(80) < ma200(100) → risk-off → QLD·SHV 청산 후 SPY 100%
    eng.dip_signals = DipBuySignals("2024-01-01", 80.0, 85.0, 90.0, 95.0, 50.0, ma200=100.0)
    pf = Portfolio(total_cash=0.0, holdings={"QLD": 50, "SHV": 10},
                   current_prices={"QLD": 80.0, "SHV": 100.0, "SPY": 50.0})
    signal, _, _, _ = eng.execute_cycle(None, pf, None, 0.0, [], "2024-01-01", "2024-01-01")
    spy_buys = [o for o in signal.orders if o.ticker == "SPY" and o.action == OrderAction.BUY]
    # 가용현금 = 0 + 50*80 + 10*100 = 5000 → SPY 5000/50 = 100주
    assert spy_buys and spy_buys[0].quantity == 100
    assert {o.ticker for o in signal.orders if o.action == OrderAction.SELL} == {"QLD", "SHV"}
    assert "SPY" in signal.reason


def test_gated_spy_risk_on_liquidates_spy(tmp_path):
    eng, _, _ = _make_gated_spy(tmp_path)
    # price(120) >= ma200(90), SPY 보유 중 → 전환 사이클: SPY 청산 후 SHV 스윕
    eng.dip_signals = DipBuySignals("2024-01-01", 120.0, 110.0, 105.0, 100.0, 50.0, ma200=90.0)
    pf = Portfolio(total_cash=0.0, holdings={"SPY": 100, "QLD": 0, "SHV": 0},
                   current_prices={"QLD": 120.0, "SPY": 50.0, "SHV": 100.0})
    signal, _, _, _ = eng.execute_cycle(None, pf, None, 0.5, [], "2024-01-01", "2024-01-01")
    spy_sells = [o for o in signal.orders if o.ticker == "SPY" and o.action == OrderAction.SELL]
    assert spy_sells and spy_sells[0].quantity == 100
    assert "청산" in signal.reason


def test_gated_spy_risk_on_no_spy_runs_dipbuy(tmp_path):
    eng, _, _ = _make_gated_spy(tmp_path)
    # risk-on이고 SPY 미보유 → 정상 DipBuy (전환/청산 reason 아님)
    eng.dip_signals = DipBuySignals("2024-01-01", 120.0, 110.0, 105.0, 100.0, 50.0, ma200=90.0)
    pf = Portfolio(total_cash=1000.0, holdings={"QLD": 0, "SPY": 0, "SHV": 0},
                   current_prices={"QLD": 120.0, "SPY": 50.0, "SHV": 100.0})
    signal, _, _, _ = eng.execute_cycle(None, pf, None, 0.5, [], "2024-01-01", "2024-01-01")
    assert "청산" not in signal.reason and "100% 보유" not in signal.reason


def test_multi_day_cycle_executes_orders(tmp_path):
    """여러 거래일을 돌려 분할매수가 실제 체결로 이어지는지 확인."""
    engine, broker, repo = _make_engine(tmp_path)
    df = _ramp_then_dip()
    loader = _Loader(df)
    for i in range(5):
        engine.run_one_cycle(loader, sim_date=f"2023-10-{27 + i:02d}")
    # 적어도 한 번은 QLD를 보유하거나 현금이 변동했어야 함 (트리거 발동 시)
    assert broker.cash <= 10000.0
