# SSO/SPYI Core Position Design

## Goal

Keep a small permanent market-participation position so the engine does not
remain entirely in cash when it starts during a sustained bull market.  Preserve
the existing dip-buy campaign as the tactical layer used to add exposure only
in discounted conditions.

## Core allocation

At first setup, calculate a fixed-share core from the current account value:

| Ticker | Core allocation |
| --- | ---: |
| SSO | 5% |
| SPYI | 15% |

The order quantity is the floor of the allocated dollar amount divided by the
current price.  The filled quantity becomes the persisted `core_quantity`.
It is never automatically rebalanced or topped up as prices change.

The engine will be attached to an account with no pre-existing SSO or SPYI
position, so migration rules for prior holdings are intentionally out of scope.

## Initial setup lifecycle

1. A fresh ticker has `core_quantity = 0` and `core_setup_complete = false`.
2. On the first normal cycle, plan only outstanding core setup buys.  Do not
   run a dip-buy campaign in that cycle.
3. Record actual fills.  A partial or rejected setup order leaves the remaining
   quantity pending and retries it on the next trading date.
4. After both ticker cores are fully established, normal independent dip-buy
   campaigns resume on later cycles.

Core setup orders remain below all sell orders and any ready channel-recovery
buy.  This preserves the existing sell-first and reservation safety rules.

## Tactical layer and exits

For each ticker:

`tactical_quantity = max(total_holding - core_quantity, 0)`

Only tactical quantity is eligible for:

- buffered channel partial exits and their trailing remainder;
- slope partial exits and their trailing remainder;
- the SSO 80% hard-cap reduction.

The cap still calculates the account's SSO ratio using total SSO value (core
plus tactical).  It calculates the quantity required to reach 78%, but sells no
more than tactical quantity.  If that cannot reach 78%, the planner records a
reason that the core floor prevented the target reduction; it never sells core.

Accordingly, a trailing “full exit” means full liquidation of the tactical
layer.  The permanent core remains and there is no bootstrap re-entry after a
tactical full exit.  Channel recovery lots restore only the tactical shares
that were sold; slope exits still have no automatic recovery buy.

## Validation

Tests must cover initial core orders, partial setup retries, no same-cycle
tactical campaign order, tactical-only exits, tactical-only hard-cap reduction,
and persistence through state serialization.  Re-run actual-price-history
replays to verify the startup and risk-layer ordering.
