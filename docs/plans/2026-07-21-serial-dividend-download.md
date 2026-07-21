# Serial Dividend Download Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent yfinance cache-lock contention during live dividend-rate lookups by disabling concurrent ticker downloads.

**Architecture:** The live engine already performs the expected-dividend lookup after Step 4 has fetched the portfolio. Keep that data flow intact and change only `YFinanceLoader.get_dividend_rates`, where the multi-ticker yfinance call is made. Pass `threads=False` to preserve the existing batch response schema while making the underlying ticker fetches serial.

**Tech Stack:** Python 3.10, yfinance, pandas, pytest, unittest.mock.

---

### Task 1: Specify the serial-download contract

**Files:**

- Modify: `tests/test_infra_data.py`
- Test: `tests/test_infra_data.py`

**Step 1: Write the failing test**

Add a test for `YFinanceLoader.get_dividend_rates` that patches `src.infra.data.yf.download`, calls the method with multiple tickers, and asserts that the call includes `threads=False` while retaining `actions=True`, `period="5d"`, `auto_adjust=False`, and `progress=False`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_infra_data.py -k dividend_rates -v`

Expected: FAIL because the yfinance call has no `threads` argument.

**Step 3: Write minimal implementation**

In `src/infra/data.py`, add `threads=False` to the existing `yf.download` call in `get_dividend_rates` only.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_infra_data.py -k dividend_rates -v`

Expected: PASS.

**Step 5: Commit**

    git add src/infra/data.py tests/test_infra_data.py docs/plans/2026-07-21-serial-dividend-download.md
    git commit -m "fix: serialize dividend-rate downloads"

### Task 2: Verify the focused live-engine boundary

**Files:**

- Test: `tests/test_core_engine.py`

**Step 1: Run the existing Step 4 expected-dividend tests**

Run: `pytest tests/test_core_engine.py -k dividend -v`

Expected: PASS, confirming the provider remains invoked after portfolio retrieval and before persistence.

**Step 2: Run the focused regression suite**

Run: `pytest tests/test_infra_data.py tests/test_core_engine.py -v`

Expected: PASS.
