# src/utils/calculator.py
import pandas as pd
import numpy as np
from src.core.models import MarketData

class IndicatorCalculator:
    def calculate(self, df: pd.DataFrame, vix_now: float) -> MarketData:
        """
        OHLCV 데이터프레임(1년치 이상)을 받아 오늘의 MarketData 스냅샷 생성
        df columns: ['Open', 'High', 'Low', 'Close', 'Volume'] (MultiIndex일 경우 처리 필요)
        """
        # [수정] 결측치 전처리 (ffill -> bfill)
        # 중간에 빈 데이터가 있으면 직전 값으로 채워서 계산 연속성 보장
        df = df.ffill().bfill()
        # 물리적으로 253개가 안 되면 12개월 모멘텀 계산 불가
        min_required = 253
        
        if len(df) < min_required:
            # 로그에 현재 개수와 함께 에러를 명시
            raise ValueError(f"Data insufficient: Need at least {min_required} rows (trading days), but got {len(df)}.")

        # 1. 전처리 (종가 시리즈 추출)
        # yfinance download 결과가 MultiIndex인 경우 대비
        if isinstance(df.columns, pd.MultiIndex):
            # SPY 컬럼만 추출 (단일 종목 가정)
            close = df.xs('Close', axis=1, level=0).iloc[:, 0]
        else:
            close = df['Close']
            
        # 2. 오늘 날짜 및 가격
        today_date = close.index[-1].strftime("%Y-%m-%d")
        current_price = close.iloc[-1]
        
        # 3. 이평선 (180일)
        ma180 = close.rolling(window=180).mean().iloc[-1]
        
        # 4. 변동성 (21일, 연율화)
        daily_ret = close.pct_change()
        # 21일 표준편차 * sqrt(252)
        volatility = daily_ret.rolling(window=21).std().iloc[-1] * np.sqrt(252)
        
        # 5. 모멘텀 스코어 ((1M + 3M + 6M + 12M) / 4)
        # 영업일 기준: 1M=21, 3M=63, 6M=126, 12M=252
        m1 = close.pct_change(periods=21).iloc[-1]
        m3 = close.pct_change(periods=63).iloc[-1]
        m6 = close.pct_change(periods=126).iloc[-1]
        m12 = close.pct_change(periods=252).iloc[-1]
        momentum = (m1 + m3 + m6 + m12) / 4.0
        
        # 6. MDD (최근 1년 고점 대비 현재가 하락률)
        rolling_max = close.rolling(window=252, min_periods=1).max().iloc[-1]
        if rolling_max == 0:
            mdd = 0.0
        else:
            mdd = (current_price - rolling_max) / rolling_max
        
        return MarketData(
            date=today_date,
            spy_price=float(current_price),
            spy_ma180=float(ma180),
            spy_volatility=float(volatility),
            spy_momentum=float(momentum),
            spy_mdd=float(mdd),
            vix=float(vix_now)
        )