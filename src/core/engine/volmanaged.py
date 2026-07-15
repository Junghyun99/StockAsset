# src/core/engine/volmanaged.py
"""변동성 관리 엔진 (QLD/QQQ/SHV).

실현변동성에 반비례해 실효 레버리지 L∈[0,2]를 조절하되, 1x 미만에서는 현금(SHV)으로
이탈한다. 고변동성 구간(위험조정수익이 나쁜 구간)의 노출을 줄여 Sharpe를 높이는
변동성 관리(volatility-managed / Moreira-Muir) 방식.
"""
from typing import List, Optional, Tuple

import pandas as pd

from src.config import ticker_display
from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.volatility_targeter import VolatilityTargeter
from src.core.models import DecisionFactor, MarketData, MarketRegime, Portfolio, TradeSignal


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
    - 턴오버 억제: 목표 L이 LEVERAGE_DEADBAND(0.15) 이상 변할 때만 재조정한다.
      vol-managed는 리밸런싱이 잦아 거래비용에 취약하므로 데드밴드가 필수다.

    성과(2008~2026, 프로덕션 엔진 경로, 실제 SHV·거래비용 0.25%/거래 포함):
    CAGR 16.3%, MDD -39.1%, Sharpe 0.76 — **QQQ 1x(15.1%/-49.5%/0.74)와 QLD 2x
    (24.3%/-79.7%/0.71)를 Sharpe 기준 모두 능가**하며, 수익은 그 사이, MDD는 최저.
    고변동성 구간 현금 이탈로 위험조정수익을 개선한 결과다.
    단서: (1) 거래비용에 민감 — 무비용 이상화 시 Sharpe~0.91이나 repo의 0.25%
    수수료(실제 ETF의 ~10배)로 0.76까지 하락, 데드밴드로 방어. 현실적 수수료
    (~0.03%)면 더 높다. (2) 단일 표본·σ_target 파라미터 의존.
    설계·검증: docs/plans/2026-07-01-volmanaged-engine.md
    """

    ASSET_GROUPS: dict = {"A": ["QLD"], "B": ["QQQ"], "C": ["SHV"]}
    REBALANCE_RATIO_A: float = 0.5    # fallback
    TARGET_VOL: float = 0.22
    MIN_LEV: float = 0.0
    MAX_LEV: float = 2.0
    SIGNAL_TICKER: str = "QQQ"        # 변동성/국면 신호 기준(레버리지 대상 자산과 일치)
    LEVERAGE_DEADBAND: float = 0.15   # 목표 L이 이만큼 이상 변할 때만 재조정(턴오버 억제)

    def collect_data(self, data_provider: IDataProvider) -> Tuple[pd.DataFrame, float]:
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
        self._applied_L: Optional[float] = None   # 데드밴드로 유지되는 현재 실효 레버리지(첫 사이클엔 목표 그대로)

    @staticmethod
    def _lev_to_weights(L: float) -> Tuple[float, float]:
        """실효 레버리지 L → (exposure, ratio_a). 순수 함수.

        exposure = min(L,1): 위험자산(A+B) 비중, 나머지 1-exposure는 C(현금).
        ratio_a  = max(L-1,0): 위험자산 내 QLD(A) 비중.
        """
        return min(L, 1.0), max(L - 1.0, 0.0)

    def _leverage_to_weights(self, current_vol: float) -> Tuple[float, float]:
        """실현변동성 → (exposure, ratio_a). L=clamp(TARGET_VOL/vol), 데드밴드 무시(raw)."""
        L = self.targeter.calculate_exposure(MarketRegime.BULL, current_vol)  # CRASH 우회
        return self._lev_to_weights(L)

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
            # 데드밴드: 목표 L이 충분히 변했을 때만 실효 L을 갱신(턴오버·거래비용 억제)
            L_target = self.targeter.calculate_exposure(MarketRegime.BULL, market_data.spy_volatility)
            if self._applied_L is None or abs(L_target - self._applied_L) > self.LEVERAGE_DEADBAND:
                self._applied_L = L_target
            exposure, ratio_a = self._lev_to_weights(self._applied_L)
            self.rebalancer.ratio_a = ratio_a
            self.rebalancer.ratio_b = round(1.0 - ratio_a, 10)
            leveraged_ticker = ticker_display(self.ASSET_GROUPS["A"][0])
            self.logger.info(
                f">>> VolManaged: vol={market_data.spy_volatility:.2%} "
                f"→ L={exposure + ratio_a:.2f}x "
                f"({leveraged_ticker} {ratio_a:.0%}, 위험 {exposure:.0%}, 현금 {1.0 - exposure:.0%})"
            )

        if prev is not None and regime != prev:
            self.logger.info(
                f"Regime Change: {prev.value} → {regime.value} "
                f"(Price={market_data.spy_price:.2f}, MA180={market_data.spy_ma180:.2f}, "
                f"Momentum={market_data.spy_momentum:.4f}, "
                f"VIX={market_data.vix:.1f}, MDD={market_data.spy_mdd:.2%})"
            )

        return regime, exposure, nan_fields

    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        """변동성 관리: 실현변동성 → 실효 레버리지 사이징이 결정요소다."""
        L = self._applied_L if self._applied_L is not None \
            else exposure + self.rebalancer.ratio_a
        return [
            DecisionFactor("realized_vol", "실현변동성(21d)", market_data.spy_volatility,
                           "percent", threshold=self.TARGET_VOL),
            DecisionFactor("target_vol", "목표 변동성", self.TARGET_VOL, "percent"),
            DecisionFactor("effective_leverage", "실효 레버리지(x)", L, "number"),
            DecisionFactor("cash_weight", "현금 비중", max(1.0 - exposure, 0.0), "percent"),
        ]


@register_engine(color="#d63384", market_type="domestic", backtest=False)
class DomesticVolManagedEngine(VolManagedEngine):
    """VolManagedEngine의 국내상장 ETF 버전 (실거래 전용).

    - 자산군 A=[418660.KS](TIGER 미국나스닥100레버리지(합성), 2x)
             B=[133690.KS](TIGER 미국나스닥100, 1x)
             C=[459580.KS](KODEX CD금리액티브, 현금성)
    - 레버리지 산출 로직은 VolManagedEngine과 완전히 동일(상속), 자산군과 신호
      티커만 국내상장 ETF로 교체한다.
    - 418660.KS(2022년 상장)/459580.KS(2023년 상장)는 상장 이력이 짧아 장기
      비교 백테스트가 불가능하므로 backtest=False로 등록해 실거래(main.py)에서만
      사용한다.
    """

    ASSET_GROUPS: dict = {"A": ["418660.KS"], "B": ["133690.KS"], "C": ["459580.KS"]}
    SIGNAL_TICKER: str = "133690.KS"
