# src/core/logic/sso_dip_signals.py
"""SSO DipBuy 전략용 지표 계산기 (순수 로직).

SSO 일봉 OHLCV에서 주봉 RSI와 200일선 괴리율을 계산한다.
주봉 RSI: 일봉을 주봉으로 리샘플링 후 Wilder RSI(14) 계산.
200일선 괴리율: (현재가 - MA200) / MA200.

SSO(2x 레버리지)를 직접 사용하면 괴리율이 ~2배 증폭되어
깊은 하락을 더 민감하게 감지하고 STAGE_1 고착 문제를 해소한다.
"""
import math
from dataclasses import dataclass

import pandas as pd

RSI_PERIOD = 14
MA200_WINDOW = 200
MIN_REQUIRED_DAYS = 250
MDD_WINDOW = 252


@dataclass(frozen=True)
class SsoDipSignals:
    """오늘의 SSO DipBuy 지표 스냅샷."""
    date: str
    weekly_rsi: float
    ma200_deviation: float
    price: float
    ma200: float
    mdd_252: float = float("nan")


class SsoDipIndicatorCalculator:
    """SSO 일봉 OHLCV에서 주봉 RSI와 200일선 괴리율을 계산한다."""

    def calculate(self, df: pd.DataFrame) -> SsoDipSignals:
        if df is None or df.empty:
            return self._nan_signals()

        df = df.copy().ffill().bfill()

        if isinstance(df.columns, pd.MultiIndex):
            close = df.xs("Close", axis=1, level=0).iloc[:, 0]
        else:
            close = df["Close"]

        if len(close) < MIN_REQUIRED_DAYS:
            return SsoDipSignals(
                date=close.index[-1].strftime("%Y-%m-%d") if len(close) > 0 else "",
                weekly_rsi=float("nan"),
                ma200_deviation=float("nan"),
                price=float(close.iloc[-1]) if len(close) > 0 else float("nan"),
                ma200=float("nan"),
            )

        date = close.index[-1].strftime("%Y-%m-%d")
        price = float(close.iloc[-1])

        ma200 = float(close.rolling(window=MA200_WINDOW).mean().iloc[-1])
        if ma200 > 0 and not math.isnan(ma200):
            deviation = (price - ma200) / ma200
        else:
            deviation = float("nan")

        trailing_close = close.tail(MDD_WINDOW)
        if len(trailing_close) == MDD_WINDOW:
            trailing_peak = float(trailing_close.max())
            mdd_252 = (price - trailing_peak) / trailing_peak
        else:
            mdd_252 = float("nan")

        weekly_close = close.resample("W-FRI").last().dropna()
        weekly_rsi = self._rsi(weekly_close) if len(weekly_close) > RSI_PERIOD else float("nan")

        return SsoDipSignals(
            date=date,
            weekly_rsi=weekly_rsi,
            ma200_deviation=deviation,
            price=price,
            ma200=ma200,
            mdd_252=mdd_252,
        )

    @staticmethod
    def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> float:
        if len(close) <= period:
            return float("nan")
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    @staticmethod
    def _nan_signals() -> SsoDipSignals:
        return SsoDipSignals(
            date="", weekly_rsi=float("nan"), ma200_deviation=float("nan"),
            price=float("nan"), ma200=float("nan"), mdd_252=float("nan"),
        )
