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


def test_calculator_declining_market():
    """
    [로직] 주가가 지속적으로 하락할 때 지표들이 의도대로 반응하는지 확인
    상황: 200원에서 시작해서 100원으로 매일 일정하게 하락
    """
    calc = IndicatorCalculator()
    
    # 1. 400일간 선형 하락 데이터 생성 (200 -> ~100)
    dates = pd.date_range(end='2024-01-01', periods=400)
    prices = np.linspace(200, 100, 400)
    df = pd.DataFrame({'Close': prices}, index=dates)
    
    data = calc.calculate(df, 20.0)
    
    # 2. 검증
    # 현재가(100)가 MA180(최근 180일 평균, 약 122.5)보다 낮아야 함
    assert data.spy_price < data.spy_ma180
    
    # 모멘텀은 확실히 음수여야 함
    assert data.spy_momentum < 0
    
    # MDD: 고점(200) 대비 현재(100) -> -0.5
    assert data.spy_mdd == pytest.approx(-0.5, rel=1e-2)

def test_calculator_ma_window_logic():
    """
    [로직] MA180이 정확히 '최근 180일'만 반영하고, 그 이전 데이터는 무시하는지 검증
    상황: 옛날(181일 전)에는 주가가 1000원이었고, 최근 180일은 100원으로 횡보 중
    기대: MA180은 옛날 가격(1000원)의 영향을 받지 않고 100원이 되어야 함
    """
    calc = IndicatorCalculator()
    
    dates = pd.date_range(end='2024-01-01', periods=400)
    prices = [100.0] * 400
    
    # 181일 전까지는 1000원 (고가)
    # iloc[-1]이 오늘이므로, -180까지가 최근 180일. 그 이전 데이터 조작.
    prices[0:200] = [1000.0] * 200 # 앞쪽 200개는 비쌈
    prices[220:] = [100.0] * 180   # 뒤쪽(최근) 180개는 쌈
    
    df = pd.DataFrame({'Close': prices}, index=dates)
    
    data = calc.calculate(df, 15.0)
    
    # 최근 180일은 모두 100원이었으므로, 평균도 100원이어야 함.
    # 만약 윈도우가 잘못되어 옛날 데이터를 포함하면 100보다 훨씬 클 것임.
    assert data.spy_ma180 == 100.0

def test_calculator_integer_inputs():
    """
    [타입] 입력 데이터가 정수형(int)이어도 출력은 실수형(float)으로 변환되는지 확인
    (JSON 직렬화 및 추후 연산 안정성 위함)
    """
    calc = IndicatorCalculator()
    
    dates = pd.date_range(end='2024-01-01', periods=300)
    # 소수점 없는 정수 리스트
    prices = [100, 101, 102] * 100 
    df = pd.DataFrame({'Close': prices}, index=dates, dtype='int64')
    
    data = calc.calculate(df, 15) # VIX도 정수로 입력
    
    # 모든 필드가 float 타입인지 검사
    assert isinstance(data.spy_price, float)
    assert isinstance(data.spy_ma180, float)
    assert isinstance(data.spy_volatility, float)
    assert isinstance(data.spy_momentum, float)
    assert isinstance(data.spy_mdd, float)
    assert isinstance(data.vix, float)