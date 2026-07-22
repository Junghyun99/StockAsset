# Account Engine Display Design

Display the configured `engine_name` from `accounts_meta.json` on portfolio account cards and in the selected-account status banner. Missing metadata renders as `-`.

The existing account metadata loader owns the runtime engine-name map, so both views consume the same source of truth. Regression tests cover metadata loading and the portfolio-card label.
