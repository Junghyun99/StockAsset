# src/core/engine/regime.py
"""국면 적응형 3-자산 전략 엔진 모음.

이 파일의 엔진들은 TradingEngine을 직접 상속하며, 국면(MarketRegime)별로
exposure와 A그룹 비중을 동적으로 매핑하는 analyze_strategy()를 오버라이드한다.
"""
from typing import Dict, List, Tuple

from src.core.models import MarketData, MarketRegime
from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine


@register_engine(color="#e377c2", backtest=False)
class QldSdyShvEngine(TradingEngine):
    """QLD/SDY/SHV 3-자산 국면 적응형 배당+레버리지 엔진.

    SDY(배당 성장)를 B그룹으로 활용하여 안정적 수익 기반을 확보하고,
    국면에 따라 SHV(현금) 비중을 조절하여 하락장 방어력을 높인다.
    - 자산군 A: [QLD]  (2x 레버리지 나스닥 ETF)
    - 자산군 B: [SDY] (배당 성장 ETF)
    - 자산군 C: [SHV]  (초단기 국채 ETF — 현금 대용)

    국면별 배분 전략 (QldSdyEngine 대비 방어력 강화):
    - BULL:        QLD 27% + SDY 63% + SHV 10%  → 공격적 배분
    - SIDEWAYS:    QLD 21% + SDY 49% + SHV 30%  → 현금 비중 확대
    - BEAR_WEAK:   QLD 15% + SDY 35% + SHV 50%  → 절반 현금화
    - BEAR_STRONG: QLD  9% + SDY 21% + SHV 70%  → 대부분 현금
    - CRASH:       QLD  6% + SDY 14% + SHV 80%  → 최소 투자
    """

    ASSET_GROUPS: dict = {
        'A': ['QLD'],
        'B': ['SDY'],
        'C': ['SHV'],
    }

    REBALANCE_RATIO_A: float = 0.3  # fallback (QldSdyEngine과 동일)

    # 국면별 ratio_a (QLD vs SDY 내 비중): 일관되게 0.3 유지
    REGIME_RATIO_A_MAP: Dict[MarketRegime, float] = {
        MarketRegime.BULL:        0.3,
        MarketRegime.SIDEWAYS:    0.3,
        MarketRegime.BEAR_WEAK:   0.3,
        MarketRegime.BEAR_STRONG: 0.3,
        MarketRegime.CRASH:       0.3,
    }

    # 국면별 exposure (A+B 위험자산 비중): 하락 시 공격적으로 축소
    REGIME_EXPOSURE_MAP: Dict[MarketRegime, float] = {
        MarketRegime.BULL:        0.9,
        MarketRegime.SIDEWAYS:    0.7,
        MarketRegime.BEAR_WEAK:   0.5,
        MarketRegime.BEAR_STRONG: 0.3,
        MarketRegime.CRASH:       0.2,
    }

    def analyze_strategy(
        self, market_data: MarketData
    ) -> Tuple[MarketRegime, float, List[str]]:
        """Step 3 오버라이드: 국면별 고정 exposure 매핑 사용."""
        nan_fields = market_data.nan_fields()
        prev_regime = self.analyzer._prev_regime

        if nan_fields:
            self.logger.error(
                f"NaN detected in: {', '.join(nan_fields)}. Treating as CRASH."
            )
            regime = MarketRegime.CRASH
            exposure = 0.0
        else:
            regime = self.analyzer.analyze(market_data)
            exposure = self.REGIME_EXPOSURE_MAP.get(regime, 0.8)

        # 국면 변화 로그
        if prev_regime is not None and regime != prev_regime:
            self.logger.info(
                f"Regime Change: {prev_regime.value} → {regime.value} "
                f"(Price={market_data.spy_price:.2f}, MA180={market_data.spy_ma180:.2f}, "
                f"Momentum={market_data.spy_momentum:.4f}, "
                f"VIX={market_data.vix:.1f}, MDD={market_data.spy_mdd:.2%})"
            )

        return regime, exposure, nan_fields


@register_engine(color="#8c564b", backtest=False)
class QldQqqShvRegimeEngine(TradingEngine):
    """QLD/QQQ/SHV 3-자산 국면 적응형 레버리지 엔진.

    BULL→CRASH 순으로 QLD(2x 레버리지) 비중을 높여 실효 레버리지를 점진적으로 증가시킨다.
    - 자산군 A: [QLD]  (2x 레버리지 나스닥 ETF)
    - 자산군 B: [QQQ]  (1x 나스닥 100 ETF)
    - 자산군 C: [SHV]  (초단기 국채 ETF — 현금 대용)

    국면별 배분 전략:
    - BULL:        QLD 21% + QQQ 49% + SHV 30%  → 실효 레버리지 0.91x
    - SIDEWAYS:    QLD 30% + QQQ 30% + SHV 40%  → 실효 레버리지 0.90x
    - BEAR_WEAK:   QLD 42% + QQQ 18% + SHV 40%  → 실효 레버리지 1.02x
    - BEAR_STRONG: QLD 59% + QQQ  7% + SHV 35%  → 실효 레버리지 1.24x
    - CRASH:       QLD 71% + QQQ  4% + SHV 25%  → 실효 레버리지 1.46x
    """

    ASSET_GROUPS: dict = {
        'A': ['QLD'],
        'B': ['QQQ'],
        'C': ['SHV'],
    }

    REBALANCE_RATIO_A: float = 0.5  # fallback (국면 맵에 없는 경우)

    # 국면별 ratio_a (QLD 비중): BULL→CRASH 순으로 증가
    REGIME_RATIO_A_MAP: Dict[MarketRegime, float] = {
        MarketRegime.BULL:        0.3,
        MarketRegime.SIDEWAYS:    0.5,
        MarketRegime.BEAR_WEAK:   0.7,
        MarketRegime.BEAR_STRONG: 0.9,
        MarketRegime.CRASH:       0.95,
    }

    # 국면별 exposure (A+B 위험자산 비중): BULL→CRASH 순으로 증가
    REGIME_EXPOSURE_MAP: Dict[MarketRegime, float] = {
        MarketRegime.BULL:        0.7,
        MarketRegime.SIDEWAYS:    0.6,
        MarketRegime.BEAR_WEAK:   0.6,
        MarketRegime.BEAR_STRONG: 0.65,
        MarketRegime.CRASH:       0.75,
    }

    def analyze_strategy(
        self, market_data: MarketData
    ) -> Tuple[MarketRegime, float, List[str]]:
        """Step 3 오버라이드: 국면별 고정 exposure 매핑 사용."""
        nan_fields = market_data.nan_fields()
        prev_regime = self.analyzer._prev_regime

        if nan_fields:
            self.logger.error(
                f"NaN detected in: {', '.join(nan_fields)}. Treating as CRASH."
            )
            regime = MarketRegime.CRASH
            exposure = 0.0
        else:
            regime = self.analyzer.analyze(market_data)
            exposure = self.REGIME_EXPOSURE_MAP.get(regime, 0.8)

        # 국면 변화 로그
        if prev_regime is not None and regime != prev_regime:
            self.logger.info(
                f"Regime Change: {prev_regime.value} → {regime.value} "
                f"(Price={market_data.spy_price:.2f}, MA180={market_data.spy_ma180:.2f}, "
                f"Momentum={market_data.spy_momentum:.4f}, "
                f"VIX={market_data.vix:.1f}, MDD={market_data.spy_mdd:.2%})"
            )

        return regime, exposure, nan_fields
