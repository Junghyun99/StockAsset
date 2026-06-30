from src.core.logic.volatility_targeter import VolatilityTargeter
from src.core.models import MarketRegime


def test_crash_exposure_default_zero():
    vt = VolatilityTargeter(target_vol=0.15)
    assert vt.calculate_exposure(MarketRegime.CRASH, 0.20) == 0.0   # 기존 동작 불변


def test_leverage_mode_range_1_to_2():
    vt = VolatilityTargeter(target_vol=0.30, min_exposure=1.0, max_exposure=2.0,
                            regime_max_exposures={}, crash_exposure=1.0)
    assert vt.calculate_exposure(MarketRegime.BULL, 0.15) == 2.0    # 0.30/0.15=2.0 (상한)
    assert vt.calculate_exposure(MarketRegime.BULL, 0.60) == 1.0    # 0.5 → 하한 1.0
    assert vt.calculate_exposure(MarketRegime.BULL, 0.30) == 1.0    # 1.0
    assert vt.calculate_exposure(MarketRegime.CRASH, 0.80) == 1.0   # CRASH도 1.0(현금화 아님)
    assert abs(vt.calculate_exposure(MarketRegime.BULL, 0.20) - 1.5) < 1e-9  # 0.30/0.20
