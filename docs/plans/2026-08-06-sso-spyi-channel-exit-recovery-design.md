# SSO/SPYI Channel Exit Recovery Design

## Goal

Make channel exit protection available in every market regime without losing
material exposure after a false breakdown recovers.  A confirmed dip-buy signal
continues to take precedence over an exit.

## Buffered exit hysteresis

Each ticker uses its 63-trading-day log-regression support line.  An exit day is
counted only when the current price is below the buffered line, and at most once
per trading date:

`price < support * (1 - breakdown_margin)`

| Ticker | Channel band | Breakdown margin | Trailing drop |
| --- | ---: | ---: | ---: |
| SSO | 3 standard deviations | 3% | 8% |
| SPYI | 2 standard deviations | 2% | 5% |

Two consecutive trading dates confirm an exit.  This applies in rising,
sideways, and falling regimes; the former `uptrend_active` gate is not used for
exit eligibility.  A recovery is observed when `price >= support`, creating a
separate upper threshold from the buffered exit line.  The gap is the sole
anti-whipsaw hysteresis mechanism.

## Exit and recovery cycle

1. On confirmation, sell 50% of the holding and enter `EXIT_LOCK`.
2. Persist the filled quantity and its sale proceeds as a recovery lot.
3. While locked, a confirmed dip-buy signal changes the state to
   `EXIT_SUPPRESSED` and prevents new channel sells.  It does not create a
   special recovery order; ordinary campaign buying remains responsible for
   that situation.
4. With no confirmed buy signal, an 8% SSO or 5% SPYI fall from the partial-sale
   lock price sells the remaining holding.  A full exit clears the recovery lot.
5. When the price recovers to the unbuffered support line while locked, buy back
   the remaining recovery-lot quantity before ordinary campaign buys, then clear
   the recovery lot and lock.

## Cash reservation

Recovery sale proceeds are a temporary per-ticker reservation, not a permanent
portfolio cash buffer.  New campaign budgets and ordinary buy orders use:

`free_cash = total_cash - sum(recovery_reserved_cash)`

On a support recovery, the recovery order may use its own reservation plus free
cash, but never another ticker's reservation.  It attempts the original sold
quantity.  If the recovery price is higher and the permitted cash cannot fund
all shares, it buys the affordable quantity and keeps the remaining recovery lot
and reservation for a later retry; ordinary buys remain blocked for that ticker
until the lot is fully restored or a full exit occurs.

## Ordering and safety

The planner remains sell-first.  After potential exit sells, ready recovery
buys are planned before normal dip-buy campaign orders.  Existing SSO hard-cap
sales keep their highest priority.  The state is persisted through the existing
engine hooks, so live trading and backtests share the behavior.
