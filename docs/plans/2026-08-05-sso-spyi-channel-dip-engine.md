# SSO/SPYI Channel Dip Engine Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a separately registered SSO/SPYI channel-protected dip-buy engine.

**Architecture:** Keep channel calculations and the stateful order planner in `core.logic`; the engine only gathers independent ticker datasets and persists planner state through the existing `TradingEngine` hooks. Backtests reuse the same engine via the registry.

**Tech Stack:** Python 3.10, pandas, pytest.

---

### Task 1: Document the approved design

**Files:**
- Create: `docs/plans/2026-08-05-sso-spyi-channel-dip-engine-design.md`

Write the final signal, campaign, channel exit, and SSO cap decisions.

### Task 2: Implement and test pure channel calculations

**Files:**
- Create: `src/core/logic/channel_regime.py`
- Test: `tests/test_core_logic_channel_regime.py`

Use TDD for 63-bar logarithmic linear regression, channel bands, and invalid input.

### Task 3: Implement and test stateful dual-asset planning

**Files:**
- Create: `src/core/logic/sso_spyi_channel_planner.py`
- Test: `tests/test_core_logic_sso_spyi_channel_planner.py`

Use TDD for daily confirmation, campaign budgets/cadence, priority, exits, and SSO cap hysteresis.

### Task 4: Integrate and test the engine

**Files:**
- Create: `src/core/engine/sso_spyi_channel_dip.py`
- Modify: `src/core/engine/__init__.py`
- Modify: `tests/test_backtest_compare.py`
- Test: `tests/test_core_engine_sso_spyi_channel_dip.py`

Register the engine for compare backtests and verify its datasets, state persistence, and interval override.

### Task 5: Verify

Run focused tests, architecture validation, and the compare test with a headless matplotlib backend where required.
