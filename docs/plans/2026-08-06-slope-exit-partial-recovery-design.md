# Slope-Exit Partial Recovery Design

## Goal

Restore a limited portion of a tactical position after a slope exit is proven
to have recovered, without changing the dip-buy campaign or using a channel
upper-breakout entry.

## Evidence and Decision

The six slope exits in compare-backtest run 34 all had a positive return over
the following 20 trading days once the slope had remained above its exit
threshold for two consecutive days. A two-day channel upper breakout was not
useful: it often occurred while the slope was still below the exit threshold,
and after slope recovery it was absent or materially late.

## Buy Rule

- A filled slope exit reserves a recovery lot equal to 50% of the filled sell
  quantity, using 50% of the filled sale proceeds as reserved cash.
- The existing slope-release condition remains the confirmation: the channel
  slope must be at or above the ticker's slope-exit threshold for two distinct
  trading dates.
- Once that confirmation clears `slope_exit_latched`, submit one recovery buy
  for the reserved quantity. The buy can use its reserved sale proceeds and,
  if the price rose, otherwise-free cash under the existing cash accounting.
- A rejected or partially filled recovery buy retries on the next trading date.
- The other 50% of the slope-exit sale stays out of the position. It can only
  return through the existing dip-buy campaign.

## Risk Boundaries

- The permanent SSO/SPYI core, slope-exit thresholds, channel-exit recovery,
  campaign cadence, and sell-first ordering are unchanged.
- A slope recovery is not conditional on the price touching the channel upper
  line or support line; its sole confirmation is the already-existing
  two-trading-day slope release.
- A pending full exit or an active buy signal retains the current precedence
  and can cancel the recovery lot through the existing exit-state paths.

## State and Data Flow

`record_fills` records the half-sized recovery lot only for a filled slope
sale. `_update_slope_exit` clears the latch after the existing two-day release.
While the exit lock remains active, `_recovery_orders` recognizes an unlocked
slope lot and places the buy. Existing recovery fill accounting consumes the
reserved quantity and cash, then clears the exit lock.

## Validation

- A filled slope exit creates exactly a half-sized reserved recovery lot.
- The recovery buy is absent before the second slope-release day and appears
  on that day without a channel-support requirement.
- Partial recovery fills leave only their remaining quantity pending for the
  next trading date.
- Existing channel recovery and slope-latch tests remain green.
