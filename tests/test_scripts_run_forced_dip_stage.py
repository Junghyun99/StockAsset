from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts import run_forced_dip_stage
from src.core.engine.domestic_qld_dip_buy import DomesticQldDipBuyEngine


@patch("scripts.run_forced_dip_stage.TradingBot")
def test_main_runs_only_requested_account_with_forced_stage(bot_class):
    engine = MagicMock(spec=DomesticQldDipBuyEngine)
    bot = bot_class.return_value
    bot.engine = engine
    bot.runners = [SimpleNamespace(account=SimpleNamespace(id="my_test"), engine=engine)]

    rc = run_forced_dip_stage.main([
        "--account", "my_test", "--stage", "1", "--reason", "2026-07-30 missed entry",
    ])

    assert rc == 0
    bot_class.assert_called_once_with(account_id="my_test", save_accounts_meta=False)
    engine.force_buy_stage.assert_called_once_with(1, "2026-07-30 missed entry")
    bot.run.assert_called_once_with()


@patch("scripts.run_forced_dip_stage.TradingBot")
def test_main_rejects_non_qld_engine(bot_class, capsys):
    bot = bot_class.return_value
    bot.engine = MagicMock()

    rc = run_forced_dip_stage.main([
        "--account", "other", "--stage", "1", "--reason", "manual entry",
    ])

    assert rc == 2
    assert "does not use DomesticQldDipBuyEngine" in capsys.readouterr().out
    bot.run.assert_not_called()
