# src/core/settlement.py
"""기간(월간) 결산 계산 — summary.json(일별 요약) 기반 순수 로직.

브로커/파일 I/O에 의존하지 않고, 일별 요약 레코드 리스트만 받아
기초/기말 자산, 순입금액, 기간손익(금액), 수익률(TWR)을 계산한다.

결산 항등식:
    기간손익 = 기말자산 - 기초자산 - 순입금액합계

순입금(net_deposit) 역산도 이 모듈의 순수 함수로 제공한다:
    순입금 = 당일현금 - 직전현금 - 당일체결현금영향
(시세 재평가는 현금에 영향을 주지 않으므로 입출금과 배당/이자 유입만 남는다.
 배당/이자는 yfinance 추정치의 정확도/시점 문제로 차감하지 않고 순입금으로
 집계한다 - 현금이 들어오지 않은 날 추정치를 차감하면 가짜 출금이 생긴다.)
"""
from dataclasses import dataclass, asdict
from typing import List, Optional

from src.core.models import TradeExecution, OrderAction, ExecutionStatus


@dataclass
class SettlementResult:
    start_date: str            # 조회 시작일 (YYYY-MM-DD)
    end_date: str              # 조회 종료일 (YYYY-MM-DD)
    base_date: Optional[str]   # 기초자산 기준 레코드 날짜
    last_date: Optional[str]   # 기말자산 기준 레코드 날짜
    start_asset: float         # 기초자산
    end_asset: float           # 기말자산
    net_deposit: float         # 순입금액 합계
    profit: float              # 기간손익(금액) = 기말 - 기초 - 순입금
    twr_pct: Optional[float]   # 수익률(TWR, %). 계산 불가 시 None
    record_count: int          # 기간 내 레코드 개수
    missing_net_deposit_count: int  # net_deposit 미기록 레코드 개수 (0으로 간주됨)

    def to_dict(self) -> dict:
        return asdict(self)


def trade_cash_impact(executions: List[TradeExecution]) -> float:
    """체결로 인한 순 현금 변동을 계산한다.

    BUY는 현금 감소(-), SELL은 현금 증가(+), 각각 수수료만큼 추가 차감.
    입출금(순입금) 역산 시 시세 변동/거래를 제외하기 위해 사용한다.
    거부(REJECTED)되었거나 수량이 0인 체결은 현금 변동이 없으므로 제외.
    """
    return sum(
        (-e.price * e.quantity - e.fee) if e.action == OrderAction.BUY
        else (e.price * e.quantity - e.fee)
        for e in executions
        if e.quantity > 0 and e.status != ExecutionStatus.REJECTED
    )


def derive_net_deposit(current_cash: float,
                       prev_cash: Optional[float],
                       executions: Optional[List[TradeExecution]] = None) -> float:
    """직전 기록 이후 발생한 순입금(외부 입출금)을 역산한다.

    prev_cash가 None(첫 기록)이면 체결 전 현금 전액을 초기 입금으로 간주한다.
    배당/이자 유입도 순입금에 포함된다 (모듈 docstring 참고).
    """
    impact = trade_cash_impact(executions or [])
    if prev_cash is None:
        return round(current_cash - impact, 2)
    return round(current_cash - prev_cash - impact, 2)


def aggregate_summary_records(account_records: dict[str, List[dict]]) -> List[dict]:
    """Aggregate account summary records into one date-keyed record sequence."""
    records_by_account = {
        account: sorted((r for r in records if r.get("date")), key=lambda r: r["date"])
        for account, records in account_records.items()
    }
    dates = sorted({r["date"] for records in records_by_account.values() for r in records})
    totals = []

    for date in dates:
        total_value = 0.0
        net_deposit = 0.0
        missing_net_deposit_count = 0
        for records in records_by_account.values():
            latest_value = None
            for record in records:
                if record["date"] > date:
                    break
                value = _finite(record.get("total_value"))
                if value is not None:
                    latest_value = value
                if record["date"] == date:
                    net_deposit += float(record.get("net_deposit") or 0.0)
                    if record.get("net_deposit") is None:
                        missing_net_deposit_count += 1
            if latest_value is not None:
                total_value += latest_value

        item = {
            "date": date,
            "total_value": total_value,
            "net_deposit": net_deposit,
        }
        if missing_net_deposit_count:
            item["missing_net_deposit_count"] = missing_net_deposit_count
        totals.append(item)

    return totals


def compute_settlement(records: List[dict], start: str, end: str) -> SettlementResult:
    """일별 요약 레코드 리스트에서 [start, end] 기간(양끝 포함) 결산을 계산한다.

    Args:
        records: repo.load_summaries() 결과. 각 항목은 date/total_value/
                 cash_balance/net_deposit 을 가진다 (net_deposit은 없을 수 있음).
        start, end: 'YYYY-MM-DD' 문자열. start <= end.

    Returns:
        SettlementResult. 기간 내 레코드가 없으면 모든 금액 0, twr_pct None.
    """
    if start > end:
        raise ValueError(f"start({start}) must be <= end({end})")

    # 날짜 오름차순 정렬 (저장 순서를 신뢰하지 않고 방어적으로 정렬)
    recs = sorted(
        (r for r in records if r.get("date")),
        key=lambda r: r["date"],
    )

    in_range = [r for r in recs if start <= r["date"][:10] <= end]
    if not in_range:
        return SettlementResult(
            start_date=start, end_date=end, base_date=None, last_date=None,
            start_asset=0.0, end_asset=0.0, net_deposit=0.0, profit=0.0,
            twr_pct=None, record_count=0, missing_net_deposit_count=0,
        )

    # 기초/기말 레코드 선택: total_value가 null(시세조회 실패 등)인 레코드를
    # 기초/기말로 쓰면 자산이 0으로 잡혀 손익이 크게 왜곡되므로, 가장 가까운
    # "유효한"(값이 있는) 레코드를 선택한다.
    #   기초: start 직전의 마지막 유효 레코드. 없으면 기간 내 첫 유효 레코드.
    #   기말: 기간 내 마지막 유효 레코드.
    # 유효 레코드가 하나도 없으면 기존 위치(기간 첫/끝)로 강등하고 금액은 0 처리.
    def _valid(r):
        return _finite(r.get("total_value")) is not None

    prior = [r for r in recs if r["date"][:10] < start]
    valid_prior = [r for r in prior if _valid(r)]
    valid_in_range = [r for r in in_range if _valid(r)]

    if valid_prior:
        base = valid_prior[-1]
    elif valid_in_range:
        base = valid_in_range[0]
    else:
        base = in_range[0]
    end_rec = valid_in_range[-1] if valid_in_range else in_range[-1]

    # 결산 창은 (base, end_rec]: 항등식(손익 = 기말 - 기초 - 순입금)이 유지되도록
    # base 이후 ~ end_rec까지 발생한 순입금만 합산한다. base가 null 레코드를
    # 건너뛰어 기간 밖 과거로 이동했다면 그 사이 순입금도 포함하고, end_rec이
    # 기간 끝보다 앞이라면 그 이후 순입금은 제외한다.
    pos = {id(r): i for i, r in enumerate(recs)}
    window = recs[pos[id(base)] + 1: pos[id(end_rec)] + 1]

    start_asset = _finite(base.get("total_value")) or 0.0
    end_asset = _finite(end_rec.get("total_value")) or 0.0
    net_deposit = round(sum(float(r.get("net_deposit") or 0.0) for r in window), 2)
    profit = round(end_asset - start_asset - net_deposit, 2)
    twr_pct = _twr_pct([base] + window)
    missing = sum(
        r.get("missing_net_deposit_count", 1 if r.get("net_deposit") is None else 0)
        for r in window
    )

    return SettlementResult(
        start_date=start, end_date=end,
        base_date=base["date"][:10], last_date=end_rec["date"][:10],
        start_asset=round(start_asset, 2), end_asset=round(end_asset, 2),
        net_deposit=net_deposit, profit=profit,
        twr_pct=twr_pct, record_count=len(in_range),
        missing_net_deposit_count=missing,
    )


def _twr_pct(seq: List[dict]) -> Optional[float]:
    """시간가중수익률(%).

    각 하위기간 수익률 = V_end / (V_start + CF) - 1, CF는 해당 레코드의 net_deposit
    (기초에 유입되었다고 가정). 시퀀스가 2개 미만이면 None.

    비정상 레코드(total_value가 null이거나 0 이하 - 시세조회 실패 등)는 단순히
    건너뛰지 않고 다음 정상 레코드까지 하위기간을 병합하며, 그 사이 발생한
    순입금은 병합 구간 분모에 누적 반영한다. 단순 스킵은 비정상 레코드 전후의
    수익률 변화를 통째로 누락시켜 TWR을 왜곡하기 때문이다.
    유효한 하위기간이 하나도 없으면 None을 반환한다.
    """
    if len(seq) < 2:
        return None
    twr = 1.0
    last_valid_val = None   # 직전 정상 레코드의 자산 (병합 구간의 기준값)
    accumulated_cf = 0.0    # 병합 구간에 누적된 순입금
    has_valid_period = False

    for rec in seq:
        val = _finite(rec.get("total_value"))
        valid = val is not None and val > 0

        if last_valid_val is None:
            # 아직 기준값이 없으면 첫 정상 레코드를 기준으로 삼는다
            # (기준 레코드의 net_deposit은 자산에 이미 반영되어 있으므로 미사용)
            if valid:
                last_valid_val = val
            continue

        accumulated_cf += float(rec.get("net_deposit") or 0.0)
        if valid:
            denom = last_valid_val + accumulated_cf
            if denom > 0:
                twr *= val / denom
                has_valid_period = True
            # 대규모 출금 등으로 분모가 0 이하이면 해당 병합 구간은 왜곡 방지를
            # 위해 반영하지 않고, 이번 정상값을 새 기준으로 삼는다
            last_valid_val = val
            accumulated_cf = 0.0

    if not has_valid_period:
        return None
    return round((twr - 1) * 100, 4)


def _finite(value) -> Optional[float]:
    """유한한 float면 반환, None/NaN/inf면 None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN or inf
        return None
    return f
