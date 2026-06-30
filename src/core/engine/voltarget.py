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
)


@register_engine(color="#20c997")
class VolTargetLeverageEngine(FullExposureEngine):
    """실현 변동성에 반비례해 QLD(2x)/QQQ(1x) 비중을 조절하는 변동성 타겟 엔진.

    - 자산군 A: [QLD] (2x), B: [QQQ] (1x). 항상 100% 투자(현금 미보유).
    - 실효 레버리지 L = clamp(TARGET_VOL / σ, 1.0, 2.0); QLD 비중 = L − 1.
      평온기 → 2x(QLD↑), 폭락기 → 1x(QQQ↑). CRASH도 현금화가 아니라 1x로 디레버리지.
    - σ = max(실현변동성 21d, VIX/100): 후행하는 실현변동성과 선행하는 내재변동성
      (VIX) 중 '더 무서운' 쪽을 채택. VIX는 패닉에 즉시 급등(후행 완화)하고,
      VIX가 잠잠한 완만한 그라인드 약세장(예: 2022)에선 실현변동성이 가드를 유지
      → 두 신호의 사각지대를 상호 보완. (VIX 과소평가 시 실현이 메우므로 별도
      레벨 스케일링 불필요. YFinance 실패 시 VIX 기본 20.0 → σ 하한 0.20 효과.)
    - 변동성/국면은 QQQ(=나스닥100 1x) 기준으로 산출(레버리지로 왜곡되지 않음).
    - 주문 생성·턴오버 throttle은 기존 Rebalancer 재사용(ratio_a를 매 사이클 동적 설정).

    백테스트(2008~2026, σ_target=0.30, 프로덕션 엔진 경로/실제 QLD·QQQ 가격):
    CAGR 19.7%, MDD -54.2%, Sharpe 0.79, 평균레버리지 1.38. QQQ 고정 1x
    (CAGR 15.1%, Sharpe 0.74)·QLD 고정 2x(CAGR 24.3%, MDD -79.7%, Sharpe 0.71)을
    Sharpe 기준 모두 능가 — 더 적은 평균레버리지로 더 높은 위험조정수익.
    실현변동성 단독(Sharpe 0.74, avgLev 1.62) 대비 max(실현,VIX)가 레버리지를
    더 효율적으로 배분(타이밍 개선)한 결과다. 단 MDD(-54%대)는 거의 줄지 않는다:
    최악 낙폭은 QQQ 자체의 ~-50% 폭락이라 ~1.1x에서도 대부분 흡수 — 꼬리 위험은
    레버리지 신호로 못 푼다(주식 이탈 수단이 별도로 필요). 리밸런싱 임계치
    0~5% 무관하게 결과 동일(신호 저빈도).
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

    @staticmethod
    def _effective_vol(market_data: MarketData) -> float:
        """레버리지 산정용 변동성 σ = max(실현변동성 21d, VIX/100).

        후행하는 실현변동성과 선행하는 내재변동성(VIX) 중 더 큰(=더 무서운) 값을
        채택한다. VIX는 패닉에 즉시 급등해 후행을 완화하고, VIX가 잠잠한 그라인드
        약세장에선 실현변동성이 가드를 유지한다.
        """
        return max(market_data.spy_volatility, market_data.vix / 100.0)

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
            sigma = self._effective_vol(market_data)
            L = self._set_leverage_ratio(regime, sigma)
            self.logger.info(
                f">>> VolTarget: σ={sigma:.2%} "
                f"(real={market_data.spy_volatility:.2%}, VIX={market_data.vix:.1f}) "
                f"→ leverage={L:.2f}x (QLD {self.rebalancer.ratio_a:.0%})"
            )
        return super().execute_cycle(market_data, portfolio, regime, exposure,
                                     nan_fields, sim_date, record_date)
