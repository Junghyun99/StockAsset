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