# tests/test_infra_repo_net_deposit.py
"""save_daily_summary의 net_deposit(순입금) 기록 동작 테스트."""
import json

import pytest

from src.core.models import (
    ExecutionStatus,
    MarketData,
    MarketRegime,
    OrderAction,
    Portfolio,
    TradeExecution,
    TradeSignal,
)
from src.infra.repo import JsonRepository


@pytest.fixture
def repo(tmp_path):
    return JsonRepository(root_path=str(tmp_path))


def _market(date):
    return MarketData(date, 100.0, 90.0, 0.2, 0.1, -0.05, 15.0)


def _signal():
    return TradeSignal(0.8, [], "test")


def _exec(action, qty, price, fee=0.0, date="2026-06-02 10:00:00"):
    return TradeExecution(
        ticker="TST", action=action, quantity=qty, price=price,
        fee=fee, date=date, status=ExecutionStatus.FILLED,
    )


def _load_summary(repo):
    with open(repo.summary_file, "r", encoding="utf-8") as f:
        return json.load(f)


def test_first_record_counts_pretrade_cash_as_initial_deposit(repo):
    """첫 레코드: 체결 전 현금이 초기 입금으로 기록된다."""
    pf = Portfolio(500.0, {"TST": 10}, {"TST": 100.0})
    execs = [_exec(OrderAction.BUY, 10, 100.0)]  # 현금 -1000
    repo.save_daily_summary(_market("2026-06-01"), _signal(), pf, MarketRegime.BULL,
                            executions=execs)
    data = _load_summary(repo)
    assert data[0]["net_deposit"] == 1500.0


def test_no_cash_change_records_zero_deposit(repo):
    pf1 = Portfolio(1000.0, {}, {})
    repo.save_daily_summary(_market("2026-06-01"), _signal(), pf1, MarketRegime.BULL)
    pf2 = Portfolio(1000.0, {}, {})
    repo.save_daily_summary(_market("2026-06-02"), _signal(), pf2, MarketRegime.BULL)
    data = _load_summary(repo)
    assert data[1]["net_deposit"] == 0.0


def test_deposit_detected_and_trades_excluded(repo):
    """입금 500 + 매수 현금유출은 순입금 500으로만 기록된다."""
    repo.save_daily_summary(_market("2026-06-01"), _signal(),
                            Portfolio(1000.0, {}, {}), MarketRegime.BULL)
    # 500 입금 후 1005(수수료 포함) 매수 -> 현금 495
    execs = [_exec(OrderAction.BUY, 10, 100.0, fee=5.0)]
    repo.save_daily_summary(_market("2026-06-02"), _signal(),
                            Portfolio(495.0, {"TST": 10}, {"TST": 100.0}),
                            MarketRegime.BULL, executions=execs)
    data = _load_summary(repo)
    assert data[1]["net_deposit"] == 500.0


def test_dividend_inflow_counted_as_deposit(repo):
    """배당 유입도 순입금으로 집계된다 (yfinance 추정치 차감은 하지 않음)."""
    repo.save_daily_summary(_market("2026-06-01"), _signal(),
                            Portfolio(1000.0, {}, {}), MarketRegime.BULL)
    repo.save_daily_summary(_market("2026-06-02"), _signal(),
                            Portfolio(1010.0, {}, {}), MarketRegime.BULL,
                            expected_dividend=10.0)
    data = _load_summary(repo)
    assert data[1]["net_deposit"] == 10.0
    assert data[1]["expected_dividend"] == 10.0  # 예상 배당은 참고용으로만 기록


def test_same_day_rerun_accumulates_net_deposit(repo):
    """같은 날 재실행 시 net_deposit은 변동분만 누적된다."""
    repo.save_daily_summary(_market("2026-06-01"), _signal(),
                            Portfolio(1000.0, {}, {}), MarketRegime.BULL)
    # 1차 실행: 300 입금
    repo.save_daily_summary(_market("2026-06-02"), _signal(),
                            Portfolio(1300.0, {}, {}), MarketRegime.BULL)
    # 같은 날 2차 실행: 추가 200 입금
    repo.save_daily_summary(_market("2026-06-02"), _signal(),
                            Portfolio(1500.0, {}, {}), MarketRegime.BULL)
    data = _load_summary(repo)
    assert len(data) == 2  # upsert 유지
    assert data[1]["net_deposit"] == 500.0


def test_upsert_of_past_date_preserves_existing_net_deposit(repo):
    """마지막 레코드보다 과거 날짜 덮어쓰기는 기존 net_deposit을 보존한다."""
    repo.save_daily_summary(_market("2026-06-01"), _signal(),
                            Portfolio(1000.0, {}, {}), MarketRegime.BULL)
    repo.save_daily_summary(_market("2026-06-02"), _signal(),
                            Portfolio(1500.0, {}, {}), MarketRegime.BULL)
    repo.save_daily_summary(_market("2026-06-03"), _signal(),
                            Portfolio(1500.0, {}, {}), MarketRegime.BULL)
    # 과거 날짜(06-02)를 다시 기록 (비정상 경로) -> 기존 500 유지
    repo.save_daily_summary(_market("2026-06-02"), _signal(),
                            Portfolio(9999.0, {}, {}), MarketRegime.BULL)
    data = _load_summary(repo)
    rec = next(r for r in data if r["date"] == "2026-06-02")
    assert rec["net_deposit"] == 500.0


def test_prev_record_without_net_deposit_still_works(repo):
    """직전 레코드에 net_deposit이 없어도(레거시) 다음 기록은 정상 계산된다."""
    legacy = [{"date": "2026-06-01", "total_value": 1000.0, "cash_balance": 1000.0}]
    with open(repo.summary_file, "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    repo.save_daily_summary(_market("2026-06-02"), _signal(),
                            Portfolio(1200.0, {}, {}), MarketRegime.BULL)
    data = _load_summary(repo)
    assert data[1]["net_deposit"] == 200.0


def test_load_summaries_returns_records(repo):
    repo.save_daily_summary(_market("2026-06-01"), _signal(),
                            Portfolio(1000.0, {}, {}), MarketRegime.BULL)
    records = repo.load_summaries()
    assert len(records) == 1
    assert records[0]["date"] == "2026-06-01"


def test_load_summaries_empty_when_no_file(repo):
    assert repo.load_summaries() == []
