# src/core/settlement.py
"""기간(월간) 결산 계산 — summary.json(일별 요약) 기반 순수 로직.

브로커/파일 I/O에 의존하지 않고, 일별 요약 레코드 리스트만 받아
기초/기말 자산, 순입금액, 기간손익(금액), 수익률(TWR)을 계산한다.

결산 항등식:
    기간손익 = 기말자산 - 기초자산 - 순입금액합계

순입금(net_deposit) 역산도 이 모듈의 순수 함수로 제공한다:
    순입금 = 당일현금 - 직전현금 - 당일체결현금영향 - 당일배당
(시세 재평가는 현금에 영향을 주지 않으므로 외부 입출금만 남는다.
 배당 유입은 손익으로 집계해야 하므로 입금에서 제외한다.)
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
                       executions: Optional[List[TradeExecution]] = None,
                       daily_dividend: float = 0.0) -> float:
    """직전 기록 이후 발생한 순입금(외부 입출금)을 역산한다.

    prev_cash가 None(첫 기록)이면 체결 전 현금 전액을 초기 입금으로 간주한다.
    daily_dividend는 배당 유입 추정치로, 현금 증가 중 배당분을 입금이 아닌
    손익으로 남기기 위해 차감한다. (배당 추정일과 실제 입금일이 어긋나면
    일 단위 노이즈가 생기지만 기간 합산에서는 상쇄된다.)
    """
    impact = trade_cash_impact(executions or [])
    if prev_cash is None:
        return round(current_cash - impact, 2)
    return round(current_cash - prev_cash - impact - daily_dividend, 2)


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

    # 기초자산: start 직전 마지막 레코드. 없으면 기간 첫 레코드를 기초로 사용.
    prior = [r for r in recs if r["date"][:10] < start]
    if prior:
        base = prior[-1]
        # 기간 내 모든 순입금이 base 이후 발생분
        contrib = in_range
        twr_seq = [base] + in_range
    else:
        base = in_range[0]
        # 첫 레코드 값에는 그날까지의 입금이 이미 반영 -> 그 이후 분만 합산
        contrib = in_range[1:]
        twr_seq = in_range

    start_asset = float(base["total_value"])
    end_asset = float(in_range[-1]["total_value"])
    net_deposit = round(sum(float(r.get("net_deposit") or 0.0) for r in contrib), 2)
    profit = round(end_asset - start_asset - net_deposit, 2)
    twr_pct = _twr_pct(twr_seq)
    missing = sum(1 for r in contrib if r.get("net_deposit") is None)

    return SettlementResult(
        start_date=start, end_date=end,
        base_date=base["date"][:10], last_date=in_range[-1]["date"][:10],
        start_asset=round(start_asset, 2), end_asset=round(end_asset, 2),
        net_deposit=net_deposit, profit=profit,
        twr_pct=twr_pct, record_count=len(in_range),
        missing_net_deposit_count=missing,
    )


def _twr_pct(seq: List[dict]) -> Optional[float]:
    """시간가중수익률(%).

    각 하위기간 수익률 = V_end / (V_start + CF) - 1, CF는 해당 레코드의 net_deposit
    (기초에 유입되었다고 가정). 시퀀스가 2개 미만이면 None.
    """
    if len(seq) < 2:
        return None
    twr = 1.0
    for i in range(1, len(seq)):
        start_val = _finite(seq[i - 1].get("total_value"))
        end_val = _finite(seq[i].get("total_value"))
        # 기준/종료 자산이 없거나(시세조회 실패로 null) 0 이하이면 왜곡되므로 스킵.
        # 특히 end_val이 0이면 곱셈이 전체 TWR을 0(-100%)으로 붕괴시키므로 반드시 가드.
        if start_val is None or end_val is None or start_val <= 0 or end_val <= 0:
            continue
        cf = float(seq[i].get("net_deposit") or 0.0)
        denom = start_val + cf
        if denom <= 0:
            # 대규모 출금 등으로 분모가 0 이하가 되면 수익률이 왜곡되므로 스킵
            continue
        twr *= end_val / denom
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
