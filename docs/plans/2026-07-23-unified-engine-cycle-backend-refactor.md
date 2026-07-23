# Unified Engine Cycle Backend Refactor Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every trading engine reuse one backend cycle and one notification policy, while concrete engines define only strategy-specific data, indicators, decisions, and state transitions.

**Scope:** Backend only. Dashboard changes and persisted-data migration are intentionally excluded.

**Architecture:** `TradingEngine` owns the complete Template Method from data collection through persistence. Engines provide declarative `StrategyDataSpec` and strategy hooks. Brokers return a complete `OrderBatchResult` with one `OrderOutcome` per requested order. The common engine turns actionable order outcomes into alerts and persists only actual fills.

**Dependency rule:** `core` depends only on core abstractions. Infrastructure provides KIS, ticker-label, repository, notification, and data-provider implementations through interfaces.

---

### Task 1: Introduce the common data and indicator pipeline

**Files:**

- Create: `src/core/engine/data_pipeline.py`
- Create: `src/core/indicators.py`
- Modify: `src/core/engine/base.py`
- Modify: concrete engines under `src/core/engine/`
- Modify: `src/utils/calculator.py`
- Test: `tests/test_core_engine_data_pipeline.py`

**Steps:**

1. Define `DataSetSpec`, `StrategyDataSpec`, and `CollectedData`.
2. Move the common indicator calculator into `core`; keep the old utility import as a compatibility re-export.
3. Implement common `collect_data()` and `calculate_indicators()` in `TradingEngine`.
4. Fetch VIX once per cycle and calculate common `MarketData` from the declared reference dataset.
5. Replace concrete collection/calculation overrides with `data_spec()` and `calculate_strategy_indicators()` hooks.

### Task 2: Model every requested order outcome

**Files:**

- Modify: `src/core/models.py`
- Modify: `src/core/interfaces.py`
- Modify: `src/infra/broker/mock.py`
- Modify: `src/infra/broker/kis_base.py`
- Modify: `src/infra/broker/kis_domestic.py`
- Modify: `src/infra/broker/kis_overseas.py`
- Modify: `src/backtest/components.py`
- Test: `tests/test_core_order_results.py`

**Steps:**

1. Add `PARTIAL`, `CANCELLED`, `SKIPPED`, `REJECTED`, and `ERROR` statuses.
2. Add `OrderOutcome` and `OrderBatchResult`.
3. Require one outcome per requested order from broker adapters.
4. Map KIS API rejection messages to `REJECTED` without raising or returning `None`.
5. Treat spread guards and deliberate cash/quantity holds as `SKIPPED`.
6. Expose only `FILLED` and `PARTIAL` executions as actual fills.

### Task 3: Seal the common cycle and notification policy

**Files:**

- Modify: `src/core/engine/base.py`
- Modify: concrete engines under `src/core/engine/`
- Test: `tests/test_core_engine_order_alerts.py`
- Test: `tests/test_core_engine_domestic_qld_dip_buy.py`

**Steps:**

1. Keep safety checks, monitoring, order execution, alerting, state commit, and persistence in `TradingEngine`.
2. Add `StrategyDecision` and strategy hooks for decision construction and state finalization.
3. Alert on `PARTIAL`, `ORDERED`, `CANCELLED`, `REJECTED`, and `ERROR`, including the broker reason.
4. Do not alert on an entirely intentional `SKIPPED` result.
5. Persist history, settlement cash effects, and tranche progress from actual fills only.
6. Verify a rejected domestic dip-buy order completes the cycle, alerts Slack, and does not consume a tranche.

### Task 4: Restore Clean Architecture boundaries

**Files:**

- Modify: `src/core/interfaces.py`
- Create: `src/infra/ticker_labels.py`
- Modify: `src/core/logic/rebalancer.py`
- Modify: `src/main.py`
- Modify: `src/backtest/runner.py`
- Test: `tests/test_core_engine_architecture.py`

**Steps:**

1. Add a core ticker-label provider abstraction.
2. Move configuration-backed ticker display lookup to infrastructure.
3. Inject that implementation from live and backtest composition roots.
4. Add structural tests that forbid concrete cycle overrides, direct adapter access, and core-to-infrastructure imports.

### Task 5: Verify compatibility and regressions

**Steps:**

1. Run focused engine, broker, notification, main integration, and architecture tests.
2. Run the non-live full Python suite.
3. Run `git diff --check` and inspect the final diff.
4. Record unrelated baseline/environment failures separately rather than changing frontend or persistence behavior.
