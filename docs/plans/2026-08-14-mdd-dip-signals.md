# MDD Dip Signal Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 252-trading-day MDD alternative to the domestic QLD dip-buy Stage 1~3 entry conditions.

**Architecture:** Extend the pure `SsoDipSignals` value object with trailing MDD computed from the same close series. Pass that value to `SsoDipPlanner`, where each existing stage retains its RSI gate and accepts either the historical MA200-deviation threshold or its new MDD threshold. Surface the value as a decision factor so persisted account summaries explain the signal.

**Tech Stack:** Python 3.10, pandas, pytest.

---

### Task 1: Add MDD calculation to signal data

**Files:**
- Modify: `src/core/logic/sso_dip_signals.py`
- Test: `tests/test_core_logic_sso_dip_signals.py`

**Step 1:** Add a failing test for trailing-252 high MDD and insufficient-data NaN behavior.

**Step 2:** Run the new test and confirm it fails because `mdd_252` does not exist.

**Step 3:** Add `MDD_WINDOW`, the `mdd_252` signal field, and the trailing-peak calculation.

**Step 4:** Re-run the new tests and confirm they pass.

### Task 2: Use MDD as an alternative Stage trigger

**Files:**
- Modify: `src/core/logic/sso_dip_planner.py`
- Test: `tests/test_core_logic_sso_dip_planner.py`

**Step 1:** Add failing tests proving Stage 1, 2, and 3 are selected when RSI and MDD meet their thresholds while MA200 deviation does not; add one test proving RSI remains mandatory.

**Step 2:** Run those tests and confirm the planner rejects the unsupported `mdd_252` signal argument.

**Step 3:** Extend stage configuration and `_detect_signal` minimally to apply the OR condition.

**Step 4:** Re-run the planner tests and confirm they pass.

### Task 3: Surface MDD in domestic decision factors

**Files:**
- Modify: `src/core/engine/domestic_qld_dip_buy.py`
- Test: `tests/test_core_engine_domestic_qld_dip_buy.py`

**Step 1:** Add a failing assertion that `mdd_252` is emitted with a -20% Stage 1 reference threshold.

**Step 2:** Run the test and confirm it fails.

**Step 3:** Add the decision factor without changing order planning or state persistence.

**Step 4:** Run the engine test and confirm it passes.

### Task 4: Verify and publish

**Files:**
- Verify: files above and `docs/plans/2026-08-14-mdd-dip-signals-design.md`

**Step 1:** Run the MDD-specific tests and the unaffected planner/engine suites using a worktree-local pytest base temp directory.

**Step 2:** Review the diff for clean-architecture direction, threshold boundaries, NaN handling, and unintended strategy-state changes.

**Step 3:** Commit implementation and tests.

**Step 4:** Push `feat/mdd-dip-signals` and create a draft PR describing the existing, unrelated signal-calculator fixture failures.
