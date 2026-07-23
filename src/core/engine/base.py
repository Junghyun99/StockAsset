# src/core/engine/base.py
import time
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional, Tuple

import pandas as pd

from src.core.interfaces import (
    IDataProvider, IBrokerAdapter, IRepository, ILogger, INotifier,
    IDividendRateProvider, IDividendSettlement, NoOpDividendSettlement,
    ITickerLabelProvider, IdentityTickerLabelProvider,
)
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution, DayResult,
    ExecutionStatus, DecisionFactor, Order, OrderAction, OrderBatchResult,
    OrderOutcome, StrategyDecision,
)
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.core.indicators import IndicatorCalculator
from src.core.engine.data_pipeline import (
    CollectedData,
    DataSetSpec,
    StrategyDataSpec,
)
from src.core.engine.registry import register_engine


@register_engine(color="#1f77b4", backtest=False)
class TradingEngine:
    """핵심 트레이딩 사이클 엔진 (Template Method 패턴).

    run_one_cycle()과 execute_cycle()이 데이터 수집부터 저장까지의 공통 흐름을
    소유한다. 구체 엔진은 데이터 요구사항, 전략 지표, 전략 결정, 전략 상태 반영
    훅만 재정의한다.

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
        benchmarks: Optional[dict] = None,
        account_label: Optional[str] = None,
        is_active: bool = True,
        dividend_rate_provider: Optional[IDividendRateProvider] = None,
        dividend_settlement: Optional[IDividendSettlement] = None,
        ticker_labels: Optional[ITickerLabelProvider] = None,
    ):
        # 클래스 속성 우선, 없으면 파라미터 사용
        groups = getattr(type(self), 'ASSET_GROUPS', asset_groups)
        effective_ratio_a = getattr(type(self), 'REBALANCE_RATIO_A', ratio_a)

        if groups is None:
            raise ValueError("asset_groups must be provided when ASSET_GROUPS class attribute is not set")

        # 국면별 ratio_a 맵 (클래스 속성 우선)
        regime_ratio_a_map = getattr(type(self), 'REGIME_RATIO_A_MAP', None)

        self.calculator = IndicatorCalculator()
        self.strategy_indicators: Any = None
        self.analyzer = RegimeAnalyzer()
        self.targeter = VolatilityTargeter(target_vol=target_vol)
        self.ticker_labels = ticker_labels or IdentityTickerLabelProvider()
        self.rebalancer = Rebalancer(
            groups,
            logger=logger,
            ratio_a=effective_ratio_a,
            regime_ratio_a_map=regime_ratio_a_map,
            ticker_labels=self.ticker_labels,
        )
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
        # 비활성(False) 계좌는 조회·국면분석·저장까지만 수행하고 매매(execute_orders)는 스킵한다.
        # IRP처럼 주문 API가 불가하거나 일시 정지하려는 계좌에 사용. 조회는 계속되어 최신 자산평가 유지.
        self.is_active = is_active
        # 멀티 계좌 Slack 알림에서 계좌를 구분하기 위한 라벨 (예: accounts.yaml의 id)
        self.account_label = account_label
        self.dividend_rate_provider = dividend_rate_provider
        self.dividend_settlement = dividend_settlement or NoOpDividendSettlement()

        # 벤치마크 {논리명: 티커}. 포트폴리오와 동일 브로커·동일 시점으로 현재가를 조회한다.
        # 백테스트는 BacktestBroker가 과거 종가를 서빙하므로 동일 경로로 동작한다.
        self.benchmarks: dict = benchmarks or {}
        self._benchmark_prices: dict = {}  # get_portfolio에서 매 사이클 갱신
        self._last_order_result = OrderBatchResult([])
        self._orphan_order_result = OrderBatchResult([])

        # 히스테리시스 상태 복원 (프로세스 재시작 시 이전 국면 유지)
        last_regime = self.repo.load_last_regime()
        if last_regime is not None:
            self.analyzer._prev_regime = last_regime
            self.logger.info(f"Restored previous regime: {last_regime.value}")

    def run_one_cycle(
        self,
        data_provider: IDataProvider,
        sim_date: Optional[str] = None,
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
        self._last_order_result = OrderBatchResult([])

        # 저장 key 및 리밸런싱 날짜로 사용할 실행일 결정
        # 백테스트: sim_date(시뮬레이션 날짜) 사용
        # 라이브: 오늘 실행일 사용 (market_data.date는 전일 미국 거래일이므로 부적합)
        record_date = sim_date or datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

        # Step 1: 데이터 수집
        self.logger.info(">>> Step 1: Data Collection")
        collected = self.collect_data(data_provider)

        # Step 2: 지표 계산
        self.logger.info(">>> Step 2: Indicator Calculation")
        market_data = self.calculate_indicators(collected)
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
        # 비활성 계좌 게이트도 공통 흐름에서 한 번만 적용한다.
        expected_dividend = self._settle_expected_dividend(portfolio, record_date)

        if self.is_active:
            signal, executions, final_pf, is_rebalancing = self.execute_cycle(
                market_data, portfolio, regime, exposure, nan_fields, sim_date, record_date
            )
        else:
            signal, executions, final_pf, is_rebalancing = self.deactivated_cycle(
                portfolio, regime, exposure, nan_fields, record_date
            )

        # Step 6: 저장 (NaN 데이터 품질 이상 시 전체 스킵 — step 4 API 오류와 동일 처리)
        self.logger.info(">>> Step 6: Archiving Data")
        if not nan_fields:
            self.persist(market_data, signal, executions, final_pf, regime, exposure,
                         is_rebalancing, sim_date, expected_dividend, record_date,
                         self._benchmark_prices, self._last_order_result)
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
            expected_dividend=expected_dividend,
            order_result=self._last_order_result,
        )

    # ── Common flow and strategy hooks ───────────────────────────────────────

    def data_spec(self) -> StrategyDataSpec:
        """전략이 필요로 하는 원천 데이터 선언."""
        return StrategyDataSpec(
            reference=DataSetSpec("reference", ("SPY",), days=400),
        )

    def collect_data(self, data_provider: IDataProvider) -> CollectedData:
        """Step 1: 선언된 모든 OHLCV와 VIX를 공통 경로로 수집한다."""
        spec = self.data_spec()
        frames = {
            dataset.key: data_provider.fetch_ohlcv(
                list(dataset.tickers), days=dataset.days
            )
            for dataset in spec.datasets
        }
        return CollectedData(frames=frames, vix=data_provider.fetch_vix(), spec=spec)

    def calculate_indicators(self, collected: CollectedData) -> MarketData:
        """Step 2: 기준 지표와 전략 전용 지표를 한 파이프라인에서 계산한다."""
        market_data = self.calculator.calculate(collected.reference, collected.vix)
        self.strategy_indicators = self.calculate_strategy_indicators(collected)
        return market_data

    def calculate_strategy_indicators(self, collected: CollectedData) -> Any:
        """전략 전용 지표 훅. 공통 기준 지표 계산 뒤 한 번 호출된다."""
        return None

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

    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        """이 엔진의 의사결정 핵심 요소 목록 (Step 6에서 저장, 대시보드 표시용).

        첫 항목이 대시보드 카드의 대표(헤드라인) 요소가 된다.
        기본 전략은 국면 판단이 핵심이므로 국면 관련 지표를 반환하며,
        서브클래스는 자기 전략의 실제 결정요소로 오버라이드한다.
        """
        return [
            DecisionFactor("regime", "시장 국면", regime.value, "text"),
            DecisionFactor("momentum", "SPY 모멘텀", market_data.spy_momentum, "percent"),
            DecisionFactor("vix", "VIX", market_data.vix, "number", threshold=30.0),
            DecisionFactor("mdd", "SPY MDD", market_data.spy_mdd, "percent", threshold=-0.20),
            DecisionFactor("volatility", "실현변동성(21d)", market_data.spy_volatility,
                           "percent", threshold=self.targeter.target_vol),
        ]

    def get_portfolio(self) -> Portfolio:
        """Step 4: 포트폴리오 조회 후 실시간 가격 업데이트 + 벤치마크 현재가 수집."""
        portfolio = self.broker.get_portfolio()
        self.logger.info("Fetching Real-time prices from Broker...")
        orphan_tickers = [
            t for t in portfolio.holdings
            if portfolio.holdings[t] > 0 and t not in self.all_tickers
        ]
        fetch_tickers = self.all_tickers + orphan_tickers
        real_time_prices = self.broker.fetch_current_prices(fetch_tickers)
        for ticker, price in real_time_prices.items():
            if price > 0:
                portfolio.current_prices[ticker] = price
        self._benchmark_prices = self._fetch_benchmark_prices()
        return portfolio

    def _fetch_benchmark_prices(self) -> dict:
        """벤치마크 {논리명: 현재가}를 self.broker로 조회한다.

        실패하거나 가격이 0 이하인 티커는 제외한다. 벤치마크 미설정 시 {} 반환.
        부가 지표이므로 매매 사이클을 막지 않는다.
        """
        if not self.benchmarks:
            return {}
        try:
            raw = self.broker.fetch_current_prices(list(self.benchmarks.values()))
            return {
                name: raw[ticker]
                for name, ticker in self.benchmarks.items()
                if raw.get(ticker, 0) > 0
            }
        except Exception as e:
            self.logger.warning(f"벤치마크 현재가 조회 실패, 빈 값으로 처리: {e}")
            return {}

    def _settle_expected_dividend(self, portfolio: Portfolio, record_date: str) -> float:
        """Calculate and settle the current holdings' expected dividend."""
        if self.dividend_rate_provider is None:
            return 0.0

        tickers = [ticker for ticker, quantity in portfolio.holdings.items() if quantity > 0]
        if not tickers:
            return 0.0

        try:
            rates = self.dividend_rate_provider.get_dividend_rates(tickers, record_date)
        except Exception as error:
            self.logger.warning(f"Dividend-rate lookup failed; using zero: {error}")
            return 0.0

        try:
            expected_dividend = sum(
                quantity * float(rates.get(ticker, 0.0))
                for ticker, quantity in portfolio.holdings.items()
                if quantity > 0
            )
        except (AttributeError, TypeError, ValueError) as error:
            self.logger.warning(f"Invalid dividend-rate data; using zero: {error}")
            return 0.0

        if expected_dividend > 0 and self.dividend_settlement is not None:
            try:
                applied_amount = self.dividend_settlement.receive_dividend(expected_dividend)
            except Exception as error:
                self.logger.warning(f"Dividend settlement failed: {error}")
            else:
                if isinstance(applied_amount, (int, float)) and not isinstance(applied_amount, bool):
                    portfolio.total_cash += applied_amount
                else:
                    self.logger.warning("Dividend settlement returned a non-numeric applied amount")

        return expected_dividend

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
        """Step 5 공통 흐름: 안전 분기 → 전략 결정 → 주문 → 알림 → 상태 반영."""
        orphan_executions: List[TradeExecution] = []
        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = False
        strategy_result = OrderBatchResult([])
        self._orphan_order_result = OrderBatchResult([])

        if not nan_fields:
            orphan_tickers = self._detect_orphan_holdings(portfolio)
            if orphan_tickers:
                self.logger.info(">>> Step 4.5: Orphan Holdings Liquidation")
                self._notify_alert(
                    f"⚠️ 엔진 변경 감지: 이전 엔진 종목 {len(orphan_tickers)}건 자동 청산",
                    detail=self._cycle_detail(),
                )
                orphan_executions, portfolio = self._liquidate_orphans(portfolio, orphan_tickers)
                final_pf = portfolio

        zero_price_tickers = [
            t for t, q in portfolio.holdings.items()
            if q > 0 and portfolio.current_prices.get(t, 0) <= 0
        ]

        target_ratio_a, rebalance_threshold = self.rebalancer.get_target_params(regime)

        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}",
                                 target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold)
            msg = (
                f"⚠️ Data Quality Alert — 매매 중단\n"
                f"날짜: {record_date}\n"
                f"NaN 필드: {', '.join(nan_fields)}\n"
                f"데이터 품질 이상으로 매매를 중단합니다."
            )
            self.logger.error(msg)
            self._notify_alert(msg, detail=self._cycle_detail())

        elif zero_price_tickers:
            display_names = [self.ticker_labels.display(t) for t in zero_price_tickers]
            signal = TradeSignal(0.0, [], f"가격 조회 실패 — 매매 중단: {', '.join(display_names)}",
                                 target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold)
            msg = (
                f"⚠️ Price Data Alert — 매매 중단\n"
                f"날짜: {record_date}\n"
                f"가격 조회 실패 종목: {', '.join(display_names)}\n"
                f"보유 종목 가격 이상으로 리밸런싱을 중단합니다.\n"
                f"total_value 왜곡으로 인한 비정상 주문 방지."
            )
            self.logger.error(msg)
            self._notify_alert(msg, detail=self._cycle_detail())

        elif (
            self.uses_trading_interval()
            and not self._is_due(sim_date)
            and regime != MarketRegime.CRASH
        ):
            signal = TradeSignal(exposure, [], f"{regime.value} (모니터링)",
                                 target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold)
            self.logger.info(
                f">>> Step 5: Monitoring "
                f"(리밸런싱 인터벌 미충족, {self.trading_interval_days}일 기준)"
            )
            self._notify_message(
                f"모니터링 완료. {regime.value} | ${portfolio.total_value:,.0f}",
                detail=self._cycle_detail(),
            )

        else:
            decision = self.build_strategy_decision(
                market_data, portfolio, regime, exposure
            )
            signal = decision.signal
            is_rebalancing = decision.is_rebalancing
            self.logger.info(f">>> Step 5: {decision.label} ({signal.reason})")

            if regime == MarketRegime.CRASH:
                crash_msg = self._build_crash_alert(market_data, portfolio)
                self.logger.error(crash_msg)
                self._notify_alert(crash_msg, detail=self._cycle_detail())

            if signal.has_orders:
                self.logger.info(f"Executing {len(signal.orders)} orders ({signal.reason})")
                strategy_result = self._execute_orders(signal.orders, sim_date)
                executions = strategy_result.actual_executions
                self._report_order_result(strategy_result, record_date)

                if executions:
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
                self.logger.info("No Rebalance Needed.")
                self._notify_message(
                    f"Bot Finished. Hold. ({regime.value})",
                    detail=self._cycle_detail(),
                )

            self.commit_strategy_state(decision, strategy_result)

        self._last_order_result = OrderBatchResult(
            self._orphan_order_result.outcomes + strategy_result.outcomes
        )
        return signal, orphan_executions + executions, final_pf, is_rebalancing

    def uses_trading_interval(self) -> bool:
        """전략 판단을 리밸런싱 주기로 제한할지 여부."""
        return True

    def build_strategy_decision(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
    ) -> StrategyDecision:
        """전략 특화 훅: 주문을 포함한 결정만 생성한다."""
        signal = self.rebalancer.generate_signal(portfolio, exposure, regime)
        return StrategyDecision(
            signal=signal,
            label="Rebalancing",
            is_rebalancing=True,
        )

    def finalize_strategy_state(
        self,
        decision: StrategyDecision,
        order_result: OrderBatchResult,
    ) -> Any:
        """전략 특화 훅: 주문 결과로 다음 상태를 확정한다."""
        return decision.proposed_state

    def commit_strategy_state(
        self,
        decision: StrategyDecision,
        order_result: OrderBatchResult,
    ) -> None:
        """상태 저장은 공통 흐름에서만 수행한다."""
        if not decision.state_key:
            return
        state = self.finalize_strategy_state(decision, order_result)
        if state is None:
            return
        self.repo.save_strategy_state(decision.state_key, state.to_dict())

    def restore_strategy_state(self, state_key: str) -> dict:
        """전략 상태 로드는 베이스 엔진을 통해서만 수행한다."""
        return self.repo.load_strategy_state(state_key)

    def _execute_orders(self, orders: List[Order], attempted_at: Optional[str] = None) -> OrderBatchResult:
        attempted_at = attempted_at or datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
        raw_result = self.broker.execute_orders(orders)
        result = self._normalize_order_result(orders, raw_result)
        return OrderBatchResult([outcome if outcome.attempted_at else replace(outcome, attempted_at=attempted_at) for outcome in result.outcomes])

    def _normalize_order_result(
        self,
        orders: List[Order],
        raw_result,
    ) -> OrderBatchResult:
        """구형 테스트 더블도 요청별 결과 계약으로 안전하게 승격한다."""
        if isinstance(raw_result, OrderBatchResult):
            if raw_result.total == len(orders):
                return raw_result
            executions = raw_result.reported_executions
        else:
            executions = list(raw_result or [])

        remaining = list(executions)
        outcomes: List[OrderOutcome] = []
        for order in orders:
            match_index = next(
                (
                    index for index, execution in enumerate(remaining)
                    if execution.ticker == order.ticker
                    and execution.action == order.action
                ),
                None,
            )
            # 구형 테스트 더블은 상세 필드 없는 객체를 요청 순서대로 반환했다.
            if match_index is None and remaining:
                match_index = 0
            if match_index is None:
                outcomes.append(OrderOutcome(
                    order,
                    ExecutionStatus.ERROR,
                    reason="broker returned no result for requested order",
                ))
                continue
            execution = remaining.pop(match_index)
            if not isinstance(execution, TradeExecution):
                ticker = order.ticker if isinstance(order.ticker, str) else "LEGACY"
                action = (
                    order.action
                    if isinstance(order.action, OrderAction)
                    else OrderAction.BUY
                )
                quantity = (
                    order.quantity
                    if isinstance(order.quantity, int) and order.quantity > 0
                    else 1
                )
                price = (
                    float(order.price)
                    if isinstance(order.price, (int, float))
                    else 0.0
                )
                execution = TradeExecution(
                    ticker=ticker,
                    action=action,
                    quantity=quantity,
                    price=price,
                    fee=0.0,
                    date=datetime.now(
                        timezone(timedelta(hours=9))
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                    status=ExecutionStatus.FILLED,
                    reason="legacy broker result",
                )
            outcomes.append(OrderOutcome(
                order,
                execution.status,
                execution,
                execution.reason,
            ))
        return OrderBatchResult(outcomes)

    def _report_order_result(
        self,
        result: OrderBatchResult,
        record_date: str,
    ) -> None:
        statuses = " ".join(
            f"{status.value.lower()}={result.count(status)}"
            for status in ExecutionStatus
        )
        self.logger.info(f"Order Summary: total={result.total} {statuses}")

        if result.warning_outcomes:
            lines = []
            for outcome in result.warning_outcomes:
                reason = outcome.reason or (
                    outcome.execution.reason if outcome.execution else ""
                )
                lines.append(
                    f"- {outcome.order.action} {outcome.order.ticker} "
                    f"{outcome.order.quantity}주: {outcome.status.value}"
                    f"{f' — {reason}' if reason else ''}"
                )
            message = (
                f"⚠️ Order Result Alert\n"
                f"날짜: {record_date}\n"
                + "\n".join(lines)
            )
            self.logger.error(message)
            self._notify_alert(message, detail=self._cycle_detail())
        elif result.actual_executions:
            self._notify_message(
                f"✅ Orders Executed. Count: {len(result.actual_executions)}",
                detail=self._cycle_detail(),
            )
        elif result.outcomes:
            self.logger.info("All orders intentionally skipped; no alert sent.")

    def deactivated_cycle(
        self,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
        nan_fields: List[str],
        record_date: str,
    ) -> Tuple[TradeSignal, List[TradeExecution], Portfolio, bool]:
        """비활성 계좌용 Step 5: 매매 없이 조회 결과만 확정한다.

        매매(execute_orders)·신호 생성(rebalancer)은 건너뛰지만, 자산평가 정확성이
        비활성 모드의 목적이므로 활성 경로와 동일한 데이터 품질 검증(NaN / 보유 종목
        0가격)은 유지해 문제 발생 시 Slack 경고를 보낸다. 검증 통과 시 조회 전용
        신호를 만들고, decision_factors 렌더링에 필요한 target_ratio_a/
        rebalance_threshold는 활성 분기와 동일하게 채운다. 반환 후 Step 6 persist가
        조회한 포트폴리오를 저장하므로 최신 자산평가·국면이 갱신된다.
        """
        target_ratio_a, rebalance_threshold = self.rebalancer.get_target_params(regime)

        # 데이터 품질 이상(NaN): Step 6에서 저장이 스킵되므로 알림만 보내 문제를 알린다.
        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}",
                                 target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold)
            msg = (
                f"⚠️ Data Quality Alert (비활성) — 조회 결과 저장 중단\n"
                f"날짜: {record_date}\n"
                f"NaN 필드: {', '.join(nan_fields)}\n"
                f"데이터 품질 이상으로 이번 조회 결과는 저장하지 않습니다."
            )
            self.logger.error(msg)
            self._notify_alert(msg, detail=self._cycle_detail())
            return signal, [], portfolio, False

        # 보유 종목 가격 조회 실패(0.0 또는 누락): 저장되는 자산평가가 왜곡되므로 경고한다.
        zero_price_tickers = [
            t for t, q in portfolio.holdings.items()
            if q > 0 and portfolio.current_prices.get(t, 0) <= 0
        ]
        if zero_price_tickers:
            display_names = [self.ticker_labels.display(t) for t in zero_price_tickers]
            signal = TradeSignal(0.0, [], f"가격 조회 실패 — 자산평가 왜곡 가능: {', '.join(display_names)}",
                                 target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold)
            msg = (
                f"⚠️ Price Data Alert (비활성) — 자산평가 왜곡 가능성\n"
                f"날짜: {record_date}\n"
                f"가격 조회 실패 종목: {', '.join(display_names)}\n"
                f"보유 종목 가격 이상으로 저장되는 자산평가가 과소평가될 수 있습니다."
            )
            self.logger.error(msg)
            self._notify_alert(msg, detail=self._cycle_detail())
            return signal, [], portfolio, False

        signal = TradeSignal(
            exposure, [], f"{regime.value} (비활성 — 조회 전용)",
            target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold,
        )
        self.logger.info(">>> Step 5: Deactivated (조회 전용, 매매 스킵)")
        self._notify_message(
            f"🔒 비활성 계좌 — 조회만 수행. {regime.value} | ${portfolio.total_value:,.0f}",
            detail=self._cycle_detail(),
        )
        return signal, [], portfolio, False

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
        expected_dividend: float = 0.0,
        record_date: Optional[str] = None,
        benchmark_prices: Optional[dict] = None,
        order_result: Optional[OrderBatchResult] = None,
    ) -> None:
        """Step 6: 저장 3종 호출."""
        effective_record_date = record_date or sim_date or market_data.date
        rebalancing_date = effective_record_date if is_rebalancing else None
        factors = self.decision_factors(market_data, regime, exposure, signal, final_pf)
        self.repo.save_daily_summary(market_data, signal, final_pf, regime,
                                     expected_dividend=expected_dividend, date_override=record_date,
                                     benchmarks=benchmark_prices, executions=executions,
                                     decision_factors=factors)
        self.repo.save_trade_history(executions, final_pf, signal.reason, sim_date=sim_date)
        if order_result is not None:
            self.repo.save_order_events(order_result)
        self.repo.update_status(
            regime, exposure, final_pf, market_data, signal.reason,
            sim_date=sim_date,
            rebalancing_date=rebalancing_date,
            decision_factors=factors,
        )

    # ── Private helpers (NOT part of template) ────────────────────────────────

    def _is_due(self, sim_date: Optional[str]) -> bool:
        """마지막 리밸런싱 이후 trading_interval_days 이상 경과했으면 True."""
        last_str = self.repo.get_last_rebalancing_date()
        if last_str is None:
            return True
        try:
            last = pd.Timestamp(last_str)
            today = pd.Timestamp(sim_date) if sim_date \
                else pd.Timestamp(datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d"))
            diff_days = (today - last).days
            # sim_date가 last_rebalancing_date보다 과거이면 stale 데이터 → 리밸런싱 실행
            if diff_days < 0:
                return True
            return diff_days >= self.trading_interval_days
        except Exception:
            return True  # 파싱 실패 시 안전하게 리밸런싱 실행

    def _detect_orphan_holdings(self, portfolio: Portfolio) -> List[str]:
        """현재 엔진의 어떤 그룹에도 속하지 않는 보유 종목 티커 목록."""
        managed = set(self.all_tickers)
        return [t for t, q in portfolio.holdings.items() if q > 0 and t not in managed]

    def _liquidate_orphans(
        self, portfolio: Portfolio, orphan_tickers: List[str]
    ) -> Tuple[List[TradeExecution], Portfolio]:
        """고아 종목 전량 매도 → 체결 결과 + 갱신된 포트폴리오 반환."""
        orders = []
        for ticker in orphan_tickers:
            qty = portfolio.holdings.get(ticker, 0)
            price = portfolio.current_prices.get(ticker, 0)
            if qty > 0 and price > 0:
                orders.append(Order(ticker, OrderAction.SELL, qty, price))
                self.logger.info(
                    f"[고아 종목] {self.ticker_labels.display(ticker)}: {qty}주 @${price:,.0f} → 전량 매도"
                )
            elif qty > 0:
                self.logger.warning(
                    f"[고아 종목] {self.ticker_labels.display(ticker)}: {qty}주 보유 중이나 가격 조회 실패 → 매도 스킵"
                )

        if not orders:
            return [], portfolio

        self.logger.info(f">>> 고아 종목 청산: {len(orders)}건 매도 실행")
        result = self._execute_orders(orders)
        self._orphan_order_result = result
        record_date = datetime.now(
            timezone(timedelta(hours=9))
        ).strftime("%Y-%m-%d")
        self._report_order_result(result, record_date)
        executions = result.actual_executions

        if executions and self.is_live_trading:
            time.sleep(3)
        if not executions:
            return [], portfolio
        try:
            updated_pf = self.broker.get_portfolio()
        except Exception as e:
            self.logger.error(f"고아 청산 후 포트폴리오 조회 실패: {e}")
            return executions, portfolio

        try:
            all_fetch = self.all_tickers + orphan_tickers
            real_time_prices = self.broker.fetch_current_prices(all_fetch)
            for t, p in real_time_prices.items():
                if p > 0:
                    updated_pf.current_prices[t] = p
            self._benchmark_prices = self._fetch_benchmark_prices()
        except Exception as e:
            self.logger.warning(f"고아 청산 후 실시간 가격 조회 실패: {e}")

        return executions, updated_pf

    def _build_crash_alert(self, market_data: MarketData, portfolio: Portfolio) -> str:
        """CRASH 알림 메시지 생성 (포지션 정보 포함)."""
        holdings_lines = []
        for ticker, qty in portfolio.holdings.items():
            if qty > 0:
                price = portfolio.current_prices.get(ticker, 0)
                value = qty * price
                holdings_lines.append(
                    f"  • {self.ticker_labels.display(ticker)}: {qty}주 (${value:,.0f})"
                )
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
            self.notifier.send_message(msg, detail=detail, account_label=self.account_label)

    def _notify_alert(self, msg: str, detail: Optional[str] = None) -> None:
        if self.notifier:
            self.notifier.send_alert(msg, detail=detail, account_label=self.account_label)


@register_engine(color="#2ca02c", backtest=True)
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

    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        """Full Exposure 계열: 국면이 아니라 목표 비율 대비 이격도가 결정요소다."""
        groups = self.rebalancer.groups
        val_a = portfolio.get_group_value(groups.get('A', []))
        val_b = portfolio.get_group_value(groups.get('B', []))
        val_risky = val_a + val_b
        # 신호에 담긴 진단값 우선 (그 시점의 실제 판단 기준), 없으면 현재 설정값
        eff_a, threshold = self.rebalancer.get_target_params(regime)
        target_a = signal.target_ratio_a if signal.target_ratio_a is not None else eff_a
        rebalance_threshold = signal.rebalance_threshold \
            if signal.rebalance_threshold is not None else threshold

        factors = [
            DecisionFactor("target_ratio_a", "목표 A그룹 비율", target_a, "percent"),
        ]
        if val_risky > 0:
            current_a = val_a / val_risky
            factors.append(DecisionFactor("current_ratio_a", "현재 A그룹 비율",
                                          current_a, "percent"))
            if target_a > 0:
                rel_dev = abs(current_a - target_a) / target_a
                factors.append(DecisionFactor("group_deviation", "A그룹 상대이탈",
                                              rel_dev, "percent",
                                              threshold=rebalance_threshold))
        factors.append(DecisionFactor("rebalance_threshold", "리밸런싱 임계치",
                                      rebalance_threshold, "percent"))
        return factors
