# Account Engine Display Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show each account's configured engine before and after account selection.

**Architecture:** Load `engine_name` into an account metadata map, then use the map in portfolio cards and the selected-account banner.

**Tech Stack:** Browser ES modules, Bootstrap 5, Node.js built-in test runner.

---

### Task 1: Add engine metadata and UI labels

**Files:** `docs/js/utils.js`, `docs/js/portfolio-cards.js`, `docs/js/main.js`, `docs/js/ui.js`, related ESM references, `tests/dashboard/account-engine-display.test.mjs`.

1. Write failing metadata and card-render tests.
2. Implement the runtime map and labels.
3. Run Node tests, syntax checks, and diff validation.
