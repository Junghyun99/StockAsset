# src/core/engine/base.py
import time
from typing import List, Optional, Tuple

import pandas as pd

from src.core.interfaces import IDataProvider, IBrokerAdapter, IRepository, ILogger, INotifier
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution, DayResult,
    ExecutionStatus,
)
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.utils.calculator import IndicatorCalculator
from src.core.engine.registry import register_engine
from src.config import ticker_display


@register_engine(color="#1f77b4")
class TradingEngine:
    """핵심 트레이딩 사이클 엔진 (Template Method 패턴).

    run_one_cycle()이 전체 사이클의 뼈대(template)를 정의하며,
    각 단계(Step 1~6)는 개별 메서드로 분리되어 서브클래스에서 오버라이드 가능하다.

    main.py (실시간)와 runner.py (백테스트) 모두 이 엔진을 재사용한다.
    환경별 차이는 주입되는 구현체(broker, data_provider, notifier)가 담당하며,
    비즈니스 로직 자체는 단일 위치(이 클래스)에서만 관리된다.

    서브클래스에 ASSET_GROUPS / REBALANCE_RATIO_A 클래스 속성이 있으면
    파라미터보다 우선 적용된다 (QldSdyEngine, QldSHVEngine 등).
    """

    def __init__(
        self,
        broker: IBrokerAdapter,
        repo: IRepository,
        logger: ILogger,
        asset_groups: Optional[dict] = None,
        ratio_a: float = 0.5,
        target_vol: float = 0.15,
        trading_interval_days: int = 5,
        notifier: Optional[INotifier] = None,  # 백테스트는 None
        is_live_trading: bool = False,
    ):
        # 클래스 속성 우선, 없으면 파라미터 사용
        groups = getattr(type(self), 'ASSET_GROUPS', asset_groups)
        effective_ratio_a = getattr(type(self), 'REBALANCE_RATIO_A', ratio_a)

        if groups is None:
            raise ValueError("asset_groups must be provided when ASSET_GROUPS class attribute is not set")

        # 국면별 ratio_a 맵 (클래스 속성 우선)
        regime_ratio_a_map = getattr(type(self), 'REGIME_RATIO_A_MAP', None)

        self.calculator = IndicatorCalculator()
        self.analyzer = RegimeAnalyzer()
        self.targeter = VolatilityTargeter(target_vol=target_vol)
        self.rebalancer = Rebalancer(groups, logger=logger, ratio_a=effective_ratio_a,
                                     regime_ratio_a_map=regime_ratio_a_map)
        self.broker = broker
        self.repo = repo
        self.logger = logger
        self.all_tickers = [t for g in groups.values() for t in g]

        # 엔진이 최종 확정한 asset_groups를 repo에 주입 (클래스 속성 오버라이드 반영)
        if hasattr(self.repo, 'asset_groups'):
            self.repo.asset_groups = groups
        self.trading_interval_days = trading_interval_days
        self.notifier = notifier
        self.is_live_trading = is_live_trading

        # 히스테리시스 상태 복원 (프로세스 재시작 시 이전 국면 유지)
        last_regime = self.repo.load_last_regime()
        if last_regime is not None:
            self.analyzer._prev_regime = last_regime
            self.logger.info(f"Restored previous regime: {last_regime.value}")

    def run_one_cycle(
        self,
        data_provider: IDataProvider,
        sim_date: Optional[str] = None,
        daily_dividend: float = 0.0,
    ) -> DayResult:
        """하루치 트레이딩 사이클 전체를 실행한다 (Template Method).

        Args:
            data_provider: OHLCV / VIX 데이터 소스.
                실시간: YFinanceLoader, 백테스트: BacktestDataLoader
            sim_date: 시뮬레이션 날짜 ("YYYY-MM-DD").
                None이면 오늘 날짜 사용 (실시간 모드).

        Returns:
            DayResult: 사이클 실행 결과 (regime, signal, executions, portfolio 등)
        """
        # 슬랙 댓글용 로그 캡처 버퍼를 사이클 단위로 초기화한다.
        # (멀티 계정 공유 로거에서 이전 계정 로그 혼입 방지 + 백테스트 메모리 바운드)
        self.logger.clear_captured_logs()

        # Step 1: 데이터 수집
        self.logger.info(">>> Step 1: Data Collection")
        spy_df, vix = self.collect_data(data_provider)

        # Step 2: 지표 계산
        self.logger.info(">>> Step 2: Indicator Calculation")
        market_data = self.calculate_indicators(spy_df, vix)
        self.logger.info(
            f"Market Data: Price={market_data.spy_price:.2f}, "
            f"VIX={market_data.vix:.2f}, MDD={market_data.spy_mdd:.2%}"
        )

        # Step 3: 국면 분석
        self.logger.info(">>> Step 3: Strategy Analysis")
        regime, exposure, nan_fields = self.analyze_strategy(market_data)
        self.logger.info(f"Regime: {regime.value} | Target Exposure: {exposure:.2f}")

        # Step 4: 포트폴리오 조회 + 실시간 가격
        self.logger.info(">>> Step 4: Portfolio Status")
        try:
            portfolio = self.get_portfolio()
        except RuntimeError as e:
            msg = f"⚠️ Portfolio API Error — 사이클 중단\n날짜: {sim_date or 'today'}\n{e}"
            self.logger.error(msg)
            self._notify_alert(msg, detail=self._cycle_detail())
            raise
        self.logger.info(
            f"Current Portfolio: Cash=${portfolio.total_cash:,.0f}, "
            f"Value=${portfolio.total_value:,.0f}"
        )

        # Step 5: 조건 분기 & 실행
        signal, executions, final_pf, is_rebalancing = self.execute_cycle(
            market_data, portfolio, regime, exposure, nan_fields, sim_date
        )

        # Step 6: 저장 (NaN 데이터 품질 이상 시 전체 스킵 — step 4 API 오류와 동일 처리)
        self.logger.info(">>> Step 6: Archiving Data")
        if not nan_fields:
            self.persist(market_data, signal, executions, final_pf, regime, exposure, is_rebalancing, sim_date, daily_dividend)
        self.logger.info(
            f"Cycle Completed: regime={regime.value} exposure={exposure:.2f} "
            f"orders={len(signal.orders)} executions={len(executions)}"
        )

        return DayResult(
            market_data=market_data,
            regime=regime,
            exposure=exposure,
            signal=signal,
            executions=executions,
            final_pf=final_pf,
            is_rebalancing=is_rebalancing,
            nan_fields=nan_fields,
            daily_dividend=daily_dividend,
        )

    # ── Overridable step methods ─────────────────────────────────────────────

    def collect_data(
        self, data_provider: IDataProvider
    ) -> Tuple[pd.DataFrame, float]:
        """Step 1: OHLCV 및 VIX 데이터를 수집한다."""
        spy_df = data_provider.fetch_ohlcv(["SPY"], days=400)
        vix = data_provider.fetch_vix()
        return spy_df, vix

    def calculate_indicators(
        self, spy_df: pd.DataFrame, vix: float
    ) -> MarketData:
        """Step 2: 시장 지표를 계산한다."""
        return self.calculator.calculate(spy_df, vix)

    def analyze_strategy(
        self, market_data: MarketData
    ) -> Tuple[MarketRegime, float, List[str]]:
        """Step 3: NaN 감지 + 국면/노출도 계산."""
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
            exposure = self.targeter.calculate_exposure(regime, market_data.spy_volatility)

        # 국면 변화 로그
        if prev_regime is not None and regime != prev_regime:
            self.logger.info(
                f"Regime Change: {prev_regime.value} → {regime.value} "
                f"(Price={market_data.spy_price:.2f}, MA180={market_data.spy_ma180:.2f}, "
                f"Momentum={market_data.spy_momentum:.4f}, "
                f"VIX={market_data.vix:.1f}, MDD={market_data.spy_mdd:.2%})"
            )

        return regime, exposure, nan_fields

    def get_portfolio(self) -> Portfolio:
        """Step 4: 포트폴리오 조회 후 실시간 가격 업데이트."""
        portfolio = self.broker.get_portfolio()
        self.logger.info("Fetching Real-time prices from Broker...")
        real_time_prices = self.broker.fetch_current_prices(self.all_tickers)
        for ticker, price in real_time_prices.items():
            if price > 0:
                portfolio.current_prices[ticker] = price
        return portfolio

    def execute_cycle(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
        nan_fields: List[str],
        sim_date: Optional[str],
    ) -> Tuple[TradeSignal, List[TradeExecution], Portfolio, bool]:
        """Step 5: 3-way 조건 분기: NaN이상 / 모니터링 / 리밸런싱."""
        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = False

        # 보유 종목 중 가격 조회 실패(0.0 또는 누락) 종목 감지
        zero_price_tickers = [
            t for t, q in portfolio.holdings.items()
            if q > 0 and portfolio.current_prices.get(t, 0) <= 0
        ]

        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}")
            msg = (
                f"⚠️ Data Quality Alert — 매매 중단\n"
                f"날짜: {market_data.date}\n"
                f"NaN 필드: {', '.join(nan_fields)}\n"
                f"데이터 품질 이상으로 매매를 중단합니다."
            )
            self.logger.error(msg)
            self._notify_alert(msg, detail=self._cycle_detail())

        elif zero_price_tickers:
            display_names = [ticker_display(t) for t in zero_price_tickers]
            signal = TradeSignal(0.0, [], f"가격 조회 실패 — 매매 중단: {', '.join(display_names)}")
            msg = (
                f"⚠️ Price Data Alert — 매매 중단\n"
                f"날짜: {market_data.date}\n"
                f"가격 조회 실패 종목: {', '.join(display_names)}\n"
                f"보유 종목 가격 이상으로 리밸런싱을 중단합니다.\n"
                f"total_value 왜곡으로 인한 비정상 주문 방지."
            )
            self.logger.error(msg)
            self._notify_alert(msg, detail=self._cycle_detail())

        elif not self._is_due(sim_date) and regime != MarketRegime.CRASH:
            signal = TradeSignal(exposure, [], f"{regime.value} (모니터링)")
            self.logger.info(
                f">>> Step 5: Monitoring "
                f"(리밸런싱 인터벌 미충족, {self.trading_interval_days}일 기준)"
            )
            self._notify_message(
                f"모니터링 완료. {regime.value} | ${portfolio.total_value:,.0f}",
                detail=self._cycle_detail(),
            )

        else:
            is_rebalancing = True
            self.logger.info(">>> Step 5: Rebalancing")
            signal = self.rebalancer.generate_signal(portfolio, exposure, regime)

            # CRASH 알림 발송
            if regime == MarketRegime.CRASH:
                crash_msg = self._build_crash_alert(market_data, portfolio)
                self.logger.error(crash_msg)
                self._notify_alert(crash_msg, detail=self._cycle_detail())

            if signal.has_orders:
                self.logger.info(f"Executing {len(signal.orders)} orders ({signal.reason})")
                executions = self.broker.execute_orders(signal.orders)

                total = len(signal.orders)
                filled = sum(1 for e in executions if e.status == ExecutionStatus.FILLED)
                partial = sum(1 for e in executions if e.status == ExecutionStatus.PARTIAL)
                ordered = sum(1 for e in executions if e.status == ExecutionStatus.ORDERED)
                rejected = sum(1 for e in executions if e.status == ExecutionStatus.REJECTED)
                failed = total - len(executions)
                self.logger.info(
                    f"Order Summary: total={total} filled={filled} partial={partial} "
                    f"ordered={ordered} rejected={rejected} failed={failed}"
                )

                if executions:
                    self._notify_message(
                        f"✅ Orders Executed. Count: {len(executions)}",
                        detail=self._cycle_detail(),
                    )
                    if self.is_live_trading:
                        time.sleep(3)
                    try:
                        final_pf = self.broker.get_portfolio()
                        self.logger.info(
                            f"Updated Portfolio: Cash=${final_pf.total_cash:,.0f}, "
                            f"Value=${final_pf.total_value:,.0f}"
                        )
                    except RuntimeError as e:
                        warn_msg = (
                            f"⚠️ 거래 후 포트폴리오 조회 실패 — 거래 전 포트폴리오로 대체\n{e}\n"
                            f"거래 기록은 정상 저장됩니다."
                        )
                        self.logger.error(warn_msg)
                        self._notify_alert(warn_msg, detail=self._cycle_detail())
                else:
                    self._notify_alert(
                        "⚠️ Orders sent but NO execution result returned.",
                        detail=self._cycle_detail(),
                    )
            else:
                self.logger.info("No Rebalance Needed.")
                self._notify_message(
                    f"Bot Finished. Hold. ({regime.value})",
                    detail=self._cycle_detail(),
                )

        return signal, executions, final_pf, is_rebalancing

    def persist(
        self,
        market_data: MarketData,
        signal: TradeSignal,
        executions: List[TradeExecution],
        final_pf: Portfolio,
        regime: MarketRegime,
        exposure: float,
        is_rebalancing: bool,
        sim_date: Optional[str],
        daily_dividend: float = 0.0,
    ) -> None:
        """Step 6: 저장 3종 호출."""
        rebalancing_date = (sim_date or market_data.date) if is_rebalancing else None
        self.repo.save_daily_summary(market_data, signal, final_pf, regime, daily_dividend=daily_dividend)
        self.repo.save_trade_history(executions, final_pf, signal.reason, sim_date=sim_date)
        self.repo.update_status(
            regime, exposure, final_pf, market_data, signal.reason,
            sim_date=sim_date,
            rebalancing_date=rebalancing_date,
        )

    # ── Private helpers (NOT part of template) ────────────────────────────────

    def _is_due(self, sim_date: Optional[str]) -> bool:
        """마지막 리밸런싱 이후 trading_interval_days 이상 경과했으면 True."""
        last_str = self.repo.get_last_rebalancing_date()
        if last_str is None:
            return True
        try:
            last = pd.Timestamp(last_str)
            today = pd.Timestamp(sim_date) if sim_date else pd.Timestamp.today().normalize()
            diff_days = (today - last).days
            # sim_date가 last_rebalancing_date보다 과거이면 stale 데이터 → 리밸런싱 실행
            if diff_days < 0:
                return True
            return diff_days >= self.trading_interval_days
        except Exception:
            return True  # 파싱 실패 시 안전하게 리밸런싱 실행

    def _build_crash_alert(self, market_data: MarketData, portfolio: Portfolio) -> str:
        """CRASH 알림 메시지 생성 (포지션 정보 포함)."""
        holdings_lines = []
        for ticker, qty in portfolio.holdings.items():
            if qty > 0:
                price = portfolio.current_prices.get(ticker, 0)
                value = qty * price
                holdings_lines.append(f"  • {ticker_display(ticker)}: {qty}주 (${value:,.0f})")
        if not holdings_lines:
            holdings_lines.append("  • (보유 종목 없음)")
        holdings_info = "\n".join(holdings_lines)
        return (
            f"🚨 CRASH Detected — 현금화 리밸런싱 실행\n"
            f"MDD: {market_data.spy_mdd:.1%} | VIX: {market_data.vix:.1f}\n"
            f"SPY: ${market_data.spy_price:.2f}\n"
            f"\n"
            f"📊 현재 포지션:\n"
            f"{holdings_info}\n"
            f"💰 현금: ${portfolio.total_cash:,.0f}\n"
            f"📈 총 자산: ${portfolio.total_value:,.0f}"
        )

    def _cycle_detail(self) -> str:
        """이번 사이클에 캡처된 전체 로그를 슬랙 댓글용 detail 문자열로 반환한다."""
        return "\n".join(self.logger.get_captured_logs())

    def _notify_message(self, msg: str, detail: Optional[str] = None) -> None:
        if self.notifier:
            self.notifier.send_message(msg, detail=detail)

    def _notify_alert(self, msg: str, detail: Optional[str] = None) -> None:
        if self.notifier:
            self.notifier.send_alert(msg, detail=detail)


@register_engine(color="#2ca02c")
class FullExposureEngine(TradingEngine):
    """항상 exposure=1.0을 유지하는 전략 엔진.

    - A/B 자산군에 항상 100% 투자 (C그룹 미배분)
    - CRASH 국면에서도 exposure=1.0 유지
    - NaN 데이터일 때만 안전장치로 exposure=0.0
    - A/B 비율 차이가 임계치 초과 시 설정 비율로 리밸런싱 (Rebalancer 기본 동작)
    """

    def analyze_strategy(
        self, market_data: MarketData
    ) -> Tuple[MarketRegime, float, List[str]]:
        """Step 3 오버라이드: 국면 분석은 수행하되 exposure는 항상 1.0."""
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
            exposure = 1.0  # 핵심: CRASH 포함 항상 100% 투자

        # 국면 변화 로그
        if prev_regime is not None and regime != prev_regime:
            self.logger.info(
                f"Regime Change: {prev_regime.value} → {regime.value} "
                f"(Price={market_data.spy_price:.2f}, MA180={market_data.spy_ma180:.2f}, "
                f"Momentum={market_data.spy_momentum:.4f}, "
                f"VIX={market_data.vix:.1f}, MDD={market_data.spy_mdd:.2%})"
            )

        return regime, exposure, nan_fields
