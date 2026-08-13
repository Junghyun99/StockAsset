# Force Dip Stage Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide a safe CLI that initializes a domestic QLD dip-buy Stage 1~3 campaign for the next automated cycle.

**Architecture:** The CLI uses `JsonRepository` to update only the account's existing `domestic_qld_dip_buy` strategy state. `SsoDipState` preserves optional forced-entry metadata through existing runtime state transitions; the planner continues to calculate tranche amounts on the next cycle.

**Tech Stack:** Python 3.10, argparse, pytest.

---

### Task 1: Preserve forced-entry audit metadata

**Files:**
- Modify: `src/core/logic/sso_dip_planner.py`
- Test: `tests/test_core_logic_sso_dip_planner.py`

**Step 1:** Write a failing state serialization test for `forced_at` and `forced_reason`.

**Step 2:** Run the test and confirm metadata cannot yet be passed to `SsoDipState`.

**Step 3:** Add optional metadata fields and preserve them in serialization and `record_filled_tranche()`.

**Step 4:** Re-run the test and confirm it passes.

### Task 2: Create the force-stage CLI

**Files:**
- Create: `scripts/force_dip_stage.py`
- Test: `tests/test_scripts_force_dip_stage.py`

**Step 1:** Write failing tests for a valid Stage 1 request and rejection of an active campaign.

**Step 2:** Run the tests and confirm the script module is absent.

**Step 3:** Implement argument parsing, Stage 1~3 validation, nonempty reason validation, IDLE-only protection, and repository state persistence.

**Step 4:** Re-run the CLI tests and confirm they pass.

### Task 3: Verify next-cycle progression

**Files:**
- Test: `tests/test_core_logic_sso_dip_planner.py`

**Step 1:** Write a planner test that uses a forced Stage 1 initial state with zero tranches and an IDLE raw signal.

**Step 2:** Run the test and confirm it proves the first 1/10 order and metadata preservation.

**Step 3:** Make only any implementation change necessary to pass; otherwise leave planner logic unchanged.

**Step 4:** Run the targeted test suite and commit implementation, tests, and plan.
