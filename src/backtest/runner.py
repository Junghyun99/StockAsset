# src/backtest/runner.py
import shutil
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from src.strategy_config import StrategyConfig
from src.core.models import TradeExecution
from src.core.engine import (
    TradingEngine, FullExposureEngine, QldSHVEngine, QldSchdEngine,
)
from src.infra.repo import JsonRepository
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
    total_dividend_income: float = 0.0  # 시뮬레이션 기간 중 수령한 총 배당금


@dataclass
class CompareBacktestResult:
    """엔진 비교 백테스트 결과 구조체"""
    engine_results: Dict[str, BacktestResult]  # {엔진명: BacktestResult}
    spy_cagr: Optional[float]
    chart_path: Optional[str]


def _calculate_dividend_income(
    today: pd.Timestamp,
    dividends_df: pd.DataFrame,
    broker: "BacktestBroker",
) -> float:
    """오늘 날짜의 배당금 × 보유 주수를 합산해 반환. 오류 시 0.0."""
    try:
        if dividends_df is None or dividends_df.empty:
            return 0.0
        if today not in dividends_df.index:
            return 0.0
        row = dividends_df.loc[today]
        total = 0.0
        for ticker, div_per_share in row.items():
            if div_per_share > 0:
                shares = broker.holdings.get(ticker, 0)
                total += shares * float(div_per_share)
        return total
    except Exception:
        return 0.0


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


def _calculate_metrics(
    summary_data: list,
    initial_cash: float,
    full_df: pd.DataFrame,
    sim_days: list,
) -> Optional[Tuple[pd.DataFrame, float, float, float, float, Optional[float], Dict[str, float]]]:
    """백테스트 결과 메트릭을 계산한다.

    Returns:
        (res_df, final_value, cagr, mdd, sharpe_ratio, spy_cagr, regime_returns)
        또는 데이터가 없으면 None
    """
    if not summary_data:
        return None

    res_df = pd.DataFrame(summary_data)
    res_df["date"] = pd.to_datetime(res_df["date"])
    res_df = res_df.set_index("date")
    if "executions" in res_df.columns:
        res_df["trade_count"] = res_df["executions"].apply(
            lambda x: len(x) if isinstance(x, list) else 0
        )
    else:
        res_df["trade_count"] = 0

    # CAGR
    final_value = res_df.iloc[-1]['total_value']
    years = (res_df.index[-1] - res_df.index[0]).days / 365.25
    cagr = (final_value / initial_cash) ** (1 / years) - 1 if years > 0 else 0.0

    # MDD
    peak = res_df['total_value'].cummax()
    drawdown = (res_df['total_value'] - peak) / peak
    mdd = float(drawdown.min())

    # Sharpe Ratio
    daily_returns = res_df['total_value'].pct_change().dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe_ratio = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))
    else:
        sharpe_ratio = 0.0

    # SPY 벤치마크
    spy_cagr = None
    try:
        spy_prices = full_df['Close']['SPY'].loc[sim_days].dropna()
        if len(spy_prices) >= 2:
            spy_return = spy_prices.iloc[-1] / spy_prices.iloc[0] - 1
            spy_cagr = float((1 + spy_return) ** (1 / years) - 1) if years > 0 else 0.0
    except Exception:
        spy_cagr = None

    # 국면별 수익률
    res_df['daily_return'] = res_df['total_value'].pct_change()
    regime_returns: Dict[str, float] = {}
    for regime_val, group in res_df.groupby('regime'):
        regime_daily = group['daily_return'].dropna()
        if len(regime_daily) > 0:
            regime_returns[str(regime_val)] = float(regime_daily.mean() * 252)

    return res_df, final_value, cagr, mdd, sharpe_ratio, spy_cagr, regime_returns


def run_backtest(start_date: str, end_date: str, initial_cash: float = 10000.0,
                  execution_interval: int = 1,
                  output_dir: str = "docs/data/backtest",
                  ratio_a: float = 0.5,
                  engine_class: type = TradingEngine,
                  run_number: Optional[str] = None,
                  reinvest_dividends: bool = True) -> Optional[BacktestResult]:
    # 0. 파라미터 검증
    if execution_interval < 1:
        raise ValueError(f"execution_interval은 1 이상이어야 합니다: {execution_interval}")

    # 1. 설정 로드
    strategy = StrategyConfig(trading_interval_days=execution_interval)
    logger = TradeLogger(log_dir="logs/backtest")

    # 엔진 클래스가 ASSET_GROUPS/REBALANCE_RATIO_A를 정의한 경우 해당 값을 우선 사용
    # (QldSchdEngine, QldSHVEngine 등 특수 엔진은 자체 자산군이 단일 진실 원천)
    effective_asset_groups = getattr(engine_class, 'ASSET_GROUPS', strategy.ASSET_GROUPS)
    effective_ratio_a = getattr(engine_class, 'REBALANCE_RATIO_A', ratio_a)

    tickers = []
    for group in effective_asset_groups.values():
        tickers.extend(group)
    tickers = list(set(tickers))  # 중복 제거
    if "SPY" not in tickers:
        tickers.append("SPY")  # 벤치마크 계산에 필요

    # 2. 데이터 준비 (10년치 한방에 로딩)
    logger.info("--- Preparing Data ---")
    full_df, full_vix, full_dividends = download_historical_data(tickers, start_date, end_date)

    # 2-1. 수신 티커 검증: 누락 티커가 하나라도 있으면 즉시 종료
    if _validate_tickers(full_df, tickers, logger):
        return None

    # 3. 컴포넌트 조립
    loader = BacktestDataLoader(full_df, full_vix)
    broker = BacktestBroker(initial_cash, logger=logger)
    backtest_data_path = output_dir
    # PNG는 누적 기록 보존, JSON만 삭제
    existing_dir = Path(backtest_data_path)
    if existing_dir.exists():
        for f in existing_dir.iterdir():
            if f.suffix == ".json":
                f.unlink()
    backtest_repo = JsonRepository(backtest_data_path, asset_groups=effective_asset_groups)

    # 3-1. TradingEngine 조립 (core 로직은 엔진 내부에서 생성)
    engine = engine_class(
        asset_groups=effective_asset_groups,
        ratio_a=effective_ratio_a,
        broker=broker,
        repo=backtest_repo,
        logger=logger,
        trading_interval_days=strategy.TRADING_INTERVAL_DAYS,
        notifier=None,          # 백테스트는 알림 없음
        is_live_trading=False,
    )

    # 4. 루프 실행 (Time Travel)
    trading_days = full_df.index
    sim_days = [d for d in trading_days if start_date <= d.strftime("%Y-%m-%d") <= end_date]

    all_executions: List[TradeExecution] = []
    trade_reason_counter: Dict[str, int] = {}
    total_dividend_income: float = 0.0

    logger.info(f"--- Starting Backtest ({len(sim_days)} trading days, interval={strategy.TRADING_INTERVAL_DAYS}) ---")

    for today in sim_days:
        logger.info(f"[{today.date()}]시작")

        # [Time Setting] 오늘 날짜 설정
        loader.set_date(today)
        broker.set_date(today)

        # [Price Injection] 오늘 종가를 브로커에 주입 (종가 매매 가정)
        try:
            close_prices = full_df['Close'].loc[today]
            current_prices = close_prices.to_dict()
            # NaN 가격 제거: yfinance에서 특정 날짜에 데이터가 없을 수 있음
            # NaN이 있으면 직전 설정 가격(broker.simulation_prices)을 유지
            current_prices = {
                t: (p if not (isinstance(p, float) and np.isnan(p))
                    else broker.simulation_prices.get(t, 0.0))
                for t, p in current_prices.items()
            }
        except Exception as e:
            logger.warning(f"[{today.date()}] 종가 추출 실패, 건너뜀: {e}")
            continue

        broker.set_prices(current_prices)

        # [Dividend] 배당금 처리 (매일, 종가 주입 직후)
        if reinvest_dividends:
            div_income = _calculate_dividend_income(today, full_dividends, broker)
            if div_income > 0:
                broker.receive_dividends(div_income)
                total_dividend_income += div_income

        sim_date = today.strftime("%Y-%m-%d")

        try:
            result = engine.run_one_cycle(loader, sim_date=sim_date)

            all_executions.extend(result.executions)

            # 매매 사유 카운터 집계
            if result.signal.has_orders:
                trade_reason_counter[result.signal.reason] = (
                    trade_reason_counter.get(result.signal.reason, 0) + 1
                )

            # 백테스트 전용: 리밸런싱 상세 로그
            if result.is_rebalancing and result.signal.has_orders:
                logger.info(
                    f"[{today.date()}] {result.regime.value} | Exposure={result.exposure:.2f} | "
                    f"Reason: {result.signal.reason}"
                )
                logger.info(
                    f"  Market: SPY={result.market_data.spy_price:.2f}, "
                    f"MA180={result.market_data.spy_ma180:.2f}, "
                    f"Momentum={result.market_data.spy_momentum:.4f}, "
                    f"Vol={result.market_data.spy_volatility:.4f}, "
                    f"VIX={result.market_data.vix:.1f}, MDD={result.market_data.spy_mdd:.2%}"
                )
                for order in result.signal.orders:
                    logger.info(
                        f"  → {order.action} {order.ticker} x{order.quantity} @${order.price:.2f}"
                    )

        except Exception as e:
            logger.error(f"Error on {today.date()}: {e}")

    # 5. 결과 분석 및 시각화
    logger.info("--- Backtest Finished ---")

    summary_data = backtest_repo._load_json(backtest_repo.summary_file, default=[])
    metrics = _calculate_metrics(summary_data, initial_cash, full_df, sim_days)
    if metrics is None:
        logger.warning("No trading data available for the given period.")
        return None

    res_df, final_value, cagr, mdd, sharpe_ratio, spy_cagr, regime_returns = metrics

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
    if reinvest_dividends and total_dividend_income > 0:
        logger.info(f"Total Dividend Income Reinvested: ${total_dividend_income:,.2f}")

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
    run_suffix = f"_{run_number}" if run_number else ""
    chart_path = f"{output_dir}/backtest_{start_date}_{end_date}{run_suffix}.png"
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
        total_dividend_income=total_dividend_income,
    )


# --- 엔진 비교 백테스트 ---

ENGINE_REGISTRY: List[Tuple[str, type]] = [
    ("TradingEngine", TradingEngine),
    ("FullExposureEngine", FullExposureEngine),
    ("QldSHVEngine", QldSHVEngine),
    ("QldSchdEngine", QldSchdEngine),
]

_ENGINE_COLORS: Dict[str, str] = {
    "TradingEngine": "#1f77b4",
    "FullExposureEngine": "#2ca02c",
    "QldSHVEngine": "#ff7f0e",
    "QldSchdEngine": "#d62728",
}


def run_compare_backtest(
    start_date: str,
    end_date: str,
    initial_cash: float = 10000.0,
    execution_interval: int = 1,
    output_dir: str = "docs/data/backtest/compare",
    run_number: Optional[str] = None,
    reinvest_dividends: bool = True,
) -> Optional[CompareBacktestResult]:
    """모든 엔진을 동시에 실행하고 결과를 비교한다."""
    if execution_interval < 1:
        raise ValueError(f"execution_interval은 1 이상이어야 합니다: {execution_interval}")

    strategy = StrategyConfig(trading_interval_days=execution_interval)
    logger = TradeLogger(log_dir="logs/backtest")

    # 1. 전체 엔진의 티커 합집합 수집
    all_tickers: set = set()
    for _, eng_cls in ENGINE_REGISTRY:
        groups = getattr(eng_cls, 'ASSET_GROUPS', strategy.ASSET_GROUPS)
        for group_tickers in groups.values():
            all_tickers.update(group_tickers)
    all_tickers.add("SPY")
    tickers = list(all_tickers)

    # 2. 데이터 1회 다운로드
    logger.info("--- Preparing Data (Compare Mode) ---")
    full_df, full_vix, full_dividends = download_historical_data(tickers, start_date, end_date)

    if _validate_tickers(full_df, tickers, logger):
        return None

    # 3. 거래일 산출
    trading_days = full_df.index
    sim_days = [d for d in trading_days if start_date <= d.strftime("%Y-%m-%d") <= end_date]

    # 4. 엔진별 독립 컴포넌트 생성
    engines: Dict[str, dict] = {}
    for name, eng_cls in ENGINE_REGISTRY:
        eff_groups = getattr(eng_cls, 'ASSET_GROUPS', strategy.ASSET_GROUPS)
        eff_ratio = getattr(eng_cls, 'REBALANCE_RATIO_A', 0.5)

        eng_output = f"{output_dir}/{name}"
        eng_path = Path(eng_output)
        if eng_path.exists():
            shutil.rmtree(eng_path)

        loader = BacktestDataLoader(full_df, full_vix)
        broker = BacktestBroker(initial_cash, logger=logger)
        repo = JsonRepository(eng_output, asset_groups=eff_groups)
        engine = eng_cls(
            asset_groups=eff_groups,
            ratio_a=eff_ratio,
            broker=broker,
            repo=repo,
            logger=logger,
            trading_interval_days=strategy.TRADING_INTERVAL_DAYS,
            notifier=None,
            is_live_trading=False,
        )
        engines[name] = {
            "engine": engine,
            "loader": loader,
            "broker": broker,
            "repo": repo,
            "executions": [],
            "reason_counter": {},
            "dividend_income": 0.0,
        }

    # 5. 시뮬레이션 루프
    logger.info(f"--- Starting Compare Backtest ({len(sim_days)} trading days) ---")

    for today in sim_days:
        # 종가 추출 (1회, 공유)
        try:
            close_prices = full_df['Close'].loc[today]
            current_prices = close_prices.to_dict()
            current_prices = {
                t: (p if not (isinstance(p, float) and np.isnan(p)) else 0.0)
                for t, p in current_prices.items()
            }
        except Exception as e:
            logger.warning(f"[{today.date()}] 종가 추출 실패, 건너뜀: {e}")
            continue

        sim_date = today.strftime("%Y-%m-%d")

        for name, ctx in engines.items():
            ctx["loader"].set_date(today)
            ctx["broker"].set_date(today)
            ctx["broker"].set_prices(current_prices)

            if reinvest_dividends:
                div_income = _calculate_dividend_income(today, full_dividends, ctx["broker"])
                if div_income > 0:
                    ctx["broker"].receive_dividends(div_income)
                    ctx["dividend_income"] += div_income

            try:
                result = ctx["engine"].run_one_cycle(ctx["loader"], sim_date=sim_date)
                ctx["executions"].extend(result.executions)
                if result.signal.has_orders:
                    ctx["reason_counter"][result.signal.reason] = (
                        ctx["reason_counter"].get(result.signal.reason, 0) + 1
                    )
            except Exception as e:
                logger.error(f"[{name}] Error on {today.date()}: {e}")

    # 6. 엔진별 메트릭 계산
    logger.info("--- Compare Backtest Finished ---")

    engine_results: Dict[str, BacktestResult] = {}
    compare_spy_cagr: Optional[float] = None

    for name, ctx in engines.items():
        summary_data = ctx["repo"]._load_json(ctx["repo"].summary_file, default=[])
        metrics = _calculate_metrics(summary_data, initial_cash, full_df, sim_days)
        if metrics is None:
            logger.warning(f"[{name}] No trading data available.")
            continue

        res_df, final_value, cagr, mdd, sharpe_ratio, spy_cagr, regime_returns = metrics

        if compare_spy_cagr is None and spy_cagr is not None:
            compare_spy_cagr = spy_cagr

        logger.info(f"[{name}] Final: ${final_value:,.0f} | CAGR: {cagr:.2%} | MDD: {mdd:.2%} | Sharpe: {sharpe_ratio:.2f}")

        engine_results[name] = BacktestResult(
            history=res_df,
            initial_cash=initial_cash,
            final_value=final_value,
            cagr=cagr,
            mdd=mdd,
            sharpe_ratio=sharpe_ratio,
            spy_cagr=spy_cagr,
            regime_returns=regime_returns,
            chart_path=None,
            trade_executions=ctx["executions"],
            trade_reason_summary=ctx["reason_counter"] if ctx["reason_counter"] else None,
            total_dividend_income=ctx["dividend_income"],
        )

    if not engine_results:
        logger.warning("No engine produced results.")
        return None

    # 7. 비교 차트 생성
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    run_suffix = f"_{run_number}" if run_number else ""
    chart_path = f"{output_dir}/compare_{start_date}_{end_date}{run_suffix}.png"

    plt.figure(figsize=(14, 7))
    for name, br in engine_results.items():
        color = _ENGINE_COLORS.get(name, None)
        plt.plot(br.history['total_value'],
                 label=f'{name} (CAGR: {br.cagr:.2%})', color=color)

    # SPY 벤치마크
    if compare_spy_cagr is not None:
        try:
            spy_benchmark = full_df['Close']['SPY'].loc[sim_days].dropna()
            spy_scaled = spy_benchmark / spy_benchmark.iloc[0] * initial_cash
            plt.plot(spy_scaled, label=f'SPY Buy&Hold (CAGR: {compare_spy_cagr:.2%})',
                     linestyle='--', color='gray', alpha=0.7)
        except Exception:
            pass

    plt.title(f"Engine Comparison ({start_date} ~ {end_date})")
    plt.ylabel("Portfolio Value ($)")
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)
    plt.savefig(chart_path)
    plt.close()
    logger.info(f"Compare chart saved: {chart_path}")

    return CompareBacktestResult(
        engine_results=engine_results,
        spy_cagr=compare_spy_cagr,
        chart_path=chart_path,
    )


if __name__ == "__main__":
    # 사용 예시: 2015년부터 2023년까지 테스트
    run_backtest("2015-01-01", "2023-12-31")
