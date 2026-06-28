# src/core/engine/__init__.py
"""트레이딩 엔진 패키지 파사드.

기존 `from src.core.engine import X` import 경로의 호환성을 유지하기 위해
모든 public 심볼을 이 모듈에서 re-export한다.

IMPORTANT: 아래 import 순서가 엔진 레지스트리 등록 순서를 결정한다.
원본 engine.py 파일에서의 클래스 정의 순서를 보존하기 위해
base → simple → regime 순서를 반드시 유지해야 한다.
"""
from src.core.engine.registry import (
    _ENGINE_REGISTRY,
    _ENGINE_COLORS,
    _ENGINE_MARKET_TYPES,
    _ENGINE_BACKTEST,
    register_engine,
)
from src.core.engine.base import TradingEngine, FullExposureEngine
from src.core.engine.simple import (
    QldSHVEngine,
    QldSdyEngine,
    QqqSdyEngine,
    SpyEngine,
    QqqEngine,
    Asset5Engine,
    DomesticAsset5Engine,
)
from src.core.engine.regime import QldSdyShvEngine, QldQqqShvRegimeEngine
from src.core.engine.dip_buy import DipBuyEngine, DipBuyGatedEngine, DipBuyGatedSpyEngine

__all__ = [
    "_ENGINE_REGISTRY",
    "_ENGINE_COLORS",
    "_ENGINE_MARKET_TYPES",
    "_ENGINE_BACKTEST",
    "register_engine",
    "TradingEngine",
    "FullExposureEngine",
    "QldSHVEngine",
    "QldSdyEngine",
    "QqqSdyEngine",
    "SpyEngine",
    "QqqEngine",
    "Asset5Engine",
    "DomesticAsset5Engine",
    "QldSdyShvEngine",
    "QldQqqShvRegimeEngine",
    "DipBuyEngine",
    "DipBuyGatedEngine",
    "DipBuyGatedSpyEngine",
]
