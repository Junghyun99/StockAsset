import logging
import pytest
from src.core.models import MarketData, Portfolio

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

    # Case 3: VIX 30.0 (Risk) — 경계값 포함
    data_boundary_vix = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.10, vix=30.0
    )
    assert data_boundary_vix.is_risk_condition() is True

    # Case 4: VIX 29.9 (Safe) — 경계값 미달
    data_safe_vix = MarketData(
        date="2024-01-01", spy_price=100, spy_ma180=90, spy_volatility=0.1, spy_momentum=0.1,
        spy_mdd=-0.10, vix=29.9
    )
    assert data_safe_vix.is_risk_condition() is False


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
# 3. Portfolio 가격 누락 경고 테스트
# ==========================================

def test_portfolio_total_value_warns_on_missing_price(caplog):
    """
    [가격 누락 경고 테스트]
    보유 종목의 가격 정보가 누락되면 경고 로그가 출력되어야 한다.
    """
    pf = Portfolio(
        total_cash=1000.0,
        holdings={'SPY': 10, 'MISSING': 5},
        current_prices={'SPY': 100.0}
    )

    with caplog.at_level(logging.WARNING, logger="src.core.models"):
        value = pf.total_value

    assert value == 2000.0
    assert any("MISSING" in record.message for record in caplog.records)


def test_portfolio_get_group_value_warns_on_missing_price(caplog):
    """
    [그룹 가치 가격 누락 경고 테스트]
    보유 중인 종목의 가격이 누락되면 get_group_value에서도 경고가 출력되어야 한다.
    """
    pf = Portfolio(
        total_cash=1000.0,
        holdings={'GLD': 10},
        current_prices={'SPY': 100.0}  # GLD 가격 누락
    )

    with caplog.at_level(logging.WARNING, logger="src.core.models"):
        value = pf.get_group_value(['GLD'])

    assert value == 0.0
    assert any("GLD" in record.message for record in caplog.records)


def test_portfolio_get_group_value_no_warning_when_not_holding(caplog):
    """
    [비보유 종목 경고 미발생 테스트]
    보유하지 않은 종목의 가격이 누락되어도 경고가 발생하지 않아야 한다.
    """
    pf = Portfolio(
        total_cash=1000.0,
        holdings={},
        current_prices={}
    )

    with caplog.at_level(logging.WARNING, logger="src.core.models"):
        value = pf.get_group_value(['GLD'])

    assert value == 0.0
    assert len(caplog.records) == 0