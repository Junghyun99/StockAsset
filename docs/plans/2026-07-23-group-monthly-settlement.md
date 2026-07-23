# Group Monthly Settlement Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generate individual and consolidated monthly settlements for both `my_*` and `spouse_*` accounts in one workflow run.

**Architecture:** Keep single-account settlement unchanged. Add reusable group discovery and per-date summary aggregation in `src.core.settlement`; group-mode CLI orchestration in `scripts.monthly_settlement` reuses the existing result formatter and settlement calculator. The GitHub Actions workflow calls group mode once with only a date range.

**Tech Stack:** Python 3.10, `argparse`, JSON files, pytest, GitHub Actions.

---

### Task 1: Add core group-summary aggregation tests

**Files:**
- Modify: `tests/test_core_settlement.py`
- Modify: `src/core/settlement.py`

**Step 1: Write the failing test**

Append tests that specify a date-keyed aggregation API. The input is a mapping of
account ID to `summary.json` records; it must sum same-day `total_value` and
`net_deposit`, retain the ISO date, and exclude non-finite account values from
the total while preserving valid accounts.

```python
def test_aggregate_summary_records_sums_assets_and_cash_flows():
    records = {
        "my_isa": [
            {"date": "2026-05-31", "total_value": 1000, "net_deposit": 0},
            {"date": "2026-06-30", "total_value": 1200, "net_deposit": 100},
        ],
        "my_pension": [
            {"date": "2026-05-31", "total_value": 2000, "net_deposit": 0},
            {"date": "2026-06-30", "total_value": 2100, "net_deposit": 0},
        ],
    }

    assert aggregate_summary_records(records) == [
        {"date": "2026-05-31", "total_value": 3000.0, "net_deposit": 0.0},
        {"date": "2026-06-30", "total_value": 3300.0, "net_deposit": 100.0},
    ]
```

Add a companion test that passes the aggregate records to `compute_settlement`
and asserts a group profit of `200.0` and the expected TWR.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_settlement.py -q`

Expected: FAIL because `aggregate_summary_records` is not importable.

**Step 3: Write minimal implementation**

In `src/core/settlement.py`, add this public helper near `compute_settlement`:

```python
def aggregate_summary_records(account_records: dict[str, List[dict]]) -> List[dict]:
    totals: dict[str, dict] = {}
    for records in account_records.values():
        for record in records:
            date = record.get("date")
            if not date:
                continue
            item = totals.setdefault(date, {
                "date": date,
                "total_value": 0.0,
                "net_deposit": 0.0,
            })
            value = _finite(record.get("total_value"))
            if value is not None:
                item["total_value"] += value
            item["net_deposit"] += float(record.get("net_deposit") or 0.0)
    return [totals[date] for date in sorted(totals)]
```

Round output values to two decimal places if required by the failing assertion.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_core_settlement.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/core/settlement.py tests/test_core_settlement.py
git commit -m "feat: aggregate settlement summaries by group"
```

### Task 2: Add group CLI discovery and reporting tests

**Files:**
- Modify: `tests/test_scripts_settlement.py`
- Modify: `scripts/monthly_settlement.py`

**Step 1: Write the failing tests**

Add tests that create `my_isa`, `my_pension`, `spouse_isa`, and an ignored
`backtest` directory under `tmp_path`. Call the new group CLI entry with the
same date range. Assert that output contains, in order:

```text
=== my 계좌 기간 결산 ===
=== 기간 결산 (my_isa) ===
=== 기간 결산 (my_pension) ===
=== 기간 결산 (my 통합) ===
=== spouse 계좌 기간 결산 ===
=== 기간 결산 (spouse_isa) ===
=== 기간 결산 (spouse 통합) ===
```

Add a separate test asserting that an absent prefix emits an explicit
`대상 계좌가 없습니다` message and returns success.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_scripts_settlement.py -q`

Expected: FAIL because group-mode parsing and report functions do not exist.

**Step 3: Write minimal implementation**

Update imports to use `aggregate_summary_records`. Add helpers with these
contracts:

```python
def discover_group_accounts(data_root: str, prefix: str) -> list[str]:
    return sorted(
        entry.name for entry in os.scandir(data_root)
        if entry.is_dir()
        and entry.name.startswith(prefix)
        and os.path.isfile(os.path.join(entry.path, "summary.json"))
    )

def build_group_report(data_root: str, group: str, start: str, end: str) -> str:
    prefix = f"{group}_"
    accounts = discover_group_accounts(data_root, prefix)
    # Build a group header, unchanged per-account build_report output, then
    # build_report(compute_settlement(aggregate_summary_records(...), start, end),
    #              f"{group} 통합").

def build_all_groups_report(data_root: str, start: str, end: str) -> str:
    return "\n\n".join(build_group_report(data_root, group, start, end)
                       for group in ("my", "spouse"))
```

Add `--all-groups` as a mutually exclusive alternative to `--account`; preserve
the current `--account` path exactly. In `main`, dispatch to group mode when
`args.all_groups` is true. Both modes retain `--start`, `--end`, and
`--data-root` validation.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_scripts_settlement.py tests/test_core_settlement.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/monthly_settlement.py tests/test_scripts_settlement.py
git commit -m "feat: report monthly settlements for account groups"
```

### Task 3: Switch the GitHub Actions workflow to group mode

**Files:**
- Modify: `.github/workflows/monthly-settlement.yml`
- Test: `tests/test_scripts_settlement.py`

**Step 1: Write the failing workflow contract test**

Add a lightweight YAML-as-text test asserting that the workflow no longer has
an `inputs.account` block and invokes `--all-groups`. This prevents a future
workflow edit from silently returning to a manually selected account.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_scripts_settlement.py -q`

Expected: FAIL because the workflow still declares `account` and supplies
`--account`.

**Step 3: Write minimal implementation**

Delete the `account` workflow-dispatch input and remove the `ACCOUNT`
environment variable. Replace the command fragment with:

```yaml
python -m scripts.monthly_settlement \
  --all-groups \
  --start "$START" \
  --end "$END" | tee settlement_report.txt
```

Do not change the job summary publication step.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_scripts_settlement.py tests/test_core_settlement.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add .github/workflows/monthly-settlement.yml tests/test_scripts_settlement.py
git commit -m "ci: run monthly settlement for both account groups"
```

### Task 4: Verify the feature

**Files:**
- Verify: `src/core/settlement.py`
- Verify: `scripts/monthly_settlement.py`
- Verify: `.github/workflows/monthly-settlement.yml`

**Step 1: Run feature-focused tests**

Run: `pytest tests/test_core_settlement.py tests/test_scripts_settlement.py -v`

Expected: PASS with no failures.

**Step 2: Run the project test suite**

Run: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/`

Expected: Existing test failures, if any, are explicitly identified as
pre-existing or investigated before completion.

**Step 3: Inspect final diff**

Run: `git diff main...HEAD --check` and `git status --short`

Expected: No whitespace errors; only the intended implementation, test,
workflow, and design/plan files differ from `main`.
