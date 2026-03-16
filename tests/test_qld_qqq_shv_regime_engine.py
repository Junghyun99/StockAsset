# tests/test_qld_qqq_shv_regime_engine.py
"""QldQqqShvRegimeEngine 및 Rebalancer regime_ratio_a_map 단위 테스트.

국면 적응형 레버리지 엔진:
- 클래스 상수(ASSET_GROUPS, REGIME_RATIO_A_MAP, REGIME_EXPOSURE_MAP) 검증
- Rebalancer regime_ratio_a_map 동작 검증 (국면별 ratio_a 조회, fallback)
- analyze_strategy() 국면별 exposure 반환 검증
- NaN 안전장치 검증
- 전체 사이클 end-to-end 검증
"""
import math
import pytest
from unittest.mock import MagicMock, patch

from src.core.engine import QldQqqShvRegimeEngine
from src.core.logic import Rebalancer
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal,
)


# ─────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────

def _make_market_data(nan_vol: bool = False, vix: float = 18.0, mdd: float = -0.08,
                      momentum: float = 0.04, spy_price: float = 520.0,
                      spy_ma180: float = 490.0) -> MarketData:
    return MarketData(
        date="2024-06-01",
        spy_price=spy_price,
        spy_ma180=spy_ma180,
        spy_volatility=math.nan if nan_vol else 0.14,
        spy_momentum=momentum,
        spy_mdd=mdd,
        vix=vix,
    )


def _make_portfolio(cash: float = 50000.0) -> Portfolio:
    return Portfolio(
        total_cash=cash,
        holdings={"QLD": 100, "QQQ": 50},
        current_prices={"QLD": 80.0, "QQQ": 450.0, "SHV": 110.0},
    )


def _make_base_deps():
    """실제 Rebalancer를 생성하는 테스트용 의존성."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    repo.load_last_regime.return_value = None
    repo.get_last_rebalancing_date.return_value = None
    return broker, repo, logger


def _build_regime_engine(repo_last_reb=None, notifier=None):
    """QldQqqShvRegimeEngine을 Mock 의존성으로 조립."""
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

        engine = QldQqqShvRegimeEngine(
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


# ─────────────────────────────────────────────────────────────────
# QldQqqShvRegimeEngine — 클래스 상수 검증
# ─────────────────────────────────────────────────────────────────

def test_regime_engine_asset_groups_A():
    """A그룹은 [QLD]."""
    assert QldQqqShvRegimeEngine.ASSET_GROUPS['A'] == ['QLD']


def test_regime_engine_asset_groups_B():
    """B그룹은 [QQQ]."""
    assert QldQqqShvRegimeEngine.ASSET_GROUPS['B'] == ['QQQ']


def test_regime_engine_asset_groups_C():
    """C그룹은 [SHV]."""
    assert QldQqqShvRegimeEngine.ASSET_GROUPS['C'] == ['SHV']


def test_regime_engine_fallback_ratio_a():
    """REBALANCE_RATIO_A fallback 값은 0.5."""
    assert QldQqqShvRegimeEngine.REBALANCE_RATIO_A == 0.5


def test_regime_engine_ratio_a_map_exists():
    """REGIME_RATIO_A_MAP이 5개 국면 모두 포함한다."""
    ratio_map = QldQqqShvRegimeEngine.REGIME_RATIO_A_MAP
    assert set(ratio_map.keys()) == {
        MarketRegime.BULL, MarketRegime.SIDEWAYS,
        MarketRegime.BEAR_WEAK, MarketRegime.BEAR_STRONG, MarketRegime.CRASH,
    }


def test_regime_engine_ratio_a_map_monotonic():
    """BULL→CRASH 순으로 ratio_a가 증가한다 (레버리지 증가)."""
    m = QldQqqShvRegimeEngine.REGIME_RATIO_A_MAP
    assert m[MarketRegime.BULL] < m[MarketRegime.SIDEWAYS]
    assert m[MarketRegime.SIDEWAYS] < m[MarketRegime.BEAR_WEAK]
    assert m[MarketRegime.BEAR_WEAK] < m[MarketRegime.BEAR_STRONG]
    assert m[MarketRegime.BEAR_STRONG] < m[MarketRegime.CRASH]


def test_regime_engine_exposure_map_exists():
    """REGIME_EXPOSURE_MAP이 5개 국면 모두 포함한다."""
    exp_map = QldQqqShvRegimeEngine.REGIME_EXPOSURE_MAP
    assert set(exp_map.keys()) == {
        MarketRegime.BULL, MarketRegime.SIDEWAYS,
        MarketRegime.BEAR_WEAK, MarketRegime.BEAR_STRONG, MarketRegime.CRASH,
    }


def test_regime_engine_crash_has_highest_leverage():
    """CRASH의 실효 레버리지가 가장 높다."""
    m = QldQqqShvRegimeEngine.REGIME_RATIO_A_MAP
    e = QldQqqShvRegimeEngine.REGIME_EXPOSURE_MAP
    # 실효 레버리지 = ratio_a * exposure * 2 + (1-ratio_a) * exposure * 1
    def eff_leverage(regime):
        ra = m[regime]
        exp = e[regime]
        return ra * exp * 2 + (1 - ra) * exp * 1
    crash_lev = eff_leverage(MarketRegime.CRASH)
    for regime in [MarketRegime.BULL, MarketRegime.SIDEWAYS,
                   MarketRegime.BEAR_WEAK, MarketRegime.BEAR_STRONG]:
        assert crash_lev > eff_leverage(regime), f"CRASH leverage should exceed {regime.value}"


# ─────────────────────────────────────────────────────────────────
# QldQqqShvRegimeEngine — Rebalancer 자동 생성
# ─────────────────────────────────────────────────────────────────

def test_regime_engine_rebalancer_has_regime_map():
    """Rebalancer에 regime_ratio_a_map이 전달된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldQqqShvRegimeEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer._regime_ratio_a_map is not None
    assert engine.rebalancer._regime_ratio_a_map == QldQqqShvRegimeEngine.REGIME_RATIO_A_MAP


def test_regime_engine_rebalancer_groups():
    """Rebalancer가 3-자산 그룹으로 생성된다."""
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldQqqShvRegimeEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer.groups == QldQqqShvRegimeEngine.ASSET_GROUPS


def test_regime_engine_all_tickers():
    """all_tickers는 QLD + QQQ + SHV 조합이다."""
    engine, _ = _build_regime_engine()
    assert set(engine.all_tickers) == {"QLD", "QQQ", "SHV"}


# ─────────────────────────────────────────────────────────────────
# QldQqqShvRegimeEngine — analyze_strategy 국면별 exposure
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("regime,expected_exposure", [
    (MarketRegime.BULL, 0.7),
    (MarketRegime.SIDEWAYS, 0.6),
    (MarketRegime.BEAR_WEAK, 0.6),
    (MarketRegime.BEAR_STRONG, 0.65),
    (MarketRegime.CRASH, 0.75),
])
def test_regime_engine_exposure_per_regime(regime, expected_exposure):
    """각 국면에서 REGIME_EXPOSURE_MAP에 따른 exposure가 반환된다."""
    engine, mocks = _build_regime_engine()
    mocks["analyzer"].analyze.return_value = regime
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data())
    assert exposure == expected_exposure
    assert nan_fields == []


def test_regime_engine_nan_exposure_zero():
    """NaN 데이터 시 exposure=0.0 (안전장치)."""
    engine, mocks = _build_regime_engine()
    _, exposure, nan_fields = engine.analyze_strategy(_make_market_data(nan_vol=True))
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields
    mocks["analyzer"].analyze.assert_not_called()


def test_regime_engine_does_not_call_targeter():
    """VolatilityTargeter를 호출하지 않는다 (고정 매핑 사용)."""
    engine, mocks = _build_regime_engine()
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_WEAK
    engine.analyze_strategy(_make_market_data())
    mocks["targeter"].calculate_exposure.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# QldQqqShvRegimeEngine — end-to-end 사이클
# ─────────────────────────────────────────────────────────────────

def test_regime_engine_end_to_end_bull():
    """BULL 사이클: exposure=0.7이 rebalancer에 전달된다."""
    engine, mocks = _build_regime_engine(repo_last_reb=None)
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    engine.rebalancer = MagicMock()
    engine.rebalancer.generate_signal.return_value = TradeSignal(0.7, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.7
    call_args = engine.rebalancer.generate_signal.call_args
    assert call_args[0][1] == 0.7  # exposure 인자


def test_regime_engine_end_to_end_crash():
    """CRASH 사이클: exposure=0.75로 리밸런싱."""
    engine, mocks = _build_regime_engine(repo_last_reb=None)
    md = _make_market_data(vix=38.0, mdd=-0.28)
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    engine.rebalancer = MagicMock()
    engine.rebalancer.generate_signal.return_value = TradeSignal(0.75, [], "Max Leverage")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.75
    assert result.is_rebalancing is True


def test_regime_engine_end_to_end_nan_no_trade():
    """NaN 시 전체 사이클: 매매 없이 종료."""
    engine, mocks = _build_regime_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)
    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.0
    assert result.is_rebalancing is False
    assert result.executions == []


# ─────────────────────────────────────────────────────────────────
# Rebalancer — regime_ratio_a_map 동작 검증
# ─────────────────────────────────────────────────────────────────

def test_rebalancer_regime_ratio_a_map_none_uses_fixed():
    """regime_ratio_a_map=None이면 고정 ratio_a를 사용한다."""
    groups = {'A': ['QLD'], 'B': ['QQQ'], 'C': ['SHV']}
    rebalancer = Rebalancer(groups, ratio_a=0.5, regime_ratio_a_map=None)
    assert rebalancer._regime_ratio_a_map is None

    pf = Portfolio(
        total_cash=100000.0,
        holdings={},
        current_prices={"QLD": 80.0, "QQQ": 450.0, "SHV": 110.0},
    )
    signal = rebalancer.generate_signal(pf, 1.0, MarketRegime.BULL)
    # 첫 투자: ratio_a=0.5 적용 → QLD 목표 = 100000 * 1.0 * 0.5 = 50000
    assert signal.target_exposure == 1.0


def test_rebalancer_regime_ratio_a_map_lookup():
    """regime_ratio_a_map에서 국면별 ratio_a를 조회한다."""
    groups = {'A': ['QLD'], 'B': ['QQQ'], 'C': ['SHV']}
    ratio_map = {
        MarketRegime.BULL: 0.3,
        MarketRegime.CRASH: 0.95,
    }
    rebalancer = Rebalancer(groups, ratio_a=0.5, regime_ratio_a_map=ratio_map)

    pf = Portfolio(
        total_cash=100000.0,
        holdings={},
        current_prices={"QLD": 80.0, "QQQ": 450.0, "SHV": 110.0},
    )

    # BULL: ratio_a=0.3 → QLD 목표 = 100000 * 0.9 * 0.3 = 27000
    signal_bull = rebalancer.generate_signal(pf, 0.9, MarketRegime.BULL)
    # 주문에서 QLD 매수금이 QQQ보다 작은지 확인
    qld_orders = [o for o in signal_bull.orders if o.ticker == 'QLD']
    qqq_orders = [o for o in signal_bull.orders if o.ticker == 'QQQ']
    if qld_orders and qqq_orders:
        qld_val = qld_orders[0].quantity * qld_orders[0].price
        qqq_val = qqq_orders[0].quantity * qqq_orders[0].price
        assert qld_val < qqq_val  # BULL에서 QLD < QQQ


def test_rebalancer_regime_ratio_a_map_fallback():
    """맵에 없는 국면은 기본 ratio_a로 폴백한다."""
    groups = {'A': ['QLD'], 'B': ['QQQ'], 'C': ['SHV']}
    ratio_map = {
        MarketRegime.BULL: 0.3,
        # SIDEWAYS 없음 → fallback to 0.5
    }
    rebalancer = Rebalancer(groups, ratio_a=0.5, regime_ratio_a_map=ratio_map)

    pf = Portfolio(
        total_cash=100000.0,
        holdings={},
        current_prices={"QLD": 80.0, "QQQ": 450.0, "SHV": 110.0},
    )

    signal = rebalancer.generate_signal(pf, 0.8, MarketRegime.SIDEWAYS)
    # SIDEWAYS → fallback ratio_a=0.5 → QLD와 QQQ 동일 목표
    qld_orders = [o for o in signal.orders if o.ticker == 'QLD']
    qqq_orders = [o for o in signal.orders if o.ticker == 'QQQ']
    if qld_orders and qqq_orders:
        qld_val = qld_orders[0].quantity * qld_orders[0].price
        qqq_val = qqq_orders[0].quantity * qqq_orders[0].price
        # 0.5:0.5 비율이므로 두 값이 비슷해야 함 (주문 단위 반올림 차이 허용)
        assert abs(qld_val - qqq_val) < max(80.0, 450.0)


def test_rebalancer_regime_ratio_a_map_validation():
    """regime_ratio_a_map 값이 [0, 1) 범위를 벗어나면 ValueError."""
    groups = {'A': ['QLD'], 'B': ['QQQ']}
    with pytest.raises(ValueError):
        Rebalancer(groups, ratio_a=0.5, regime_ratio_a_map={
            MarketRegime.BULL: 1.5,  # 잘못된 값
        })


def test_rebalancer_regime_ratio_a_map_allows_zero():
    """ratio_a=0.0은 허용된다 (전량 B그룹)."""
    groups = {'A': ['QLD'], 'B': ['QQQ']}
    rebalancer = Rebalancer(groups, ratio_a=0.5, regime_ratio_a_map={
        MarketRegime.CRASH: 0.0,
    })
    assert rebalancer._regime_ratio_a_map[MarketRegime.CRASH] == 0.0


# ─────────────────────────────────────────────────────────────────
# 기존 엔진 하위 호환성 검증
# ─────────────────────────────────────────────────────────────────

def test_existing_engines_no_regime_ratio_map():
    """기존 엔진(QldSHVEngine 등)은 REGIME_RATIO_A_MAP이 없다."""
    from src.core.engine import QldSHVEngine, QldSchdEngine
    assert not hasattr(QldSHVEngine, 'REGIME_RATIO_A_MAP')
    assert not hasattr(QldSchdEngine, 'REGIME_RATIO_A_MAP')


def test_existing_engine_rebalancer_no_regime_map():
    """기존 엔진의 Rebalancer에는 regime_ratio_a_map이 None이다."""
    from src.core.engine import QldSHVEngine
    broker, repo, logger = _make_base_deps()
    with patch('src.core.engine.IndicatorCalculator'), \
         patch('src.core.engine.RegimeAnalyzer'), \
         patch('src.core.engine.VolatilityTargeter'):
        engine = QldSHVEngine(broker=broker, repo=repo, logger=logger)
    assert engine.rebalancer._regime_ratio_a_map is None
