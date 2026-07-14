#!/usr/bin/env python3
"""summary.json 과거 레코드의 net_deposit(순입금) 백필 스크립트.

net_deposit 기록 기능 도입 이전에 쌓인 일별 요약 레코드에 대해,
현금 잔고 변화(cash_balance)와 history.json 체결 내역, daily_dividend로
일별 순입금을 역산해 채워 넣는다.

    순입금 = 당일현금 - 직전현금 - (직전기록일, 당일] 체결현금영향 - 당일배당

이미 net_deposit이 있는 레코드는 건드리지 않는다 (멱등).
첫 레코드는 직전 현금이 없으므로 '체결 전 현금 = 초기 입금'으로 간주한다
(결산 계산에서 첫 레코드의 net_deposit은 합산에 포함되지 않으므로 참고값).

주의: history.json은 최근 N건만 보관하므로, 히스토리가 잘려 나간 구간을
백필하면 그 구간의 매매 현금흐름이 입출금으로 잘못 집계될 수 있다.
스크립트가 히스토리 커버리지를 검사해 경고를 출력한다.

사용법:
    python -m scripts.backfill_net_deposit --account my_test            # 실제 반영
    python -m scripts.backfill_net_deposit --account my_test --dry-run  # 미리보기
"""
import argparse
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", required=True,
                        help="대상 계정 id (docs/data/<account>/)")
    parser.add_argument("--data-root", default="docs/data",
                        help="데이터 루트 경로 (기본: docs/data)")
    parser.add_argument("--dry-run", action="store_true",
                        help="파일을 수정하지 않고 계산 결과만 출력")
    return parser.parse_args(argv)


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _exec_cash_impact(ex: dict) -> float:
    """체결 dict 1건의 현금 영향. BUY: -(금액+수수료), SELL: +금액-수수료."""
    amount = float(ex.get("price") or 0.0) * float(ex.get("quantity") or 0)
    fee = float(ex.get("fee") or 0.0)
    if (ex.get("action") or "").upper() == "BUY":
        return -amount - fee
    return amount - fee


def collect_executions_by_date(history: list) -> dict:
    """history.json에서 유효 체결을 날짜(YYYY-MM-DD)별 현금영향 합계로 집계한다."""
    impacts = {}
    for tx in history:
        tx_date = (tx.get("date") or "")[:10]
        for ex in (tx.get("executions") or []):
            if not ex.get("quantity") or (ex.get("status") or "").upper() == "REJECTED":
                continue
            date_key = (ex.get("date") or tx_date)[:10]
            impacts[date_key] = impacts.get(date_key, 0.0) + _exec_cash_impact(ex)
    return impacts


def _impact_in_window(impacts: dict, after: str, until: str) -> float:
    """(after, until] 구간 날짜들의 체결 현금영향 합계. after가 None이면 <= until 전부."""
    total = 0.0
    for d, v in impacts.items():
        if d <= until and (after is None or d > after):
            total += v
    return total


def backfill(summaries: list, history: list) -> list:
    """net_deposit이 없는 레코드를 역산해 채운다.

    Returns:
        변경 내역 리스트 [{date, cash, prev_cash, trade_impact, dividend, net_deposit}]
    """
    impacts = collect_executions_by_date(history)
    ordered = sorted(range(len(summaries)), key=lambda i: summaries[i].get("date") or "")
    changes = []
    prev_date = None
    prev_cash = None
    for i in ordered:
        rec = summaries[i]
        date = (rec.get("date") or "")[:10]
        cash = rec.get("cash_balance")
        if rec.get("net_deposit") is None and cash is not None:
            dividend = float(rec.get("daily_dividend") or 0.0)
            impact = _impact_in_window(impacts, prev_date, date)
            if prev_cash is None:
                # 첫 레코드: 체결 전 현금 = 초기 입금 (배당 차감 없음)
                nd = round(float(cash) - impact, 2)
            else:
                nd = round(float(cash) - float(prev_cash) - impact - dividend, 2)
            rec["net_deposit"] = nd
            changes.append({
                "date": date, "cash": cash, "prev_cash": prev_cash,
                "trade_impact": round(impact, 2), "dividend": dividend,
                "net_deposit": nd,
            })
        if cash is not None:
            prev_date = date
            prev_cash = cash
    return changes


def check_history_coverage(summaries: list, history: list) -> str:
    """summary 구간보다 history가 늦게 시작하면 경고 문구를 반환한다 (없으면 '')."""
    if not summaries or not history:
        return ""
    first_summary = min((s.get("date") or "")[:10] for s in summaries if s.get("date"))
    first_history = min((h.get("date") or "")[:10] for h in history if h.get("date"))
    # 첫 summary 레코드는 초기 입금으로 처리되므로 그 다음 날부터 커버되면 충분
    if first_history > first_summary:
        return (f"경고: history.json 시작일({first_history})이 summary 시작일"
                f"({first_summary})보다 늦습니다. 그 사이 매매가 있었다면 해당 구간"
                f" 순입금이 부정확할 수 있습니다.")
    return ""


def main(argv=None) -> int:
    args = parse_args(argv)
    root = os.path.join(args.data_root, args.account)
    summary_path = os.path.join(root, "summary.json")
    if not os.path.exists(summary_path):
        print(f"오류: summary.json이 없습니다: {summary_path}", file=sys.stderr)
        return 2

    summaries = _load_json(summary_path, default=[])
    history = _load_json(os.path.join(root, "history.json"), default=[])

    warning = check_history_coverage(summaries, history)
    if warning:
        print(warning)

    changes = backfill(summaries, history)
    if not changes:
        print(f"[{args.account}] 백필할 레코드가 없습니다 (모두 net_deposit 보유).")
        return 0

    print(f"[{args.account}] net_deposit 백필 대상: {len(changes)}건")
    print(f"{'date':<12}{'prev_cash':>14}{'cash':>14}{'trade':>12}{'div':>8}{'net_deposit':>14}")
    for c in changes:
        prev = "-" if c["prev_cash"] is None else f"{c['prev_cash']:,.0f}"
        print(f"{c['date']:<12}{prev:>14}{c['cash']:>14,.0f}"
              f"{c['trade_impact']:>12,.0f}{c['dividend']:>8,.0f}{c['net_deposit']:>14,.0f}")

    if args.dry_run:
        print("(dry-run: 파일을 수정하지 않았습니다)")
        return 0

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=4, ensure_ascii=False)
    print(f"저장 완료: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
