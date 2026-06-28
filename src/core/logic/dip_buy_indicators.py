# src/core/logic/dip_buy_indicators.py
"""눌림목 분할매수 전략용 지표 계산기 (순수 로직).

단일 종목 OHLCV에서 MA20/60/120, RSI(14)를 계산해 DipBuySignals를 만든다.
공용 MarketData(SPY 중심 모델)와 분리하여 SRP를 지킨다.
"""
from dataclasses import dataclass

import pandas as pd

RSI_PERIOD = 14


@dataclass(frozen=True)
class DipBuySignals:
    """오늘의 눌림목 지표 스냅샷 (단일 종목 기준)."""
    date: str
    price: float      # 종가
    ma20: float
    ma60: float
    ma120: float
    rsi: float        # RSI(14)
    ma200: float = float("nan")   # 추세 게이트용(선택). 데이터 부족 시 NaN.


class DipBuyIndicatorCalculator:
    """OHLCV에서 MA20/60/120, RSI(14)를 계산한다 (순수 로직)."""

    def calculate(self, df: pd.DataFrame) -> DipBuySignals:
        # 데이터 수집 실패 등으로 빈 DataFrame이 들어오면 NaN 신호로 안전 degrade.
        # (엔진은 NaN 지표에서 매매를 스킵한다.)
        if df is None or df.empty:
            return DipBuySignals(
                date="", price=float("nan"),
                ma20=float("nan"), ma60=float("nan"),
                ma120=float("nan"), rsi=float("nan"),
            )
        df = df.copy().ffill().bfill()
        # IDataProvider 계약: 단일 종목 → SingleIndex. MultiIndex는 방어 코드.
        if isinstance(df.columns, pd.MultiIndex):
            close = df.xs("Close", axis=1, level=0).iloc[:, 0]
        else:
            close = df["Close"]

        date = close.index[-1].strftime("%Y-%m-%d")
        price = float(close.iloc[-1])

        def ma(window: int) -> float:
            if len(close) < window:
                return float("nan")
            return float(close.rolling(window=window).mean().iloc[-1])

        return DipBuySignals(
            date=date,
            price=price,
            ma20=ma(20),
            ma60=ma(60),
            ma120=ma(120),
            rsi=self._rsi(close),
            ma200=ma(200),
        )

    @staticmethod
    def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> float:
        """Wilder smoothing 기반 RSI(14). 데이터 부족 시 NaN, 무손실 구간 100."""
        if len(close) <= period:
            return float("nan")
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        # Wilder smoothing == EMA(alpha=1/period)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))
