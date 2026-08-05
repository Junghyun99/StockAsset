# SSO/SPYI Channel Exit Recovery Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply buffered all-regime channel exits and restore partial-sale
exposure when the channel support recovers.

**Architecture:** Extend the pure `SsoSpyiChannelPlanner` state with a persisted
recovery lot and reservation.  Keep the engine interface unchanged; it continues
to feed current prices and record broker fills into the planner.

**Tech Stack:** Python 3.10, pandas, pytest.

---

### Task 1: Specify buffered all-regime exit behavior with failing tests

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Modify: `src/core/logic/sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Add focused tests proving that a two-day price below `support * (1-margin)` sells
without `uptrend_active`, and that a first-day breach or a price above the
buffered line does not sell.  Assert SSO uses 3% and SPYI 2% margins.

**Step 2: Verify failure**

Run `pytest tests/test_core_logic_sso_spyi_channel_planner.py -q` and confirm the
new assertions fail because the current planner still gates exits by uptrend and
uses the raw support line.

**Step 3: Implement the minimum behavior**

Add per-ticker `breakdown_margin` and updated trailing settings to
`CHANNEL_RULES`.  Count a breach below the buffered line and remove the uptrend
requirement from `_exit_orders`.

**Step 4: Verify green**

Run the focused planner test file.

### Task 2: Add recovery-lot reservation with failing tests

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Modify: `src/core/logic/sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Cover: partial-sale fill creates a persisted recovery lot; ordinary buy capacity
excludes that reservation; support recovery creates a priority buy for the sold
quantity; a recovery buy clears the lot after fill; a full trailing exit clears
the lot.

**Step 2: Verify failure**

Run only the new tests and confirm they fail due to missing recovery state and
orders.

**Step 3: Implement the minimum behavior**

Persist the recovery quantity, cash reservation, and pending recovery fill.  Add
recovery ordering after exits and before campaign buys.  Use reservation-aware
cash for campaign budget initialization and orders.  Update fill handling for
partial and complete recovery buys.

**Step 4: Verify green**

Run the focused planner test file.

### Task 3: Regression verification

**Files:**
- Test: `tests/test_core_logic_channel_regime.py`
- Test: `tests/test_core_engine_sso_spyi_channel_dip.py`
- Test: `tests/test_backtest_compare.py`

**Step 1: Run focused tests**

Run:
`pytest tests/test_core_logic_sso_spyi_channel_planner.py tests/test_core_logic_channel_regime.py tests/test_core_engine_sso_spyi_channel_dip.py -q`

**Step 2: Run compare regression**

Run `MPLBACKEND=Agg pytest tests/test_backtest_compare.py -q`.

**Step 3: Commit**

Stage only planner, its tests, and these design/plan documents.  Commit with a
message describing buffered exits and recovery buybacks.
