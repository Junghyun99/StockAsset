# src/backtest/runner.py
import shutil
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from src.config import Config
from src.strategy_config import StrategyConfig
from src.core.models import TradeExecution
from src.core.engine import (
    _ENGINE_REGISTRY as ENGINE_REGISTRY,
    _ENGINE_COLORS,
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
    sim_days: list,
) -> Optional[Tuple[pd.DataFrame, float, float, float, float, Dict[str, float]]]:
    """백테스트 결과 메트릭을 계산한다.

    Returns:
        (res_df, final_value, cagr, mdd, sharpe_ratio, regime_returns)
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

    # 국면별 수익률
    res_df['daily_return'] = res_df['total_value'].pct_change()
    regime_returns: Dict[str, float] = {}
    for regime_val, group in res_df.groupby('regime'):
        regime_daily = group['daily_return'].dropna()
        if len(regime_daily) > 0:
            regime_returns[str(regime_val)] = float(regime_daily.mean() * 252)

    return res_df, final_value, cagr, mdd, sharpe_ratio, regime_returns


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
    logger = TradeLogger(log_dir="logs/backtest", run_number=run_number)

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
        _cfg = Config()
        repo = JsonRepository(
            eng_output,
            asset_groups=eff_groups,
            max_summary_records=_cfg.MAX_SUMMARY_RECORDS,
            max_history_records=_cfg.MAX_HISTORY_RECORDS,
        )
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

    prev_prices: Dict[str, float] = {}  # NaN 대체용 전날 가격 (forward-fill)

    for today in sim_days:
        # 종가 추출 (1회, 공유)
        try:
            close_prices = full_df['Close'].loc[today]
            current_prices = close_prices.to_dict()
            # NaN 가격 제거: yfinance에서 특정 날짜에 데이터가 없을 수 있음
            # NaN이 있으면 직전 설정 가격(prev_prices)으로 대체 (forward-fill)
            current_prices = {
                t: (p if not pd.isna(p) else prev_prices.get(t))
                for t, p in current_prices.items()
                if not pd.isna(p) or prev_prices.get(t) is not None
            }
            prev_prices = current_prices
        except Exception as e:
            logger.warning(f"[{today.date()}] 종가 추출 실패, 건너뜀: {e}")
            continue

        sim_date = today.strftime("%Y-%m-%d")

        for name, ctx in engines.items():
            ctx["loader"].set_date(today)
            ctx["broker"].set_date(today)
            ctx["broker"].set_prices(current_prices)

            div_income = 0.0
            if reinvest_dividends:
                div_income = _calculate_dividend_income(today, full_dividends, ctx["broker"])
                if div_income > 0:
                    ctx["broker"].receive_dividends(div_income)
                    ctx["dividend_income"] += div_income

            try:
                result = ctx["engine"].run_one_cycle(
                    ctx["loader"],
                    sim_date=sim_date,
                    daily_dividend=div_income,
                )
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

    for name, ctx in engines.items():
        summary_data = ctx["repo"]._load_json(ctx["repo"].summary_file, default=[])
        metrics = _calculate_metrics(summary_data, initial_cash, sim_days)
        if metrics is None:
            logger.warning(f"[{name}] No trading data available.")
            continue

        res_df, final_value, cagr, mdd, sharpe_ratio, regime_returns = metrics

        logger.info(f"[{name}] Final: ${final_value:,.0f} | CAGR: {cagr:.2%} | MDD: {mdd:.2%} | Sharpe: {sharpe_ratio:.2f}")

        # status.json에 initial_cash와 backtest_start_date 저장 (JS 정확한 totalReturn 계산용)
        status_path = ctx["repo"].status_file
        status_data = ctx["repo"]._load_json(status_path, default={})
        status_data["initial_cash"] = initial_cash
        status_data["backtest_start_date"] = start_date
        ctx["repo"]._save_json(status_path, status_data)

        engine_results[name] = BacktestResult(
            history=res_df,
            initial_cash=initial_cash,
            final_value=final_value,
            cagr=cagr,
            mdd=mdd,
            sharpe_ratio=sharpe_ratio,
            spy_cagr=None,  # 아래에서 SpyEngine 결과로 일괄 설정
            regime_returns=regime_returns,
            chart_path=None,
            trade_executions=ctx["executions"],
            trade_reason_summary=ctx["reason_counter"] if ctx["reason_counter"] else None,
            total_dividend_income=ctx["dividend_income"],
        )

    # SpyEngine 결과를 벤치마크로 설정
    spy_engine_result = engine_results.get('SpyEngine')
    compare_spy_cagr: Optional[float] = spy_engine_result.cagr if spy_engine_result is not None else None
    spy_portfolio: Optional[pd.Series] = (
        spy_engine_result.history['total_value'] if spy_engine_result is not None else None
    )
    # 각 엔진의 spy_cagr을 SpyEngine 결과로 설정 (SpyEngine 자신은 제외)
    for name, br in engine_results.items():
        if name != 'SpyEngine':
            br.spy_cagr = compare_spy_cagr

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

    # SpyEngine 포트폴리오를 벤치마크 라인으로 표시 (이미 엔진 라인에 포함되어 있으나 강조)
    if compare_spy_cagr is not None and spy_portfolio is not None:
        plt.plot(spy_portfolio, label=f'SPY Buy&Hold (CAGR: {compare_spy_cagr:.2%})',
                 linestyle='--', color='gray', alpha=0.7)

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
