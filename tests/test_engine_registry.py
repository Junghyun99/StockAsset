# tests/test_engine_registry.py
"""엔진 레지스트리 backtest 플래그 테스트."""
from src.core.engine.registry import (
    _ENGINE_REGISTRY, _ENGINE_BACKTEST, register_engine,
)
from src.core.engine import TradingEngine


def test_existing_engines_default_backtest_true():
    """명시적으로 backtest=False로 등록되지 않은 엔진들은 backtest=True여야 한다."""
    for name, _ in _ENGINE_REGISTRY:
        if _ENGINE_BACKTEST.get(name) is False:
            continue  # 의도적으로 백테스트 제외된 엔진
        assert _ENGINE_BACKTEST.get(name, True) is True, (
            f"{name}의 backtest 플래그가 True가 아님"
        )


def test_register_engine_backtest_false():
    """backtest=False로 등록한 엔진은 _ENGINE_BACKTEST에서 False여야 한다."""
    registry_before = len(_ENGINE_REGISTRY)

    @register_engine(name="_TestNoBacktest", backtest=False)
    class _TestNoBacktestEngine(TradingEngine):
        pass

    assert _ENGINE_BACKTEST["_TestNoBacktest"] is False

    # cleanup: 테스트용 엔진 제거
    _ENGINE_REGISTRY.pop()
    del _ENGINE_BACKTEST["_TestNoBacktest"]
    assert len(_ENGINE_REGISTRY) == registry_before


def test_register_engine_backtest_default_true():
    """backtest 파라미터 생략 시 기본값 True로 등록된다."""
    registry_before = len(_ENGINE_REGISTRY)

    @register_engine(name="_TestDefaultBacktest")
    class _TestDefaultBacktestEngine(TradingEngine):
        pass

    assert _ENGINE_BACKTEST["_TestDefaultBacktest"] is True

    # cleanup
    _ENGINE_REGISTRY.pop()
    del _ENGINE_BACKTEST["_TestDefaultBacktest"]
    assert len(_ENGINE_REGISTRY) == registry_before
