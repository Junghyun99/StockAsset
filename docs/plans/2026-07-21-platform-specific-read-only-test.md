# Platform-Specific Read-Only Test Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the repository test suite collect on Windows while preserving the real read-only file test on supported Unix environments.

**Architecture:** Keep the existing filesystem-permission test unchanged. Replace its marker predicate with a platform-safe condition: skip Windows before consulting a POSIX-only effective user ID, and also skip root because root can write despite the read-only mode.

**Tech Stack:** Python 3.10, pytest, standard library `os`.

---

### Task 1: Capture the Windows collection failure

**Files:**

- Modify: `tests/test_infra_repo.py:481`
- Test: `tests/test_infra_repo.py`

**Step 1: Write the failing test**

Replace the marker's direct `os.getuid()` access with an assertion that the marker expression can be evaluated when `os.name == "nt"` and no POSIX user-ID function exists.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_infra_repo.py -v`

Expected: collection fails on Windows with `AttributeError: module 'os' has no attribute 'getuid'`.

**Step 3: Write minimal implementation**

Use a marker predicate of `os.name == "nt" or os.geteuid() == 0`; Python short-circuits the expression on Windows before accessing the POSIX-only API.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_infra_repo.py -v`

Expected: successful collection; the Unix-only test is skipped on Windows.

### Task 2: Run regression checks

**Files:**

- Test: `tests/test_infra_repo.py`

**Step 1: Run the focused test file**

Run: `pytest tests/test_infra_repo.py -v`

Expected: no collection errors; all applicable tests pass.

**Step 2: Run the full suite**

Run: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/`

Expected: no collection error from `os.getuid()`; report any unrelated failures separately.

**Step 3: Commit**

    git add tests/test_infra_repo.py docs/plans/2026-07-21-platform-specific-read-only-test-design.md docs/plans/2026-07-21-platform-specific-read-only-test.md
    git commit -m "test: skip read-only file test on Windows"
