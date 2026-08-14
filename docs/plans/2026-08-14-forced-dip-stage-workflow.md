# Forced Dip Stage Workflow Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide a token-cache-enabled GitHub Actions UI workflow that runs one forced DipBuy stage for `my_test`.

**Architecture:** A dedicated manual workflow fixes the account argument to `my_test`, accepts a constrained Stage and reason, and calls the existing Python CLI. It mirrors the domestic live workflow's holiday, concurrency, encrypted KIS token-cache, data-commit, and failure-notification boundaries without changing production trading code.

**Tech Stack:** GitHub Actions YAML, Python pytest static workflow assertions, KIS credentials stored as GitHub secrets.

---

### Task 1: Specify the workflow contract with a failing static test

**Files:**
- Create: `tests/test_workflow_forced_dip_stage.py`
- Create: `.github/workflows/run-forced-dip-stage.yml`

**Step 1: Write the failing test**

Add assertions that read the new YAML as text and require:
- manual dispatch inputs `stage` and `reason`, with Stage choices 1, 2, 3;
- no account input and a fixed `--account my_test` CLI command;
- the shared `live-trading-domestic` concurrency group;
- a Korean holiday step without a skip/bypass input;
- encrypted token cache restore/decrypt/encrypt/save steps using `KIS_TOKEN_CACHE_KEY`;
- `MY_TEST_KIS_*` secrets and the restricted dashboard/log commit pattern.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_forced_dip_stage.py -q`

Expected: FAIL because `.github/workflows/run-forced-dip-stage.yml` does not exist.

### Task 2: Add the manual workflow

**Files:**
- Create: `.github/workflows/run-forced-dip-stage.yml`

**Step 1: Implement the minimum workflow**

Create a `workflow_dispatch` workflow named `Run Forced DipBuy Stage`. Define `stage` as a required `choice` input with `1`, `2`, and `3`; define `reason` as required text. Set `contents: write`, use `ubuntu-latest`, a 15-minute timeout, and the `live-trading-domestic` concurrency group.

Add checkout, Python 3.10 setup, dependency installation, and the no-bypass Korean holiday guard copied from `live-trading-domestic.yml`. Copy the restore/decrypt/encrypt/save encrypted token-cache stages and their `kis-token-domestic-` key namespace.

Run the existing CLI exactly as:

```bash
python -m scripts.run_forced_dip_stage \
  --account my_test \
  --stage "${{ inputs.stage }}" \
  --reason "${{ inputs.reason }}"
```

Inject only `MY_TEST_KIS_APP_KEY`, `MY_TEST_KIS_APP_SECRET`, `MY_TEST_KIS_ACC_NO`, Slack secrets, and `KIS_TOKEN_CACHE_KEY` where needed. Copy the restricted auto-commit and failure Slack notification patterns from the domestic live workflow.

**Step 2: Run test to verify it passes**

Run: `pytest tests/test_workflow_forced_dip_stage.py -q`

Expected: PASS.

### Task 3: Regression verification and commit

**Files:**
- Create: `.github/workflows/run-forced-dip-stage.yml`
- Create: `tests/test_workflow_forced_dip_stage.py`

**Step 1: Run related checks**

Run:

```bash
pytest tests/test_workflow_forced_dip_stage.py tests/test_scripts_run_forced_dip_stage.py -q
git diff --check
```

Expected: all tests pass and no whitespace errors.

**Step 2: Commit**

```bash
git add .github/workflows/run-forced-dip-stage.yml tests/test_workflow_forced_dip_stage.py docs/plans/2026-08-14-forced-dip-stage-workflow.md
git commit -m "feat: add forced dip stage workflow"
```
