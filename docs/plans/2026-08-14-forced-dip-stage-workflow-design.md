# Forced Dip Stage Workflow Design

## Goal

Allow an operator to run the existing one-time forced DipBuy Stage command from the GitHub Actions UI without exposing an account selector or bypassing market safety checks.

## Design

Add a manual-only workflow, `run-forced-dip-stage.yml`. It fixes the target account to `my_test`, accepts only a Stage choice (`1`, `2`, or `3`) and a required reason, and invokes `python -m scripts.run_forced_dip_stage`.

The workflow performs the same Korean holiday check as domestic live trading and has no bypass input. It shares the `live-trading-domestic` concurrency group, preventing it from running beside the normal domestic cycle. It restores, decrypts, encrypts, and saves the encrypted KIS token cache with the existing key scheme so a reusable token can avoid unnecessary issuance.

Only the `MY_TEST_KIS_*` credentials and common Slack/token-cache secrets are injected. After a non-holiday run, it commits only dashboard data and CI logs; failures notify Slack.

## Safety Boundaries

- The GitHub UI cannot select another account.
- The script still validates that `my_test` is a domestic QLD engine before placing an order.
- Holidays stop before credentials are used for trading.
- The existing data, price, active-account, order, execution, and persisted-state gates remain in the Python runtime.

## Testing

Add a static workflow test that parses the YAML and asserts the manual inputs, fixed account command, holiday gate, shared concurrency group, token-cache encryption steps, and restricted commit pattern.
