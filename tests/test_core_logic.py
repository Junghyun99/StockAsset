# tests/test_core_logic.py
import pytest
from unittest.mock import MagicMock
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.core.models import MarketRegime, Order, OrderAction

# ==========================================
# 1. RegimeAnalyzer 테스트 (국면 판단의 정교함)
# ==========================================

def test_regime_crash_conditions(create_market_data):
    # Case 1: VIX ≥ 30 AND MDD ≤ -10% → CRASH (복합 조건)
    analyzer1 = RegimeAnalyzer()
    data_vix = create_market_data(vix=30.1, mdd=-0.11)
    assert analyzer1.analyze(data_vix) == MarketRegime.CRASH

    # Case 1b: VIX ≥ 30이지만 MDD -3% (미미한 하락) → CRASH 아님 (이슈 #192 수정)
    analyzer1b = RegimeAnalyzer()
    data_vix_spike_only = create_market_data(vix=35.0, mdd=-0.03)
    assert analyzer1b.analyze(data_vix_spike_only) != MarketRegime.CRASH

    # Case 2: MDD ≤ -20% → CRASH (VIX 무관)
    analyzer2 = RegimeAnalyzer()
    data_mdd = create_market_data(mdd=-0.21)
    assert analyzer2.analyze(data_mdd) == MarketRegime.CRASH

    # Case 3: 둘 다 정상이면 CRASH 아님 (이전 상태가 CRASH가 아닌 경우)
    analyzer3 = RegimeAnalyzer()
    data_normal = create_market_data(vix=29.9, mdd=-0.19)
    assert analyzer3.analyze(data_normal) != MarketRegime.CRASH

def test_regime_crash_hysteresis_stays_in_crash(create_market_data):
    """
    [히스테리시스] CRASH 진입 후, 진입 조건은 해소되었지만 탈출 조건 미충족 시
    CRASH를 유지해야 한다 (휩쏘 방지).
    진입: VIX≥30 OR MDD≤-20%, 탈출: VIX<25 AND MDD>-15%
    """
    analyzer = RegimeAnalyzer()

    # Step 1: CRASH 진입 (VIX=35)
    data_crash = create_market_data(vix=35, mdd=-0.10)
    assert analyzer.analyze(data_crash) == MarketRegime.CRASH

    # Step 2: VIX가 28로 하락 → 진입 조건 미충족이지만 탈출 조건도 미충족 (28 ≥ 25)
    data_hysteresis = create_market_data(vix=28, mdd=-0.10)
    assert analyzer.analyze(data_hysteresis) == MarketRegime.CRASH  # 히스테리시스로 CRASH 유지

    # Step 3: VIX가 26으로 추가 하락 → 여전히 탈출 조건 미충족 (26 ≥ 25)
    data_still_zone = create_market_data(vix=26, mdd=-0.10)
    assert analyzer.analyze(data_still_zone) == MarketRegime.CRASH


def test_regime_crash_hysteresis_exits_crash(create_market_data):
    """
    [히스테리시스] CRASH 진입 후, 탈출 조건 충족 시 (VIX<25 AND MDD>-15%)
    정상 국면으로 복귀해야 한다.
    """
    analyzer = RegimeAnalyzer()

    # Step 1: CRASH 진입
    data_crash = create_market_data(vix=35, mdd=-0.25)
    assert analyzer.analyze(data_crash) == MarketRegime.CRASH

    # Step 2: 탈출 조건 충족 (VIX=20 < 25, MDD=-0.05 > -15%)
    data_exit = create_market_data(vix=20, mdd=-0.05, price=110, ma=100, mom=0.06)
    result = analyzer.analyze(data_exit)
    assert result != MarketRegime.CRASH
    assert result == MarketRegime.BULL  # price>MA, momentum≥0.05


def test_regime_crash_hysteresis_partial_exit_fails(create_market_data):
    """
    [히스테리시스] 탈출 조건 중 하나만 충족하면 CRASH에서 빠져나올 수 없다.
    VIX<25이지만 MDD≤-15%, 또는 MDD>-15%이지만 VIX≥25.
    """
    analyzer = RegimeAnalyzer()

    # CRASH 진입
    data_crash = create_market_data(vix=32, mdd=-0.22)
    assert analyzer.analyze(data_crash) == MarketRegime.CRASH

    # Case 1: VIX 충족, MDD 미충족 → CRASH 유지
    data_vix_ok = create_market_data(vix=20, mdd=-0.16)
    assert analyzer.analyze(data_vix_ok) == MarketRegime.CRASH

    # Case 2: MDD 충족, VIX 미충족 → CRASH 유지
    data_mdd_ok = create_market_data(vix=27, mdd=-0.05)
    assert analyzer.analyze(data_mdd_ok) == MarketRegime.CRASH


def test_regime_crash_hysteresis_reentry(create_market_data):
    """
    [히스테리시스] CRASH 탈출 후 MDD≤-20% 극단적 하락 시 쿨다운 무시하고 즉시 재진입해야 한다.
    """
    analyzer = RegimeAnalyzer()

    # CRASH 진입 (VIX=35, MDD=-0.12 → 복합 조건 충족)
    assert analyzer.analyze(create_market_data(vix=35, mdd=-0.12)) == MarketRegime.CRASH

    # CRASH 탈출 (VIX=20, MDD=-0.05)
    data_exit = create_market_data(vix=20, mdd=-0.05, price=110, ma=100, mom=0.06)
    assert analyzer.analyze(data_exit) != MarketRegime.CRASH

    # 극단적 하락 (MDD≤-20%) → 쿨다운 중에도 즉시 CRASH 재진입
    assert analyzer.analyze(create_market_data(vix=31, mdd=-0.21)) == MarketRegime.CRASH


def test_regime_crash_cooldown_blocks_vix_reentry(create_market_data):
    """
    [쿨다운] CRASH 탈출 후 쿨다운 기간(기본 10일) 동안 VIX/MDD 복합 조건에 의한
    재진입이 차단되어야 한다.
    """
    analyzer = RegimeAnalyzer(crash_cooldown_days=3)

    # CRASH 진입 (VIX=35, MDD=-0.12)
    assert analyzer.analyze(create_market_data(vix=35, mdd=-0.12)) == MarketRegime.CRASH

    # CRASH 탈출 (VIX=20, MDD=-0.05) → 쿨다운 3일 시작
    data_exit = create_market_data(vix=20, mdd=-0.05, price=110, ma=100, mom=0.06)
    assert analyzer.analyze(data_exit) != MarketRegime.CRASH

    # 쿨다운 중 VIX/MDD 복합 조건 (VIX=31, MDD=-0.11) → 차단되어야 함 (day 1/3)
    assert analyzer.analyze(create_market_data(vix=31, mdd=-0.11)) != MarketRegime.CRASH

    # 쿨다운 중 (day 2/3)
    assert analyzer.analyze(create_market_data(vix=31, mdd=-0.11)) != MarketRegime.CRASH

    # 쿨다운 만료 (day 3/3)
    assert analyzer.analyze(create_market_data(vix=31, mdd=-0.11)) != MarketRegime.CRASH

    # 쿨다운 종료 후 → CRASH 재진입 허용
    assert analyzer.analyze(create_market_data(vix=31, mdd=-0.11)) == MarketRegime.CRASH


def test_regime_crash_cooldown_allows_extreme_mdd(create_market_data):
    """
    [쿨다운] 쿨다운 기간 중에도 MDD≤-20% 극단적 하락 시 즉시 CRASH 진입해야 한다.
    """
    analyzer = RegimeAnalyzer(crash_cooldown_days=10)

    # CRASH 진입 후 탈출
    assert analyzer.analyze(create_market_data(vix=35, mdd=-0.12)) == MarketRegime.CRASH
    data_exit = create_market_data(vix=20, mdd=-0.05, price=110, ma=100, mom=0.06)
    assert analyzer.analyze(data_exit) != MarketRegime.CRASH

    # 쿨다운 중 MDD=-25% → 즉시 CRASH 재진입 허용
    assert analyzer.analyze(create_market_data(vix=25, mdd=-0.25)) == MarketRegime.CRASH


def test_regime_crash_cooldown_zero_disables_cooldown(create_market_data):
    """
    [쿨다운] crash_cooldown_days=0 시 쿨다운 없이 기존 동작과 동일해야 한다.
    """
    analyzer = RegimeAnalyzer(crash_cooldown_days=0)

    # CRASH 진입
    assert analyzer.analyze(create_market_data(vix=35, mdd=-0.12)) == MarketRegime.CRASH

    # CRASH 탈출
    data_exit = create_market_data(vix=20, mdd=-0.05, price=110, ma=100, mom=0.06)
    assert analyzer.analyze(data_exit) != MarketRegime.CRASH

    # 탈출 직후 VIX/MDD 복합 조건 충족 → 즉시 재진입 허용 (쿨다운 없음)
    assert analyzer.analyze(create_market_data(vix=31, mdd=-0.11)) == MarketRegime.CRASH


def test_regime_crash_hysteresis_custom_thresholds(create_market_data):
    """
    [히스테리시스] crash_exit_vix, crash_exit_mdd 커스텀 값이 적용되는지 확인.
    """
    # 탈출 조건을 더 느슨하게 설정: VIX<28, MDD>-18%
    analyzer = RegimeAnalyzer(crash_exit_vix=28.0, crash_exit_mdd=-0.18)

    # CRASH 진입 (VIX=32, MDD=-0.11 → 복합 조건 충족)
    assert analyzer.analyze(create_market_data(vix=32, mdd=-0.11)) == MarketRegime.CRASH

    # VIX=27 < 28 AND MDD=-0.10 > -18% → 탈출 성공
    data_exit = create_market_data(vix=27, mdd=-0.10, price=110, ma=100, mom=0.06)
    assert analyzer.analyze(data_exit) != MarketRegime.CRASH


def test_regime_crash_no_hysteresis_without_prior_crash(create_market_data):
    """
    [히스테리시스] 이전 상태가 CRASH가 아니면 히스테리시스 구간에서도
    정상 국면으로 판정해야 한다 (히스테리시스는 CRASH 탈출에만 적용).
    """
    analyzer = RegimeAnalyzer()

    # 처음부터 히스테리시스 구간 데이터 (VIX=28, CRASH 진입 조건 미충족)
    data = create_market_data(vix=28, mdd=-0.10, price=110, ma=100, mom=0.06)
    assert analyzer.analyze(data) != MarketRegime.CRASH  # CRASH 이력 없으므로 정상 판정


def test_regime_crash_default_hysteresis_thresholds():
    """히스테리시스 기본값이 올바르게 설정되는지 확인."""
    analyzer = RegimeAnalyzer()
    assert analyzer.crash_exit_vix == 25.0
    assert analyzer.crash_exit_mdd == -0.15


def test_regime_bear_classifications(create_market_data):
    # Case 1: Bear Strong (가격 < MA 그리고 모멘텀 < 0)
    analyzer1 = RegimeAnalyzer()
    data_strong = create_market_data(price=90, ma=100, mom=-0.01)
    assert analyzer1.analyze(data_strong) == MarketRegime.BEAR_STRONG

    # Case 2: Bear Weak (가격 < MA 이지만 모멘텀 > 0) — 이전 국면 없음, 진입 판정
    analyzer2 = RegimeAnalyzer()
    data_weak_1 = create_market_data(price=90, ma=100, mom=0.01)
    assert analyzer2.analyze(data_weak_1) == MarketRegime.BEAR_WEAK

    # Case 3: Bear Weak (가격 > MA 이지만 모멘텀 < 0) — 이전 국면 없음, 진입 판정
    analyzer3 = RegimeAnalyzer()
    data_weak_2 = create_market_data(price=110, ma=100, mom=-0.01)
    assert analyzer3.analyze(data_weak_2) == MarketRegime.BEAR_WEAK

def test_regime_bear_strong_hysteresis_stays_in_bear_strong(create_market_data):
    """
    [이슈 #191] Bear_Strong↔Bear_Weak 히스테리시스:
    BEAR_STRONG 진입 후 momentum이 0을 막 넘어도 출구 임계치(0.01) 이하이면
    BEAR_STRONG을 유지해야 한다 (휩쏘 방지).
    진입: momentum < 0 AND price < MA180
    탈출: momentum > 0.01 AND price > MA180 * 1.01
    """
    analyzer = RegimeAnalyzer()

    # Step 1: BEAR_STRONG 진입 (momentum=-0.0022, price < MA)
    data_strong = create_market_data(price=90, ma=100, mom=-0.0022)
    assert analyzer.analyze(data_strong) == MarketRegime.BEAR_STRONG

    # Step 2: momentum이 +0.003으로 반전했지만 출구 임계치(0.01) 미달 → BEAR_STRONG 유지
    data_boundary = create_market_data(price=90, ma=100, mom=0.003)
    assert analyzer.analyze(data_boundary) == MarketRegime.BEAR_STRONG

    # Step 3: momentum=0.009 (여전히 임계치 미달) → BEAR_STRONG 유지
    data_below_threshold = create_market_data(price=90, ma=100, mom=0.009)
    assert analyzer.analyze(data_below_threshold) == MarketRegime.BEAR_STRONG


def test_regime_bear_strong_hysteresis_exits_when_clear(create_market_data):
    """
    [이슈 #191] BEAR_STRONG에서 momentum과 price가 모두 출구 조건을 명확히 충족하면
    탈출해야 한다.
    탈출 조건: momentum > 0.01 AND price > MA180 * 1.01
    """
    analyzer = RegimeAnalyzer()

    # Step 1: BEAR_STRONG 진입
    data_strong = create_market_data(price=90, ma=100, mom=-0.02)
    assert analyzer.analyze(data_strong) == MarketRegime.BEAR_STRONG

    # Step 2: 출구 조건 충족 (momentum=0.02 > 0.01, price=103 > 100*1.01=101)
    # → BEAR_STRONG 탈출, 두 조건 모두 양수이므로 SIDEWAYS 또는 BULL
    data_clear = create_market_data(price=103, ma=100, mom=0.02)
    result = analyzer.analyze(data_clear)
    assert result in (MarketRegime.SIDEWAYS, MarketRegime.BULL)


def test_regime_bear_strong_hysteresis_ma_buffer(create_market_data):
    """
    [이슈 #191] price가 MA180 근처에서 진동할 때:
    momentum은 임계치 초과지만 price가 MA*1.01 미달이면 BEAR_STRONG 유지.
    """
    analyzer = RegimeAnalyzer()

    # Step 1: BEAR_STRONG 진입 (price < MA)
    data_strong = create_market_data(price=98, ma=100, mom=-0.01)
    assert analyzer.analyze(data_strong) == MarketRegime.BEAR_STRONG

    # Step 2: momentum > 0.01 충족, 하지만 price=100.5 < MA*1.01=101 → BEAR_STRONG 유지
    data_ma_border = create_market_data(price=100.5, ma=100, mom=0.015)
    assert analyzer.analyze(data_ma_border) == MarketRegime.BEAR_STRONG

    # Step 3: 이번엔 price=102 > MA*1.01=101 AND momentum=0.015 > 0.01 → 탈출
    data_clear_ma = create_market_data(price=102, ma=100, mom=0.015)
    result = analyzer.analyze(data_clear_ma)
    assert result in (MarketRegime.SIDEWAYS, MarketRegime.BULL)


def test_regime_bear_strong_custom_exit_thresholds(create_market_data):
    """
    [이슈 #191] bear_strong_exit_momentum_threshold와 bear_strong_exit_ma_buffer를
    커스텀 값으로 주입하면 해당 임계치가 적용되어야 한다.
    """
    # 더 엄격한 출구 조건 (momentum > 0.02 AND price > MA * 1.02)
    analyzer = RegimeAnalyzer(
        bear_strong_exit_momentum_threshold=0.02,
        bear_strong_exit_ma_buffer=0.02,
    )

    # Step 1: BEAR_STRONG 진입
    data_strong = create_market_data(price=90, ma=100, mom=-0.01)
    assert analyzer.analyze(data_strong) == MarketRegime.BEAR_STRONG

    # Step 2: momentum=0.015 > 기본 0.01이지만 커스텀 0.02 미달 → BEAR_STRONG 유지
    data_below_custom = create_market_data(price=103, ma=100, mom=0.015)
    assert analyzer.analyze(data_below_custom) == MarketRegime.BEAR_STRONG

    # Step 3: momentum=0.025 > 0.02 AND price=103 > 100*1.02=102 → 탈출
    data_above_custom = create_market_data(price=103, ma=100, mom=0.025)
    result = analyzer.analyze(data_above_custom)
    assert result in (MarketRegime.SIDEWAYS, MarketRegime.BULL)


def test_regime_bear_strong_default_exit_thresholds():
    """
    [이슈 #191] 기본 Bear_Strong 탈출 임계치가 올바르게 설정되어 있는지 확인.
    """
    analyzer = RegimeAnalyzer()
    assert analyzer.bear_strong_exit_momentum_threshold == 0.01
    assert analyzer.bear_strong_exit_ma_buffer == 0.01
    assert analyzer.bear_strong_exit_momentum_threshold == RegimeAnalyzer.DEFAULT_BEAR_STRONG_EXIT_MOMENTUM_THRESHOLD
    assert analyzer.bear_strong_exit_ma_buffer == RegimeAnalyzer.DEFAULT_BEAR_STRONG_EXIT_MA_BUFFER


def test_regime_bear_strong_hysteresis_whipsaw_scenario(create_market_data):
    """
    [이슈 #191] 실제 2023년 3월 휩쏘 시나리오 재현:
    momentum이 -0.03 ~ 0.003 사이에서 진동할 때 BEAR_STRONG이 유지되어야 한다.
    히스테리시스 없으면 6번 전환, 히스테리시스 적용 후 BEAR_STRONG 유지.
    """
    analyzer = RegimeAnalyzer()

    # BEAR_STRONG 진입
    assert analyzer.analyze(create_market_data(price=90, ma=100, mom=-0.0344)) == MarketRegime.BEAR_STRONG
    # 이슈 데이터: momentum이 -0.03 ~ +0.003 사이에서 진동
    assert analyzer.analyze(create_market_data(price=103, ma=100, mom=-0.0303)) == MarketRegime.BEAR_STRONG
    assert analyzer.analyze(create_market_data(price=90, ma=100, mom=-0.0466)) == MarketRegime.BEAR_STRONG
    assert analyzer.analyze(create_market_data(price=103, ma=100, mom=-0.0278)) == MarketRegime.BEAR_STRONG
    assert analyzer.analyze(create_market_data(price=90, ma=100, mom=-0.0206)) == MarketRegime.BEAR_STRONG
    # momentum=-0.0096, price가 MA 위 → 이전엔 Bear_Weak로 전환됐지만 이제 BEAR_STRONG 유지
    assert analyzer.analyze(create_market_data(price=103, ma=100, mom=-0.0096)) == MarketRegime.BEAR_STRONG


def test_regime_bull_vs_sideways(create_market_data):
    analyzer = RegimeAnalyzer()
    
    # Case 1: Sideways (0 < 모멘텀 < 0.05)
    data_side = create_market_data(price=110, ma=100, mom=0.04)
    assert analyzer.analyze(data_side) == MarketRegime.SIDEWAYS
    
    # Case 2: Bull (모멘텀 >= 0.05)
    data_bull = create_market_data(price=110, ma=100, mom=0.05)
    assert analyzer.analyze(data_bull) == MarketRegime.BULL

    # Case 3: Sideways (모멘텀 == 0, 가격 > MA → 중립이므로 SIDEWAYS)
    data_zero_mom = create_market_data(price=110, ma=100, mom=0.0)
    assert analyzer.analyze(data_zero_mom) == MarketRegime.SIDEWAYS


def test_regime_custom_bull_threshold(create_market_data):
    """
    [커스텀 BULL 임계치 테스트]
    bull_momentum_threshold를 외부에서 주입하면 해당 임계치가 적용되어야 한다.
    기본 임계치 0.05에서는 BULL인 모멘텀 0.08이,
    커스텀 임계치 0.10에서는 SIDEWAYS가 되어야 한다.
    """
    # Case 1: 기본 임계치 (0.05) → 모멘텀 0.08은 BULL
    analyzer_default = RegimeAnalyzer()
    data = create_market_data(price=110, ma=100, mom=0.08)
    assert analyzer_default.analyze(data) == MarketRegime.BULL

    # Case 2: 커스텀 임계치 (0.10) → 모멘텀 0.08은 SIDEWAYS
    analyzer_custom = RegimeAnalyzer(bull_momentum_threshold=0.10)
    assert analyzer_custom.analyze(data) == MarketRegime.SIDEWAYS

    # Case 3: 커스텀 임계치 (0.10) → 모멘텀 0.10은 BULL (경계값)
    data_boundary = create_market_data(price=110, ma=100, mom=0.10)
    assert analyzer_custom.analyze(data_boundary) == MarketRegime.BULL


def test_regime_default_bull_threshold_unchanged():
    """
    [기본 BULL 임계치 유지 테스트]
    bull_momentum_threshold를 지정하지 않으면 기본값 0.05가 적용되어야 한다.
    """
    analyzer = RegimeAnalyzer()
    assert analyzer.bull_momentum_threshold == 0.05
    assert analyzer.bull_momentum_threshold == RegimeAnalyzer.DEFAULT_BULL_MOMENTUM_THRESHOLD


def test_regime_bull_sideways_hysteresis_stays_in_bull(create_market_data):
    """
    [이슈 #190] Bull↔Sideways 히스테리시스: BULL 진입 후 momentum이 진입 임계치(0.05) 아래로
    내려가도 출구 임계치(0.03) 이상이면 BULL을 유지해야 한다 (휩쏘 방지).
    진입: momentum ≥ 0.05, 탈출: momentum < 0.03
    """
    analyzer = RegimeAnalyzer()

    # Step 1: BULL 진입 (momentum=0.06 ≥ 0.05)
    data_bull = create_market_data(price=110, ma=100, mom=0.06)
    assert analyzer.analyze(data_bull) == MarketRegime.BULL

    # Step 2: momentum이 0.04로 하락 → 진입 임계치 미충족이지만 출구 임계치(0.03) 이상 → BULL 유지
    data_boundary = create_market_data(price=110, ma=100, mom=0.04)
    assert analyzer.analyze(data_boundary) == MarketRegime.BULL  # 히스테리시스로 BULL 유지

    # Step 3: momentum이 0.035로 추가 하락 → 여전히 출구 임계치(0.03) 이상 → BULL 유지
    data_still_bull = create_market_data(price=110, ma=100, mom=0.035)
    assert analyzer.analyze(data_still_bull) == MarketRegime.BULL


def test_regime_bull_sideways_hysteresis_exits_bull(create_market_data):
    """
    [이슈 #190] Bull↔Sideways 히스테리시스: BULL 진입 후 momentum이 출구 임계치(0.03) 미만으로
    내려가면 SIDEWAYS로 전환되어야 한다.
    """
    analyzer = RegimeAnalyzer()

    # Step 1: BULL 진입
    data_bull = create_market_data(price=110, ma=100, mom=0.06)
    assert analyzer.analyze(data_bull) == MarketRegime.BULL

    # Step 2: momentum이 0.02로 하락 → 출구 임계치(0.03) 미만 → SIDEWAYS 전환
    data_exit = create_market_data(price=110, ma=100, mom=0.02)
    assert analyzer.analyze(data_exit) == MarketRegime.SIDEWAYS


def test_regime_bull_exit_threshold_not_applied_without_prior_bull(create_market_data):
    """
    [이슈 #190] 이전 국면이 BULL이 아닌 경우, 진입 임계치(0.05)가 적용되어야 한다.
    SIDEWAYS에서 momentum=0.04는 BULL로 진입할 수 없다.
    """
    analyzer = RegimeAnalyzer()

    # Step 1: SIDEWAYS 진입 (momentum=0.04 < 0.05)
    data_side = create_market_data(price=110, ma=100, mom=0.04)
    assert analyzer.analyze(data_side) == MarketRegime.SIDEWAYS

    # Step 2: 이전 국면이 SIDEWAYS이므로 진입 임계치 적용 → momentum=0.04는 여전히 SIDEWAYS
    data_still_side = create_market_data(price=110, ma=100, mom=0.04)
    assert analyzer.analyze(data_still_side) == MarketRegime.SIDEWAYS


# ==========================================
# 2. VolatilityTargeter 테스트 (비중 계산의 한계점)
# ==========================================

def test_vol_targeter_caps_and_floors():
    targeter = VolatilityTargeter(target_vol=0.15)
    
    # Case 1: Crash -> Exposure 0
    assert targeter.calculate_exposure(MarketRegime.CRASH, 0.1) == 0.0
    
    # Case 2: Bear Strong Cap (Max 0.4)
    # 계산값: 0.15 / 0.10 = 1.5배 -> 0.4로 제한
    assert targeter.calculate_exposure(MarketRegime.BEAR_STRONG, 0.10) == 0.4
    
    # Case 3: Bear Weak Cap (Max 0.6)
    # 계산값: 0.15 / 0.10 = 1.5배 -> 0.6으로 제한
    assert targeter.calculate_exposure(MarketRegime.BEAR_WEAK, 0.10) == 0.6
    
    # Case 4: Min Floor (Min 0.2)
    # 계산값: 0.15 / 1.0 (변동성 100%) = 0.15배 -> 0.2로 보정
    assert targeter.calculate_exposure(MarketRegime.BULL, 1.0) == 0.2

def test_vol_targeter_zero_division():
    targeter = VolatilityTargeter()
    # 변동성이 0이어도 에러 없이 1.0(Cap)이나 적절한 값이 나와야 함
    # 로직 내부에서 MIN_VOLATILITY_FLOOR로 보정하므로: 0.15 / 0.001 = 150 -> Cap 1.0
    assert targeter.calculate_exposure(MarketRegime.BULL, 0.0) == 1.0

def test_vol_targeter_min_volatility_floor_boundary():
    """MIN_VOLATILITY_FLOOR 경계값 테스트"""
    targeter = VolatilityTargeter(target_vol=0.15)
    floor = VolatilityTargeter.MIN_VOLATILITY_FLOOR

    # Case 1: 정확히 MIN_VOLATILITY_FLOOR → 보정 적용 (조건: > floor이 아님)
    # vol = 0.001이므로 base_ratio = 0.15 / 0.001 = 150 → Cap 1.0
    assert targeter.calculate_exposure(MarketRegime.BULL, floor) == 1.0

    # Case 2: MIN_VOLATILITY_FLOOR보다 약간 큰 값 → 보정 없이 원래 값 사용
    slightly_above = floor + 1e-6
    result = targeter.calculate_exposure(MarketRegime.BULL, slightly_above)
    expected = min(0.15 / slightly_above, 1.0)
    expected = max(expected, 0.2)
    assert abs(result - expected) < 1e-9

    # Case 3: 음수 변동성 → MIN_VOLATILITY_FLOOR로 보정
    assert targeter.calculate_exposure(MarketRegime.BULL, -0.05) == 1.0

    # Case 4: 상수 값이 0.001인지 확인
    assert VolatilityTargeter.MIN_VOLATILITY_FLOOR == 0.001


def test_vol_targeter_custom_regime_max_exposures():
    """
    [커스텀 국면별 exposure 상한선 테스트]
    regime_max_exposures를 외부에서 주입하면 해당 상한선이 적용되어야 한다.
    """
    custom_max_exposures = {
        MarketRegime.BEAR_STRONG: 0.3,
        MarketRegime.BEAR_WEAK: 0.5,
    }
    targeter = VolatilityTargeter(target_vol=0.15, regime_max_exposures=custom_max_exposures)

    # BEAR_STRONG: 0.15/0.10 = 1.5 → 상한 0.3
    assert targeter.calculate_exposure(MarketRegime.BEAR_STRONG, 0.10) == 0.3

    # BEAR_WEAK: 0.15/0.10 = 1.5 → 상한 0.5
    assert targeter.calculate_exposure(MarketRegime.BEAR_WEAK, 0.10) == 0.5


def test_vol_targeter_custom_min_exposure():
    """
    [커스텀 exposure 하한선 테스트]
    min_exposure를 외부에서 주입하면 해당 하한선이 적용되어야 한다.
    """
    targeter = VolatilityTargeter(target_vol=0.15, min_exposure=0.1)

    # 변동성 100% → 0.15/1.0 = 0.15 → 기본 min 0.2면 0.2인데, 커스텀 0.1이므로 0.15
    assert targeter.calculate_exposure(MarketRegime.BULL, 1.0) == 0.15

    # 변동성 200% → 0.15/2.0 = 0.075 → min 0.1 적용
    assert targeter.calculate_exposure(MarketRegime.BULL, 2.0) == 0.1


def test_vol_targeter_custom_max_exposure():
    """
    [커스텀 exposure 상한선 테스트]
    max_exposure를 변경하면 regime_max_exposures에 없는 국면에 해당 값이 적용되어야 한다.
    """
    targeter = VolatilityTargeter(target_vol=0.15, max_exposure=0.8)

    # BULL: 0.15/0.01 = 15.0 → 기본 상한 1.0이 아닌 0.8로 제한
    assert targeter.calculate_exposure(MarketRegime.BULL, 0.01) == 0.8


def test_vol_targeter_default_values_unchanged():
    """
    [기본값 유지 테스트]
    파라미터를 지정하지 않으면 기존 기본값이 그대로 적용되어야 한다.
    """
    targeter = VolatilityTargeter()

    # 기본 min_exposure (하한선)
    assert targeter.min_exposure == 0.2
    assert targeter.min_exposure == VolatilityTargeter.DEFAULT_MIN_EXPOSURE

    # 기본 max_exposure (상한선)
    assert targeter.max_exposure == 1.0
    assert targeter.max_exposure == VolatilityTargeter.DEFAULT_MAX_EXPOSURE

    # 기본 regime_max_exposures (국면별 상한선)
    assert targeter._regime_max_exposures == VolatilityTargeter.DEFAULT_REGIME_MAX_EXPOSURES

    # 인스턴스의 regime_max_exposures 수정이 클래스 상수에 영향을 주지 않는지 확인
    targeter._regime_max_exposures[MarketRegime.BEAR_STRONG] = 0.99
    assert VolatilityTargeter.DEFAULT_REGIME_MAX_EXPOSURES[MarketRegime.BEAR_STRONG] == 0.4


# ==========================================
# 3. Rebalancer 테스트 (리밸런싱 조건과 주문)
# ==========================================

def test_rebalancer_threshold_logic(create_portfolio):
    # A그룹: SPY, B그룹: IEF
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: 총자산 100만, SPY 55만(55%), IEF 45만(45%) -> 차이 10%
    pf = create_portfolio(
        holdings={'SPY': 550, 'IEF': 450}, 
        prices={'SPY': 1000, 'IEF': 1000}
    )
    # 총액 1,000,000. Ratio A=0.55, Ratio B=0.45. 상대이탈 = 0.05/0.5 = 10%

    # Case 1: 횡보장 (Threshold 0.025) -> 상대이탈 10%이므로 리밸런싱 해야 함
    signal_side = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)
    assert signal_side.has_orders is True
    assert "비율 재조정" in signal_side.reason

    # Case 2: 하락장 (Threshold 0.05) -> 상대이탈 10% > 5% → 리밸런싱 발생
    signal_bear = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BEAR_WEAK)
    assert signal_bear.has_orders is True
    assert "비율 재조정" in signal_bear.reason

def test_rebalancer_crash_sells_all_risky_assets(create_portfolio):
    """
    [CRASH 시나리오]
    폭락장(MDD/VIX 위험) 감지 시 exposure=0.0 → A/B 전량 매도, C(SHV) 매수.
    Rebalancer는 CRASH도 일반 리밸런싱으로 처리한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF'], 'C': ['SHV']}
    rebalancer = Rebalancer(groups)

    # 상황: 주식을 들고 있는 상태
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100, 'IEF': 100, 'SHV': 100}
    )

    # CRASH 발생 → exposure=0.0 → A/B 전량 매도 주문 생성
    signal = rebalancer.generate_signal(pf, target_exposure=0.0, regime=MarketRegime.CRASH)

    # 기대 결과: A/B 매도 주문이 생성되어야 함
    assert signal.has_orders is True
    sell_orders = [o for o in signal.orders if o.action == OrderAction.SELL]
    assert len(sell_orders) >= 2  # SPY, IEF 매도

    spy_sell = next(o for o in sell_orders if o.ticker == 'SPY')
    ief_sell = next(o for o in sell_orders if o.ticker == 'IEF')
    assert spy_sell.quantity == 10  # 전량 매도
    assert ief_sell.quantity == 10  # 전량 매도

def test_rebalancer_exposure_reduction(create_portfolio):
    """투자비중을 1.0 -> 0.5로 줄일 때 현금 확보 확인"""
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 현재: SPY 500만원, IEF 500만원 (총 1000만원, 풀매수 상태)
    pf = create_portfolio(holdings={'SPY': 50, 'IEF': 50}, prices={'SPY': 100000, 'IEF': 100000})
    
    # 목표: 비중 0.5 (500만원만 투자하고, 500만원은 현금화)
    signal = rebalancer.generate_signal(pf, target_exposure=0.5, regime=MarketRegime.BULL)
    
    assert signal.has_orders is True
    
    # 목표 금액: A 250만, B 250만. (현재 각 500만)
    # 따라서 각각 절반씩 매도해야 함 (각 25주 매도)
    spy_order = next(o for o in signal.orders if o.ticker == 'SPY')
    ief_order = next(o for o in signal.orders if o.ticker == 'IEF')
    
    assert spy_order.action == OrderAction.SELL
    assert spy_order.quantity == 25
    assert ief_order.action == OrderAction.SELL
    assert ief_order.quantity == 25


 # ==========================================
# 4. 현실 운영 시나리오 (Operational Edge Cases)
# ==========================================

def test_rebalancer_idempotency(create_portfolio):
    """
    [멱등성 테스트]
    이미 목표 비중을 완벽하게 맞춘 상태에서 봇이 다시 실행되면?
    -> 주문이 0개여야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: 총자산 200만, 목표비중 1.0 (풀매수)
    # 현재: SPY 100만(50%), IEF 100만(50%) -> 이미 완벽함
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10}, 
        prices={'SPY': 100000, 'IEF': 100000}
    )
    
    # 횡보장 가정 (비중 1.0 유지)
    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)
    
    # 리밸런싱 불필요 판단
    assert signal.has_orders is False
    # 주문이 하나도 없어야 함
    assert len(signal.orders) == 0
    assert "추가 주문 없음" in signal.reason

def test_rebalancer_cash_injection(create_portfolio):
    """
    [추가 입금 테스트]
    A:B 비율은 완벽하지만(리밸런싱 불필요), 현금이 많이 들어온 경우?
    -> 비율을 유지한 채로 '매수' 주문이 나가야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: 원래 SPY 100만, IEF 100만 있었음 (1:1).
    # 그런데 현금 200만을 추가 입금함. (총자산 400만)
    pf = create_portfolio(
        cash=2000000, 
        holdings={'SPY': 10, 'IEF': 10}, 
        prices={'SPY': 100000, 'IEF': 100000}
    )
    
    # 목표: 투자비중 1.0 (400만원 모두 투자 원함)
    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)
    
    # 비율(50:50) 자체는 틀어지지 않았으므로 리밸런싱 불필요.
    # 하지만 'Exposure'를 맞추기 위해 주문은 생성되어야 함.
    assert "exposure 조정" in signal.reason

    # 로직 검증:
    # Target A = 400만 * 1.0 * 0.5 = 200만
    # Current A = 100만 -> 100만 매수 필요 (10주)
    
    spy_order = next((o for o in signal.orders if o.ticker == 'SPY'), None)
    ief_order = next((o for o in signal.orders if o.ticker == 'IEF'), None)
    
    assert spy_order is not None
    assert spy_order.action == OrderAction.BUY
    assert spy_order.quantity == 10 # 100만원어치 추가 매수
    
    assert ief_order is not None
    assert ief_order.action == OrderAction.BUY
    assert ief_order.quantity == 10

def test_rebalancer_small_balance_rounding(create_portfolio):
    """
    [소액 잔고 테스트]
    사야 할 금액이 주당 가격보다 작을 때?
    -> 주문 수량이 0이 되어야 하고, 주문 목록에 포함되지 않거나 무시되어야 함.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: SPY 가격이 비쌈 (50만원)
    # 목표 비중 계산 결과 10만원어치를 더 사야 함.
    pf = create_portfolio(
        holdings={'SPY': 10}, # 500만원
        prices={'SPY': 500000}
    )
    
    # 강제로 목표 금액을 현재가치 + 10만원으로 설정하는 시나리오 유도
    # (여기서는 로직상 미세 조정이 어려우므로, 로직의 _create_orders 함수만 단위 테스트)
    
    # 직접 내부 함수 테스트 (Unit Test의 장점)
    # 목표매수금액: 100,000원, 현재가: 500,000원 -> 0.2주 -> 0주
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=5100000)
    
    # 현재가치 500만 vs 목표 510만 -> 차이 10만 -> 10만/50만 = 0.2 -> int(0)
    # 주문이 생성되지 않아야 함
    assert len(orders) == 0   

def test_rebalancer_sell_rounding_ceil(create_portfolio):
    """
    [매도 절삭 편향 수정 테스트]
    매도 시 math.ceil을 사용하여 목표에 더 가깝게 매도하는지 확인.
    예: 34.8주를 팔아야 할 때 -> 35주 매도 (기존 int()는 34주)
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # SPY 50주 × $33 = $1,650 보유
    pf = create_portfolio(
        holdings={'SPY': 50},
        prices={'SPY': 33.0}
    )

    # 목표 금액 $500 -> 매도 필요: (1650-500)/33 = 34.84주
    # math.ceil(34.84) = 35주 매도
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=500.0)

    assert len(orders) == 1
    assert orders[0].action == OrderAction.SELL
    assert orders[0].quantity == 35  # int()였다면 34

def test_rebalancer_sell_quantity_capped_by_holdings(create_portfolio):
    """
    [매도 수량 상한 테스트]
    매도 수량이 보유 수량을 초과하면 안 된다.
    예: 3주 보유, 목표 금액이 현재가보다 약간 낮으면
    ceil 반올림으로 4주 매도가 계산될 수 있으나, 3주로 제한되어야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # SPY 3주 × $95 = $285 보유
    pf = create_portfolio(
        holdings={'SPY': 3},
        prices={'SPY': 95.0}
    )

    # 목표 금액 $50 -> 매도 필요: (285-50)/95 = 2.47주 -> ceil = 3주 (OK, 보유량과 같음)
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=50.0)
    assert len(orders) == 1
    assert orders[0].action == OrderAction.SELL
    assert orders[0].quantity <= 3

    # 목표 금액 $1 -> 매도 필요: (285-1)/95 = 2.989주 -> ceil = 3주 (보유량과 같으므로 OK)
    orders2 = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=1.0)
    assert orders2[0].quantity <= 3

    # 목표 금액 $0 -> 매도 필요: 285/95 = 3.0주 -> ceil = 3주 (정확히 보유량)
    orders3 = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=0.0)
    assert orders3[0].quantity == 3

    # 핵심: 목표 금액이 음수(이론상 불가하지만 부동소수점 오차 등)
    # -> 매도 필요: (285-(-10))/95 = 3.105주 -> ceil = 4주, 하지만 보유 3주이므로 3주로 제한
    orders4 = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=-10.0)
    assert orders4[0].quantity == 3  # 보유 수량 초과 방지


def test_rebalancer_buy_rounding_floor(create_portfolio):
    """
    [매수 절삭 테스트]
    매수 시 math.floor를 사용하여 자금 초과를 방지하는지 확인.
    예: 30.3주를 사야 할 때 -> 30주 매수 (자금 초과 방지)
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # 현재 SPY 0주, 가격 $33
    pf = create_portfolio(
        holdings={},
        prices={'SPY': 33.0}
    )

    # 목표 금액 $1,000 -> 매수 필요: 1000/33 = 30.30주
    # math.floor(30.30) = 30주 매수
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=1000.0)

    assert len(orders) == 1
    assert orders[0].action == OrderAction.BUY
    assert orders[0].quantity == 30  # 자금 초과 방지

def test_rebalancer_order_sequence(create_portfolio):
    """
    [주문 순서 테스트]
    현금이 없고 SHV만 있는 상태에서 리밸런싱 할 때,
    반드시 SELL 주문이 BUY 주문보다 앞에 와야 한다.
    """
    groups = {'A': ['SSO'], 'B': ['IEF'], 'C': ['SHV']}
    rebalancer = Rebalancer(groups)
    
    # 현금 0원, SHV(C) 1000만원 보유
    # 목표: A매수, B매수 (C를 팔아서 사야 함)
    pf = create_portfolio(
        cash=0.0,
        holdings={'SHV': 100}, # 1000만원
        prices={'SSO': 100, 'IEF': 100, 'SHV': 100}
    )
    
    # 횡보장, 100% 투자 -> A:33%, B:33%, C:33% 목표 가정 (예시)
    # 실제 로직: A, B 목표 채우고 나머지가 C
    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)
    
    # 1. 주문이 생성되었는지 확인
    assert len(signal.orders) > 0
    
    # 2. 첫 번째 주문이 반드시 'SELL' 이어야 함 (SHV 매도)
    assert signal.orders[0].action == OrderAction.SELL
    assert signal.orders[0].ticker == "SHV"
    
    # 3. 그 뒤에 'BUY' 주문이 와야 함
    assert signal.orders[-1].action == OrderAction.BUY


def test_rebalancer_reason_rebalance_but_no_orders(create_portfolio):
    """
    [케이스 4: 첫 투자이지만 주문 단위 미달]
    첫 투자(val_risky=0 → is_first_investment=True)인데,
    주당 가격이 비싸서 매수 수량이 전부 floor → 0주.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # 현금 50만, 보유 종목 없음 (첫 투자 → is_first_investment=True)
    # 주당 가격 100만 → target 25만/종목 → floor(0.25) = 0주
    pf = create_portfolio(
        cash=500000,
        holdings={},
        prices={'SPY': 1000000, 'IEF': 1000000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)

    assert signal.has_orders is False
    assert "첫 투자" in signal.reason
    assert "단위 미달" in signal.reason


def test_rebalancer_first_investment_reason(create_portfolio):
    """
    [첫 투자 reason 메시지 테스트]
    위험자산(A+B) 보유액이 0인 경우 첫 투자 전용 reason이 설정되어야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # 현금 100만, 보유 종목 없음 (첫 투자)
    pf = create_portfolio(
        cash=1000000,
        holdings={},
        prices={'SPY': 100000, 'IEF': 100000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    assert signal.has_orders is True
    assert "첫 투자" in signal.reason
    assert "50:50" in signal.reason  # 기본 ratio_a=0.5


def test_rebalancer_c_group_target_not_negative(create_portfolio):
    """
    [C그룹 음수 방어 테스트]
    target_exposure가 1.0을 초과하는 값이 전달되더라도
    C그룹(SHV) 목표 금액이 음수가 되어서는 안 된다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF'], 'C': ['SHV']}
    rebalancer = Rebalancer(groups)

    pf = create_portfolio(
        cash=0.0,
        holdings={'SPY': 50, 'IEF': 50, 'SHV': 10},
        prices={'SPY': 100, 'IEF': 100, 'SHV': 100}
    )
    # total_value = 11,000
    # target_exposure=1.5 -> A+B 목표 = 11,000 * 1.5 = 16,500 (총자산 초과)
    # target_val_c가 음수가 되면 SHV에 음수 목표가 전달되어 비정상 매도 발생
    signal = rebalancer.generate_signal(pf, target_exposure=1.5, regime=MarketRegime.BULL)

    # C그룹 주문이 있다면, 최대 보유 수량까지만 매도해야 함
    shv_orders = [o for o in signal.orders if o.ticker == 'SHV']
    for o in shv_orders:
        if o.action == OrderAction.SELL:
            assert o.quantity <= 10  # 보유 수량 초과 매도 불가


# ==========================================
# 6. 가격 누락 경고 테스트
# ==========================================

def test_rebalancer_warns_on_missing_price(create_portfolio):
    """
    [가격 누락 경고 테스트]
    보유 종목의 가격 정보가 누락되면 Rebalancer가 ILogger를 통해 경고해야 한다.
    """
    mock_logger = MagicMock()
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, logger=mock_logger)

    # MISSING 종목을 보유하고 있지만 가격 정보가 없음
    pf = create_portfolio(
        cash=1000.0,
        holdings={'SPY': 10, 'MISSING': 5},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    # ILogger.warning이 MISSING 종목에 대해 호출되었는지 확인
    mock_logger.warning.assert_called()
    warning_messages = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert any("MISSING" in msg for msg in warning_messages)


def test_rebalancer_no_warning_when_all_prices_present(create_portfolio):
    """
    [가격 정상 시 경고 미발생 테스트]
    모든 보유 종목의 가격이 있으면 경고가 발생하지 않아야 한다.
    """
    mock_logger = MagicMock()
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, logger=mock_logger)

    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    # 가격 누락 관련 warning이 없어야 함
    warning_messages = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert not any("누락" in msg for msg in warning_messages)


# ==========================================
# 7. Rebalancer 커스텀 임계치 주입 테스트
# ==========================================

def test_rebalancer_custom_threshold_map(create_portfolio):
    """
    [커스텀 임계치 테스트]
    threshold_map을 외부에서 주입하면 해당 임계치가 적용되어야 한다.
    상대이탈 기준으로 판정한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}

    # A=518, B=482 → ratio_a=0.518, rel_dev=0.018/0.5=3.6%
    pf_small = create_portfolio(
        holdings={'SPY': 518, 'IEF': 482},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    # Case 1: 기본 임계치 (BULL=0.075) → 상대이탈 3.6% < 7.5% → 리밸런싱 불필요
    rebalancer_default = Rebalancer(groups)
    signal_default = rebalancer_default.generate_signal(pf_small, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal_default.has_orders is False

    # Case 2: 커스텀 임계치 (BULL=0.03) → 상대이탈 3.6% > 3.0% → 리밸런싱 필요
    custom_thresholds = {
        MarketRegime.BULL: 0.03,
        MarketRegime.SIDEWAYS: 0.025,
        MarketRegime.BEAR_WEAK: 0.05,
        MarketRegime.BEAR_STRONG: 0.05,
    }
    rebalancer_custom = Rebalancer(groups, threshold_map=custom_thresholds)
    signal_custom = rebalancer_custom.generate_signal(pf_small, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal_custom.has_orders is True
    assert "비율 재조정" in signal_custom.reason


def test_rebalancer_default_threshold_map_unchanged(create_portfolio):
    """
    [기본 임계치 유지 테스트]
    threshold_map을 지정하지 않으면 기존 기본값이 그대로 적용되어야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}

    # 기본 임계치가 클래스 상수와 동일한지 확인
    rebalancer = Rebalancer(groups)
    assert rebalancer._threshold_map == Rebalancer.DEFAULT_THRESHOLD_MAP

    # 인스턴스의 threshold_map 수정이 클래스 상수에 영향을 주지 않는지 확인
    rebalancer._threshold_map[MarketRegime.BULL] = 0.99
    assert Rebalancer.DEFAULT_THRESHOLD_MAP[MarketRegime.BULL] == 0.075


# ==========================================
# 7-1. Rebalancer 커스텀 비율(ratio_a) 테스트
# ==========================================

def test_rebalancer_custom_ratio_70_30(create_portfolio):
    """ratio_a=0.7로 첫 투자 시 A:B = 70:30 비율로 진입해야 한다."""
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, ratio_a=0.7)

    pf = create_portfolio(
        cash=1000000,
        holdings={},
        prices={'SPY': 100000, 'IEF': 100000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    assert signal.has_orders is True
    assert "첫 투자" in signal.reason
    assert "70:30" in signal.reason

    # SPY 목표: 1,000,000 * 1.0 * 0.7 = 700,000 → 7주
    # IEF 목표: 1,000,000 * 1.0 * 0.3 = 300,000 → 3주
    spy_order = next(o for o in signal.orders if o.ticker == 'SPY')
    ief_order = next(o for o in signal.orders if o.ticker == 'IEF')
    assert spy_order.action == OrderAction.BUY
    assert spy_order.quantity == 7
    assert ief_order.action == OrderAction.BUY
    assert ief_order.quantity == 3


def test_rebalancer_custom_ratio_rebalance_trigger(create_portfolio):
    """목표 비율(70:30)에서 크게 벗어나면 리밸런싱이 발생해야 한다."""
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, ratio_a=0.7)

    # 현재: SPY 50%(500주), IEF 50%(500주) → ratio_a=0.5, 목표 0.7 대비 이탈 0.20
    pf = create_portfolio(
        holdings={'SPY': 500, 'IEF': 500},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    # BULL threshold=0.075 → 이탈 0.20 > 0.075 → 리밸런싱 발생
    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal.has_orders is True
    assert "비율 재조정" in signal.reason


def test_rebalancer_custom_ratio_no_rebalance(create_portfolio):
    """목표 비율(70:30) 근처이면 리밸런싱이 발생하지 않아야 한다."""
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, ratio_a=0.7)

    # 현재: SPY 72%(720주), IEF 28%(280주) → ratio_a=0.72, 목표 0.7 대비 이탈 0.02
    pf = create_portfolio(
        holdings={'SPY': 720, 'IEF': 280},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    # BULL threshold=0.075 → 이탈 0.02 < 0.075 → 리밸런싱 불필요
    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal.has_orders is False


def test_rebalancer_invalid_ratio_raises():
    """ratio_a가 0 이하 또는 1 이상이면 ValueError가 발생해야 한다."""
    groups = {'A': ['SPY'], 'B': ['IEF']}

    import pytest
    with pytest.raises(ValueError):
        Rebalancer(groups, ratio_a=0.0)
    with pytest.raises(ValueError):
        Rebalancer(groups, ratio_a=1.0)
    with pytest.raises(ValueError):
        Rebalancer(groups, ratio_a=-0.1)
    with pytest.raises(ValueError):
        Rebalancer(groups, ratio_a=1.5)


def test_rebalancer_custom_ratio_reason_string(create_portfolio):
    """reason 메시지에 올바른 비율이 표시되어야 한다."""
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, ratio_a=0.6)

    pf = create_portfolio(
        cash=1000000,
        holdings={},
        prices={'SPY': 100000, 'IEF': 100000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)
    assert "60:40" in signal.reason


# ==========================================
# 8. 미세 주문 필터링 테스트 (Issue #85)
# ==========================================

def test_rebalancer_filters_micro_orders_on_small_cash(create_portfolio):
    """
    [미세 주문 필터링 테스트]
    비율 유지(needs_rebalance=False) 상태에서 소액 현금 유입 시
    총 주문 금액이 min_order_pct 미만이면 주문이 필터링되어야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)  # min_order_pct=0.05 (5%)

    # 상황: SPY 50만(500@1000), IEF 50만(500@1000), 소액 현금 1만원
    # total = 1,010,000. ratio_a=0.5, ratio_b=0.5 → needs_rebalance=False
    # target_val_a = 505,000 → diff = 5,000 → floor(5000/1000)=5주 매수
    # 총 주문 금액 = 10,000 < 1,010,000 * 0.05 = 50,500 → 필터링
    pf = create_portfolio(
        cash=10000,
        holdings={'SPY': 500, 'IEF': 500},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    assert signal.has_orders is False
    assert "추가 주문 없음" in signal.reason


def test_rebalancer_allows_large_exposure_orders(create_portfolio):
    """
    [대규모 주문 허용 테스트]
    비율 유지 상태에서도 대규모 현금 유입(5% 초과) 시 주문이 실행되어야 한다.
    기존 test_rebalancer_cash_injection 시나리오와 동일.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)  # min_order_pct=0.05 (5%)

    # 상황: SPY 100만, IEF 100만, 현금 200만 추가 (총 400만)
    # 총 주문 금액 ≈ 200만 = 50% >> 5% → 필터링되지 않음
    pf = create_portfolio(
        cash=2000000,
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100000, 'IEF': 100000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)

    assert signal.has_orders is True
    assert "exposure 조정" in signal.reason


def test_rebalancer_no_filter_when_rebalance_needed(create_portfolio):
    """
    [리밸런싱 필요 시 필터 미적용 테스트]
    needs_rebalance=True이면 미세 주문 필터가 적용되지 않아야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # SPY 55만(55%), IEF 45만(45%) → rel_dev=0.05/0.5=10% > SIDEWAYS threshold 2.5%
    pf = create_portfolio(
        holdings={'SPY': 550, 'IEF': 450},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)

    assert signal.has_orders is True
    assert "비율 재조정" in signal.reason


def test_rebalancer_custom_min_order_pct(create_portfolio):
    """
    [커스텀 min_order_pct 테스트]
    min_order_pct를 0으로 설정하면 미세 주문 필터가 비활성화되어야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, min_order_pct=0.0)

    # 소액 현금 유입 시 min_order_pct=0이면 필터링하지 않음
    # SPY 500@1000 = 50만, IEF 500@1000 = 50만, 현금 1만
    # diff per stock = 5,000 → floor(5000/1000) = 5주 → 주문 생성됨
    pf = create_portfolio(
        cash=10000,
        holdings={'SPY': 500, 'IEF': 500},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    # min_order_pct=0 → 필터 비활성화 → 소액이라도 주문 생성
    assert signal.has_orders is True
    assert "exposure 조정" in signal.reason


def test_rebalancer_default_min_order_pct_unchanged():
    """
    [기본 min_order_pct 유지 테스트]
    min_order_pct를 지정하지 않으면 기본값 0.05가 적용되어야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    assert rebalancer.min_order_pct == 0.05
    assert rebalancer.min_order_pct == Rebalancer.DEFAULT_MIN_ORDER_PCT


def test_create_group_orders_logs_ticker_detail(create_portfolio):
    """_create_group_orders는 group_name과 종목별 현재/목표/주문 정보를 logger.info로 출력해야 한다."""
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY', 'QLD']}, logger=mock_logger)

    pf = create_portfolio(
        holdings={'SPY': 3, 'QLD': 0},
        prices={'SPY': 100.0, 'QLD': 50.0}
    )
    # 목표: 각 $400 (SPY: 현재 $300 → +$100 매수, QLD: 현재 $0 → +$400 매수)
    rebalancer._create_group_orders(pf, ['SPY', 'QLD'], group_target_amt=800.0, group_name='A그룹')

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]

    # 그룹 헤더 출력 확인
    assert any('A그룹' in msg for msg in info_calls)
    # 각 종목 로그 포함 확인
    assert any('SPY' in msg for msg in info_calls)
    assert any('QLD' in msg for msg in info_calls)
    # 현재가치/목표/diff/주문방향 포함 확인
    assert any('→ BUY' in msg for msg in info_calls)


def test_create_group_orders_logs_no_order_reason(create_portfolio):
    """주문 수량이 0일 때 '주문 없음' 사유가 로깅되어야 한다."""
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY']}, logger=mock_logger)

    pf = create_portfolio(
        holdings={'SPY': 10},
        prices={'SPY': 500000.0}   # 주당 50만원 → 매수 수량 0
    )
    # 목표 510만원 → 차이 10만원 → floor(10만/50만)=0주 → 주문 없음
    rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=5100000.0, group_name='A그룹')

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    assert any('주문 없음' in msg or '수량 미달' in msg for msg in info_calls)


def test_create_group_orders_no_log_without_logger(create_portfolio):
    """logger가 None이면 _create_group_orders는 아무 로그도 출력하지 않아야 한다."""
    rebalancer = Rebalancer({'A': ['SPY']}, logger=None)
    pf = create_portfolio(holdings={'SPY': 5}, prices={'SPY': 100.0})
    # 예외 없이 실행되어야 함
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=1000.0, group_name='A그룹')
    assert isinstance(orders, list)


def test_generate_signal_logs_entry_context(create_portfolio):
    """generate_signal은 시작 시 regime, exposure, total_value를 로깅해야 한다."""
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=0.8, regime=MarketRegime.BULL)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 입력 컨텍스트 헤더 출력 확인
    assert any('[입력]' in msg for msg in info_calls)
    # regime 로깅
    assert any('Bull' in msg or 'Regime' in msg for msg in info_calls)
    # exposure 로깅
    assert any('0.80' in msg or '0.8' in msg or 'Exposure' in msg for msg in info_calls)


def test_generate_signal_logs_portfolio_section(create_portfolio):
    """generate_signal은 A/B/C 그룹별 평가액과 비중을 로깅해야 한다."""
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF'], 'C': ['SHV']}, logger=mock_logger)
    pf = create_portfolio(
        cash=2000.0,
        holdings={'SPY': 10, 'IEF': 8, 'SHV': 5},
        prices={'SPY': 100.0, 'IEF': 100.0, 'SHV': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=0.8, regime=MarketRegime.BULL)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 포트폴리오 섹션 헤더
    assert any('포트폴리오' in msg for msg in info_calls)
    # A, B, C 그룹 각각 언급
    assert any('A그룹' in msg for msg in info_calls)
    assert any('B그룹' in msg for msg in info_calls)
    assert any('C그룹' in msg for msg in info_calls)


def test_generate_signal_logs_ratio_judgment(create_portfolio):
    """generate_signal은 ratio_A, ratio_B, diff, threshold, 판정 결과를 로깅해야 한다."""
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    # ratio_A=0.55, ratio_B=0.45, diff=10% → BULL threshold 15% → 비율 유지
    pf = create_portfolio(
        holdings={'SPY': 550, 'IEF': 450},
        prices={'SPY': 1000.0, 'IEF': 1000.0}
    )

    rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 비중 판정 섹션
    assert any('비중 판정' in msg for msg in info_calls)
    # diff와 threshold 수치 포함
    assert any('10.0%' in msg or '10%' in msg or '0.100' in msg or '현재 차이' in msg for msg in info_calls)
    assert any('15.0%' in msg or '15%' in msg or '0.150' in msg or '임계치' in msg for msg in info_calls)


def test_generate_signal_logs_target_amounts(create_portfolio):
    """generate_signal은 A/B/C 그룹별 현재 금액과 목표 금액을 로깅해야 한다."""
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=0.8, regime=MarketRegime.BULL)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 목표 금액 섹션
    assert any('목표 금액' in msg for msg in info_calls)
    # exposure와 ratio 계산 근거 포함
    assert any('0.80' in msg or '0.8' in msg or 'exposure' in msg.lower() for msg in info_calls)


def test_generate_signal_logs_final_summary(create_portfolio):
    """generate_signal은 최종 주문 건수, 총 주문금액, reason을 로깅해야 한다."""
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    pf = create_portfolio(
        cash=2000000.0,
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100000.0, 'IEF': 100000.0}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 최종 주문 섹션 (BUY/SELL 건수 또는 주문 없음)
    assert any('최종 주문' in msg or '주문' in msg for msg in info_calls)
    # reason이 로그에 포함됨
    assert any(signal.reason in msg or '결정 사유' in msg for msg in info_calls)


def test_generate_signal_no_log_without_logger(create_portfolio):
    """logger=None이면 generate_signal은 어떤 로그도 시도하지 않고 정상 동작해야 한다."""
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=None)
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )
    signal = rebalancer.generate_signal(pf, target_exposure=0.8, regime=MarketRegime.BULL)
    assert isinstance(signal.reason, str)


def test_generate_signal_logs_crash_rebalancing(create_portfolio):
    """CRASH 시에도 입력 정보, 주문 결과가 로깅되어야 한다."""
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF'], 'C': ['SHV']}, logger=mock_logger)
    pf = create_portfolio(holdings={'SPY': 10}, prices={'SPY': 100.0, 'IEF': 100.0, 'SHV': 100.0})

    signal = rebalancer.generate_signal(pf, target_exposure=0.0, regime=MarketRegime.CRASH)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 입력 정보가 로깅되어야 함
    assert any('[입력]' in msg for msg in info_calls)
    # CRASH에서도 주문이 생성됨 (exposure=0 → 매도)
    assert signal.has_orders is True


# ==========================================
# 개별 상대이탈(relative deviation) 임계치 테스트
# ==========================================

def test_rebalancer_relative_deviation_asymmetric(create_portfolio):
    """
    [비대칭 비율 상대이탈 테스트]
    ratio_a=0.7일 때, A=76% B=24%이면
    rel_dev_a = |0.76-0.7|/0.7 = 8.6%, rel_dev_b = |0.24-0.3|/0.3 = 20%
    BULL threshold=7.5% → B가 초과하므로 리밸런싱 발동.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, ratio_a=0.7)

    pf = create_portfolio(
        holdings={'SPY': 760, 'IEF': 240},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal.has_orders is True
    assert "비율 재조정" in signal.reason


def test_rebalancer_relative_deviation_symmetric_unchanged(create_portfolio):
    """
    [대칭 비율(50:50) 상대이탈 테스트]
    ratio_a=0.5, A=55% B=45%이면
    rel_dev_a = |0.55-0.5|/0.5 = 10%, rel_dev_b = 10%
    BULL threshold=7.5% → 둘 다 초과하므로 리밸런싱 발동.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, ratio_a=0.5)

    pf = create_portfolio(
        holdings={'SPY': 550, 'IEF': 450},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal.has_orders is True


def test_rebalancer_relative_deviation_below_threshold(create_portfolio):
    """
    [상대이탈 임계치 미만 테스트]
    ratio_a=0.5, A=53% B=47%이면
    rel_dev_a = |0.53-0.5|/0.5 = 6%, rel_dev_b = 6%
    BULL threshold=7.5% → 둘 다 미만이므로 리밸런싱 불필요.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, ratio_a=0.5)

    pf = create_portfolio(
        holdings={'SPY': 530, 'IEF': 470},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal.has_orders is False


def test_rebalancer_crash_in_default_threshold_map():
    """CRASH가 DEFAULT_THRESHOLD_MAP에 명시적으로 포함되어야 한다."""
    assert MarketRegime.CRASH in Rebalancer.DEFAULT_THRESHOLD_MAP
    assert Rebalancer.DEFAULT_THRESHOLD_MAP[MarketRegime.CRASH] == 0.05


def test_rebalancer_crash_threshold_triggers_rebalance(create_portfolio):
    """
    [CRASH 임계치 테스트 - FullExposureEngine 시나리오]
    CRASH 국면에서 exposure=1.0일 때,
    CRASH threshold(0.05)를 초과하면 리밸런싱이 발생해야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # rel_dev = 0.06/0.5 = 12% > CRASH threshold 5% → 리밸런싱 발생
    pf = create_portfolio(
        holdings={'SPY': 560, 'IEF': 440},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.CRASH)
    assert signal.has_orders is True
    assert "비율 재조정" in signal.reason