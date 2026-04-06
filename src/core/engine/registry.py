# src/core/engine/registry.py
from typing import Dict, List, Tuple

# 엔진 자동 등록 레지스트리
_ENGINE_REGISTRY: List[Tuple[str, type]] = []
_ENGINE_COLORS: Dict[str, str] = {}
_ENGINE_MARKET_TYPES: Dict[str, str] = {}


def register_engine(name: str = None, color: str = "#6c757d", market_type: str = "overseas"):
    """엔진 클래스를 레지스트리에 자동 등록하는 데코레이터.

    Args:
        name: 레지스트리에 등록할 이름. 기본값은 클래스명(__name__).
        color: 대시보드 차트 색상 (hex). 기본값은 회색(#6c757d).
        market_type: 시장 유형 ('overseas' 또는 'domestic'). 기본값은 'overseas'.
    """
    def decorator(cls):
        key = name or cls.__name__
        _ENGINE_REGISTRY.append((key, cls))
        _ENGINE_COLORS[key] = color
        _ENGINE_MARKET_TYPES[key] = market_type
        return cls
    return decorator
