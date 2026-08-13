# IDLE Target-Weight Rebalance Wording Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Label IDLE leveraged-ETF purchases as target-weight rebalances rather than tranche buys.

**Architecture:** Change only the planner's display reason. Orders, state transitions, and Stage 1–3 wording remain unchanged.

**Tech Stack:** Python 3.10, pytest.

---

### Task 1: Capture the IDLE reason requirement

**Files:**

- Modify: `tests/test_core_logic_sso_dip_planner.py`
- Test: `tests/test_core_logic_sso_dip_planner.py`

**Step 1: Write the failing test**

Add a test that calls `SsoDipPlanner.plan()` with an IDLE signal and a
portfolio below the 20% leveraged-ETF target. Assert the reason contains
`IDLE 목표비중 보정 매수` and excludes `분할매수`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_logic_sso_dip_planner.py -q`

Expected: FAIL because the current reason includes `IDLE ... 분할매수`.

### Task 2: Format the IDLE reason separately

**Files:**

- Modify: `src/core/logic/sso_dip_planner.py:133-136`
- Test: `tests/test_core_logic_sso_dip_planner.py`

**Step 1: Write minimal implementation**

Choose `목표비중 보정 매수` when `new_state.level == SignalLevel.IDLE`; use
the existing tranche reason otherwise.

**Step 2: Run tests to verify behavior**

Run: `pytest tests/test_core_logic_sso_dip_planner.py tests/test_core_engine_domestic_qld_dip_buy.py -q`

Expected: PASS.

**Step 3: Commit**

```powershell
git add src/core/logic/sso_dip_planner.py tests/test_core_logic_sso_dip_planner.py docs/plans/2026-08-14-idle-target-rebalance-wording*.md
git commit -m "fix: clarify idle target-weight buys"
```
