# tests/test_scripts_settlement.py
"""monthly_settlement CLI 스크립트 테스트."""
import json
import os

import pytest

from scripts import monthly_settlement


def _write_account(root, account, summaries, history=None):
    acc_dir = os.path.join(str(root), account)
    os.makedirs(acc_dir, exist_ok=True)
    with open(os.path.join(acc_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summaries, f)
    if history is not None:
        with open(os.path.join(acc_dir, "history.json"), "w", encoding="utf-8") as f:
            json.dump(history, f)
    return acc_dir


def _rec(date, value, cash, net_deposit=0.0, dividend=0.0):
    return {"date": date, "total_value": value, "cash_balance": cash,
            "net_deposit": net_deposit, "daily_dividend": dividend}


class TestMonthlySettlementCli:
    def test_report_printed(self, tmp_path, capsys):
        _write_account(tmp_path, "acc1", [
            _rec("2026-05-31", 1000.0, 100.0),
            _rec("2026-06-10", 1600.0, 100.0, net_deposit=500.0),
            _rec("2026-06-28", 1650.0, 100.0),
        ])
        rc = monthly_settlement.main([
            "--account", "acc1", "--start", "2026-06-01", "--end", "2026-06-30",
            "--data-root", str(tmp_path),
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "기간 결산 (acc1)" in out
        assert "KRW 1,000" in out       # 기초자산
        assert "KRW 500" in out         # 순입금
        assert "+KRW 150" in out        # 기간손익

    def test_missing_net_deposit_warning(self, tmp_path, capsys):
        _write_account(tmp_path, "acc1", [
            _rec("2026-05-31", 1000.0, 100.0),
            {"date": "2026-06-10", "total_value": 1100.0, "cash_balance": 100.0},
        ])
        rc = monthly_settlement.main([
            "--account", "acc1", "--start", "2026-06-01", "--end", "2026-06-30",
            "--data-root", str(tmp_path),
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "순입금 미기록 레코드 1건" in out

    def test_no_records_in_range(self, tmp_path, capsys):
        _write_account(tmp_path, "acc1", [_rec("2026-01-05", 1000.0, 100.0)])
        rc = monthly_settlement.main([
            "--account", "acc1", "--start", "2026-06-01", "--end", "2026-06-30",
            "--data-root", str(tmp_path),
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "일별 요약 데이터가 없습니다" in out

    def test_missing_account_returns_error(self, tmp_path, capsys):
        rc = monthly_settlement.main([
            "--account", "nope", "--start", "2026-06-01", "--end", "2026-06-30",
            "--data-root", str(tmp_path),
        ])
        assert rc == 2
        assert "summary.json이 없습니다" in capsys.readouterr().err

    def test_start_after_end_returns_error(self, tmp_path, capsys):
        rc = monthly_settlement.main([
            "--account", "acc1", "--start", "2026-06-30", "--end", "2026-06-01",
            "--data-root", str(tmp_path),
        ])
        assert rc == 2
        assert "뒤입니다" in capsys.readouterr().err

    def test_invalid_date_rejected(self, tmp_path):
        with pytest.raises(SystemExit):
            monthly_settlement.parse_args([
                "--account", "acc1", "--start", "2026/06/01", "--end", "2026-06-30",
            ])

    def test_date_normalized_zero_pad(self):
        args = monthly_settlement.parse_args([
            "--account", "acc1", "--start", "2026-6-1", "--end", "2026-6-30",
        ])
        assert args.start == "2026-06-01"
        assert args.end == "2026-06-30"
