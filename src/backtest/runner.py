# src/backtest/runner.py
import shutil
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from src.config import Config
from src.core.models import MarketRegime, TradeExecution, TradeSignal
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.infra.repo import JsonRepository
from src.utils.calculator import IndicatorCalculator
from src.utils.logger import TradeLogger
from src.backtest.fetcher import download_historical_data
from src.backtest.components import BacktestDataLoader, BacktestBroker


@dataclass
class BacktestResult:
    """백테스트 결과 구조체"""
    history: pd.DataFrame              # 날짜별 포트폴리오 이력
    initial_cash: float                # 초기 자금
    final_value: float                 # 최종 자산가치
    cagr: float                        # 연환산 수익률
    mdd: float                         # 최대 낙폭 (음수, 예: -0.25 = -25%)
    sharpe_ratio: float                # 샤프 비율 (연환산, 무위험수익률 0% 가정)
    spy_cagr: Optional[float]          # SPY Buy&Hold 연환산 수익률 (None = 데이터 없음)
    regime_returns: Dict[str, float]   # 국면별 연환산 평균 수익률
    chart_path: Optional[str]          # 저장된 차트 파일 경로
    trade_executions: Optional[List[TradeExecution]] = None  # 전체 매매 체결 기록
    trade_reason_summary: Optional[Dict[str, int]] = None  # 매매 사유별 발생 횟수


def _validate_tickers(full_df: pd.DataFrame, required: List[str], logger: TradeLogger) -> List[str]:
    """
    full_df에 실제로 수신된 티커와 required를 비교해 누락된 티커를 반환한다.
    누락이 있으면 경고를 출력하고, 호출자가 처리 방식을 결정한다.
    """
    if isinstance(full_df.columns, pd.MultiIndex):
        available = set(full_df.columns.get_level_values(1).unique())
    else:
        available = set(full_df.columns)

    missing = [t for t in required if t not in available]
    if missing:
        logger.warning(f"⚠️ 데이터 미수신 티커 {missing} — 백테스트를 중단합니다.")
    return missing


def run_backtest(start_date: str, end_date: str, initial_cash: float = 10000.0,
                  execution_interval: int = 1,
                  output_dir: str = "docs/data/backtest") -> Optional[BacktestResult]:
    # 0. 파라미터 검증
    if execution_interval < 1:
        raise ValueError(f"execution_interval은 1 이상이어야 합니다: {execution_interval}")

    # 1. 설정 로드
    config = Config()
    logger = TradeLogger(log_dir="logs/backtest")
    tickers = []
    for group in config.ASSET_GROUPS.values():
        tickers.extend(group)
    tickers = list(set(tickers)) # 중복 제거
    if "SPY" not in tickers:
        tickers.append("SPY")  # 벤치마크 계산에 필요

    # 2. 데이터 준비 (10년치 한방에 로딩)
    logger.info("--- Preparing Data ---")
    full_df, full_vix = download_historical_data(tickers, start_date, end_date)

    # 2-1. 수신 티커 검증: 누락 티커가 하나라도 있으면 즉시 종료
    if _validate_tickers(full_df, tickers, logger):
        return None

    # 3. 컴포넌트 조립
    loader = BacktestDataLoader(full_df, full_vix)
    broker = BacktestBroker(initial_cash, logger=logger)
    backtest_data_path = output_dir
    shutil.rmtree(backtest_data_path, ignore_errors=True)
    backtest_repo = JsonRepository(backtest_data_path)

    # Core Logic (그대로 재사용!)
    calculator = IndicatorCalculator()
    analyzer = RegimeAnalyzer()
    targeter = VolatilityTargeter(target_vol=0.15)
    rebalancer = Rebalancer(config.ASSET_GROUPS, logger=logger)

    # 4. 루프 실행 (Time Travel)
    # 실제 데이터가 있는 날짜(거래일)만 루프
    trading_days = full_df.index
    # 사용자가 요청한 구간으로 필터링
    sim_days = [d for d in trading_days if start_date <= d.strftime("%Y-%m-%d") <= end_date]

    all_executions: List[TradeExecution] = []
    trade_reason_counter: Dict[str, int] = {}  # 매매 사유별 카운터
    days_since_last_execution = execution_interval  # 첫날 즉시 실행되도록 초기화

    # 히스테리시스 상태 복원 (main.py 방식: repo에서 마지막 국면 로드)
    last_regime = backtest_repo.load_last_regime()
    if last_regime is not None:
        analyzer._prev_regime = last_regime
        logger.info(f"Restored previous regime: {last_regime.value}")

    logger.info(f"--- Starting Backtest ({len(sim_days)} trading days, interval={execution_interval}) ---")

    for today in sim_days:
        logger.info(f"[{today.date()}]시작")
        # [Time Setting] 오늘 날짜 설정
        loader.set_date(today)
        broker.set_date(today)

        # [Price Injection] 오늘 종가를 브로커에 주입 (종가 매매 가정)
        current_prices = {}
        try:
            # 가장 확실한 방법: full_df['Close']에서 추출
            close_prices = full_df['Close'].loc[today]
            current_prices = close_prices.to_dict()

        except Exception as e:
            logger.warning(f"[{today.date()}] 종가 추출 실패, 건너뜀: {e}")
            continue

        broker.set_prices(current_prices)

        # 실행 간격 체크: is_execution_day 플래그로 분기 (지표 계산은 항상 실행)
        days_since_last_execution += 1
        is_execution_day = days_since_last_execution >= execution_interval
        if is_execution_day:
            days_since_last_execution = 0  # 실행일: 카운터 리셋

        # === 봇 로직 실행 (Main.py와 동일 흐름) ===
        try:
            # 1. 지표 계산 (항상 실행)
            df_slice = loader.fetch_ohlcv(["SPY"], days=400)
            vix_val = loader.fetch_vix()
            market_data = calculator.calculate(df_slice, vix_val)

            # 2. 전략 판단 (NaN 체크 + 국면/노출도 계산)
            nan_fields = market_data.nan_fields()
            nan_triggered = bool(nan_fields)  # NaN 여부를 별도로 추적
            # 국면 변화 감지를 위해 analyze() 호출 전에 캡처 (main.py 방식과 동일)
            prev_regime_for_log = analyzer._prev_regime
            if nan_triggered:
                # NaN → 데이터 품질 이상으로 매매 중단 (신뢰할 수 없는 데이터로 거래 불가)
                regime = MarketRegime.CRASH
                exposure = 0.0
            else:
                regime = analyzer.analyze(market_data)
                exposure = targeter.calculate_exposure(regime, market_data.spy_volatility)

            # 국면 변화 로그 (analyzer._prev_regime은 analyze() 내부에서 자동 갱신됨)
            if prev_regime_for_log is not None and regime != prev_regime_for_log:
                logger.info(
                    f"[{today.date()}] Regime Change: {prev_regime_for_log.value} → {regime.value} "
                    f"(Price={market_data.spy_price:.2f}, MA180={market_data.spy_ma180:.2f}, "
                    f"Momentum={market_data.spy_momentum:.4f}, VIX={market_data.vix:.1f}, MDD={market_data.spy_mdd:.2%})"
                )

            # 3. 포트폴리오 현황 조회 (main.py Step 4 방식 — 조건 분기 전 무조건 실행)
            current_pf = broker.get_portfolio()
            current_pf.current_prices = current_prices  # 가격 동기화

            # 4. 조건 분기 (main.py 동기화)
            day_executions: List[TradeExecution] = []
            if nan_triggered:
                # NaN: signal 생성 후 저장까지 진행
                signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}")
            elif not is_execution_day and regime != MarketRegime.CRASH:
                # 모니터링 날: 인터벌 미충족 & non-CRASH → 리밸런싱 없이 저장만
                signal = TradeSignal(exposure, [], f"{regime.value} (모니터링)")
            else:
                # 리밸런싱 실행 (CRASH는 인터벌 무시하고 즉시 실행)
                signal = rebalancer.generate_signal(current_pf, exposure, regime)

                if signal.has_orders:
                    # 매매 사유 로그: 왜 매수/매도하는지 기록
                    logger.info(
                        f"[{today.date()}] {regime.value} | Exposure={exposure:.2f} | "
                        f"Reason: {signal.reason}"
                    )
                    logger.info(
                        f"  Market: SPY={market_data.spy_price:.2f}, MA180={market_data.spy_ma180:.2f}, "
                        f"Momentum={market_data.spy_momentum:.4f}, Vol={market_data.spy_volatility:.4f}, "
                        f"VIX={market_data.vix:.1f}, MDD={market_data.spy_mdd:.2%}"
                    )
                    for order in signal.orders:
                        logger.info(
                            f"  → {order.action} {order.ticker} x{order.quantity} @${order.price:.2f}"
                        )
                    day_executions = broker.execute_orders(signal.orders)
                    all_executions.extend(day_executions)
                    # 매매 사유 카운터 집계
                    trade_reason_counter[signal.reason] = trade_reason_counter.get(signal.reason, 0) + 1

            # 5. 결과 기록 (NaN 포함 항상 실행 — main.py 동기화)
            final_pf = broker.get_portfolio()
            sim_date_str = today.strftime("%Y-%m-%d")
            backtest_repo.save_daily_summary(market_data, signal, final_pf, regime)
            backtest_repo.save_trade_history(day_executions, final_pf, signal.reason, sim_date=sim_date_str)
            backtest_repo.update_status(regime, exposure, final_pf, market_data, signal.reason, sim_date=sim_date_str)

        except Exception as e:
            logger.error(f"Error on {today.date()}: {e}")

    # 5. 결과 분석 및 시각화
    logger.info("--- Backtest Finished ---")

    summary_data = backtest_repo._load_json(backtest_repo.summary_file, default=[])
    if not summary_data:
        logger.warning("No trading data available for the given period.")
        return None

    res_df = pd.DataFrame(summary_data)
    res_df["date"] = pd.to_datetime(res_df["date"])
    res_df = res_df.set_index("date")
    # 파생 컬럼: 체결 수 (executions 없는 날은 0)
    if "executions" in res_df.columns:
        res_df["trade_count"] = res_df["executions"].apply(
            lambda x: len(x) if isinstance(x, list) else 0
        )
    else:
        res_df["trade_count"] = 0

    # CAGR (연환산 수익률)
    final_value = res_df.iloc[-1]['total_value']
    years = (res_df.index[-1] - res_df.index[0]).days / 365.25
    cagr = (final_value / initial_cash) ** (1 / years) - 1 if years > 0 else 0.0

    # MDD (최대 낙폭)
    peak = res_df['total_value'].cummax()
    drawdown = (res_df['total_value'] - peak) / peak
    mdd = float(drawdown.min())

    # Sharpe Ratio (연환산, 무위험수익률 0% 가정)
    daily_returns = res_df['total_value'].pct_change().dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe_ratio = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))
    else:
        sharpe_ratio = 0.0

    # SPY 벤치마크 (Buy & Hold)
    spy_cagr = None
    try:
        spy_prices = full_df['Close']['SPY'].loc[sim_days].dropna()
        if len(spy_prices) >= 2:
            spy_return = spy_prices.iloc[-1] / spy_prices.iloc[0] - 1
            spy_cagr = float((1 + spy_return) ** (1 / years) - 1) if years > 0 else 0.0
    except Exception:
        spy_cagr = None

    # 국면별 연환산 평균 수익률
    res_df['daily_return'] = res_df['total_value'].pct_change()
    regime_returns: Dict[str, float] = {}
    for regime_val, group in res_df.groupby('regime'):
        regime_daily = group['daily_return'].dropna()
        if len(regime_daily) > 0:
            regime_returns[str(regime_val)] = float(regime_daily.mean() * 252)

    # 결과 출력
    logger.info(f"Initial: ${initial_cash:,.0f} -> Final: ${final_value:,.0f}")
    logger.info(f"CAGR: {cagr:.2%} | MDD: {mdd:.2%} | Sharpe: {sharpe_ratio:.2f}")
    if spy_cagr is not None:
        logger.info(f"SPY Buy&Hold CAGR: {spy_cagr:.2%} | Excess CAGR: {cagr - spy_cagr:.2%}")
    if regime_returns:
        logger.info("Regime Returns (annualized avg daily):")
        for regime_name, regime_ret in regime_returns.items():
            logger.info(f"  {regime_name}: {regime_ret:.2%}")

    # 거래 통계 출력
    logger.info(f"Total Executions: {len(all_executions)}")
    if all_executions:
        ticker_counts = Counter(e.ticker for e in all_executions)
        action_counts = Counter(f"{e.ticker}/{e.action}" for e in all_executions)
        logger.info(f"Trade Frequency by Ticker: {dict(ticker_counts)}")
        logger.info(f"Trade Frequency by Ticker/Action: {dict(action_counts)}")

    # 매매 사유별 통계 출력
    if trade_reason_counter:
        logger.info("Trade Reasons:")
        for reason, count in sorted(trade_reason_counter.items(), key=lambda x: -x[1]):
            logger.info(f"  {reason}: {count}회")

    # 차트 저장 (plt.show() 대신 파일로 저장)
    Path("docs").mkdir(parents=True, exist_ok=True)
    chart_path = f"{output_dir}/backtest_{start_date}_{end_date}.png"
    plt.figure(figsize=(12, 6))
    plt.plot(res_df['total_value'], label='Portfolio Value')
    if spy_cagr is not None:
        try:
            spy_benchmark = full_df['Close']['SPY'].loc[sim_days].dropna()
            spy_scaled = spy_benchmark / spy_benchmark.iloc[0] * initial_cash
            plt.plot(spy_scaled, label=f'SPY Buy&Hold (CAGR: {spy_cagr:.2%})',
                     linestyle='--', alpha=0.7)
        except Exception:
            pass
    plt.title(f"Backtest Result ({start_date} ~ {end_date})")
    plt.legend()
    plt.savefig(chart_path)
    plt.close()
    logger.info(f"Chart saved: {chart_path}")

    return BacktestResult(
        history=res_df,
        initial_cash=initial_cash,
        final_value=final_value,
        cagr=cagr,
        mdd=mdd,
        sharpe_ratio=sharpe_ratio,
        spy_cagr=spy_cagr,
        regime_returns=regime_returns,
        chart_path=chart_path,
        trade_executions=all_executions,
        trade_reason_summary=trade_reason_counter if trade_reason_counter else None,
    )


if __name__ == "__main__":
    # 사용 예시: 2015년부터 2023년까지 테스트
    run_backtest("2015-01-01", "2023-12-31")
