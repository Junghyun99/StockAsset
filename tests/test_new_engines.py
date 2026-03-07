# tests/test_new_engines.py
"""QldSHVEngine 및 QldSchdEngine 단위 테스트.

두 엔진 모두 FullExposureEngine을 상속하며:
- 클래스 상수(ASSET_GROUPS, REBALANCE_RATIO_A) 검증
- 기본 Rebalancer 자동 생성 검증
- analyze_strategy() 동작 (FullExposureEngine 상속) 검증
- 전체 사이클 end-to-end 검증
"""
import math
import pytest
from unittest.mock import MagicMock, patch

from src.core.engine import QldSHVEngine, QldSchdEngine
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


def _make_portfolio(cash: float = 50000.0) -> Portfolio:
    return Portfolio(
        total_cash=cash,
        holdings={"QLD": 100},
        current_prices={"QLD": 80.0, "SHV": 110.0, "SCHD": 75.0},
    )


def _build_qld_shv_engine(repo_last_reb=None, notifier=None):
    """QldSHVEngine을 Mock 의존성으로 조립."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = repo_last_reb
    repo.load_last_regime.return_value = None
    broker.get_portfolio.return_value = _make_portfolio()
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

        engine = QldSHVEngine(
            broker=broker,
            repo=repo,
            logger=logger,
            trading_interval_days=5,
            notifier=notifier,
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


def _build_qld_schd_engine(repo_last_reb=None, notifier=None):
    """QldSchdEngine을 Mock 의존성으로 조립."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = repo_last_reb
    repo.load_last_regime.return_value = None
    broker.get_portfolio.return_value = _make_portfolio()
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

        engine = QldSchdEngine(
            broker=broker,
            repo=repo,
            logger=logger,
            trading_interval_days=5,
            notifier=notifier,
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


def _make_base_deps():
    """Rebalancer를 실제로 생성하는 테스트용 의존성."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    return broker, repo, logger


# ─────────────────────────────────────────────────────────────────
# QldSHVEngine — 클래스 상수 검증
# ─────────────────────────────────────────────────────────────────

def test_qld_shv_asset_groups_A():
    """QldSHVEngine의 A그룹은 [QLD]."""
    assert QldSHVEngine.ASSET_GROUPS['A'] == ['QLD']


def test_qld_shv_asset_groups_B():
    """QldSHVEngine의 B그룹은 [SHV]."""
    assert QldSHVEngine.ASSET_GROUPS['B'] == ['SHV']


def test_qld_shv_no_C_group():
    """QldSHVEngine에는 C그룹(현금)이 없다."""
    assert 'C' not in QldSHVEngine.ASSET_GROUPS


# ─────────────────────────────────────────────────────────────────
# QldSHVEngine — 기본 Rebalancer 자동 생성
# ─────────────────────────────────────────────────────────────────

def test_qld_shv_default_rebalancer_groups():
    """rebalancer가 클래스 ASSET_GROUPS로 자동 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSHVEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == QldSHVEngine.ASSET_GROUPS


def test_qld_shv_default_rebalancer_ratio_a():
    """rebalancer ratio_a는 Rebalancer 기본값(0.5)."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSHVEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.ratio_a == Rebalancer.DEFAULT_RATIO_A


def test_qld_shv_all_tickers():
    """all_tickers는 QLD + SHV 조합이다."""
    engine, _ = _build_qld_shv_engine()
    assert set(engine.all_tickers) == {"QLD", "SHV"}


# ─────────────────────────────────────────────────────────────────
# QldSHVEngine — analyze_strategy (FullExposureEngine 상속)
# ─────────────────────────────────────────────────────────────────

def test_qld_shv_bull_exposure_1():
    """BULL 국면에서 exposure=1.0."""
    engine, mocks = _build_qld_shv_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0
    assert nan_fields == []


def test_qld_shv_crash_exposure_1():
    """CRASH 국면에서도 exposure=1.0 (NaN 아닐 때)."""
    engine, mocks = _build_qld_shv_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    _, exposure, _ = engine.analyze_strategy(_make_market_data(vix=40.0, mdd=-0.30))
    assert exposure == 1.0


def test_qld_shv_nan_exposure_zero():
    """NaN 데이터 시 exposure=0.0 (안전장치)."""
    engine, mocks = _build_qld_shv_engine()
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data(nan_vol=True))
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields
    mocks["analyzer"].analyze.assert_not_called()


def test_qld_shv_does_not_call_targeter():
    """FullExposureEngine처럼 targeter를 호출하지 않는다."""
    engine, mocks = _build_qld_shv_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_WEAK
    engine.analyze_strategy(_make_market_data())
    mocks["targeter"].calculate_exposure.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# QldSHVEngine — end-to-end 사이클
# ─────────────────────────────────────────────────────────────────

def test_qld_shv_end_to_end_rebalancing():
    """전체 사이클: exposure=1.0이 rebalancer에 전달된다."""
    engine, mocks = _build_qld_shv_engine(repo_last_reb=None)
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["rebalancer"] = MagicMock()
    engine.rebalancer = mocks["rebalancer"]
    engine.rebalancer.generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 1.0  # 두 번째 위치 인자 = exposure


def test_qld_shv_end_to_end_nan_no_trade():
    """NaN 시 전체 사이클: 매매 없이 종료."""
    engine, mocks = _build_qld_shv_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)
    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.0
    assert result.is_rebalancing is False
    assert result.executions == []


# ─────────────────────────────────────────────────────────────────
# QldSchdEngine — 클래스 상수 검증
# ─────────────────────────────────────────────────────────────────

def test_qld_schd_asset_groups_A():
    """QldSchdEngine의 A그룹은 [QLD]."""
    assert QldSchdEngine.ASSET_GROUPS['A'] == ['QLD']


def test_qld_schd_asset_groups_B():
    """QldSchdEngine의 B그룹은 [SCHD]."""
    assert QldSchdEngine.ASSET_GROUPS['B'] == ['SCHD']


def test_qld_schd_no_C_group():
    """QldSchdEngine에는 C그룹(현금)이 없다."""
    assert 'C' not in QldSchdEngine.ASSET_GROUPS


def test_qld_schd_rebalance_ratio_a_class_constant():
    """REBALANCE_RATIO_A 클래스 상수가 0.3이다."""
    assert QldSchdEngine.REBALANCE_RATIO_A == 0.3


# ─────────────────────────────────────────────────────────────────
# QldSchdEngine — 기본 Rebalancer 자동 생성
# ─────────────────────────────────────────────────────────────────

def test_qld_schd_default_rebalancer_groups():
    """rebalancer가 클래스 ASSET_GROUPS로 자동 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSchdEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == QldSchdEngine.ASSET_GROUPS


def test_qld_schd_default_rebalancer_ratio_a():
    """rebalancer ratio_a=0.3으로 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSchdEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.ratio_a == 0.3


def test_qld_schd_default_rebalancer_ratio_b():
    """ratio_b = 1 - ratio_a = 0.7."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSchdEngine(broker=broker, repo=repo, logger=logger)
    assert abs(engine.rebalancer.ratio_b - 0.7) < 1e-9


def test_qld_schd_all_tickers():
    """all_tickers는 QLD + SCHD 조합이다."""
    engine, _ = _build_qld_schd_engine()
    assert set(engine.all_tickers) == {"QLD", "SCHD"}


# ─────────────────────────────────────────────────────────────────
# QldSchdEngine — analyze_strategy (FullExposureEngine 상속)
# ─────────────────────────────────────────────────────────────────

def test_qld_schd_bull_exposure_1():
    """BULL 국면에서 exposure=1.0."""
    engine, mocks = _build_qld_schd_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0
    assert nan_fields == []


def test_qld_schd_bear_strong_exposure_1():
    """BEAR_STRONG 국면에서도 exposure=1.0."""
    engine, mocks = _build_qld_schd_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_STRONG
    _, exposure, _ = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0


def test_qld_schd_crash_exposure_1():
    """CRASH 국면에서도 exposure=1.0 (NaN 아닐 때)."""
    engine, mocks = _build_qld_schd_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    _, exposure, _ = engine.analyze_strategy(_make_market_data(vix=40.0, mdd=-0.30))
    assert exposure == 1.0


def test_qld_schd_nan_exposure_zero():
    """NaN 데이터 시 exposure=0.0 (안전장치)."""
    engine, mocks = _build_qld_schd_engine()
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data(nan_vol=True))
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields
    mocks["analyzer"].analyze.assert_not_called()


def test_qld_schd_does_not_call_targeter():
    """FullExposureEngine처럼 targeter를 호출하지 않는다."""
    engine, mocks = _build_qld_schd_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.SIDEWAYS
    engine.analyze_strategy(_make_market_data())
    mocks["targeter"].calculate_exposure.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# QldSchdEngine — end-to-end 사이클
# ─────────────────────────────────────────────────────────────────

def test_qld_schd_end_to_end_rebalancing():
    """전체 사이클: exposure=1.0이 rebalancer에 전달된다."""
    engine, mocks = _build_qld_schd_engine(repo_last_reb=None)
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.SIDEWAYS
    mocks["rebalancer"] = MagicMock()
    engine.rebalancer = mocks["rebalancer"]
    engine.rebalancer.generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 1.0


def test_qld_schd_end_to_end_crash():
    """CRASH에서도 exposure=1.0으로 리밸런싱 실행."""
    engine, mocks = _build_qld_schd_engine(repo_last_reb=None)
    md = _make_market_data(vix=38.0, mdd=-0.28)
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    mocks["rebalancer"] = MagicMock()
    engine.rebalancer = mocks["rebalancer"]
    engine.rebalancer.generate_signal.return_value = TradeSignal(1.0, [], "Full Exposure")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    assert result.is_rebalancing is True
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 1.0


def test_qld_schd_end_to_end_nan_no_trade():
    """NaN 시 전체 사이클: 매매 없이 종료."""
    engine, mocks = _build_qld_schd_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)
    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.0
    assert result.is_rebalancing is False
    assert result.executions == []


# ─────────────────────────────────────────────────────────────────
# 두 엔진 비교: ratio_a 차이 검증
# ─────────────────────────────────────────────────────────────────

def test_engines_ratio_a_differs():
    """QldSHVEngine(0.5) vs QldSchdEngine(0.3) ratio_a 차이."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        shv_engine = QldSHVEngine(broker=broker, repo=repo, logger=logger)
        schd_engine = QldSchdEngine(broker=broker, repo=repo, logger=logger)
    assert shv_engine.rebalancer.ratio_a == 0.5
    assert schd_engine.rebalancer.ratio_a == 0.3
    assert shv_engine.rebalancer.ratio_a != schd_engine.rebalancer.ratio_a


def test_engines_asset_groups_differ():
    """두 엔진의 B그룹 자산이 다르다 (SHV vs SCHD)."""
    assert QldSHVEngine.ASSET_GROUPS['B'] != QldSchdEngine.ASSET_GROUPS['B']
    assert QldSHVEngine.ASSET_GROUPS['A'] == QldSchdEngine.ASSET_GROUPS['A']
