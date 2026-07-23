# Group Monthly Settlement Design

## Goal

Extend the monthly settlement workflow so one execution always produces separate
monthly-settlement results for the `my_*` and `spouse_*` account groups.  Each
group includes every individual account report and one consolidated report.

## Scope

- Discover accounts automatically from `docs/data/<account>/summary.json`.
- Include only directories whose account IDs begin with `my_` or `spouse_`.
- Keep the existing single-account CLI contract available.
- Add a group mode that accepts the same date range and data-root arguments, but
  no account selector.
- Remove the manual account choice from the GitHub Actions workflow and publish
  the two group results in one job summary.

## Data Flow

1. The CLI scans the data root for account directories with a `summary.json`.
2. It assigns discovered account IDs to the `my_` or `spouse_` group, sorting
   IDs for deterministic output.
3. For each account, it uses the existing `load_summaries`, `compute_settlement`,
   and report formatter to emit the unchanged individual settlement format.
4. To calculate a group total, it constructs one daily aggregate record for each
   calendar date. `total_value` and `net_deposit` are summed across the accounts
   that have a record on that date.
5. The aggregate records go through the existing `compute_settlement` function.
   This preserves the established profit identity and TWR calculation while
   treating group-level cash flows as the sum of its accounts' cash flows.

## Output

The group-mode report has two top-level sections in fixed order: `my` then
`spouse`. Each section contains the individual account reports followed by a
consolidated report. The consolidated report uses the same line format as a
single-account report, labelled with the group name (for example, `my 통합`).

If a group has no matching accounts, its section explicitly says that there are
no settlement targets. The other group is still processed. A missing
`summary.json` for a discovered directory is not possible by definition; an
unreadable or malformed summary remains a CLI error, matching the current
single-account failure behaviour.

## Workflow Inputs

The GitHub Actions workflow retains only `start` and `end`. It invokes group
mode once, then writes the entire report to the job summary. There is no
account-type or account-ID input because both groups are always generated.

## Testing

- Add CLI tests for automatic discovery, deterministic ordering, separate
  `my`/`spouse` sections, and empty groups.
- Add a group aggregation test asserting summed assets, net deposits, profit,
  and TWR through the existing settlement calculation.
- Update workflow assertions or review the YAML to ensure it no longer exposes
  an account selector and invokes group mode.
