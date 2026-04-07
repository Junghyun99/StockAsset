from typing import Dict, Optional
from src.core.models import MarketRegime


class VolatilityTargeter:
    # 변동성이 이 값 이하일 경우 보정하여 0으로 나누기를 방지
    MIN_VOLATILITY_FLOOR = 0.001

    # 국면별 exposure 상한선 기본값
    DEFAULT_REGIME_MAX_EXPOSURES: Dict[MarketRegime, float] = {
        MarketRegime.BEAR_STRONG: 0.4,
        MarketRegime.BEAR_WEAK: 0.6,
    }

    # exposure 하한선 기본값
    DEFAULT_MIN_EXPOSURE = 0.2

    # exposure 상한선 기본값 (regime_max_exposures에 없는 국면에 적용)
    DEFAULT_MAX_EXPOSURE = 1.0

    def __init__(self, target_vol: float = 0.15,
                 min_exposure: float = DEFAULT_MIN_EXPOSURE,
                 regime_max_exposures: Optional[Dict[MarketRegime, float]] = None,
                 max_exposure: float = DEFAULT_MAX_EXPOSURE):
        self.target_vol = target_vol
        self.min_exposure = min_exposure
        self._regime_max_exposures = dict(regime_max_exposures) if regime_max_exposures is not None else dict(self.DEFAULT_REGIME_MAX_EXPOSURES)
        self.max_exposure = max_exposure

    def calculate_exposure(self, regime: MarketRegime, current_vol: float) -> float:
        if regime == MarketRegime.CRASH:
            return 0.0

        # 0으로 나누기 방지: 극소 변동성을 최솟값으로 보정
        vol = current_vol if current_vol > self.MIN_VOLATILITY_FLOOR else self.MIN_VOLATILITY_FLOOR

        # 기본 비율 (Target Vol / Current Vol)
        base_ratio = self.target_vol / vol

        # 국면별 exposure 상한선
        upper = self._regime_max_exposures.get(regime, self.max_exposure)

        # 상한선·하한선 적용
        exposure = min(base_ratio, upper)
        return max(exposure, self.min_exposure)
