#!/usr/bin/env python3
"""기간(월간) 결산 CLI.

summary.json(일별 요약)을 기반으로 지정한 기간의
기초자산 / 기말자산 / 순입금액 / 기간손익(금액) / 수익률(TWR)을 계산해 출력한다.

결산 항등식: 기간손익 = 기말자산 - 기초자산 - 순입금액

net_deposit(순입금) 기록이 없는 과거 레코드는 0으로 간주되며, 해당 건수를
리포트에 경고로 표시한다.

사용법:
    python -m scripts.monthly_settlement --account my_test --start 2026-06-01 --end 2026-06-30
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.core.settlement import compute_settlement

DATE_FMT = "%Y-%m-%d"


def _valid_date(text: str) -> str:
    """YYYY-MM-DD 형식 검증 후 zero-pad 정규화된 문자열을 반환한다.

    strptime이 '2026-6-1' 같은 비패딩 입력도 허용하므로, 레코드 날짜와의
    사전식(lexicographic) 비교가 어긋나지 않도록 canonical form으로 통일한다.
    """
    try:
        dt = datetime.strptime(text, DATE_FMT)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"날짜 형식이 올바르지 않습니다: '{text}' (형식: YYYY-MM-DD, 예: 2026-06-01)"
        )
    return dt.strftime(DATE_FMT)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", required=True,
                        help="결산 대상 계정 id (docs/data/<account>/summary.json)")
    parser.add_argument("--start", required=True, type=_valid_date,
                        help="조회 시작일 (YYYY-MM-DD, 예: 2026-06-01)")
    parser.add_argument("--end", required=True, type=_valid_date,
                        help="조회 종료일 (YYYY-MM-DD, 예: 2026-06-30)")
    parser.add_argument("--data-root", default="docs/data",
                        help="데이터 루트 경로 (기본: docs/data)")
    return parser.parse_args(argv)


def load_summaries(data_root: str, account: str) -> list:
    """docs/data/<account>/summary.json을 읽기 전용으로 로드한다.

    JsonRepository는 생성 시 asset_groups.json을 덮어쓰는 부수효과가 있어
    조회 전용인 결산 CLI에서는 파일을 직접 읽는다.
    """
    path = os.path.join(data_root, account, "summary.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"summary.json이 없습니다: {path} (계정 id 확인: --account {account})")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_krw(value) -> str:
    """금액을 KRW 단위 ASCII 문자열로 포매팅한다. None은 '-'."""
    if value is None:
        return "-"
    return f"KRW {value:,.0f}"


def build_report(result, account: str) -> str:
    """결산 결과를 사람이 읽는 리포트 문자열로 조립한다."""
    twr = "-" if result.twr_pct is None else f"{result.twr_pct:+.2f}%"
    profit_sign = "+" if result.profit >= 0 else ""
    lines = [
        f"=== 기간 결산 ({account}) ===",
        f"기간           : {result.start_date} ~ {result.end_date}",
        f"레코드 개수    : {result.record_count}건",
    ]
    if result.record_count == 0:
        lines.append("")
        lines.append("해당 기간에 일별 요약 데이터가 없습니다. (봇 실행 이력 확인 필요)")
        return "\n".join(lines)
    lines += [
        f"기초자산일     : {result.base_date}",
        f"기말자산일     : {result.last_date}",
        "-" * 40,
        f"기초자산       : {format_krw(result.start_asset)}",
        f"기말자산       : {format_krw(result.end_asset)}",
        f"순입금액       : {format_krw(result.net_deposit)}",
        f"기간손익(금액) : {profit_sign}{format_krw(result.profit)}",
        f"수익률(TWR)    : {twr}",
    ]
    if result.missing_net_deposit_count:
        lines += [
            "-" * 40,
            f"주의: 순입금 미기록 레코드 {result.missing_net_deposit_count}건을 0으로 간주했습니다.",
            "  기간 중 입출금이 있었다면 손익이 왜곡될 수 있습니다.",
        ]
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.start > args.end:
        print(f"오류: 시작일({args.start})이 종료일({args.end})보다 뒤입니다.",
              file=sys.stderr)
        return 2

    try:
        records = load_summaries(args.data_root, args.account)
    except FileNotFoundError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2

    result = compute_settlement(records, args.start, args.end)
    print(build_report(result, args.account))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
