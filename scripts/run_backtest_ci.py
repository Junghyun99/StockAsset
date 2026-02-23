"""GitHub Actions CI용 백테스트 실행 스크립트."""
import os
import sys


def main() -> None:
    start = os.environ["BACKTEST_START"]
    end = os.environ["BACKTEST_END"]
    cash = float(os.environ.get("BACKTEST_CASH", "10000"))

    # backtest runner import는 src 경로 설정 후
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.backtest.runner import run_backtest  # noqa: PLC0415

    print(f"=== 백테스트 시작: {start} ~ {end}, 초기자본: {cash:,.0f} ===")
    result = run_backtest(start, end, cash)

    if result is None:
        print("ERROR: 백테스트 결과 없음 (데이터 부족 또는 거래일 없음)")
        sys.exit(1)

    spy_cagr_str = f"{result.spy_cagr:.2%}" if result.spy_cagr is not None else "N/A"

    lines = [
        f"## 백테스트 결과 ({start} ~ {end})",
        "",
        "| 항목 | 값 |",
        "|------|-----|",
        f"| 초기 자본 | ${result.initial_cash:,.0f} |",
        f"| 최종 자산 | ${result.final_value:,.0f} |",
        f"| CAGR | {result.cagr:.2%} |",
        f"| MDD | {result.mdd:.2%} |",
        f"| Sharpe Ratio | {result.sharpe_ratio:.2f} |",
        f"| SPY Buy&Hold CAGR | {spy_cagr_str} |",
        "",
        "### 국면별 수익률",
    ]
    for regime, ret in result.regime_returns.items():
        lines.append(f"- **{regime}**: {ret:.2%}")

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
