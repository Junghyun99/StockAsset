# Platform-Specific Read-Only Test Design

## Goal

Allow the test suite to collect on Windows while retaining the real filesystem-permission test on supported Unix environments.

## Decision

`test_repo_read_only_file` will run only on non-root POSIX environments. Windows will be skipped because it lacks `os.getuid()` and its `chmod` behavior does not reliably make a file unwritable for the current user. Root will remain skipped because root can bypass the intended write restriction.

## Implementation

Replace the import-time `os.getuid()` predicate with a cross-platform condition that first excludes Windows, then safely checks the effective user ID only where it is available. Add a focused regression test that imports the test module under a simulated Windows environment and proves collection no longer raises `AttributeError`.

## Verification

Run the focused repository test file on Windows to confirm collection succeeds, then run the full suite if the remaining environment permits it.
