# src/core/engine/volmanaged.py
"""변동성 관리 엔진 (QLD/QQQ/SHV).

실현변동성에 반비례해 실효 레버리지 L∈[0,2]를 조절하되, 1x 미만에서는 현금(SHV)으로
이탈한다. 고변동성 구간(위험조정수익이 나쁜 구간)의 노출을 줄여 Sharpe를 높이는
변동성 관리(volatility-managed / Moreira-Muir) 방식.
"""
from typing import List, Tuple

import pandas as pd

from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.volatility_targeter import VolatilityTargeter
from src.core.models import MarketData, MarketRegime


@register_engine(color="#6f42c1")
class VolManagedEngine(TradingEngine):
    """실현변동성에 반비례해 실효 레버리지 L∈[0,2]를 조절하는 변동성 관리 엔진.

    - 자산군 A=[QLD](2x), B=[QQQ](1x), C=[SHV](현금). L에 따라 3그룹 비중 결정.
    - L = clamp(TARGET_VOL / 실현변동성21d, MIN_LEV, MAX_LEV). 순수 실현변동성 기반
      (VIX는 국면 CRASH 판정에만 쓰고 레버리지 사이징엔 쓰지 않는다 — PR #350 참고).
    - 매핑: exposure=min(L,1)(위험비중 A+B, 나머지 1-exposure는 C 현금),
      ratio_a=max(L-1,0)(위험자산 내 QLD 비중).
        L=0.5 → 현금50%+QQQ50% | L=1 → QQQ100% | L=1.5 → QLD50%+QQQ50% | L=2 → QLD100%
    - 핵심: 1x 미만 현금 이탈을 허용해 고변동성 구간을 회피 — 고정 1x 바닥(VolTarget)
      대비 MDD를 크게 줄이고 위험조정수익을 개선한다.

    성과 수치는 프로덕션 엔진 경로 검증 후 반영한다(계획: docs/plans/2026-07-01-volmanaged-engine.md).
    """

    ASSET_GROUPS: dict = {"A": ["QLD"], "B": ["QQQ"], "C": ["SHV"]}
    REBALANCE_RATIO_A: float = 0.5    # fallback
    TARGET_VOL: float = 0.22
    MIN_LEV: float = 0.0
    MAX_LEV: float = 2.0
    SIGNAL_TICKER: str = "QQQ"        # 변동성/국면 신호 기준(레버리지 대상 자산과 일치)

    def collect_data(self, data_provider: IDataProvider):
        """Step 1 오버라이드: 변동성/국면 신호를 QQQ(레버리지 대상)에서 산출.

        base(TradingEngine)는 SPY로 신호를 뽑지만, 이 엔진은 QQQ/QLD를 운용하므로
        변동성 관리가 포트폴리오와 일치하도록 QQQ 기준으로 산출한다.
        """
        df = data_provider.fetch_ohlcv([self.SIGNAL_TICKER], days=400)
        vix = data_provider.fetch_vix()
        return df, vix

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # targeter를 순수 vol→레버리지 클램프로 재사용한다. calculate_exposure를
        # BULL 국면으로 호출해 CRASH 오버라이드를 우회하므로 crash_exposure는 미사용.
        self.targeter = VolatilityTargeter(
            target_vol=self.TARGET_VOL,
            min_exposure=self.MIN_LEV,
            max_exposure=self.MAX_LEV,
            regime_max_exposures={},        # 국면 디리스크 캡 비활성(순수 vol)
            crash_exposure=self.MIN_LEV,
        )

    def _leverage_to_weights(self, current_vol: float) -> Tuple[float, float]:
        """실현변동성 → (exposure, ratio_a). L=clamp(TARGET_VOL/vol). 순수 vol 기반.

        exposure = min(L,1): 위험자산(A+B) 비중, 나머지 1-exposure는 C(현금).
        ratio_a  = max(L-1,0): 위험자산 내 QLD(A) 비중.
        """
        L = self.targeter.calculate_exposure(MarketRegime.BULL, current_vol)  # CRASH 우회
        exposure = min(L, 1.0)
        ratio_a = max(L - 1.0, 0.0)
        return exposure, ratio_a

    def analyze_strategy(
        self, market_data: MarketData
    ) -> Tuple[MarketRegime, float, List[str]]:
        """Step 3 오버라이드: 실현변동성 기반 exposure/ratio_a 동적 설정."""
        nan_fields = market_data.nan_fields()
        prev = self.analyzer._prev_regime

        if nan_fields:
            self.logger.error(
                f"NaN detected in: {', '.join(nan_fields)}. Treating as CRASH."
            )
            regime, exposure = MarketRegime.CRASH, 0.0
        else:
            regime = self.analyzer.analyze(market_data)
            exposure, ratio_a = self._leverage_to_weights(market_data.spy_volatility)
            self.rebalancer.ratio_a = ratio_a
            self.rebalancer.ratio_b = round(1.0 - ratio_a, 10)
            self.logger.info(
                f">>> VolManaged: vol={market_data.spy_volatility:.2%} "
                f"→ L={exposure + ratio_a:.2f}x "
                f"(QLD {ratio_a:.0%}, 위험 {exposure:.0%}, 현금 {1.0 - exposure:.0%})"
            )

        if prev is not None and regime != prev:
            self.logger.info(
                f"Regime Change: {prev.value} → {regime.value} "
                f"(Price={market_data.spy_price:.2f}, MA180={market_data.spy_ma180:.2f}, "
                f"Momentum={market_data.spy_momentum:.4f}, "
                f"VIX={market_data.vix:.1f}, MDD={market_data.spy_mdd:.2%})"
            )

        return regime, exposure, nan_fields
