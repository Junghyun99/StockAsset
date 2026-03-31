# tests/test_new_engines.py
"""QldSHVEngine 및 QldSdyEngine 단위 테스트.

두 엔진 모두 FullExposureEngine을 상속하며:
- 클래스 상수(ASSET_GROUPS, REBALANCE_RATIO_A) 검증
- 기본 Rebalancer 자동 생성 검증
- analyze_strategy() 동작 (FullExposureEngine 상속) 검증
- 전체 사이클 end-to-end 검증
"""
import math
import pytest
from unittest.mock import MagicMock, patch

from src.core.engine import QldSHVEngine, QldSdyEngine, Asset5Engine, QqqSdyEngine, DomesticAsset5Engine
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
        current_prices={"QLD": 80.0, "SHV": 110.0, "SDY": 75.0},
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
    """QldSdyEngine을 Mock 의존성으로 조립."""
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

        engine = QldSdyEngine(
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
# QldSdyEngine — 클래스 상수 검증
# ─────────────────────────────────────────────────────────────────

def test_qld_schd_asset_groups_A():
    """QldSdyEngine의 A그룹은 [QLD]."""
    assert QldSdyEngine.ASSET_GROUPS['A'] == ['QLD']


def test_qld_schd_asset_groups_B():
    """QldSdyEngine의 B그룹은 [SDY]."""
    assert QldSdyEngine.ASSET_GROUPS['B'] == ['SDY']


def test_qld_schd_no_C_group():
    """QldSdyEngine에는 C그룹(현금)이 없다."""
    assert 'C' not in QldSdyEngine.ASSET_GROUPS


def test_qld_schd_rebalance_ratio_a_class_constant():
    """REBALANCE_RATIO_A 클래스 상수가 0.3이다."""
    assert QldSdyEngine.REBALANCE_RATIO_A == 0.3


# ─────────────────────────────────────────────────────────────────
# QldSdyEngine — 기본 Rebalancer 자동 생성
# ─────────────────────────────────────────────────────────────────

def test_qld_schd_default_rebalancer_groups():
    """rebalancer가 클래스 ASSET_GROUPS로 자동 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSdyEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == QldSdyEngine.ASSET_GROUPS


def test_qld_schd_default_rebalancer_ratio_a():
    """rebalancer ratio_a=0.3으로 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSdyEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.ratio_a == 0.3


def test_qld_schd_default_rebalancer_ratio_b():
    """ratio_b = 1 - ratio_a = 0.7."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSdyEngine(broker=broker, repo=repo, logger=logger)
    assert abs(engine.rebalancer.ratio_b - 0.7) < 1e-9


def test_qld_schd_all_tickers():
    """all_tickers는 QLD + SDY 조합이다."""
    engine, _ = _build_qld_schd_engine()
    assert set(engine.all_tickers) == {"QLD", "SDY"}


# ─────────────────────────────────────────────────────────────────
# QldSdyEngine — analyze_strategy (FullExposureEngine 상속)
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
# QldSdyEngine — end-to-end 사이클
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
    """QldSHVEngine(0.5) vs QldSdyEngine(0.3) ratio_a 차이."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        shv_engine = QldSHVEngine(broker=broker, repo=repo, logger=logger)
        schd_engine = QldSdyEngine(broker=broker, repo=repo, logger=logger)
    assert shv_engine.rebalancer.ratio_a == 0.5
    assert schd_engine.rebalancer.ratio_a == 0.3
    assert shv_engine.rebalancer.ratio_a != schd_engine.rebalancer.ratio_a


def test_engines_asset_groups_differ():
    """두 엔진의 B그룹 자산이 다르다 (SHV vs SDY)."""
    assert QldSHVEngine.ASSET_GROUPS['B'] != QldSdyEngine.ASSET_GROUPS['B']
    assert QldSHVEngine.ASSET_GROUPS['A'] == QldSdyEngine.ASSET_GROUPS['A']


# ─────────────────────────────────────────────────────────────────
# QqqSdyEngine — 클래스 상수 검증
# ─────────────────────────────────────────────────────────────────

def test_qqq_schd_asset_groups_A():
    """QqqSdyEngine의 A그룹은 [QQQ]."""
    assert QqqSdyEngine.ASSET_GROUPS['A'] == ['QQQ']


def test_qqq_schd_asset_groups_B():
    """QqqSdyEngine의 B그룹은 [SDY]."""
    assert QqqSdyEngine.ASSET_GROUPS['B'] == ['SDY']


def test_qqq_schd_no_C_group():
    """QqqSdyEngine에는 C그룹(현금)이 없다."""
    assert 'C' not in QqqSdyEngine.ASSET_GROUPS


def test_qqq_schd_rebalance_ratio_a_class_constant():
    """REBALANCE_RATIO_A 클래스 상수가 0.3이다."""
    assert QqqSdyEngine.REBALANCE_RATIO_A == 0.3


# ─────────────────────────────────────────────────────────────────
# QqqSdyEngine — 기본 Rebalancer 자동 생성
# ─────────────────────────────────────────────────────────────────

def _build_qqq_schd_engine(repo_last_reb=None, notifier=None):
    """QqqSdyEngine을 Mock 의존성으로 조립."""
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

        engine = QqqSdyEngine(
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


def test_qqq_schd_default_rebalancer_groups():
    """rebalancer가 클래스 ASSET_GROUPS로 자동 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QqqSdyEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == QqqSdyEngine.ASSET_GROUPS


def test_qqq_schd_default_rebalancer_ratio_a():
    """rebalancer ratio_a=0.3으로 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QqqSdyEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.ratio_a == 0.3


def test_qqq_schd_default_rebalancer_ratio_b():
    """ratio_b = 1 - ratio_a = 0.7."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QqqSdyEngine(broker=broker, repo=repo, logger=logger)
    assert abs(engine.rebalancer.ratio_b - 0.7) < 1e-9


def test_qqq_schd_all_tickers():
    """all_tickers는 QQQ + SDY 조합이다."""
    engine, _ = _build_qqq_schd_engine()
    assert set(engine.all_tickers) == {"QQQ", "SDY"}


# ─────────────────────────────────────────────────────────────────
# QqqSdyEngine — analyze_strategy (FullExposureEngine 상속)
# ─────────────────────────────────────────────────────────────────

def test_qqq_schd_bull_exposure_1():
    """BULL 국면에서 exposure=1.0."""
    engine, mocks = _build_qqq_schd_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0
    assert nan_fields == []


def test_qqq_schd_crash_exposure_1():
    """CRASH 국면에서도 exposure=1.0 (NaN 아닐 때)."""
    engine, mocks = _build_qqq_schd_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    _, exposure, _ = engine.analyze_strategy(_make_market_data(vix=40.0, mdd=-0.30))
    assert exposure == 1.0


def test_qqq_schd_nan_exposure_zero():
    """NaN 데이터 시 exposure=0.0 (안전장치)."""
    engine, mocks = _build_qqq_schd_engine()
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data(nan_vol=True))
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields
    mocks["analyzer"].analyze.assert_not_called()


def test_qqq_schd_does_not_call_targeter():
    """FullExposureEngine처럼 targeter를 호출하지 않는다."""
    engine, mocks = _build_qqq_schd_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_WEAK
    engine.analyze_strategy(_make_market_data())
    mocks["targeter"].calculate_exposure.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# QqqSdyEngine — end-to-end 사이클
# ─────────────────────────────────────────────────────────────────

def test_qqq_schd_end_to_end_rebalancing():
    """전체 사이클: exposure=1.0이 rebalancer에 전달된다."""
    engine, mocks = _build_qqq_schd_engine(repo_last_reb=None)
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["rebalancer"] = MagicMock()
    engine.rebalancer = mocks["rebalancer"]
    engine.rebalancer.generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 1.0


def test_qqq_schd_end_to_end_nan_no_trade():
    """NaN 시 전체 사이클: 매매 없이 종료."""
    engine, mocks = _build_qqq_schd_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)
    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.0
    assert result.is_rebalancing is False
    assert result.executions == []


def test_qqq_schd_a_group_differs_from_qld_schd():
    """QqqSdyEngine과 QldSdyEngine의 A그룹이 다르다 (QQQ vs QLD)."""
    assert QqqSdyEngine.ASSET_GROUPS['A'] != QldSdyEngine.ASSET_GROUPS['A']
    assert QqqSdyEngine.ASSET_GROUPS['B'] == QldSdyEngine.ASSET_GROUPS['B']


# ─────────────────────────────────────────────────────────────────
# Asset5Engine (자산5분법) — 클래스 상수 검증
# ─────────────────────────────────────────────────────────────────

def test_asset5_asset_groups_A():
    """Asset5Engine의 A그룹은 [SPY, EEM]."""
    assert Asset5Engine.ASSET_GROUPS['A'] == ['SPY', 'EEM']


def test_asset5_asset_groups_B():
    """Asset5Engine의 B그룹은 [TLT, EMB, GLD]."""
    assert Asset5Engine.ASSET_GROUPS['B'] == ['TLT', 'EMB', 'GLD']


def test_asset5_no_C_group():
    """Asset5Engine에는 C그룹(현금)이 없다."""
    assert 'C' not in Asset5Engine.ASSET_GROUPS


def test_asset5_rebalance_ratio_a_class_constant():
    """REBALANCE_RATIO_A 클래스 상수가 0.4이다."""
    assert Asset5Engine.REBALANCE_RATIO_A == 0.4


# ─────────────────────────────────────────────────────────────────
# Asset5Engine — 기본 Rebalancer 자동 생성
# ─────────────────────────────────────────────────────────────────

def test_asset5_default_rebalancer_groups():
    """rebalancer가 클래스 ASSET_GROUPS로 자동 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = Asset5Engine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == Asset5Engine.ASSET_GROUPS


def test_asset5_default_rebalancer_ratio_a():
    """rebalancer ratio_a=0.4으로 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = Asset5Engine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.ratio_a == 0.4


def test_asset5_default_rebalancer_ratio_b():
    """ratio_b = 1 - ratio_a = 0.6."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = Asset5Engine(broker=broker, repo=repo, logger=logger)
    assert abs(engine.rebalancer.ratio_b - 0.6) < 1e-9


def test_asset5_all_tickers():
    """all_tickers는 A그룹 + B그룹 전체 5개 티커다."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    broker.get_portfolio.return_value = Portfolio(
        total_cash=50000.0,
        holdings={},
        current_prices={},
    )
    broker.fetch_current_prices.return_value = {}

    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.VolatilityTargeter'), \
         patch('src.core.engine.Rebalancer'):
        MockAnalyzer.return_value._prev_regime = None
        engine = Asset5Engine(broker=broker, repo=repo, logger=logger)

    assert set(engine.all_tickers) == {'SPY', 'EEM', 'TLT', 'EMB', 'GLD'}


# ─────────────────────────────────────────────────────────────────
# Asset5Engine — analyze_strategy (FullExposureEngine 상속)
# ─────────────────────────────────────────────────────────────────

def _build_asset5_engine(repo_last_reb=None, notifier=None):
    """Asset5Engine을 Mock 의존성으로 조립."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = repo_last_reb
    repo.load_last_regime.return_value = None
    broker.get_portfolio.return_value = Portfolio(
        total_cash=50000.0,
        holdings={'SPY': 50},
        current_prices={'SPY': 400.0, 'EEM': 50.0, 'TLT': 95.0, 'EMB': 90.0, 'GLD': 180.0},
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

        engine = Asset5Engine(
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


def test_asset5_bull_exposure_1():
    """BULL 국면에서 exposure=1.0."""
    engine, mocks = _build_asset5_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0
    assert nan_fields == []


def test_asset5_crash_exposure_1():
    """CRASH 국면에서도 exposure=1.0 (NaN 아닐 때)."""
    engine, mocks = _build_asset5_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    _, exposure, _ = engine.analyze_strategy(_make_market_data(vix=40.0, mdd=-0.30))
    assert exposure == 1.0


def test_asset5_nan_exposure_zero():
    """NaN 데이터 시 exposure=0.0 (안전장치)."""
    engine, mocks = _build_asset5_engine()
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data(nan_vol=True))
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields
    mocks["analyzer"].analyze.assert_not_called()


def test_asset5_does_not_call_targeter():
    """FullExposureEngine처럼 targeter를 호출하지 않는다."""
    engine, mocks = _build_asset5_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_STRONG
    engine.analyze_strategy(_make_market_data())
    mocks["targeter"].calculate_exposure.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# Asset5Engine — end-to-end 사이클
# ─────────────────────────────────────────────────────────────────

def test_asset5_end_to_end_rebalancing():
    """전체 사이클: exposure=1.0이 rebalancer에 전달된다."""
    engine, mocks = _build_asset5_engine(repo_last_reb=None)
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["rebalancer"] = MagicMock()
    engine.rebalancer = mocks["rebalancer"]
    engine.rebalancer.generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 1.0


def test_asset5_end_to_end_nan_no_trade():
    """NaN 시 전체 사이클: 매매 없이 종료."""
    engine, mocks = _build_asset5_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)
    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.0
    assert result.is_rebalancing is False
    assert result.executions == []


# ─────────────────────────────────────────────────────────────────
# DomesticAsset5Engine (국내 자산5분법) — 클래스 상수 검증
# ─────────────────────────────────────────────────────────────────

def test_domestic_asset5_asset_groups_A():
    """DomesticAsset5Engine의 A그룹은 [069500, 360750]."""
    assert DomesticAsset5Engine.ASSET_GROUPS['A'] == ['069500.KS', '360750.KS']


def test_domestic_asset5_asset_groups_B():
    """DomesticAsset5Engine의 B그룹은 [411060, 305080, 365780]."""
    assert DomesticAsset5Engine.ASSET_GROUPS['B'] == ['411060.KS', '305080.KS', '365780.KS']


def test_domestic_asset5_no_C_group():
    """DomesticAsset5Engine에는 C그룹(현금)이 없다."""
    assert 'C' not in DomesticAsset5Engine.ASSET_GROUPS


def test_domestic_asset5_rebalance_ratio_a_class_constant():
    """REBALANCE_RATIO_A 클래스 상수가 0.4이다."""
    assert DomesticAsset5Engine.REBALANCE_RATIO_A == 0.4


# ─────────────────────────────────────────────────────────────────
# DomesticAsset5Engine — 기본 Rebalancer 자동 생성
# ─────────────────────────────────────────────────────────────────

def test_domestic_asset5_default_rebalancer_groups():
    """rebalancer가 클래스 ASSET_GROUPS로 자동 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = DomesticAsset5Engine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == DomesticAsset5Engine.ASSET_GROUPS


def test_domestic_asset5_default_rebalancer_ratio_a():
    """rebalancer ratio_a=0.4으로 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = DomesticAsset5Engine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.ratio_a == 0.4


def test_domestic_asset5_default_rebalancer_ratio_b():
    """ratio_b = 1 - ratio_a = 0.6."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = DomesticAsset5Engine(broker=broker, repo=repo, logger=logger)
    assert abs(engine.rebalancer.ratio_b - 0.6) < 1e-9


def test_domestic_asset5_all_tickers():
    """all_tickers는 A그룹 + B그룹 전체 5개 티커다."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    broker.get_portfolio.return_value = Portfolio(
        total_cash=5000000.0,
        holdings={},
        current_prices={},
    )
    broker.fetch_current_prices.return_value = {}

    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.VolatilityTargeter'), \
         patch('src.core.engine.Rebalancer'):
        MockAnalyzer.return_value._prev_regime = None
        engine = DomesticAsset5Engine(broker=broker, repo=repo, logger=logger)

    assert set(engine.all_tickers) == {'069500.KS', '360750.KS', '411060.KS', '305080.KS', '365780.KS'}


# ─────────────────────────────────────────────────────────────────
# DomesticAsset5Engine — analyze_strategy (FullExposureEngine 상속)
# ─────────────────────────────────────────────────────────────────

def _build_domestic_asset5_engine(repo_last_reb=None, notifier=None):
    """DomesticAsset5Engine을 Mock 의존성으로 조립."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = repo_last_reb
    repo.load_last_regime.return_value = None
    broker.get_portfolio.return_value = Portfolio(
        total_cash=5000000.0,
        holdings={'069500.KS': 50},
        current_prices={
            '069500.KS': 35000.0, '360750.KS': 12000.0,
            '411060.KS': 15000.0, '305080.KS': 10000.0, '365780.KS': 11000.0,
        },
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

        engine = DomesticAsset5Engine(
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


def test_domestic_asset5_bull_exposure_1():
    """BULL 국면에서 exposure=1.0."""
    engine, mocks = _build_domestic_asset5_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data())
    assert exposure == 1.0
    assert nan_fields == []


def test_domestic_asset5_crash_exposure_1():
    """CRASH 국면에서도 exposure=1.0 (NaN 아닐 때)."""
    engine, mocks = _build_domestic_asset5_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    _, exposure, _ = engine.analyze_strategy(_make_market_data(vix=40.0, mdd=-0.30))
    assert exposure == 1.0


def test_domestic_asset5_nan_exposure_zero():
    """NaN 데이터 시 exposure=0.0 (안전장치)."""
    engine, mocks = _build_domestic_asset5_engine()
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data(nan_vol=True))
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields
    mocks["analyzer"].analyze.assert_not_called()


def test_domestic_asset5_does_not_call_targeter():
    """FullExposureEngine처럼 targeter를 호출하지 않는다."""
    engine, mocks = _build_domestic_asset5_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_STRONG
    engine.analyze_strategy(_make_market_data())
    mocks["targeter"].calculate_exposure.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# DomesticAsset5Engine — end-to-end 사이클
# ─────────────────────────────────────────────────────────────────

def test_domestic_asset5_end_to_end_rebalancing():
    """전체 사이클: exposure=1.0이 rebalancer에 전달된다."""
    engine, mocks = _build_domestic_asset5_engine(repo_last_reb=None)
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["rebalancer"] = MagicMock()
    engine.rebalancer = mocks["rebalancer"]
    engine.rebalancer.generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 1.0


def test_domestic_asset5_end_to_end_nan_no_trade():
    """NaN 시 전체 사이클: 매매 없이 종료."""
    engine, mocks = _build_domestic_asset5_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)
    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.0
    assert result.is_rebalancing is False
    assert result.executions == []
