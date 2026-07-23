# tests/test_core_settlement.py
import pytest

from src.core.models import TradeExecution, OrderAction, ExecutionStatus
from src.core.settlement import (
    aggregate_summary_records,
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
        # 0 구간은 다음 정상 레코드까지 병합되어 전체 변화가 반영됨 (1200/1000-1 = +20%)
        assert r.twr_pct == pytest.approx(20.0)

    def test_twr_merges_null_total_value_period(self):
        """total_value가 None(null)인 구간은 병합되어 전체 수익률이 유지된다."""
        recs = [
            _rec("2026-06-01", 1000.0),
            {"date": "2026-06-10", "total_value": None, "net_deposit": 0.0},
            _rec("2026-06-28", 1100.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        assert r.twr_pct == pytest.approx(10.0)

    def test_twr_merged_period_accumulates_cash_flow(self):
        """병합된 비정상 구간의 순입금도 분모에 누적 반영된다."""
        recs = [
            _rec("2026-06-01", 1000.0),
            # 비정상 레코드에 1000 입금 -> 다음 정상 구간 분모는 1000+1000
            {"date": "2026-06-10", "total_value": None, "net_deposit": 1000.0},
            _rec("2026-06-28", 2200.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        assert r.twr_pct == pytest.approx(10.0)  # 2200/(1000+1000)-1

    def test_twr_skips_nonpositive_start_value(self):
        """기준 자산이 0 이하이면 다음 정상 레코드가 기준이 된다 (예외 없이 처리)."""
        recs = [
            _rec("2026-06-01", 0.0),
            _rec("2026-06-15", 100.0, net_deposit=100.0),
            _rec("2026-06-28", 150.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        assert r.twr_pct == pytest.approx(50.0)  # 150/100-1

    def test_twr_none_when_no_valid_period(self):
        """유효한 하위기간이 하나도 없으면 0%가 아니라 None을 반환한다."""
        recs = [
            _rec("2026-06-01", 1000.0),
            {"date": "2026-06-10", "total_value": None, "net_deposit": 0.0},
            {"date": "2026-06-28", "total_value": None, "net_deposit": 0.0},
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-28")
        assert r.twr_pct is None

    def test_null_boundaries_resolve_to_nearest_valid_record(self):
        """기초/기말 레코드가 null이면 가장 가까운 유효 레코드를 기초/기말로 쓴다."""
        recs = [
            {"date": "2026-06-01", "total_value": None, "net_deposit": 0.0},
            _rec("2026-06-15", 1000.0),
            {"date": "2026-06-28", "total_value": None, "net_deposit": 0.0},
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.start_asset == 1000.0
        assert r.end_asset == 1000.0
        assert r.base_date == "2026-06-15"
        assert r.last_date == "2026-06-15"
        assert r.profit == 0.0

    def test_null_end_record_uses_last_valid_and_excludes_later_deposits(self):
        """기말이 null이면 마지막 유효 레코드가 기말이 되고, 그 이후 순입금은 제외된다."""
        recs = [
            _rec("2026-05-31", 1000.0),
            _rec("2026-06-15", 1200.0, net_deposit=100.0),
            # 마지막 날 시세조회 실패 + 입금 500: 기말은 6/15, 500은 합산 제외
            {"date": "2026-06-28", "total_value": None, "net_deposit": 500.0},
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.last_date == "2026-06-15"
        assert r.end_asset == 1200.0
        assert r.net_deposit == 100.0
        assert r.profit == 100.0  # 1200 - 1000 - 100

    def test_null_prior_base_walks_back_and_keeps_identity(self):
        """직전 레코드가 null이면 그 이전 유효 레코드가 기초가 되고,
        그 사이(기간 밖) 순입금도 합산해 항등식이 유지된다."""
        recs = [
            _rec("2026-05-28", 1000.0),
            # start 직전 레코드가 비정상이지만 200 입금이 기록됨
            {"date": "2026-05-31", "total_value": None, "net_deposit": 200.0},
            _rec("2026-06-15", 1300.0),
        ]
        r = compute_settlement(recs, "2026-06-01", "2026-06-30")
        assert r.base_date == "2026-05-28"
        assert r.start_asset == 1000.0
        assert r.net_deposit == 200.0
        assert r.profit == 100.0  # 1300 - 1000 - 200

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


class TestAggregateSummaryRecords:
    def test_sums_same_date_assets_and_cash_flows(self):
        records = {
            "my_isa": [
                _rec("2026-05-31", 1000.0),
                _rec("2026-06-30", 1200.0, net_deposit=100.0),
            ],
            "my_pension": [
                _rec("2026-05-31", 2000.0),
                _rec("2026-06-30", 2100.0),
            ],
            "my_failed_account": [
                _rec("2026-06-30", float("nan"), net_deposit=50.0),
            ],
        }

        assert aggregate_summary_records(records) == [
            {"date": "2026-05-31", "total_value": 3000.0, "net_deposit": 0.0},
            {"date": "2026-06-30", "total_value": 3300.0, "net_deposit": 150.0},
        ]

    def test_aggregated_records_calculate_group_profit_and_twr(self):
        records = {
            "my_isa": [
                _rec("2026-05-31", 1000.0),
                _rec("2026-06-30", 1200.0, net_deposit=100.0),
            ],
            "my_pension": [
                _rec("2026-05-31", 2000.0),
                _rec("2026-06-30", 2100.0),
            ],
        }

        result = compute_settlement(
            aggregate_summary_records(records), "2026-06-01", "2026-06-30"
        )

        assert result.profit == 200.0
        assert result.twr_pct == pytest.approx(6.4516)

    def test_preserves_missing_net_deposit_metadata_for_settlement(self):
        records = {
            "my_isa": [
                _rec("2026-05-31", 1000.0),
                {"date": "2026-06-30", "total_value": 1100.0},
            ],
            "my_pension": [
                _rec("2026-05-31", 2000.0),
                _rec("2026-06-30", 2100.0, net_deposit=50.0),
            ],
        }

        result = compute_settlement(
            aggregate_summary_records(records), "2026-06-01", "2026-06-30"
        )

        assert result.net_deposit == 50.0
        assert result.missing_net_deposit_count == 1

    def test_carries_latest_valid_value_to_other_accounts_record_dates(self):
        records = {
            "my_isa": [
                _rec("2026-05-31", 1000.0),
                _rec("2026-06-30", 1200.0, net_deposit=100.0),
            ],
            "my_pension": [
                _rec("2026-05-31", 2000.0),
                _rec("2026-06-15", 2100.0, net_deposit=25.0),
            ],
        }

        assert aggregate_summary_records(records) == [
            {"date": "2026-05-31", "total_value": 3000.0, "net_deposit": 0.0},
            {"date": "2026-06-15", "total_value": 3100.0, "net_deposit": 25.0},
            {"date": "2026-06-30", "total_value": 3300.0, "net_deposit": 100.0},
        ]

    def test_invalid_constituent_snapshot_excludes_same_day_cash_flow(self):
        records = {
            "my_isa": [
                _rec("2026-05-31", 1000.0),
                {"date": "2026-06-30", "total_value": None, "net_deposit": 500.0},
            ],
            "my_pension": [
                _rec("2026-05-31", 2000.0),
                _rec("2026-06-15", 2100.0),
                _rec("2026-06-30", 2200.0),
            ],
        }

        aggregate = aggregate_summary_records(records)

        assert aggregate[-1] == {
            "date": "2026-06-30", "total_value": None, "net_deposit": 500.0,
        }
        result = compute_settlement(aggregate, "2026-06-01", "2026-06-30")
        assert result.last_date == "2026-06-15"
        assert result.net_deposit == 0.0
        assert result.profit == 100.0
        assert result.twr_pct == pytest.approx(3.3333)


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

    def test_non_trade_cash_inflow_counted_as_deposit(self):
        """배당/이자 등 거래 외 현금 유입은 순입금으로 집계된다 (추정 차감 없음)"""
        assert derive_net_deposit(1010.0, 1000.0) == 10.0

    def test_first_record_counts_pretrade_cash_as_initial_deposit(self):
        """첫 기록: 체결 전 현금 = 초기 입금"""
        execs = [_exec(OrderAction.BUY, 10, 100.0)]  # 현금 -1000
        assert derive_net_deposit(500.0, None, execs) == 1500.0

    def test_withdrawal_is_negative(self):
        assert derive_net_deposit(700.0, 1000.0) == -300.0
