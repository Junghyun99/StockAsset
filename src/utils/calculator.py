# src/utils/calculator.py
import pandas as pd
import numpy as np
from src.core.models import MarketData

MOMENTUM_EMA_SPAN = 5  # 모멘텀 EMA 평활화 기간 (작을수록 빠른 반응, 클수록 안정적)


class IndicatorCalculator:
    def calculate(self, df: pd.DataFrame, vix_now: float) -> MarketData:
        """
        OHLCV 데이터프레임(1년치 이상)을 받아 오늘의 MarketData 스냅샷 생성
        df columns: ['Open', 'High', 'Low', 'Close', 'Volume'] (MultiIndex일 경우 처리 필요)
        """
        # [수정] 결측치 전처리 (ffill -> bfill)
        # 중간에 빈 데이터가 있으면 직전 값으로 채워서 계산 연속성 보장
        df = df.copy().ffill().bfill()
        # 물리적으로 253개가 안 되면 12개월 모멘텀 계산 불가
        min_required = 253
        
        if len(df) < min_required:
            # 로그에 현재 개수와 함께 에러를 명시
            raise ValueError(f"Data insufficient: Need at least {min_required} rows (trading days), but got {len(df)}.")

        # 1. 전처리 (종가 시리즈 추출)
        # IDataProvider 계약: 단일 종목 → SingleIndex ['Open','High','Low','Close','Volume']
        # MultiIndex 분기는 계약 미준수 구현체에 대한 방어 코드
        if isinstance(df.columns, pd.MultiIndex):
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
        
        # 5. 모멘텀 스코어 ((1M + 3M + 6M + 12M) / 4) + EMA 평활화
        # 영업일 기준: 1M=21, 3M=63, 6M=126, 12M=252
        # EMA 적용으로 일일 노이즈로 인한 휩쏘(whipsaw) 방지
        m1 = close.pct_change(periods=21)
        m3 = close.pct_change(periods=63)
        m6 = close.pct_change(periods=126)
        m12 = close.pct_change(periods=252)
        raw_momentum = (m1 + m3 + m6 + m12) / 4.0
        momentum = raw_momentum.ewm(span=MOMENTUM_EMA_SPAN, adjust=False).mean().iloc[-1]
        
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