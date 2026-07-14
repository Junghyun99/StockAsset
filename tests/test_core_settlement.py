# tests/test_core_settlement.py
import pytest

from src.core.models import TradeExecution, OrderAction, ExecutionStatus
from src.core.settlement import (
    compute_settlement,
    derive_net_deposit,
    trade_cash_impact,
)


def _rec(date, value, cash=0.0, net_deposit=0.0):
    return {
        "date": date,
        "total_value": value,
        "cash_balance": cash,
        "net_deposit": net_deposit,
    }


def _exec(action, qty, price, fee=0.0, status=ExecutionStatus.FILLED):
    return TradeExecution(
        ticker="TST", action=action, quantity=qty, price=price,
        fee=fee, date="2026-06-01 10:00:00", status=status,
    )


class TestComputeSettlement:
    def test_empty_range_returns_zero(self):
        recs = [_rec("2026-05-15", 1000.0)]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.record_count == 0
        assert r.start_asset == 0.0 and r.end_asset == 0.0
        assert r.profit == 0.0 and r.twr_pct is None

    def test_start_end_asset_and_profit_pure_gain(self):
        """입금 없이 시세만 상승 -> 손익 = 기말 - 기초"""
        recs = [
            _rec("2026-06-01", 1000.0),
            _rec("2026-06-15", 1100.0),
            _rec("2026-06-28", 1200.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        # 기간 직전 레코드가 없으므로 첫 레코드가 기초
        assert r.start_asset == 1000.0
        assert r.end_asset == 1200.0
        assert r.net_deposit == 0.0
        assert r.profit == 200.0

    def test_uses_prior_record_as_base(self):
        """start 직전 레코드가 기초자산이 된다"""
        recs = [
            _rec("2026-05-31", 1000.0),
            _rec("2026-06-10", 1300.0),
            _rec("2026-06-28", 1500.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.base_date == "2026-05-31"
        assert r.start_asset == 1000.0
        assert r.end_asset == 1500.0
        assert r.profit == 500.0

    def test_net_deposit_excluded_from_profit(self):
        """기간 중 입금분은 손익에서 제외된다 (기초 직전 레코드 존재)"""
        recs = [
            _rec("2026-05-31", 1000.0),
            # 500 입금 후 시세로 +100 -> 자산 1600
            _rec("2026-06-10", 1600.0, net_deposit=500.0),
            _rec("2026-06-28", 1650.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.net_deposit == 500.0
        # profit = 1650 - 1000 - 500 = 150
        assert r.profit == 150.0

    def test_first_record_net_deposit_excluded_when_no_prior(self):
        """기초 직전 레코드가 없으면 첫 레코드 net_deposit은 합산 제외"""
        recs = [
            _rec("2026-06-01", 1000.0, net_deposit=1000.0),  # 초기 원금
            _rec("2026-06-20", 1200.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.start_asset == 1000.0
        assert r.net_deposit == 0.0
        assert r.profit == 200.0

    def test_twr_excludes_deposit_effect(self):
        """TWR은 입금 효과를 제거한다.

        기초 1000 -> 입금 1000 후 2000 (수익 0%) -> 2200 (수익 +10%)
        TWR = (2000/(1000+1000)-1=0) 이후 (2200/2000-1=0.1) -> +10%
        """
        recs = [
            _rec("2026-05-31", 1000.0),
            _rec("2026-06-10", 2000.0, net_deposit=1000.0),
            _rec("2026-06-28", 2200.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.twr_pct == pytest.approx(10.0)

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError):
            compute_settlement([], "2026-06-30", "2026-06-01")

    def test_boundary_inclusive(self):
        """start/end 양끝 날짜 포함"""
        recs = [
            _rec("2026-06-01", 1000.0),
            _rec("2026-06-30", 1100.0),
            _rec("2026-07-01", 9999.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.record_count == 2
        assert r.last_date == "2026-06-30"

    def test_twr_skips_nonpositive_denominator(self):
        """대규모 출금으로 분모가 0 이하가 되는 구간은 스킵되어 왜곡/오류가 없다."""
        recs = [
            _rec("2026-05-31", 1000.0),
            # 2000 출금(net_deposit=-2000) -> denom = 1000 + (-2000) < 0 -> 스킵
            _rec("2026-06-10", 500.0, net_deposit=-2000.0),
            _rec("2026-06-28", 600.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        # 예외 없이 숫자를 반환해야 한다
        assert r.twr_pct is not None
        # 두 번째 구간(600/500-1=+20%)만 반영
        assert r.twr_pct == pytest.approx(20.0)

    def test_twr_not_collapsed_by_zero_end_value(self):
        """종료 자산이 0(시세조회 실패 등)인 구간이 전체 TWR을 -100%로 붕괴시키지 않는다."""
        recs = [
            _rec("2026-06-01", 1000.0),
            _rec("2026-06-10", 0.0),   # 비정상 0 자산
            _rec("2026-06-20", 1100.0),
            _rec("2026-06-28", 1200.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        # 0 구간은 스킵되고 정상 구간만 반영 (1200/1100-1 = +9.09%)
        assert r.twr_pct == pytest.approx(9.0909, abs=1e-3)

    def test_twr_skips_null_total_value(self):
        """total_value가 None(null)인 구간도 예외 없이 스킵된다."""
        recs = [
            _rec("2026-06-01", 1000.0),
            {"date": "2026-06-10", "total_value": None, "net_deposit": 0.0},
            _rec("2026-06-28", 1100.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        assert r.twr_pct is not None

    def test_twr_skips_nonpositive_start_value(self):
        """기준 자산이 0 이하인 구간도 스킵된다 (예외 없이 처리)."""
        recs = [
            _rec("2026-06-01", 0.0),
            _rec("2026-06-15", 100.0, net_deposit=100.0),
            _rec("2026-06-28", 150.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        assert r.twr_pct is not None

    def test_records_sorted_defensively(self):
        """저장 순서가 뒤섞여 있어도 날짜순으로 정렬해 계산한다"""
        recs = [
            _rec("2026-06-28", 1200.0),
            _rec("2026-06-01", 1000.0),
            _rec("2026-06-15", 1100.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        assert r.start_asset == 1000.0
        assert r.end_asset == 1200.0

    def test_missing_net_deposit_counted_and_treated_as_zero(self):
        """net_deposit 미기록(과거) 레코드는 0으로 간주하고 건수를 보고한다"""
        recs = [
            _rec("2026-05-31", 1000.0),
            {"date": "2026-06-10", "total_value": 1100.0},          # 키 없음
            {"date": "2026-06-20", "total_value": 1150.0, "net_deposit": None},
            _rec("2026-06-28", 1200.0, net_deposit=50.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.missing_net_deposit_count == 2
        assert r.net_deposit == 50.0
        assert r.profit == 150.0  # 1200 - 1000 - 50

    def test_result_to_dict(self):
        r = compute_settlement([_rec("2026-06-01", 1000.0)], "2026-06-01", "2026-06-30")
        d = r.to_dict()
        assert d["start_asset"] == 1000.0
        assert d["record_count"] == 1


class TestTradeCashImpact:
    def test_buy_decreases_and_sell_increases_cash(self):
        execs = [
            _exec(OrderAction.BUY, 10, 100.0, fee=5.0),   # -1005
            _exec(OrderAction.SELL, 5, 200.0, fee=3.0),   # +997
        ]
        assert trade_cash_impact(execs) == pytest.approx(-8.0)

    def test_rejected_and_zero_quantity_excluded(self):
        execs = [
            _exec(OrderAction.BUY, 0, 100.0),
            _exec(OrderAction.BUY, 10, 100.0, status=ExecutionStatus.REJECTED),
        ]
        assert trade_cash_impact(execs) == 0.0


class TestDeriveNetDeposit:
    def test_no_activity_no_deposit(self):
        assert derive_net_deposit(1000.0, 1000.0) == 0.0

    def test_deposit_detected_from_cash_increase(self):
        assert derive_net_deposit(1500.0, 1000.0) == 500.0

    def test_trade_cash_flow_excluded(self):
        """매수로 현금이 줄어든 것은 입출금이 아니다"""
        execs = [_exec(OrderAction.BUY, 10, 100.0, fee=5.0)]  # 현금 -1005
        assert derive_net_deposit(495.0, 1500.0, execs) == 0.0

    def test_dividend_excluded_from_deposit(self):
        """배당 유입은 입금이 아니라 손익으로 남긴다"""
        assert derive_net_deposit(1010.0, 1000.0, daily_dividend=10.0) == 0.0

    def test_first_record_counts_pretrade_cash_as_initial_deposit(self):
        """첫 기록: 체결 전 현금 = 초기 입금"""
        execs = [_exec(OrderAction.BUY, 10, 100.0)]  # 현금 -1000
        assert derive_net_deposit(500.0, None, execs) == 1500.0

    def test_withdrawal_is_negative(self):
        assert derive_net_deposit(700.0, 1000.0) == -300.0
