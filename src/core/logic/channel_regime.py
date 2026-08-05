"""Log-linear regression channel calculation used by channel exit strategies."""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ChannelSnapshot:
    price: float = float("nan")
    mid: float = float("nan")
    support: float = float("nan")
    resistance: float = float("nan")
    slope_pct: float = float("nan")
    is_valid: bool = False


def classify_channel(
    frame: pd.DataFrame | None,
    lookback: int = 63,
    stddev_k: float = 2.0,
) -> ChannelSnapshot:
    """Calculate the latest log-regression channel from close prices."""
    if frame is None or frame.empty or lookback <= 1 or len(frame) < lookback:
        return ChannelSnapshot()

    close = _close_series(frame).tail(lookback)
    if len(close) != lookback or close.isna().any() or (close <= 0).any():
        return ChannelSnapshot()

    log_price = np.log(close.to_numpy(dtype=float))
    index = np.arange(lookback, dtype=float)
    slope, intercept = np.polyfit(index, log_price, 1)
    fitted = slope * index + intercept
    sigma = float(np.std(log_price - fitted))
    final_mid = math.exp(float(fitted[-1]))
    return ChannelSnapshot(
        price=float(close.iloc[-1]),
        mid=final_mid,
        support=math.exp(float(fitted[-1] - stddev_k * sigma)),
        resistance=math.exp(float(fitted[-1] + stddev_k * sigma)),
        slope_pct=(math.exp(float(slope * (lookback - 1))) - 1.0) * 100.0,
        is_valid=True,
    )


def _close_series(frame: pd.DataFrame) -> pd.Series:
    if isinstance(frame.columns, pd.MultiIndex):
        return frame.xs("Close", axis=1, level=0).iloc[:, 0]
    return frame["Close"]
