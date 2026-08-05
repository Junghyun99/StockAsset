# SSO/SPYI Slope Exit Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add independently-confirmed slope-down exits for SSO and SPYI without
automatic recovery buying.

**Architecture:** Extend the persisted per-ticker planner state with daily
slope confirmation, a once-per-deterioration latch, and an exit origin.  Reuse
the existing partial-sale and trailing-lock machinery, while limiting recovery
lots to channel-originated exits.

**Tech Stack:** Python 3.10, pandas, pytest.

---

### Task 1: Specify slope exits with failing tests

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Modify: `src/core/logic/sso_spyi_channel_planner.py`

**Step 1: Write the failing tests**

Add tests for SSO's two-day -6% slope confirmation and SPYI's two-day -4%
confirmation when no buffered channel breach exists.  Assert the first day does
not sell and the second sells half the holding.

**Step 2: Run tests to verify red**

Run `pytest tests/test_core_logic_sso_spyi_channel_planner.py -q`.
Expected: the new slope exit assertions fail because the planner has no
slope-down exit rule.

### Task 2: Persist origin and prevent automatic slope recovery buys

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Modify: `src/core/logic/sso_spyi_channel_planner.py`

**Step 1: Write the failing tests**

Assert a filled slope partial sale sets the slope origin and latch, creates no
recovery quantity or cash reservation, and a support rebound clears the lock
without producing a buy order.

**Step 2: Implement the minimum behavior**

Persist the origin through pending exit fills.  Restrict recovery-lot creation
and recovery orders to channel exits.  On a slope rebound, clear only its lock.

**Step 3: Verify green**

Run the focused planner tests.

### Task 3: Add once-per-deterioration protection

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Modify: `src/core/logic/sso_spyi_channel_planner.py`

**Step 1: Write the failing test**

After a slope-sale latch, verify the planner does not repeat the sale while
the slope stays below the threshold.  Verify two non-triggering daily slopes
release the latch and a later two-day deterioration can sell again.

**Step 2: Implement the minimum behavior**

Update the slope confirmation and release counters at most once per trading
date, using the current same-day value as the final state.

**Step 3: Verify green**

Run the focused planner tests.

### Task 4: Regression verification and review

**Files:**
- Test: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Test: `tests/test_core_logic_channel_regime.py`
- Test: `tests/test_core_engine_sso_spyi_channel_dip.py`
- Test: `tests/test_backtest_compare.py`

**Step 1: Run focused tests**

Run `pytest tests/test_core_logic_sso_spyi_channel_planner.py tests/test_core_logic_channel_regime.py tests/test_core_engine_sso_spyi_channel_dip.py -q`.

**Step 2: Run compare regression**

Run `$env:MPLBACKEND='Agg'; pytest tests/test_backtest_compare.py -q`.

**Step 3: Review and commit**

Review the planner state transitions and commit planner, tests, and this
design/implementation documentation.
