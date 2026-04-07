from typing import Optional
from src.core.models import MarketRegime, MarketData


class RegimeAnalyzer:
    # BULL/SIDEWAYS 판정 기본 모멘텀 임계치 (SPY 6개월 수익률 기준)
    DEFAULT_BULL_MOMENTUM_THRESHOLD = 0.05

    # BULL 탈출 히스테리시스 기본값 (진입보다 낮게 설정하여 Bull↔Sideways 휩쏘 방지)
    # 진입: momentum ≥ 0.05, 탈출: momentum < 0.03
    DEFAULT_BULL_EXIT_MOMENTUM_THRESHOLD = 0.03

    # CRASH 탈출 히스테리시스 기본값 (진입보다 엄격하게 설정하여 휩쏘 방지)
    # 진입: VIX ≥ 30 OR MDD ≤ -20%
    # 탈출: VIX < 25 AND MDD > -15%
    DEFAULT_CRASH_EXIT_VIX = 25.0
    DEFAULT_CRASH_EXIT_MDD = -0.15

    # CRASH 탈출 후 쿨다운 기간 기본값 (거래일 기준)
    # 쿨다운 기간 동안 VIX/MDD 복합 조건(VIX≥30 AND MDD≤-10%)에 의한 재진입을 차단
    # 단, MDD≤-20% 극단적 하락 시에는 쿨다운 무시하고 즉시 CRASH 진입
    DEFAULT_CRASH_COOLDOWN_DAYS = 10

    # Bear_Strong 탈출 히스테리시스 기본값 (Bear_Strong↔Bear_Weak 휩쏘 방지)
    # 탈출: momentum > 0.01 AND price > MA180 * 1.01
    DEFAULT_BEAR_STRONG_EXIT_MOMENTUM_THRESHOLD = 0.01
    DEFAULT_BEAR_STRONG_EXIT_MA_BUFFER = 0.01

    def __init__(self, bull_momentum_threshold: float = 0.05,
                 bull_exit_momentum_threshold: float = DEFAULT_BULL_EXIT_MOMENTUM_THRESHOLD,
                 crash_exit_vix: float = DEFAULT_CRASH_EXIT_VIX,
                 crash_exit_mdd: float = DEFAULT_CRASH_EXIT_MDD,
                 crash_cooldown_days: int = DEFAULT_CRASH_COOLDOWN_DAYS,
                 bear_strong_exit_momentum_threshold: float = DEFAULT_BEAR_STRONG_EXIT_MOMENTUM_THRESHOLD,
                 bear_strong_exit_ma_buffer: float = DEFAULT_BEAR_STRONG_EXIT_MA_BUFFER):
        self.bull_momentum_threshold = bull_momentum_threshold
        self.bull_exit_momentum_threshold = bull_exit_momentum_threshold
        self.crash_exit_vix = crash_exit_vix
        self.crash_exit_mdd = crash_exit_mdd
        self.crash_cooldown_days = crash_cooldown_days
        self.bear_strong_exit_momentum_threshold = bear_strong_exit_momentum_threshold
        self.bear_strong_exit_ma_buffer = bear_strong_exit_ma_buffer
        self._prev_regime: Optional[MarketRegime] = None
        self._crash_cooldown_remaining: int = 0  # 쿨다운 잔여 거래일

    def analyze(self, data: MarketData) -> MarketRegime:
        # 1. CRASH 진입 조건 확인
        if data.is_risk_condition():
            # MDD≤-20% 극단적 하락 → 쿨다운 무시하고 즉시 CRASH 진입
            if data.spy_mdd <= -0.20:
                regime = MarketRegime.CRASH
            # 쿨다운 기간 중이면 VIX/MDD 복합 조건에 의한 재진입 차단
            elif self._crash_cooldown_remaining > 0:
                regime = self._classify_non_crash(data)
            else:
                regime = MarketRegime.CRASH
        # 2. 이전에 CRASH였으면 탈출 조건 확인 (히스테리시스)
        elif self._prev_regime == MarketRegime.CRASH:
            can_exit = data.vix < self.crash_exit_vix and data.spy_mdd > self.crash_exit_mdd
            if can_exit:
                regime = self._classify_non_crash(data)
                self._crash_cooldown_remaining = self.crash_cooldown_days  # 쿨다운 시작
            else:
                regime = MarketRegime.CRASH  # 탈출 조건 미충족 → CRASH 유지
        # 3. 일반 국면 판정
        else:
            regime = self._classify_non_crash(data)

        # 쿨다운 카운터 감소 (CRASH가 아닌 국면일 때만)
        # CRASH 탈출 당일(prev_regime=CRASH)은 감소하지 않음 → 탈출 다음 날부터 카운트
        if regime != MarketRegime.CRASH and self._crash_cooldown_remaining > 0 and self._prev_regime != MarketRegime.CRASH:
            self._crash_cooldown_remaining -= 1

        self._prev_regime = regime
        return regime

    def _classify_non_crash(self, data: MarketData) -> MarketRegime:
        """CRASH가 아닌 국면을 판정한다."""
        is_bear_momentum = data.spy_momentum < 0
        is_below_ma = data.spy_price < data.spy_ma180

        if is_bear_momentum and is_below_ma:
            return MarketRegime.BEAR_STRONG

        # Bear_Strong 히스테리시스: 이전 국면이 BEAR_STRONG이면 버퍼 조건 충족 시에만 탈출 허용
        # (momentum≈0 또는 price≈MA180 경계에서 Bear_Strong↔Bear_Weak 휩쏘 방지)
        if self._prev_regime == MarketRegime.BEAR_STRONG:
            can_exit = (
                data.spy_momentum > self.bear_strong_exit_momentum_threshold
                and data.spy_price > data.spy_ma180 * (1 + self.bear_strong_exit_ma_buffer)
            )
            if not can_exit:
                return MarketRegime.BEAR_STRONG  # 탈출 조건 미충족 → BEAR_STRONG 유지

        if is_bear_momentum or is_below_ma:
            return MarketRegime.BEAR_WEAK

        # 이 시점: momentum >= 0 AND price >= MA
        # Bull 히스테리시스: 이전 국면이 BULL이면 낮은 출구 임계치 적용하여 휩쏘 방지
        if self._prev_regime == MarketRegime.BULL:
            threshold = self.bull_exit_momentum_threshold
        else:
            threshold = self.bull_momentum_threshold
        if data.spy_momentum >= threshold:
            return MarketRegime.BULL
        else:
            # momentum이 0 이상 임계치 미만 → 횡보장
            return MarketRegime.SIDEWAYS
