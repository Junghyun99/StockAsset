# Dip-Buy Funding Margin Design

## Goal

Ensure a planned leveraged-ETF purchase remains affordable after the broker's
2% cash safety margin and estimated fees are applied.

## Decision

The dip-buy planner will use a configurable funding safety margin matching the
broker's current 98% buy budget.  When a leveraged-ETF purchase needs funding,
the planner will sell enough income ETF shares to make the post-sale cash
balance cover the purchase price divided by that margin, plus an estimated
sell fee.

This keeps the funding decision in core strategy logic without making core
depend on the KIS broker.  The margin and fee estimate are named planner
constants so their relationship to broker policy is explicit and testable.

## Data flow

1. The planner determines the integer leveraged-ETF buy quantity from the
   portfolio's current price.
2. It calculates the minimum cash balance that satisfies the 98% buy budget,
   including estimated income-ETF sell fees.
3. It rounds the resulting income-ETF sale up to a whole share and caps it at
   the held quantity.
4. The existing broker still refreshes cash and enforces its own 98% guard
   immediately before submitting the buy.

## Error handling and limits

If the income-ETF holding cannot cover the calculated shortfall, the planner
keeps the existing capped sale behavior.  The broker remains the final guard
and can skip or reduce an unaffordable buy; no execution state advances unless
the leveraged order fills.

## Testing

Add a regression test based on the 2026-08-12 incident: 9,560 cash, a 42,140
leveraged-ETF purchase, and an income ETF priced at 10,890 must plan four
income-ETF shares for sale, not three.  Keep the existing test suite covering
the cap-at-holdings path.
