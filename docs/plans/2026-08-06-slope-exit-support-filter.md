# Slope-Exit Support Filter Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Require concurrent price-below-support and negative-slope confirmation for slope exits, and make their reserved recovery reliable.

**Architecture:** Keep state and priority changes in the pure `SsoSpyiChannelPlanner`. Reuse existing exit origin, recovery-lot persistence, and order fill accounting; only change the criteria that advance the slope counter and the lock paths that currently discard a valid slope lot.

**Tech Stack:** Python 3.10, pytest.

---

### Task 1: Specify combined slope/support confirmation

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Modify: `src/core/logic/sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Add tests that prove a negative slope above support does not advance toward a
slope exit, that two consecutive dates satisfying both conditions sell, and
that a support recapture resets the pending count.

**Step 2: Verify RED**

Run: `pytest tests/test_core_logic_sso_spyi_channel_planner.py -v --basetemp=.pytest-tmp`

Expected: new tests fail because the current counter ignores price.

**Step 3: Implement the minimum rule**

Advance `slope_exit_days` only when the slope is below the ticker threshold
and price is below the unbuffered support; reset otherwise.

**Step 4: Verify GREEN**

Run the command from Step 2. Expected: PASS.

### Task 2: Specify slope recovery priority

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Modify: `src/core/logic/sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Add tests that retain a slope lock across support recapture and place the
reserved recovery order after two release dates even if a dip-buy signal is
confirmed.

**Step 2: Verify RED**

Run the targeted new tests with `pytest ... -v --basetemp=.pytest-tmp`.

Expected: failures because support recapture clears the slope lock and a dip
signal suppresses the recovery lot.

**Step 3: Implement the minimum state-order changes**

Do not clear a slope-originated lock on support recapture while it has a
reserved lot. Prioritize the released slope lot ahead of dip-signal suppression
and campaign orders.

**Step 4: Verify GREEN**

Run the command from Step 2. Expected: PASS.

### Task 3: Verify integration

**Files:**
- Test: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Test: `tests/test_core_engine_sso_spyi_channel_dip.py`
- Test: `tests/test_backtest_compare.py`

**Step 1: Run focused suite**

Run: `pytest tests/test_core_logic_sso_spyi_channel_planner.py tests/test_core_engine_sso_spyi_channel_dip.py tests/test_backtest_compare.py -v --basetemp=.pytest-tmp`

**Step 2: Inspect change quality**

Run: `git diff --check` and inspect the planner/test diff.

**Step 3: Commit**

Run: `git add docs/plans/2026-08-06-slope-exit-support-filter-design.md docs/plans/2026-08-06-slope-exit-support-filter.md src/core/logic/sso_spyi_channel_planner.py tests/test_core_logic_sso_spyi_channel_planner.py && git commit -m "feat: filter slope exits by support"`
