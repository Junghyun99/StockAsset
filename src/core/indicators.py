"""공통 시장 지표 계산 도메인 서비스."""

import numpy as np
import pandas as pd

from src.core.models import MarketData

MOMENTUM_EMA_SPAN = 5


class IndicatorCalculator:
    """기준 OHLCV로 기존 ``MarketData`` 호환 지표를 계산한다."""

    def calculate(self, df: pd.DataFrame, vix_now: float) -> MarketData:
        df = df.copy().ffill().bfill()
        min_required = 253

        if len(df) < min_required:
            raise ValueError(
                f"Data insufficient: Need at least {min_required} rows "
                f"(trading days), but got {len(df)}."
            )

        if isinstance(df.columns, pd.MultiIndex):
            close = df.xs("Close", axis=1, level=0).iloc[:, 0]
        else:
            close = df["Close"]

        today_date = close.index[-1].strftime("%Y-%m-%d")
        current_price = close.iloc[-1]
        ma180 = close.rolling(window=180).mean().iloc[-1]
        daily_ret = close.pct_change()
        volatility = daily_ret.rolling(window=21).std().iloc[-1] * np.sqrt(252)

        m1 = close.pct_change(periods=21)
        m3 = close.pct_change(periods=63)
        m6 = close.pct_change(periods=126)
        m12 = close.pct_change(periods=252)
        raw_momentum = (m1 + m3 + m6 + m12) / 4.0
        momentum = raw_momentum.ewm(
            span=MOMENTUM_EMA_SPAN, adjust=False
        ).mean().iloc[-1]

        rolling_max = close.rolling(window=252, min_periods=1).max().iloc[-1]
        mdd = 0.0 if rolling_max == 0 else (current_price - rolling_max) / rolling_max

        return MarketData(
            date=today_date,
            spy_price=float(current_price),
            spy_ma180=float(ma180),
            spy_volatility=float(volatility),
            spy_momentum=float(momentum),
            spy_mdd=float(mdd),
            vix=float(vix_now),
        )
