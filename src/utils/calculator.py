"""이전 import 경로 호환용 모듈.

도메인 계산 구현은 ``src.core.indicators``에 있다.
"""

from src.core.indicators import IndicatorCalculator, MOMENTUM_EMA_SPAN

__all__ = ["IndicatorCalculator", "MOMENTUM_EMA_SPAN"]
