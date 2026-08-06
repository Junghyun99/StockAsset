# Slope-Exit Support Filter Design

## Goal

Prevent delayed slope exits during price rebounds by requiring that the
negative channel-slope condition and price below channel support occur together
for two trading dates.

## Exit Rule

- SSO: trigger a slope exit only after two consecutive dates where the 63-day
  channel slope is below -6% and price is below channel support.
- SPYI: use the same rule with a -4% slope threshold.
- Either condition becoming false resets the confirmation count.
- A simultaneous buffered channel breach remains `SLOPE`-originated, preserving
  the current slope-first priority. A buffered breach without the slope
  condition remains a `CHANNEL` exit.

## Recovery Rule

- A filled slope exit continues to reserve half of its filled quantity.
- Recapturing support does not clear a slope exit lock before slope release.
- After two dates with slope at or above its exit threshold, the reserved 50%
  recovery order is placed before dip-buy campaign orders, even when a dip
  signal is confirmed.
- Remaining sold shares re-enter only through the unchanged dip-buy campaign.

## Boundaries

- Core allocations, dip thresholds and cadence, channel-exit thresholds,
  trailing full exits, and hard-cap logic are unchanged.
- `support` is the unbuffered lower channel line. Channel exits retain their
  existing SSO 3% and SPYI 2% breakdown buffers.

## Validation

- Test the joint two-day slope/support confirmation, reset behavior, slope
  precedence, and unchanged channel-only exit.
- Test that support recapture preserves a slope recovery reservation until the
  two-day slope release and that recovery wins over a simultaneous dip signal.
- Run planner, engine, and compare-backtest focused suites.
