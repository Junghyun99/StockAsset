# Portfolio Ungrouped Ticker Fix Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep the portfolio dashboard usable when a holding is absent from the configured asset groups.

**Architecture:** `getAssetGroup` will consider only configuration entries that expose a `tickers` array. An ungrouped ticker will fall through to the existing `Other` fallback, allowing allocation rendering to continue even when `aliases` metadata is present.

**Tech Stack:** Browser ES modules, Node.js built-in test runner.

---

### Task 1: Guard asset-group lookup

**Files:**

- Create: `tests/dashboard/portfolio-utils.test.mjs`
- Modify: `docs/js/utils.js:153-161`

**Step 1: Write the failing test**

Add a Node test that calls `getAssetGroup` with a ticker absent from `A`, `B`, and `C`, while the configuration includes an `aliases` object. Assert that it returns the `Other` fallback without throwing.

**Step 2: Run test to verify it fails**

Run: `node --test tests/dashboard/portfolio-utils.test.mjs`

Expected: FAIL with an error reading `includes` from `undefined`.

**Step 3: Write minimal implementation**

In `getAssetGroup`, call `.includes()` only when `info.tickers` is an array.

**Step 4: Run test to verify it passes**

Run: `node --test tests/dashboard/portfolio-utils.test.mjs`

Expected: PASS.

**Step 5: Verify related behavior**

Run the Node test and `node --check` for the changed dashboard modules.
