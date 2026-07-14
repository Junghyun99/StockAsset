import math
from dataclasses import asdict

import pytest
from src.core.models import DecisionFactor, MarketData, Portfolio

# ==========================================
# 1. MarketData 테스트 (경계값 검증)
# ==========================================

def test_market_data_boundary_conditions():
    """
    [경계값 테스트]
    MDD가 정확히 -20%이거나, VIX가 정확히 30일 때는 위험으로 간주하는가?
    로직: mdd <= -0.20 OR vix >= 30 (경계값 포함, 보수적 판정)
    """
    # Case 1: MDD -20% (Risk) — 경계값 포함
    data_boundary_mdd = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.20, vix=20.0
    )
    assert data_boundary_mdd.is_risk_condition() is True

    # Case 2: MDD -19.9% (Safe) — 경계값 미달
    data_safe_mdd = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.199999, vix=20.0
    )
    assert data_safe_mdd.is_risk_condition() is False

    # Case 3: VIX 30.0 AND MDD -10% (Risk) — 복합 조건 경계값
    # 새 조건: VIX ≥ 30 AND MDD ≤ -10% → CRASH
    data_boundary_vix = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.10, vix=30.0
    )
    assert data_boundary_vix.is_risk_condition() is True

    # Case 4: VIX 29.9 AND MDD -10% (Safe) — VIX 경계값 미달
    data_safe_vix = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.10, vix=29.9
    )
    assert data_safe_vix.is_risk_condition() is False

    # Case 5: VIX 35.0, MDD -3% (Safe) — VIX 스파이크지만 실제 하락 미미
    # 이슈 #192: 강한 상승장에서 VIX 단독 스파이크 시 CRASH 제외
    data_vix_spike_only = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.03, vix=35.0
    )
    assert data_vix_spike_only.is_risk_condition() is False

    # Case 6: VIX 30.0, MDD -9.9% (Safe) — MDD가 -10% 미만이면 CRASH 제외
    data_vix_with_mild_drop = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.099, vix=30.0
    )
    assert data_vix_with_mild_drop.is_risk_condition() is False


# ==========================================
# 2. Portfolio 테스트 (예외 상황 검증)
# ==========================================

def test_portfolio_missing_price_safety():
    """
    [누락 데이터 테스트]
    보유 종목은 있는데, 현재가 정보(Prices)가 딕셔너리에 없다면?
    -> 에러가 나지 않고 가치를 0으로 계산해야 한다. (.get(t, 0) 동작 확인)
    """
    pf = Portfolio(
        total_cash=1000.0,
        holdings={'SPY': 10, 'UNKNOWN_STOCK': 5}, # 알 수 없는 주식 보유
        current_prices={'SPY': 100.0} # UNKNOWN_STOCK 가격 정보 없음
    )
    
    # 총 가치 = 현금(1000) + SPY(10*100) + UNKNOWN(5*0) = 2000
    assert pf.total_value == 2000.0
    
    # 그룹 가치 계산 시에도 에러가 안 나야 함
    val = pf.get_group_value(['UNKNOWN_STOCK'])
    assert val == 0.0

def test_portfolio_empty_state():
    """
    [빈 껍데기 테스트]
    보유 종목도 없고 현금도 없으면?
    """
    pf = Portfolio(
        total_cash=0.0,
        holdings={},
        current_prices={}
    )
    
    assert pf.total_value == 0.0
    assert pf.get_group_value(['SPY']) == 0.0

def test_portfolio_query_non_existent_ticker():
    """
    [존재하지 않는 종목 조회]
    내 포트폴리오에 없는 종목의 그룹 가치를 물어보면?
    """
    pf = Portfolio(
        total_cash=1000.0,
        holdings={'SPY': 10},
        current_prices={'SPY': 100.0, 'GLD': 50.0}
    )
    
    # GLD는 가격 정보는 있지만, 내 holdings에는 없음 -> 가치는 0이어야 함
    assert pf.get_group_value(['GLD']) == 0.0


# ==========================================
# 3. MarketData NaN 감지 테스트
# ==========================================

def test_nan_fields_normal_data():
    """정상 데이터 → NaN 필드 없음"""
    data = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90,
        spy_volatility=0.15, spy_momentum=0.05, spy_mdd=-0.05, vix=20.0
    )
    assert data.nan_fields() == []

def test_nan_fields_single_nan():
    """변동성만 NaN → 해당 필드만 반환"""
    data = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90,
        spy_volatility=float('nan'), spy_momentum=0.05, spy_mdd=-0.05, vix=20.0
    )
    assert data.nan_fields() == ['spy_volatility']

def test_nan_fields_multiple_nan():
    """여러 필드 NaN → 모든 NaN 필드 반환"""
    data = MarketData(
        date="2024-01-01", spy_price=float('nan'), spy_ma180=90,
        spy_volatility=float('nan'), spy_momentum=0.05, spy_mdd=-0.05, vix=float('nan')
    )
    result = data.nan_fields()
    assert 'spy_price' in result
    assert 'spy_volatility' in result
    assert 'vix' in result
    assert len(result) == 3


# ==========================================
# 4. DecisionFactor 테스트
# ==========================================

def test_decision_factor_defaults():
    """format 기본값 number, threshold 기본값 None"""
    f = DecisionFactor(key="vix", label="VIX", value=17.2)
    assert f.format == "number"
    assert f.threshold is None

def test_decision_factor_serialization():
    """asdict로 JSON 저장 가능한 dict가 나와야 한다"""
    f = DecisionFactor(key="mdd", label="SPY MDD", value=-0.07,
                       format="percent", threshold=-0.20)
    assert asdict(f) == {"key": "mdd", "label": "SPY MDD", "value": -0.07,
                         "format": "percent", "threshold": -0.20}

def test_decision_factor_text_value():
    """국면 같은 텍스트 값도 담을 수 있어야 한다"""
    f = DecisionFactor(key="regime", label="시장 국면", value="Bull", format="text")
    assert f.value == "Bull"