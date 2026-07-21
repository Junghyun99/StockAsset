import json

from scripts.migrate_expected_dividend import migrate_summaries
from src.core.models import MarketData, MarketRegime, Portfolio, TradeSignal
from src.infra.repo import JsonRepository


def _summary_path(data_root, account_id):
    account_dir = data_root / account_id
    account_dir.mkdir(parents=True)
    return account_dir / "summary.json"


def test_save_daily_summary_writes_expected_dividend(tmp_path):
    repo = JsonRepository(root_path=str(tmp_path))
    market = MarketData("2026-07-21", 100.0, 90.0, 0.2, 0.1, -0.05, 15.0)
    portfolio = Portfolio(1000.0, {"SPY": 1}, {"SPY": 100.0})

    repo.save_daily_summary(
        market,
        TradeSignal(1.0, [], "test"),
        portfolio,
        MarketRegime.BULL,
        expected_dividend=55.25,
    )

    record = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))[0]
    assert record["expected_dividend"] == 55.25
    assert "daily_dividend" not in record


def test_migrate_summaries_renames_legacy_key_and_is_idempotent(tmp_path):
    legacy = _summary_path(tmp_path, "legacy")
    legacy.write_text(
        json.dumps([{"date": "2026-07-20", "daily_dividend": 3.5}]),
        encoding="utf-8",
    )
    both = _summary_path(tmp_path, "both")
    both.write_text(
        json.dumps([
            {
                "date": "2026-07-20",
                "daily_dividend": 3.5,
                "expected_dividend": 7.25,
            }
        ]),
        encoding="utf-8",
    )

    assert migrate_summaries(tmp_path) == 2
    assert migrate_summaries(tmp_path) == 0

    legacy_record = json.loads(legacy.read_text(encoding="utf-8"))[0]
    both_record = json.loads(both.read_text(encoding="utf-8"))[0]
    assert legacy_record == {"date": "2026-07-20", "expected_dividend": 3.5}
    assert both_record == {"date": "2026-07-20", "expected_dividend": 7.25}


def test_migrate_summaries_includes_nested_backtest_summaries(tmp_path):
    nested = tmp_path / "backtest" / "compare" / "Engine" / "summary.json"
    nested.parent.mkdir(parents=True)
    nested.write_text(json.dumps([{"daily_dividend": 1.5}]), encoding="utf-8")

    assert migrate_summaries(tmp_path) == 1
    assert json.loads(nested.read_text(encoding="utf-8")) == [{"expected_dividend": 1.5}]
