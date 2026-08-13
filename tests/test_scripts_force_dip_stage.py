from src.core.logic.sso_dip_planner import SignalLevel, SsoDipState
from src.infra.repo import JsonRepository
from scripts.force_dip_stage import force_stage


STATE_KEY = "domestic_qld_dip_buy"


def test_force_stage_initializes_unstarted_campaign(tmp_path):
    repo = JsonRepository(str(tmp_path))
    repo.save_strategy_state(STATE_KEY, SsoDipState().to_dict())
    asset_groups = {"A": {"tickers": ["418660.KS"]}}
    (tmp_path / "asset_groups.json").write_text(json.dumps(asset_groups), encoding="utf-8")

    state = force_stage(
        data_root=str(tmp_path.parent),
        account=tmp_path.name,
        stage=1,
        reason="2026-07-30 missed entry",
        forced_at="2026-08-14T10:00:00+09:00",
    )

    assert state.level == SignalLevel.BUY_STAGE_1
    assert state.tranche_total == 0
    assert state.tranche_completed == 0
    assert state.tranche_amount == 0.0
    assert state.forced_reason == "2026-07-30 missed entry"
    assert repo.load_strategy_state(STATE_KEY)["level"] == "BUY_STAGE_1"
    assert json.loads((tmp_path / "asset_groups.json").read_text(encoding="utf-8")) == asset_groups


def test_force_stage_rejects_active_campaign(tmp_path):
    repo = JsonRepository(str(tmp_path))
    repo.save_strategy_state(STATE_KEY, SsoDipState(
        level=SignalLevel.BUY_STAGE_1,
        tranche_total=10,
        tranche_completed=2,
        tranche_amount=100.0,
    ).to_dict())

    try:
        force_stage(
            data_root=str(tmp_path.parent), account=tmp_path.name, stage=1,
            reason="retry", forced_at="2026-08-14T10:00:00+09:00",
        )
    except ValueError as error:
        assert "active campaign" in str(error)
    else:
        raise AssertionError("active campaign must not be overwritten")
import json
