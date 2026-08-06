# SSO/SPYI Channel Dip Stage-1 Expansion Design

## Goal

Raise the permanent core allocation to SSO 10% and SPYI 30%, while allowing a broader but bounded first dip-buy entry.

## Buy Rules

- Core setup buys 10% SSO and 30% SPYI from the initial portfolio value.
- Signal levels 2 and 3 remain unchanged: both weekly RSI and MA200 deviation must meet their current thresholds.
- Level 1 is confirmed when either its existing weekly RSI threshold or its existing MA200-deviation threshold is met. The existing two-trading-day confirmation remains required.
- The existing phase budgets and five-trading-day cadence are unchanged for every confirmed signal level.

## Risk Boundaries

- Channel and slope exits, recovery lots, SSO hard cap, and sell-first ordering are unchanged.
- The broader level-1 condition does not alter deeper-buy thresholds or create a recovery buy after a slope exit.

## Validation

- Unit tests cover core quantities, level-1 OR behavior, unchanged level-2/3 AND behavior, and the phase-1-only stop for a level-1 campaign.
- Focused planner and engine tests must pass before the compare-backtest regression test is run.
