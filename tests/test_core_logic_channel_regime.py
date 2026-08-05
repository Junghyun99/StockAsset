import math

import numpy as np
import pandas as pd
import pytest

from src.core.logic.channel_regime import classify_channel


def _frame(prices: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {"Close": prices}, index=pd.bdate_range("2024-01-01", periods=len(prices))
    )


def test_classify_channel_returns_log_regression_bands_and_slope():
    prices = 100.0 * np.exp(np.arange(63) * math.log(1.10) / 62)

    channel = classify_channel(_frame(prices), lookback=63, stddev_k=2.0)

    assert channel.slope_pct == pytest.approx(10.0, abs=0.01)
    assert channel.support < channel.mid < channel.resistance
    assert channel.price == pytest.approx(prices[-1])


def test_classify_channel_requires_positive_lookback_prices():
    frame = _frame(np.ones(63))
    frame.iloc[-1, 0] = 0.0

    channel = classify_channel(frame, lookback=63, stddev_k=2.0)

    assert not channel.is_valid
