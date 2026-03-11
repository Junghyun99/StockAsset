"""GitHub Actions CI용 엔진 비교 백테스트 실행 스크립트."""
import os
import sys


def main() -> None:
    start = os.environ["BACKTEST_START"]
    end = os.environ["BACKTEST_END"]
    cash = float(os.environ.get("BACKTEST_CASH", "10000"))
    interval = int(os.environ.get("BACKTEST_INTERVAL", "1"))

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.backtest.runner import run_compare_backtest  # noqa: PLC0415

    run_number = os.environ.get("GITHUB_RUN_NUMBER")

    print(f"=== 엔진 비교 백테스트 시작: {start} ~ {end}, 초기자본: {cash:,.0f}, 실행간격: {interval}거래일 ===")
    result = run_compare_backtest(
        start, end, cash,
        execution_interval=interval,
        run_number=run_number,
    )

    if result is None:
        print("ERROR: 비교 백테스트 결과 없음 (데이터 부족 또는 거래일 없음)")
        sys.exit(1)

    spy_str = f"{result.spy_cagr:.2%}" if result.spy_cagr is not None else "N/A"

    lines = [
        f"## 엔진 비교 백테스트 결과 ({start} ~ {end})",
        "",
        "| 엔진 | 최종 자산 | CAGR | MDD | Sharpe | 배당금 |",
        "|------|----------|------|-----|--------|--------|",
    ]
    for name, r in result.engine_results.items():
        lines.append(
            f"| {name} | ${r.final_value:,.0f} | {r.cagr:.2%} | "
            f"{r.mdd:.2%} | {r.sharpe_ratio:.2f} | ${r.total_dividend_income:,.2f} |"
        )
    lines.append(f"| **SPY Buy&Hold** | - | {spy_str} | - | - | - |")

    if result.chart_path:
        lines.append(f"\n차트 저장 경로: `{result.chart_path}`")

    summary = "\n".join(lines) + "\n"

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_file:
        with open(summary_file, "w") as f:
            f.write(summary)

    print(summary)


if __name__ == "__main__":
    main()
