# tests/test_qqq_engine.py
"""QqqEngine 단위 테스트.

QQQ Buy&Hold 벤치마크를 시뮬레이션하는 엔진:
- A그룹: [QQQ], B그룹: [SHV]
- FullExposureEngine 상속 → 항상 exposure=1.0
- REBALANCE_RATIO_A=0.999 → 사실상 100% QQQ 투자
"""
import math
import pytest
from unittest.mock import MagicMock, patch

from src.core.engine import QqqEngine, FullExposureEngine, _ENGINE_REGISTRY as ENGINE_REGISTRY
from src.core.logic import Rebalancer
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal,
)


# ─────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────

def _make_market_data(nan_vol: bool = False, vix: float = 18.0, mdd: float = -0.08) -> MarketData:
    return MarketData(
        date="2024-06-01",
        spy_price=520.0,
        spy_ma180=490.0,
        spy_volatility=math.nan if nan_vol else 0.14,
        spy_momentum=0.04,
        spy_mdd=mdd,
        vix=vix,
    )


def _make_base_deps():
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    return broker, repo, logger


def _build_qqq_engine(repo_last_reb=None):
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = repo_last_reb
    repo.load_last_regime.return_value = None
    broker.get_portfolio.return_value = Portfolio(
        total_cash=10000.0,
        holdings={"QQQ": 20},
        current_prices={"QQQ": 480.0, "SHV": 110.0},
    )
    broker.fetch_current_prices.return_value = {}

    with patch('src.core.engine.IndicatorCalculator') as MockCalc, \
         patch('src.core.engine.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.VolatilityTargeter') as MockTargeter, \
         patch('src.core.engine.Rebalancer') as MockRebalancer:

        calculator = MockCalc.return_value
        analyzer = MockAnalyzer.return_value
        analyzer._prev_regime = None
        targeter = MockTargeter.return_value
        rebalancer = MockRebalancer.return_value

        engine = QqqEngine(
            broker=broker,
            repo=repo,
            logger=logger,
            trading_interval_days=5,
        )

    return engine, {
        "calculator": calculator,
        "analyzer": analyzer,
        "targeter": targeter,
        "rebalancer": rebalancer,
        "broker": broker,
        "repo": repo,
        "logger": logger,
        "data_provider": data_provider,
    }


# ─────────────────────────────────────────────────────────────────
# 클래스 상수 검증
# ─────────────────────────────────────────────────────────────────

def test_qqq_engine_asset_groups_A():
    """QqqEngine의 A그룹은 [QQQ]."""
    assert QqqEngine.ASSET_GROUPS['A'] == ['QQQ']


def test_qqq_engine_asset_groups_B():
    """QqqEngine의 B그룹은 [SHV]."""
    assert QqqEngine.ASSET_GROUPS['B'] == ['SHV']


def test_qqq_engine_no_C_group():
    """QqqEngine에는 C그룹이 없다."""
    assert 'C' not in QqqEngine.ASSET_GROUPS


def test_qqq_engine_rebalance_ratio_a():
    """REBALANCE_RATIO_A는 0.999로 사실상 100% QQQ 투자."""
    assert QqqEngine.REBALANCE_RATIO_A == 0.999


def test_qqq_engine_is_full_exposure_subclass():
    """QqqEngine은 FullExposureEngine의 서브클래스다."""
    assert issubclass(QqqEngine, FullExposureEngine)


# ─────────────────────────────────────────────────────────────────
# 레지스트리 등록 검증
# ─────────────────────────────────────────────────────────────────

def test_qqq_engine_registered_in_registry():
    """QqqEngine이 ENGINE_REGISTRY에 등록되어 있다."""
    names = [name for name, _ in ENGINE_REGISTRY]
    assert "QqqEngine" in names


def test_qqq_engine_registry_class_is_qqq_engine():
    """레지스트리에서 'QqqEngine' 이름으로 QqqEngine 클래스가 반환된다."""
    for name, cls in ENGINE_REGISTRY:
        if name == "QqqEngine":
            assert cls is QqqEngine
            break


# ─────────────────────────────────────────────────────────────────
# Rebalancer 자동 생성 검증
# ─────────────────────────────────────────────────────────────────

def test_qqq_engine_rebalancer_groups():
    """rebalancer가 QqqEngine.ASSET_GROUPS로 자동 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QqqEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == QqqEngine.ASSET_GROUPS


def test_qqq_engine_rebalancer_ratio_a():
    """rebalancer ratio_a=0.999로 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QqqEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.ratio_a == 0.999


def test_qqq_engine_rebalancer_ratio_b():
    """ratio_b = 1 - 0.999 = 0.001."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QqqEngine(broker=broker, repo=repo, logger=logger)
    assert abs(engine.rebalancer.ratio_b - 0.001) < 1e-9


def test_qqq_engine_all_tickers():
    """all_tickers는 QQQ + SHV 조합이다."""
    engine, _ = _build_qqq_engine()
    assert set(engine.all_tickers) == {"QQQ", "SHV"}


# ─────────────────────────────────────────────────────────────────
# analyze_strategy — FullExposureEngine 상속 검증
# ─────────────────────────────────────────────────────────────────

def test_qqq_engine_bull_exposure_1():
    """BULL 국면에서 exposure=1.0."""
    engine, mocks = _build_qqq_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0
    assert nan_fields == []


def test_qqq_engine_crash_exposure_1():
    """CRASH 국면에서도 exposure=1.0 (NaN 아닐 때)."""
    engine, mocks = _build_qqq_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    _, exposure, _ = engine.analyze_strategy(_make_market_data(vix=40.0, mdd=-0.30))
    assert exposure == 1.0


def test_qqq_engine_bear_strong_exposure_1():
    """BEAR_STRONG 국면에서도 exposure=1.0."""
    engine, mocks = _build_qqq_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_STRONG
    _, exposure, _ = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0


def test_qqq_engine_nan_exposure_zero():
    """NaN 데이터 시 exposure=0.0 (안전장치)."""
    engine, mocks = _build_qqq_engine()
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data(nan_vol=True))
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields
    mocks["analyzer"].analyze.assert_not_called()


def test_qqq_engine_does_not_call_targeter():
    """FullExposureEngine처럼 targeter를 호출하지 않는다."""
    engine, mocks = _build_qqq_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.SIDEWAYS
    engine.analyze_strategy(_make_market_data())
    mocks["targeter"].calculate_exposure.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# end-to-end 사이클
# ─────────────────────────────────────────────────────────────────

def test_qqq_engine_end_to_end_rebalancing():
    """전체 사이클: exposure=1.0이 rebalancer에 전달된다."""
    engine, mocks = _build_qqq_engine(repo_last_reb=None)
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    engine.rebalancer = MagicMock()
    engine.rebalancer.generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 1.0  # exposure 인자


def test_qqq_engine_end_to_end_nan_no_trade():
    """NaN 시 전체 사이클: 매매 없이 종료."""
    engine, mocks = _build_qqq_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)
    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.0
    assert result.is_rebalancing is False
    assert result.executions == []
