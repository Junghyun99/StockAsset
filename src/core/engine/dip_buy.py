# src/core/engine/dip_buy.py
"""오즐웅줍 눌림목 분할매수 엔진.

QLD 단일 종목을 대상으로 이동평균선(MA20/60/120) 눌림목과 RSI 과매도/과열을
트리거로 현금을 분할 투입/회수한다. 트랜치 큐는 strategy_state.json에 영속화되어
백테스트(엔진 재사용)와 라이브(매일 재시작)가 동일한 코드 경로로 동작한다.
"""
from typing import List, Optional, Tuple

import pandas as pd

from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.dip_buy_indicators import DipBuyIndicatorCalculator
from src.core.logic.dip_buy_planner import DipBuyPlanner, DipBuyState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution,
)


@register_engine(color="#e45756")
class DipBuyEngine(TradingEngine):
    """QLD 단일 종목 눌림목 분할매수 전략 엔진.

    - 자산군 A: [QLD] (현금은 예수금으로 보유, 별도 현금 ETF 미사용)
    - 트리거(종가 ±2% 밴드): MA20 터치 10% / MA60·120 부근 50% 5일 분할 /
      MA120 아래 & RSI<30 100% 40일 분할 / RSI>70 목표 현금비중 20%까지 5일 분할 매도
    - 트랜치 큐/무장 상태는 repo(strategy_state.json)에 영속화
    """

    ASSET_GROUPS: dict = {"A": ["QLD"]}
    BAND: float = 0.02
    SELL_TARGET_CASH_RATIO: float = 0.20
    STATE_KEY: str = "dip_buy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ticker = self.ASSET_GROUPS["A"][0]
        self._dip_calc = DipBuyIndicatorCalculator()
        self._planner = DipBuyPlanner(
            ticker=self._ticker,
            band=self.BAND,
            sell_target_cash_ratio=self.SELL_TARGET_CASH_RATIO,
        )
        # 트랜치 큐/무장 상태 복원 (국면 히스테리시스 복원과 동일 패턴)
        self.dip_state = DipBuyState.from_dict(self.repo.load_strategy_state(self.STATE_KEY))
        self.dip_signals = None

    def collect_data(self, data_provider: IDataProvider) -> Tuple[pd.DataFrame, float]:
        """Step 1 오버라이드: SPY 대신 대상 티커(QLD) OHLCV를 수집한다."""
        df = data_provider.fetch_ohlcv([self._ticker], days=400)
        vix = data_provider.fetch_vix()
        return df, vix

    def calculate_indicators(self, spy_df: pd.DataFrame, vix: float) -> MarketData:
        """Step 2 오버라이드: 대시보드/repo 호환 MarketData + 눌림목 지표 동시 계산."""
        self.dip_signals = self._dip_calc.calculate(spy_df)
        return self.calculator.calculate(spy_df, vix)

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
        """Step 5 오버라이드: Rebalancer 대신 DipBuyPlanner로 트리거 기반 매매."""
        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = False

        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}")
            self.logger.error(f"NaN detected: {', '.join(nan_fields)} — 매매 중단")
            return signal, executions, final_pf, is_rebalancing

        orders, reason, new_state = self._planner.plan(
            self.dip_signals, portfolio, self.dip_state
        )

        signal = TradeSignal(exposure, orders, reason)
        self.logger.info(f">>> Step 5: DipBuy ({reason})")

        if orders:
            is_rebalancing = True
            self.logger.info(f"Executing {len(orders)} orders ({reason})")
            executions = self.broker.execute_orders(orders)
            try:
                final_pf = self.broker.get_portfolio()
            except RuntimeError as e:
                self.logger.error(f"거래 후 포트폴리오 조회 실패 — 거래 전 포트폴리오로 대체: {e}")
                final_pf = portfolio

        # 상태 갱신 + 영속화는 주문 실행 시도 이후에 수행한다. execute_orders가
        # 예외로 중단되면 차감된 트랜치 상태가 저장되지 않아, 다음 거래일에 동일
        # 상태로 재시도된다 (주문 미실행 + 상태 차감의 불일치 방지).
        self.dip_state = new_state
        self.repo.save_strategy_state(self.STATE_KEY, new_state.to_dict())

        return signal, executions, final_pf, is_rebalancing
