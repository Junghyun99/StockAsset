# Slope-Exit Partial Recovery Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Buy back 50% of a filled slope-exit sale after the existing two-day slope-release confirmation.

**Architecture:** Reuse the planner's existing recovery-lot state and fill accounting. Extend only the slope-exit fill path and recovery eligibility; channel recovery and dip-buy campaigns remain separate.

**Tech Stack:** Python 3.10, pytest.

---

### Task 1: Specify the slope recovery lot

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`

**Step 1: Write the failing test**

Replace the slope-exit assertion that requires no recovery lot with a test
that fills a 10-share slope sale and expects a five-share lot with $500
reserved at a $100 fill price.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_logic_sso_spyi_channel_planner.py::test_filled_slope_exit_reserves_half_for_recovery -v --basetemp=.pytest-tmp`

Expected: FAIL because slope exits currently create no recovery lot.

**Step 3: Implement the minimal code**

In `record_fills`, create a 50%-sized recovery quantity and reserved cash for
each filled slope-exit execution.

**Step 4: Run test to verify it passes**

Run the command from Step 2. Expected: PASS.

### Task 2: Specify release-gated ordering and retries

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Modify: `src/core/logic/sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Add tests proving that a slope recovery does not order before the second
release day, orders its reserved half on that day even below channel support,
and retries an unfilled order on the next trading date.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core_logic_sso_spyi_channel_planner.py -v --basetemp=.pytest-tmp`

Expected: FAIL because unlocked slope exits currently clear the lock without
placing a recovery buy.

**Step 3: Implement the minimal code**

Keep an unlocked slope exit in `EXIT_LOCK` until its recovery lot is ordered,
and permit `_recovery_orders` to place that order after `slope_exit_latched`
becomes false. Preserve the current channel-support rule for channel exits.

**Step 4: Run tests to verify they pass**

Run the command from Step 2. Expected: PASS.

### Task 3: Verify planner and engine integration

**Files:**
- Test: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Test: `tests/test_core_engine_sso_spyi_channel_dip.py`
- Test: `tests/test_backtest_compare.py`

**Step 1: Run focused suite**

Run: `pytest tests/test_core_logic_sso_spyi_channel_planner.py tests/test_core_engine_sso_spyi_channel_dip.py tests/test_backtest_compare.py -v --basetemp=.pytest-tmp`

**Step 2: Inspect the diff**

Run: `git diff --check` and `git diff -- src/core/logic/sso_spyi_channel_planner.py tests/test_core_logic_sso_spyi_channel_planner.py`.

**Step 3: Commit**

Run: `git add docs/plans/2026-08-06-slope-exit-partial-recovery-design.md docs/plans/2026-08-06-slope-exit-partial-recovery.md src/core/logic/sso_spyi_channel_planner.py tests/test_core_logic_sso_spyi_channel_planner.py && git commit -m "feat: partially recover slope exits"`
