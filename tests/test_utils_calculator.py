import pytest
import pandas as pd
import numpy as np
from src.utils.calculator import IndicatorCalculator

@pytest.fixture
def mock_ohlcv_data():
    """300일치 가상 데이터 생성"""
    dates = pd.date_range(end='2024-01-01', periods=300)
    # 가격이 서서히 오르는 추세
    prices = np.linspace(100, 200, 300) 
    df = pd.DataFrame({'Close': prices}, index=dates)
    return df

def test_calculator_basic_metrics(mock_ohlcv_data):
    """[기본] 지표 계산 로직 검증"""
    calc = IndicatorCalculator()
    vix_value = 15.0
    
    market_data = calc.calculate(mock_ohlcv_data, vix_value)
    
    # 1. 가격 확인
    assert market_data.spy_price == 200.0
    # 2. VIX 전달 확인
    assert market_data.vix == 15.0
    # 3. MDD 계산 확인 (계속 올랐으니 MDD는 0에 가까워야 함)
    assert market_data.spy_mdd == 0.0
    # 4. 모멘텀 확인 (가격이 올랐으니 양수)
    assert market_data.spy_momentum > 0

def test_calculator_insufficient_data():
    """[예외] 데이터가 252일 미만일 때"""
    calc = IndicatorCalculator()
    short_data = pd.DataFrame({'Close': [100]*100}) # 100일치
    
    with pytest.raises(ValueError, match="Data insufficient"):
        calc.calculate(short_data, 20.0)

def test_calculator_multiindex_handling():
    """[다양성] yfinance 최신 버전의 MultiIndex 컬럼 처리"""
    dates = pd.date_range(periods=300, end='2024-01-01')
    # MultiIndex 생성: (Price, Ticker) -> ('Close', 'SPY')
    columns = pd.MultiIndex.from_tuples([('Close', 'SPY')])
    df = pd.DataFrame(np.random.rand(300, 1), index=dates, columns=columns)
    
    calc = IndicatorCalculator()
    # 에러 없이 계산되어야 함
    market_data = calc.calculate(df, 20.0)
    assert isinstance(market_data.spy_price, float)


def test_calculator_resilience_to_nan_values():
    """
    [심화] 중간에 결측치(NaN)가 섞인 데이터가 들어왔을 때 처리
    상황: 거래 정지 등으로 며칠간 가격이 NaN인 경우
    """
    calc = IndicatorCalculator()
    
    # 1. 데이터 생성 (300일)
    dates = pd.date_range(end='2024-01-01', periods=300)
    prices = np.linspace(100, 200, 300)
    df = pd.DataFrame({'Close': prices}, index=dates)
    
    # 2. 고의로 중간에 NaN 주입 (최근 데이터 포함)
    df.iloc[-5] = np.nan # 5일 전 데이터 유실
    df.iloc[-10] = np.nan
    
    # 3. 계산 시도 (에러가 나면 안 됨)
    # Pandas의 rolling 함수는 기본적으로 NaN을 건너뛰거나 처리함
    try:
        market_data = calc.calculate(df, 20.0)
        
        # 4. 검증
        # 값이 계산되어 나왔는지 (NaN이 아니어야 함)
        assert not np.isnan(market_data.spy_price)
        assert not np.isnan(market_data.spy_ma180)
        
        # 만약 마지막 날(iloc[-1])이 NaN이면? -> 이건 fetcher에서 걸러지거나 에러가 날 수 있음.
        # IndicatorCalculator는 보통 ffill() 등을 안 하므로, 마지막 값이 NaN이면 결과도 NaN일 수 있음.
        # 이 테스트는 "중간 결측치"에 대한 내성을 확인.
    except Exception as e:
        pytest.fail(f"Calculator crashed on NaN data: {e}")



def test_calculator_flat_market():
    """
    [수학] 주가가 변동 없이 일정할 때(Flat), 지표들이 0으로 나오는지 확인
    """
    calc = IndicatorCalculator()
    
    # 1. 300일간 가격이 100원으로 고정된 데이터 생성
    dates = pd.date_range(end='2024-01-01', periods=300)
    df = pd.DataFrame({'Close': [100.0] * 300}, index=dates)
    
    # 2. 계산
    data = calc.calculate(df, 15.0)
    
    # 3. 검증
    assert data.spy_price == 100.0
    assert data.spy_ma180 == 100.0       # 평균도 100
    assert data.spy_volatility == 0.0    # 변동성 0
    assert data.spy_momentum == 0.0      # 수익률 0
    assert data.spy_mdd == 0.0           # 낙폭 0

def test_calculator_mdd_logic():
    """
    [수학] MDD(최대 낙폭) 계산이 정확한지 수치 검증
    상황: 1년 내 최고가 200원 -> 현재가 100원 (MDD -50%)
    """
    calc = IndicatorCalculator()
    
    dates = pd.date_range(end='2024-01-01', periods=300)
    # 기본 100원
    prices = [100.0] * 300
    # 200일 전쯤에 200원 찍음 (고점)
    prices[100] = 200.0 
    
    df = pd.DataFrame({'Close': prices}, index=dates)
    
    data = calc.calculate(df, 15.0)
    
    # 공식: (100 - 200) / 200 = -0.5
    assert data.spy_mdd == -0.5
    assert data.spy_price == 100.0

def test_calculator_missing_column():
    """
    [방어] DataFrame에 'Close' 컬럼이 아예 없을 때
    """
    calc = IndicatorCalculator()
    
    dates = pd.date_range(end='2024-01-01', periods=300)
    # 'Open'만 있고 'Close'가 없는 데이터
    df = pd.DataFrame({'Open': [100.0] * 300}, index=dates)
    
    # KeyError가 발생해야 함
    with pytest.raises(KeyError):
        calc.calculate(df, 20.0)

def test_calculator_date_format():
    """
    [형식] 인덱스의 타임스탬프가 'YYYY-MM-DD' 문자열로 잘 변환되는지
    """
    calc = IndicatorCalculator()
    
    # 시간 정보가 포함된 날짜 (2024-01-01 15:30:00)
    dates = pd.date_range(end='2024-01-01 15:30:00', periods=300)
    df = pd.DataFrame({'Close': [100.0] * 300}, index=dates)
    
    data = calc.calculate(df, 15.0)
    
    # 시간 정보는 잘리고 날짜만 나와야 함
    assert data.date == "2024-01-01"