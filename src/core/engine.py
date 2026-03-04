# src/core/engine.py
import time
from typing import List, Optional, Tuple

import pandas as pd

from src.core.interfaces import IDataProvider, IBrokerAdapter, IRepository, ILogger, INotifier
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution, DayResult
)
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.utils.calculator import IndicatorCalculator


class TradingEngine:
    """핵심 트레이딩 사이클 엔진.

    main.py (실시간)와 runner.py (백테스트) 모두 이 엔진을 재사용한다.
    환경별 차이는 주입되는 구현체(broker, data_provider, notifier)가 담당하며,
    비즈니스 로직 자체는 단일 위치(이 클래스)에서만 관리된다.
    """

    def __init__(
        self,
        calculator: IndicatorCalculator,
        analyzer: RegimeAnalyzer,
        targeter: VolatilityTargeter,
        rebalancer: Rebalancer,
        broker: IBrokerAdapter,
        repo: IRepository,
        logger: ILogger,
        all_tickers: List[str],
        trading_interval_days: int = 5,
        notifier: Optional[INotifier] = None,  # 백테스트는 None
        is_live_trading: bool = False,
    ):
        self.calculator = calculator
        self.analyzer = analyzer
        self.targeter = targeter
        self.rebalancer = rebalancer
        self.broker = broker
        self.repo = repo
        self.logger = logger
        self.all_tickers = all_tickers
        self.trading_interval_days = trading_interval_days
        self.notifier = notifier
        self.is_live_trading = is_live_trading

    def run_one_cycle(
        self,
        data_provider: IDataProvider,
        sim_date: Optional[str] = None,
    ) -> DayResult:
        """하루치 트레이딩 사이클 전체를 실행한다.

        Args:
            data_provider: OHLCV / VIX 데이터 소스.
                실시간: YFinanceLoader, 백테스트: BacktestDataLoader
            sim_date: 시뮬레이션 날짜 ("YYYY-MM-DD").
                None이면 오늘 날짜 사용 (실시간 모드).

        Returns:
            DayResult: 사이클 실행 결과 (regime, signal, executions, portfolio 등)
        """
        # Step 1~2: 데이터 수집 & 지표 계산
        self.logger.info(">>> Step 1: Data Collection")
        spy_df = data_provider.fetch_ohlcv(["SPY"], days=400)
        vix = data_provider.fetch_vix()

        self.logger.info(">>> Step 2: Indicator Calculation")
        market_data = self.calculator.calculate(spy_df, vix)
        self.logger.info(
            f"Market Data: Price={market_data.spy_price}, "
            f"VIX={market_data.vix}, MDD={market_data.spy_mdd:.2%}"
        )

        # Step 3: 국면 분석
        self.logger.info(">>> Step 3: Strategy Analysis")
        regime, exposure, nan_fields = self._analyze_regime(market_data)
        self.logger.info(f"Regime: {regime.value} | Target Exposure: {exposure:.2f}")

        # Step 4: 포트폴리오 조회 + 실시간 가격
        self.logger.info(">>> Step 4: Portfolio Status")
        portfolio = self._get_portfolio()
        self.logger.info(
            f"Current Portfolio: Cash=${portfolio.total_cash:,.0f}, "
            f"Value=${portfolio.total_value:,.0f}"
        )

        # Step 5: 조건 분기 & 실행
        signal, executions, final_pf, is_rebalancing = self._execute_cycle(
            market_data, portfolio, regime, exposure, nan_fields, sim_date
        )

        # Step 6: 저장
        self.logger.info(">>> Step 6: Archiving Data")
        self._persist(market_data, signal, executions, final_pf, regime, exposure, is_rebalancing, sim_date)

        return DayResult(
            market_data=market_data,
            regime=regime,
            exposure=exposure,
            signal=signal,
            executions=executions,
            final_pf=final_pf,
            is_rebalancing=is_rebalancing,
            nan_fields=nan_fields,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _analyze_regime(
        self, market_data: MarketData
    ) -> Tuple[MarketRegime, float, List[str]]:
        """NaN 감지 + 국면/노출도 계산."""
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

    def _get_portfolio(self) -> Portfolio:
        """포트폴리오 조회 후 실시간 가격 업데이트."""
        portfolio = self.broker.get_portfolio()
        self.logger.info("Fetching Real-time prices from Broker...")
        real_time_prices = self.broker.fetch_current_prices(self.all_tickers)
        for ticker, price in real_time_prices.items():
            if price > 0:
                portfolio.current_prices[ticker] = price
        return portfolio

    def _execute_cycle(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
        nan_fields: List[str],
        sim_date: Optional[str],
    ) -> Tuple[TradeSignal, List[TradeExecution], Portfolio, bool]:
        """3-way 조건 분기: NaN이상 / 모니터링 / 리밸런싱."""
        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = False

        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}")
            msg = (
                f"⚠️ Data Quality Alert — 매매 중단\n"
                f"날짜: {market_data.date}\n"
                f"NaN 필드: {', '.join(nan_fields)}\n"
                f"데이터 품질 이상으로 매매를 중단합니다."
            )
            self.logger.error(msg)
            self._notify_alert(msg)

        elif not self._is_due(sim_date) and regime != MarketRegime.CRASH:
            signal = TradeSignal(exposure, [], f"{regime.value} (모니터링)")
            self.logger.info(
                f">>> Step 5: Monitoring "
                f"(리밸런싱 인터벌 미충족, {self.trading_interval_days}일 기준)"
            )
            self._notify_message(
                f"모니터링 완료. {regime.value} | ${portfolio.total_value:,.0f}"
            )

        else:
            is_rebalancing = True
            self.logger.info(">>> Step 5: Rebalancing")
            signal = self.rebalancer.generate_signal(portfolio, exposure, regime)

            # CRASH 알림 발송
            if regime == MarketRegime.CRASH:
                crash_msg = self._build_crash_alert(market_data, portfolio)
                self.logger.error(crash_msg)
                self._notify_alert(crash_msg)

            if signal.has_orders:
                self.logger.info(f"Signal Generated: {signal.reason}")
                self.logger.info(f"Executing {len(signal.orders)} orders...")
                executions = self.broker.execute_orders(signal.orders)

                if executions:
                    self._notify_message(f"✅ Orders Executed. Count: {len(executions)}")
                    if self.is_live_trading:
                        time.sleep(3)
                    final_pf = self.broker.get_portfolio()
                    self.logger.info(
                        f"Updated Portfolio: Cash=${final_pf.total_cash:,.0f}, "
                        f"Value=${final_pf.total_value:,.0f}"
                    )
                else:
                    self._notify_alert("⚠️ Orders sent but NO execution result returned.")
            else:
                self.logger.info("No Rebalance Needed.")
                self._notify_message(f"Bot Finished. Hold. ({regime.value})")

        return signal, executions, final_pf, is_rebalancing

    def _is_due(self, sim_date: Optional[str]) -> bool:
        """마지막 리밸런싱 이후 trading_interval_days 이상 경과했으면 True."""
        last_str = self.repo.get_last_rebalancing_date()
        if last_str is None:
            return True
        try:
            last = pd.Timestamp(last_str)
            today = pd.Timestamp(sim_date) if sim_date else pd.Timestamp.today().normalize()
            return (today - last).days >= self.trading_interval_days
        except Exception:
            return True  # 파싱 실패 시 안전하게 리밸런싱 실행

    def _persist(
        self,
        market_data: MarketData,
        signal: TradeSignal,
        executions: List[TradeExecution],
        final_pf: Portfolio,
        regime: MarketRegime,
        exposure: float,
        is_rebalancing: bool,
        sim_date: Optional[str],
    ) -> None:
        """저장 3종 호출."""
        rebalancing_date = (sim_date or market_data.date) if is_rebalancing else None
        self.repo.save_daily_summary(market_data, signal, final_pf, regime)
        self.repo.save_trade_history(executions, final_pf, signal.reason, sim_date=sim_date)
        self.repo.update_status(
            regime, exposure, final_pf, market_data, signal.reason,
            sim_date=sim_date,
            rebalancing_date=rebalancing_date,
        )

    def _build_crash_alert(self, market_data: MarketData, portfolio: Portfolio) -> str:
        """CRASH 알림 메시지 생성 (포지션 정보 포함)."""
        holdings_lines = []
        for ticker, qty in portfolio.holdings.items():
            if qty > 0:
                price = portfolio.current_prices.get(ticker, 0)
                value = qty * price
                holdings_lines.append(f"  • {ticker}: {qty}주 (${value:,.0f})")
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

    def _notify_message(self, msg: str) -> None:
        if self.notifier:
            self.notifier.send_message(msg)

    def _notify_alert(self, msg: str) -> None:
        if self.notifier:
            self.notifier.send_alert(msg)
