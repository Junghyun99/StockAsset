# SSO/SPYI Slope Exit Design

## Goal

Protect the account when the regression channel itself turns down, without
turning a temporary rebound into an automatic high-price repurchase.

## Confirmation

The planner evaluates the current 63-trading-day channel slope once per trading
date.  Same-day executions overwrite the provisional value and never add a
second confirmation day.

| Ticker | Slope exit threshold | Confirmation |
| --- | ---: | ---: |
| SSO | slope_pct < -6% | 2 consecutive trading dates |
| SPYI | slope_pct < -4% | 2 consecutive trading dates |

This is independent of the buffered lower-channel exit.  If both conditions
confirm on the same evaluation, the slope exit takes precedence because it
signals a broader trend deterioration.

## Exit lifecycle

1. A confirmed slope exit sells 50% of the current holding and enters
   `EXIT_LOCK`.
2. The remaining position follows the ticker-specific trailing lock: 8% for
   SSO and 5% for SPYI.  A further fall sells the remaining holding.
3. A confirmed dip-buy signal still suppresses a pending or active exit in the
   same cycle; normal campaign buying is then allowed.
4. A recovery to the channel support releases a slope `EXIT_LOCK`, but it does
   **not** create a recovery lot or an automatic buy order.  Any new purchase
   must come from the ordinary dip-buy signals.

## Repeat-sale guard

After a slope partial sale is actually filled, the ticker latches that slope
exit.  It cannot sell again for the same continuous negative-slope episode,
even after the lock is released by a rebound.  The latch releases only after
the slope is no longer below its threshold for two consecutive trading dates.
The next deterioration must then obtain a fresh two-day confirmation.

## Interaction with channel exits and cash

Buffered lower-channel exits keep their existing recovery-lot behavior.  Only
channel-originated partial sales reserve proceeds and buy the sold quantity back
on an unbuffered-support recovery.  Slope-originated sales reserve no cash, so
their proceeds are immediately available to normal campaigns, subject to the
existing cash and ticker-priority rules.
