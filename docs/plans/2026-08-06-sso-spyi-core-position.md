# SSO/SPYI Core Position Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish one fixed-share core allocation of SSO 5% and SPYI 15%,
then restrict dip campaigns and all risk exits to tactical shares above it.

**Architecture:** Persist each ticker's target core shares, filled core shares,
and outstanding setup quantity in `AssetState`.  The planner calculates both
targets from the same first-cycle portfolio value, prioritizes outstanding core
setup orders after sells/recoveries, and uses `holding - core_quantity` for
tactical exits and the SSO hard-cap sell limit.

**Tech Stack:** Python 3.10, pytest, existing pure planner and engine state
serialization.

---

### Task 1: Add persisted core setup state

**Files:**
- Modify: `src/core/logic/sso_spyi_channel_planner.py: AssetState and SsoSpyiChannelPlanner.plan`
- Test: `tests/test_core_logic_sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Add a fresh-state test using a $10,000 portfolio at SSO $100 and SPYI $50.
It must expect setup-only buys of 5 SSO shares and 30 SPYI shares, with no
campaign buy in the same plan.  Add serialization assertions for persisted core
target, filled, and pending quantities.

**Step 2: Run tests to verify red**

Run:
`pytest tests/test_core_logic_sso_spyi_channel_planner.py -q`

Expected: FAIL because core state and setup orders do not exist.

**Step 3: Implement minimal core state and orders**

Add `CORE_ALLOCATIONS = {"SSO": 0.05, "SPYI": 0.15}` and persisted fields:
`core_target_quantity`, `core_quantity`, `pending_core_quantity`, and
`pending_core_date`.  On the first plan, calculate both targets from the same
portfolio total value.  Return outstanding setup buy orders before the
dip-buy campaign.

**Step 4: Verify green**

Run the focused test file.

### Task 2: Make core setup fill-aware and retry-safe

**Files:**
- Modify: `src/core/logic/sso_spyi_channel_planner.py: record_fills and setup helpers`
- Test: `tests/test_core_logic_sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Cover a partial core fill, an unfilled setup retry on the following trading
date, and the rule that normal campaigns remain blocked until both cores are
fully established.

**Step 2: Run tests to verify red**

Run only the new core-retry tests and confirm missing or incorrect state.

**Step 3: Implement minimal fill handling**

On core-buy fills, add the actual quantity to `core_quantity`, clear only the
filled pending quantity, and retain the target.  Reset a stale pending order on
the next date so the remaining setup quantity can retry.  Do not count core
orders as campaign phase orders or modify campaign cash/cadence.

**Step 4: Verify green**

Run the focused test file.

### Task 3: Limit exits and hard-cap reductions to tactical shares

**Files:**
- Modify: `src/core/logic/sso_spyi_channel_planner.py: _exit_orders, _start_exit, _start_full_exit, _sso_cap_order`
- Test: `tests/test_core_logic_sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Add tests proving a slope or channel partial exit sells half of tactical shares,
a trailing full exit sells only the remaining tactical shares, and an SSO
hard-cap order uses total SSO value for exposure but cannot sell more than its
tactical quantity.  Cover the core-floor reason when 78% cannot be reached.

**Step 2: Run tests to verify red**

Run the new exit tests and confirm current code sells from all holdings.

**Step 3: Implement tactical quantity helper**

Add a helper equivalent to `max(portfolio.holdings[ticker] - state.core_quantity, 0)`.
Use it for partial exit, trailing full exit, pending exit retry bounds, and
hard-cap maximum sale.  Keep total holding value in the hard-cap ratio and
needed-reduction calculation.

**Step 4: Verify green**

Run the focused test file.

### Task 4: Preserve existing recovery and regression behavior

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`
- Test: `tests/test_core_logic_channel_regime.py`
- Test: `tests/test_core_engine_sso_spyi_channel_dip.py`
- Test: `tests/test_backtest_compare.py`

**Step 1: Add regression tests**

Verify channel recovery lots restore only tactical shares and slope exits still
reserve no cash or make no automatic recovery buy.  Verify a tactical full exit
does not reset core quantities or trigger a new bootstrap order.

**Step 2: Run focused regression tests**

Run:
`pytest tests/test_core_logic_sso_spyi_channel_planner.py tests/test_core_logic_channel_regime.py tests/test_core_engine_sso_spyi_channel_dip.py -q`

**Step 3: Run comparison regression**

Run:
`$env:MPLBACKEND='Agg'; pytest tests/test_backtest_compare.py -q`

**Step 4: Run actual-price replay**

Use the analysis script with the cached SSO/SPYI history to confirm that first
setup creates only the 5%/15% core orders and subsequent campaign orders use
remaining cash.

**Step 5: Commit**

Stage planner, planner tests, and this plan.  Commit with a message describing
fixed core positions and tactical-only exits.
