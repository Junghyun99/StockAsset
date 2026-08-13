# Dip-Buy Funding Margin Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fund dip-buy leveraged-ETF purchases with sufficient income-ETF sales to satisfy the broker's 98% buy margin and estimated sell fee.

**Architecture:** Keep funding arithmetic in `SsoDipPlanner`, using explicit policy constants rather than importing infrastructure code.  The KIS broker retains its independent live cash and spread validation immediately before a purchase.

**Tech Stack:** Python 3.10, pytest.

---

### Task 1: Capture the 2026-08-12 funding regression

**Files:**

- Modify: `tests/test_core_logic_sso_dip_planner.py`
- Test: `tests/test_core_logic_sso_dip_planner.py`

**Step 1: Write the failing test**

Add a planner test with 9,560 cash, a 42,140 leveraged-ETF price, and a
10,890 income-ETF price.  Assert that the buy of one leveraged share is paired
with an income-ETF sale of four shares.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_logic_sso_dip_planner.py -q`

Expected: the new assertion fails because the current planner sells three
income-ETF shares.

**Step 3: Commit**

```powershell
git add tests/test_core_logic_sso_dip_planner.py
git commit -m "test: cover dip-buy funding safety margin"
```

### Task 2: Apply funding safety margin in the planner

**Files:**

- Modify: `src/core/logic/sso_dip_planner.py:119-132`
- Test: `tests/test_core_logic_sso_dip_planner.py`

**Step 1: Write minimal implementation**

Define explicit planner constants for the 98% buy margin and estimated sell
fee rate.  Calculate the required post-sale cash as buy cost divided by the
margin plus estimated sell fees, then round the income-ETF sale quantity up.

**Step 2: Run regression test to verify it passes**

Run: `pytest tests/test_core_logic_sso_dip_planner.py -q`

Expected: PASS.

**Step 3: Run relevant broker tests**

Run: `pytest tests/test_core_logic_sso_dip_planner.py tests/test_core_order_results.py -q`

Expected: PASS.

**Step 4: Commit**

```powershell
git add src/core/logic/sso_dip_planner.py tests/test_core_logic_sso_dip_planner.py
git commit -m "fix: fund dip-buy orders with safety margin"
```

### Task 3: Verify the change

**Files:**

- Verify only: `src/core/logic/sso_dip_planner.py`
- Verify only: `tests/test_core_logic_sso_dip_planner.py`

**Step 1: Run the full non-live test suite with coverage**

Run: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/ --ignore=tests/test_infra_broker_kis_domestic_live.py`

Expected: PASS with total coverage at or above 80%.

**Step 2: Inspect the final diff and working tree**

Run: `git diff --check; git status --short`

Expected: no whitespace errors and only the intended files changed.
