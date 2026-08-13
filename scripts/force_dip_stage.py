#!/usr/bin/env python3
"""Initialize the next domestic QLD dip-buy campaign from a chosen buy stage."""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from src.core.logic.sso_dip_planner import SignalLevel, SsoDipState


STATE_KEY = "domestic_qld_dip_buy"
KST = timezone(timedelta(hours=9))


def force_stage(
    data_root: str,
    account: str,
    stage: int,
    reason: str,
    forced_at: str | None = None,
) -> SsoDipState:
    if stage not in (1, 2, 3):
        raise ValueError("stage must be one of: 1, 2, 3")
    if not reason.strip():
        raise ValueError("reason is required")

    state_path = os.path.join(data_root, account, "strategy_state.json")
    try:
        with open(state_path, "r", encoding="utf-8") as state_file:
            states = json.load(state_file)
    except FileNotFoundError:
        states = {}
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid strategy state JSON: {error}") from error

    current = SsoDipState.from_dict(states.get(STATE_KEY))
    if current.level != SignalLevel.IDLE or current.tranche_total != 0:
        raise ValueError("active campaign exists; refusing to overwrite it")

    state = SsoDipState(
        level=SignalLevel[f"BUY_STAGE_{stage}"],
        forced_at=forced_at or datetime.now(KST).isoformat(timespec="seconds"),
        forced_reason=reason.strip(),
    )
    states[STATE_KEY] = state.to_dict()
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as state_file:
        json.dump(states, state_file, indent=4, ensure_ascii=False)
    return state


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--stage", required=True, type=int, choices=(1, 2, 3))
    parser.add_argument("--reason", required=True)
    parser.add_argument("--data-root", default="docs/data")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        state = force_stage(args.data_root, args.account, args.stage, args.reason)
    except ValueError as error:
        print(f"error: {error}")
        return 2
    print(
        f"Forced {state.level.value} for {args.account}; "
        f"next cycle will initialize its tranche schedule."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
