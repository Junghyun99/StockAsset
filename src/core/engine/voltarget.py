# src/core/engine/voltarget.py
"""변동성 타겟 레버리지 엔진 (QLD/QQQ 블렌드).

실현 변동성에 반비례해 QLD(2x)/QQQ(1x) 비중을 조절(실효 레버리지 1~2x)한다.
평온기엔 레버리지업(QLD↑), 폭락기엔 디레버리지(QQQ↑). 고정 일간리셋 2x ETF가
'가장 위험할 때 못 줄이는' 한계를, 비율 조절로 동적으로 해결한 형태.

켈리식 처방(레버리지 ∝ target_vol/σ)을 기존 VolatilityTargeter(레버리지 모드)로
구현하고, 주문 생성·턴오버 throttle은 기존 Rebalancer를 재사용한다.
"""
from typing import List, Optional, Tuple

import pandas as pd

from src.core.engine.base import FullExposureEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.volatility_targeter import VolatilityTargeter
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution,
    DecisionFactor,
)


@register_engine(color="#20c997")
class VolTargetLeverageEngine(FullExposureEngine):
    """실현 변동성에 반비례해 QLD(2x)/QQQ(1x) 비중을 조절하는 변동성 타겟 엔진.

    - 자산군 A: [QLD] (2x), B: [QQQ] (1x). 항상 100% 투자(현금 미보유).
    - 실효 레버리지 L = clamp(TARGET_VOL / 실현변동성21d, 1.0, 2.0); QLD 비중 = L − 1.
      평온기 → 2x(QLD↑), 고변동성 → 1x(QQQ↑). CRASH도 현금화가 아니라 1x로 디레버리지.
    - 레버리지 사이징은 **실현변동성(21일)만** 사용한다. VIX는 국면 CRASH 판정
      (RegimeAnalyzer.is_risk_condition)에만 쓰이고 레버리지 크기 결정엔 쓰지 않는다.
      한때 σ=max(실현, VIX/100)을 썼으나(PR #348), 실제 VIX로 재평가한 결과
      realized 단독(Sharpe ~0.73)보다 오히려 나빴다(max: ~0.60). VIX는 내재변동성
      리스크 프리미엄 때문에 실현보다 상시 높아 max가 σ를 과대평가 → 레버리지를
      만성적으로 낮춰 수익만 깎았고, CRASH 방어 이득도 없었다(CRASH는 VIX로 별도
      판정). → PR #350에서 realized 단독으로 롤백.
    - 변동성/국면은 QQQ(=나스닥100 1x) 기준으로 산출(레버리지로 왜곡되지 않음).
    - 주문 생성·턴오버 throttle은 기존 Rebalancer 재사용(ratio_a를 매 사이클 동적 설정).

    성과(2008~2026, σ_target=0.30, 실제 VIX, realized 단독 사이징):
    CAGR ~19%, MDD ~-55%, Sharpe ~0.73, 평균레버리지 ~1.6. **1x QQQ(Sharpe ~0.74)를
    위험조정수익 기준 넘지 못한다** — 평균 ~1.6x 레버리지를 써도 변동성이 커져
    Sharpe 이득이 없다. QLD 단순보유(CAGR ~24%, MDD ~-80%, Sharpe ~0.71)보다
    CAGR는 낮고 Sharpe는 비슷하다. 원인: 2x ETF 일간리셋 감쇠 + 후행 신호
    미스타이밍. 장기 자동운용용으로는 부적합하며, 단기·목적성 레버리지 도구로만
    제한 사용 권장.

    이력: PR #348에서 σ=max(실현,VIX)로 도입됐으나, 당시 평가는 백테스트 하네스가
    VIX를 상수 20.0으로 잘못 먹인 버그(BacktestDataLoader.fetch_vix)로 오측된
    것이었다. 실제 VIX로 재평가 시 max는 realized 단독보다 나빠(0.60 vs 0.73)
    PR #350에서 realized 단독으로 롤백했다.
    """

    ASSET_GROUPS: dict = {"A": ["QLD"], "B": ["QQQ"]}
    REBALANCE_RATIO_A: float = 0.5          # 초기값(매 사이클 동적 갱신)
    TARGET_VOL: float = 0.30
    MIN_LEVERAGE: float = 1.0
    MAX_LEVERAGE: float = 2.0
    SIGNAL_TICKER: str = "QQQ"              # 변동성/국면 신호 기준(1x 나스닥100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 부모(TradingEngine)가 만든 self.targeter를 '레버리지 모드'로 재할당한다.
        # FullExposureEngine은 analyze_strategy에서 targeter를 쓰지 않으므로(exposure=1.0
        # 고정) 이 슬롯을 안전하게 재사용 — 미사용 중복 인스턴스를 남기지 않는다.
        self.targeter = VolatilityTargeter(
            target_vol=self.TARGET_VOL,
            min_exposure=self.MIN_LEVERAGE,
            max_exposure=self.MAX_LEVERAGE,
            regime_max_exposures={},           # 레버리지 모드: 국면 디리스크 캡 비활성
            crash_exposure=self.MIN_LEVERAGE,  # CRASH도 1x로 디레버리지(현금화 아님)
        )

    def collect_data(self, data_provider: IDataProvider) -> Tuple[pd.DataFrame, float]:
        """Step 1 오버라이드: 변동성/국면 신호를 QQQ(1x 나스닥)에서 산출."""
        df = data_provider.fetch_ohlcv([self.SIGNAL_TICKER], days=400)
        vix = data_provider.fetch_vix()
        return df, vix

    def _set_leverage_ratio(self, regime: MarketRegime, current_vol: float) -> float:
        """변동성→레버리지→QLD 비중(ratio_a) 동적 설정. 반환: 실효 레버리지 L."""
        L = self.targeter.calculate_exposure(regime, current_vol)
        w = min(max(L - 1.0, 0.0), 1.0)        # QLD 비중
        self.rebalancer.ratio_a = w
        self.rebalancer.ratio_b = round(1.0 - w, 10)
        return L

    def execute_cycle(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
        nan_fields: List[str],
        sim_date: Optional[str],
        record_date: str,
    ) -> Tuple[TradeSignal, List[TradeExecution], Portfolio, bool]:
        if not nan_fields:
            # 레버리지 사이징은 실현변동성만 사용(VIX는 CRASH 판정 전용)
            L = self._set_leverage_ratio(regime, market_data.spy_volatility)
            self.logger.info(
                f">>> VolTarget: vol={market_data.spy_volatility:.2%} "
                f"→ leverage={L:.2f}x (QLD {self.rebalancer.ratio_a:.0%})"
            )
        return super().execute_cycle(market_data, portfolio, regime, exposure,
                                     nan_fields, sim_date, record_date)

    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        """변동성 타겟: 실현변동성 → QLD/QQQ 블렌드 레버리지가 결정요소다."""
        w = self.rebalancer.ratio_a          # QLD 비중 = L - 1
        return [
            DecisionFactor("realized_vol", "실현변동성(21d)", market_data.spy_volatility,
                           "percent", threshold=self.TARGET_VOL),
            DecisionFactor("target_vol", "목표 변동성", self.TARGET_VOL, "percent"),
            DecisionFactor("effective_leverage", "실효 레버리지(x)", 1.0 + w, "number"),
            DecisionFactor("leveraged_weight", "QLD 비중", w, "percent"),
        ]
