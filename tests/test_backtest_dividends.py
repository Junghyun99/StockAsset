"""Tests for the shared backtest dividend adapters."""

import pandas as pd

import src.backtest.runner as runner
from src.backtest.components import (
    BacktestDataLoader,
    BacktestBroker,
    BacktestDividendSettlement,
)


def test_runner_has_no_legacy_dividend_calculator():
    """Dividend amounts must be calculated only by the shared engine path."""
    assert not hasattr(runner, "_calculate_dividend_income")


def test_backtest_data_loader_returns_positive_rates_for_requested_date():
    date = pd.Timestamp("2024-03-15")
    loader = BacktestDataLoader(
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(
            {"SDY": [0.0, 0.5], "QLD": [0.25, 0.0]},
            index=[pd.Timestamp("2024-03-14"), date],
        ),
    )

    assert loader.get_dividend_rates(["SDY", "QLD", "MISSING"], "2024-03-15") == {
        "SDY": 0.5
    }


def test_backtest_dividend_settlement_credits_broker_cash():
    broker = BacktestBroker(initial_cash=10_000.0)

    BacktestDividendSettlement(broker).receive_dividend(250.0)

    assert broker.cash == 10_250.0
