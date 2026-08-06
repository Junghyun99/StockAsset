# SSO/SPYI Channel Dip Stage-1 Expansion Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Increase core exposure to SSO 10% and SPYI 30%, and broaden only level-1 dip detection with OR semantics.

**Architecture:** Keep allocation constants, signal classification, and phase transitions inside the pure `SsoSpyiChannelPlanner`. The engine continues to gather data and persist state unchanged. Extend the existing planner test module to lock down all changed behavior.

**Tech Stack:** Python 3.10, pytest.

---

### Task 1: Specify changed core and signal rules

**Files:**
- Modify: `tests/test_core_logic_sso_spyi_channel_planner.py`

**Step 1: Write failing tests**

Add tests that assert core setup buys 10 SSO shares and 60 SPYI shares for a $10,000 portfolio at $100/$50 prices; level 1 is emitted for either qualifying metric; and levels 2/3 still require both metrics.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core_logic_sso_spyi_channel_planner.py -v`

**Step 3: Implement the minimal rule changes**

Update `CORE_ALLOCATIONS` and `_signal_level` in `src/core/logic/sso_spyi_channel_planner.py`.

**Step 4: Run focused tests**

Run: `pytest tests/test_core_logic_sso_spyi_channel_planner.py -v`

### Task 2: Verify integration and compare regression

**Files:**
- Test: `tests/test_core_engine_sso_spyi_channel_dip.py`
- Test: `tests/test_backtest_compare.py`

**Step 1: Run focused test suite**

Run: `pytest tests/test_core_logic_sso_spyi_channel_planner.py tests/test_core_engine_sso_spyi_channel_dip.py tests/test_backtest_compare.py -v`

**Step 2: Run architectural validation**

Run: `python -m pytest tests/test_core_logic_sso_spyi_channel_planner.py tests/test_core_engine_sso_spyi_channel_dip.py -q`

**Step 3: Commit implementation**

Run: `git add src/core/logic/sso_spyi_channel_planner.py tests/test_core_logic_sso_spyi_channel_planner.py docs/plans/2026-08-06-sso-spyi-channel-dip-stage1-or.md && git commit -m "feat: broaden channel dip stage one"`
