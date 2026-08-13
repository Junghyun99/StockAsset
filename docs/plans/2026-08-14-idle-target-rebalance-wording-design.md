# IDLE Target-Weight Rebalance Wording Design

## Goal

Make IDLE-state leveraged-ETF buys distinguishable from Stage 1–3 tranche buys
in logs, stored status data, and the dashboard.

## Decision

Keep the existing order calculation unchanged. When the planned state is
`IDLE`, label the leveraged-ETF order as `IDLE 목표비중 보정 매수`; retain the
existing `BUY_STAGE_N ... 분할매수` wording for the three signal stages.

## Testing

Add a planner test that produces an IDLE leveraged-ETF buy and asserts the
reason includes the new label and does not include `분할매수`.
