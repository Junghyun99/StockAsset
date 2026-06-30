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
    - 실효 레버리지 L = clamp(TARGET_VOL / 실현변동성, 1.0, 2.0); QLD 비중 = L − 1.
      평온기 → 2x(QLD↑), 폭락기 → 1x(QQQ↑). CRASH도 현금화가 아니라 1x로 디레버리지.
    - 변동성/국면은 QQQ(=나스닥100 1x) 기준으로 산출(레버리지로 왜곡되지 않음).
    - 주문 생성·턴오버 throttle은 기존 Rebalancer 재사용(ratio_a를 매 사이클 동적 설정).

    백테스트(2008~2026, σ=0.30): CAGR ~23%, MDD ~-55%, Sharpe ~0.83 — 같은 평균
    레버리지의 고정 블렌드보다 우수(폭락기 디레버리지 효과). 단 실현변동성 후행으로
    급락 초기 일부 손실은 불가피.
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
            L = self._set_leverage_ratio(regime, market_data.spy_volatility)
            self.logger.info(
                f">>> VolTarget: vol={market_data.spy_volatility:.2%} "
                f"→ leverage={L:.2f}x (QLD {self.rebalancer.ratio_a:.0%})"
            )
        return super().execute_cycle(market_data, portfolio, regime, exposure,
                                     nan_fields, sim_date, record_date)
