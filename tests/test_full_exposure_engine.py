# tests/test_full_exposure_engine.py
"""FullExposureEngine 단위 테스트.

TradingEngine의 서브클래스로, analyze_strategy()만 오버라이드하여
항상 exposure=1.0을 유지하는 전략을 검증한다.
"""
import math
import pytest
from unittest.mock import MagicMock, patch
from src.core.engine import FullExposureEngine
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution,
    Order, OrderAction, ExecutionStatus, DayResult
)


# ─────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────

def _make_market_data(nan_vol=False, vix=18.0, mdd=-0.08) -> MarketData:
    return MarketData(
        date="2024-01-10",
        spy_price=450.0,
        spy_ma180=420.0,
        spy_volatility=math.nan if nan_vol else 0.12,
        spy_momentum=0.05,
        spy_mdd=mdd,
        vix=vix,
    )


def _make_portfolio(cash=10000.0) -> Portfolio:
    return Portfolio(
        total_cash=cash,
        holdings={"SSO": 10},
        current_prices={"SSO": 100.0},
    )


def _make_engine(repo_last_reb=None, notifier=None):
    """FullExposureEngine Mock 조립."""
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

        engine = FullExposureEngine(
            asset_groups={'A': ['SSO', 'QLD'], 'B': ['IEF', 'GLD'], 'C': ['SHV']},
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
# analyze_strategy() 단위 테스트
# ─────────────────────────────────────────────────────────────────

def test_full_exposure_bull_returns_1():
    """BULL 국면에서 exposure=1.0 반환."""
    engine, mocks = _make_engine()
    md = _make_market_data()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL

    regime, exposure, nan_fields = engine.analyze_strategy(md)

    assert regime == MarketRegime.BULL
    assert exposure == 1.0
    assert nan_fields == []


def test_full_exposure_bear_strong_returns_1():
    """BEAR_STRONG 국면에서도 exposure=1.0 반환."""
    engine, mocks = _make_engine()
    md = _make_market_data()
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_STRONG

    regime, exposure, nan_fields = engine.analyze_strategy(md)

    assert regime == MarketRegime.BEAR_STRONG
    assert exposure == 1.0


def test_full_exposure_crash_returns_1():
    """CRASH 국면에서도 exposure=1.0 반환 (NaN 아닐 때)."""
    engine, mocks = _make_engine()
    md = _make_market_data(vix=35.0, mdd=-0.25)
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH

    regime, exposure, nan_fields = engine.analyze_strategy(md)

    assert regime == MarketRegime.CRASH
    assert exposure == 1.0


def test_full_exposure_nan_returns_zero():
    """NaN 데이터 시 안전장치로 exposure=0.0 반환."""
    engine, mocks = _make_engine()
    md = _make_market_data(nan_vol=True)

    regime, exposure, nan_fields = engine.analyze_strategy(md)

    assert regime == MarketRegime.CRASH
    assert exposure == 0.0
    assert "spy_volatility" in nan_fields
    # NaN일 때 analyzer.analyze()는 호출되지 않아야 함
    mocks["analyzer"].analyze.assert_not_called()


def test_full_exposure_does_not_call_targeter():
    """FullExposureEngine은 targeter를 호출하지 않는다."""
    engine, mocks = _make_engine()
    md = _make_market_data()
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL

    engine.analyze_strategy(md)

    mocks["targeter"].calculate_exposure.assert_not_called()


def test_full_exposure_logs_regime_change():
    """국면 변화 시 로그를 남긴다."""
    engine, mocks = _make_engine()
    mocks["analyzer"]._prev_regime = MarketRegime.BULL
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_WEAK
    md = _make_market_data()

    engine.analyze_strategy(md)

    # logger.info가 "Regime Change" 메시지로 호출됐는지 확인
    log_calls = [str(c) for c in mocks["logger"].info.call_args_list]
    assert any("Regime Change" in c for c in log_calls)


# ─────────────────────────────────────────────────────────────────
# End-to-end 사이클 테스트
# ─────────────────────────────────────────────────────────────────

def test_full_exposure_end_to_end_rebalancing():
    """전체 사이클: exposure=1.0이 rebalancer에 전달되는지 확인."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BEAR_WEAK
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    assert result.regime == MarketRegime.BEAR_WEAK
    # rebalancer에 exposure=1.0이 전달됐는지 확인
    call_args = mocks["rebalancer"].generate_signal.call_args
    assert call_args[0][1] == 1.0  # 두 번째 위치 인자 = exposure


def test_full_exposure_crash_end_to_end():
    """CRASH에서도 exposure=1.0으로 리밸런싱 실행."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data(vix=35.0, mdd=-0.25)

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Full Exposure")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 1.0
    assert result.is_rebalancing is True
    call_args = mocks["rebalancer"].generate_signal.call_args
    assert call_args[0][1] == 1.0


def test_full_exposure_nan_end_to_end():
    """NaN 시 전체 사이클: exposure=0.0, 매매 중단."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)

    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.exposure == 0.0
    assert result.is_rebalancing is False
    assert result.executions == []
    mocks["rebalancer"].generate_signal.assert_not_called()
