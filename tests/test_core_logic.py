# tests/test_core_logic.py
import pytest
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.core.models import MarketRegime, Order

# ==========================================
# 1. RegimeAnalyzer 테스트 (국면 판단의 정교함)
# ==========================================

def test_regime_crash_conditions(create_market_data):
    analyzer = RegimeAnalyzer()
    
    # Case 1: VIX > 30 -> CRASH
    data_vix = create_market_data(vix=30.1)
    assert analyzer.analyze(data_vix) == MarketRegime.CRASH
    
    # Case 2: MDD < -20% -> CRASH
    data_mdd = create_market_data(mdd=-0.21)
    assert analyzer.analyze(data_mdd) == MarketRegime.CRASH
    
    # Case 3: 둘 다 정상이면 CRASH 아님
    data_normal = create_market_data(vix=29.9, mdd=-0.19)
    assert analyzer.analyze(data_normal) != MarketRegime.CRASH

def test_regime_bear_classifications(create_market_data):
    analyzer = RegimeAnalyzer()
    
    # Case 1: Bear Strong (가격 < MA 그리고 모멘텀 < 0)
    data_strong = create_market_data(price=90, ma=100, mom=-0.01)
    assert analyzer.analyze(data_strong) == MarketRegime.BEAR_STRONG
    
    # Case 2: Bear Weak (가격 < MA 이지만 모멘텀 > 0)
    data_weak_1 = create_market_data(price=90, ma=100, mom=0.01)
    assert analyzer.analyze(data_weak_1) == MarketRegime.BEAR_WEAK
    
    # Case 3: Bear Weak (가격 > MA 이지만 모멘텀 < 0)
    data_weak_2 = create_market_data(price=110, ma=100, mom=-0.01)
    assert analyzer.analyze(data_weak_2) == MarketRegime.BEAR_WEAK

def test_regime_bull_vs_sideways(create_market_data):
    analyzer = RegimeAnalyzer()
    
    # Case 1: Sideways (0 < 모멘텀 < 0.05)
    data_side = create_market_data(price=110, ma=100, mom=0.04)
    assert analyzer.analyze(data_side) == MarketRegime.SIDEWAYS
    
    # Case 2: Bull (모멘텀 >= 0.05)
    data_bull = create_market_data(price=110, ma=100, mom=0.05)
    assert analyzer.analyze(data_bull) == MarketRegime.BULL


# ==========================================
# 2. VolatilityTargeter 테스트 (비중 계산의 한계점)
# ==========================================

def test_vol_targeter_caps_and_floors():
    targeter = VolatilityTargeter(target_vol=0.15)
    
    # Case 1: Crash -> Exposure 0
    assert targeter.calculate_exposure(MarketRegime.CRASH, 0.1) == 0.0
    
    # Case 2: Bear Strong Cap (Max 0.4)
    # 계산값: 0.15 / 0.10 = 1.5배 -> 0.4로 제한
    assert targeter.calculate_exposure(MarketRegime.BEAR_STRONG, 0.10) == 0.4
    
    # Case 3: Bear Weak Cap (Max 0.6)
    # 계산값: 0.15 / 0.10 = 1.5배 -> 0.6으로 제한
    assert targeter.calculate_exposure(MarketRegime.BEAR_WEAK, 0.10) == 0.6
    
    # Case 4: Min Floor (Min 0.2)
    # 계산값: 0.15 / 1.0 (변동성 100%) = 0.15배 -> 0.2로 보정
    assert targeter.calculate_exposure(MarketRegime.BULL, 1.0) == 0.2

def test_vol_targeter_zero_division():
    targeter = VolatilityTargeter()
    # 변동성이 0이어도 에러 없이 1.0(Cap)이나 적절한 값이 나와야 함
    # 로직 내부에서 0.001로 보정하므로: 0.15 / 0.001 = 150 -> Cap 1.0
    assert targeter.calculate_exposure(MarketRegime.BULL, 0.0) == 1.0


# ==========================================
# 3. Rebalancer 테스트 (리밸런싱 조건과 주문)
# ==========================================

def test_rebalancer_threshold_logic(create_portfolio):
    # A그룹: SPY, B그룹: IEF
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: 총자산 100만, SPY 55만(55%), IEF 45만(45%) -> 차이 10%
    pf = create_portfolio(
        holdings={'SPY': 550, 'IEF': 450}, 
        prices={'SPY': 1000, 'IEF': 1000}
    )
    # 총액 1,000,000. Ratio A=0.55, Ratio B=0.45. Diff = 0.10
    
    # Case 1: 횡보장 (Threshold 0.05) -> 10% 차이이므로 리밸런싱 해야 함
    signal_side = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)
    assert signal_side.rebalance_needed is True
    assert "Threshold" in signal_side.reason and "초과" in signal_side.reason
    
    # Case 2: 하락장 (Threshold 0.10) -> 10% 차이는 초과가 아님(GT). 유지.
    # 로직: diff > threshold. 0.10 > 0.10 is False.
    signal_bear = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BEAR_WEAK)
    assert signal_bear.rebalance_needed is False
    assert len(signal_bear.orders) == 0

def test_rebalancer_crash_emergency_stop(create_portfolio):
    """
    [CRASH 시나리오 수정]
    폭락장(MDD/VIX 위험) 감지 시 -> '전량 매도'가 아니라 '매매 중단(Stop)'이어야 함.
    사용자가 직접 개입하기 전까지 봇은 아무것도 하지 않는다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: 주식을 들고 있는 상태
    pf = create_portfolio(holdings={'SPY': 10, 'IEF': 10}, prices={'SPY': 100, 'IEF': 100})
    
    # CRASH 발생 -> Target Exposure가 0.0으로 계산되어 넘어오더라도
    # Rebalancer는 이를 무시하고 주문을 생성하지 않아야 한다.
    signal = rebalancer.generate_signal(pf, target_exposure=0.0, regime=MarketRegime.CRASH)
    
    # 기대 결과: 리밸런싱 False, 주문 0건
    assert signal.rebalance_needed is False
    assert len(signal.orders) == 0
    assert "Emergency Stop" in signal.reason

def test_rebalancer_exposure_reduction(create_portfolio):
    """투자비중을 1.0 -> 0.5로 줄일 때 현금 확보 확인"""
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 현재: SPY 500만원, IEF 500만원 (총 1000만원, 풀매수 상태)
    pf = create_portfolio(holdings={'SPY': 50, 'IEF': 50}, prices={'SPY': 100000, 'IEF': 100000})
    
    # 목표: 비중 0.5 (500만원만 투자하고, 500만원은 현금화)
    signal = rebalancer.generate_signal(pf, target_exposure=0.5, regime=MarketRegime.BULL)
    
    assert signal.rebalance_needed is True
    
    # 목표 금액: A 250만, B 250만. (현재 각 500만)
    # 따라서 각각 절반씩 매도해야 함 (각 25주 매도)
    spy_order = next(o for o in signal.orders if o.ticker == 'SPY')
    ief_order = next(o for o in signal.orders if o.ticker == 'IEF')
    
    assert spy_order.action == "SELL"
    assert spy_order.quantity == 25
    assert ief_order.action == "SELL"
    assert ief_order.quantity == 25


 # ==========================================
# 4. 현실 운영 시나리오 (Operational Edge Cases)
# ==========================================

def test_rebalancer_idempotency(create_portfolio):
    """
    [멱등성 테스트]
    이미 목표 비중을 완벽하게 맞춘 상태에서 봇이 다시 실행되면?
    -> 주문이 0개여야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: 총자산 200만, 목표비중 1.0 (풀매수)
    # 현재: SPY 100만(50%), IEF 100만(50%) -> 이미 완벽함
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10}, 
        prices={'SPY': 100000, 'IEF': 100000}
    )
    
    # 횡보장 가정 (비중 1.0 유지)
    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)
    
    # 리밸런싱 불필요 판단
    assert signal.rebalance_needed is False
    # 주문이 하나도 없어야 함
    assert len(signal.orders) == 0

def test_rebalancer_cash_injection(create_portfolio):
    """
    [추가 입금 테스트]
    A:B 비율은 완벽하지만(리밸런싱 불필요), 현금이 많이 들어온 경우?
    -> 비율을 유지한 채로 '매수' 주문이 나가야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: 원래 SPY 100만, IEF 100만 있었음 (1:1).
    # 그런데 현금 200만을 추가 입금함. (총자산 400만)
    pf = create_portfolio(
        cash=2000000, 
        holdings={'SPY': 10, 'IEF': 10}, 
        prices={'SPY': 100000, 'IEF': 100000}
    )
    
    # 목표: 투자비중 1.0 (400만원 모두 투자 원함)
    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)
    
    # 비율(50:50) 자체는 틀어지지 않았으므로 rebalance_needed는 False일 수 있음.
    # 하지만 'Exposure'를 맞추기 위해 주문은 생성되어야 함.
    
    # 로직 검증: 
    # Logic에서 rebalance_needed가 False여도 target_exposure 계산은 수행함.
    # Target A = 400만 * 1.0 * 0.5 = 200만
    # Current A = 100만 -> 100만 매수 필요 (10주)
    
    spy_order = next((o for o in signal.orders if o.ticker == 'SPY'), None)
    ief_order = next((o for o in signal.orders if o.ticker == 'IEF'), None)
    
    assert spy_order is not None
    assert spy_order.action == "BUY"
    assert spy_order.quantity == 10 # 100만원어치 추가 매수
    
    assert ief_order is not None
    assert ief_order.action == "BUY"
    assert ief_order.quantity == 10

def test_rebalancer_small_balance_rounding(create_portfolio):
    """
    [소액 잔고 테스트]
    사야 할 금액이 주당 가격보다 작을 때?
    -> 주문 수량이 0이 되어야 하고, 주문 목록에 포함되지 않거나 무시되어야 함.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)
    
    # 상황: SPY 가격이 비쌈 (50만원)
    # 목표 비중 계산 결과 10만원어치를 더 사야 함.
    pf = create_portfolio(
        holdings={'SPY': 10}, # 500만원
        prices={'SPY': 500000}
    )
    
    # 강제로 목표 금액을 현재가치 + 10만원으로 설정하는 시나리오 유도
    # (여기서는 로직상 미세 조정이 어려우므로, 로직의 _create_orders 함수만 단위 테스트)
    
    # 직접 내부 함수 테스트 (Unit Test의 장점)
    # 목표매수금액: 100,000원, 현재가: 500,000원 -> 0.2주 -> 0주
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=5100000)
    
    # 현재가치 500만 vs 목표 510만 -> 차이 10만 -> 10만/50만 = 0.2 -> int(0)
    # 주문이 생성되지 않아야 함
    assert len(orders) == 0   

def test_rebalancer_order_sequence(create_portfolio):
    """
    [주문 순서 테스트]
    현금이 없고 SHV만 있는 상태에서 리밸런싱 할 때,
    반드시 SELL 주문이 BUY 주문보다 앞에 와야 한다.
    """
    groups = {'A': ['SSO'], 'B': ['IEF'], 'C': ['SHV']}
    rebalancer = Rebalancer(groups)
    
    # 현금 0원, SHV(C) 1000만원 보유
    # 목표: A매수, B매수 (C를 팔아서 사야 함)
    pf = create_portfolio(
        cash=0.0,
        holdings={'SHV': 100}, # 1000만원
        prices={'SSO': 100, 'IEF': 100, 'SHV': 100}
    )
    
    # 횡보장, 100% 투자 -> A:33%, B:33%, C:33% 목표 가정 (예시)
    # 실제 로직: A, B 목표 채우고 나머지가 C
    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)
    
    # 1. 주문이 생성되었는지 확인
    assert len(signal.orders) > 0
    
    # 2. 첫 번째 주문이 반드시 'SELL' 이어야 함 (SHV 매도)
    assert signal.orders[0].action == "SELL"
    assert signal.orders[0].ticker == "SHV"
    
    # 3. 그 뒤에 'BUY' 주문이 와야 함
    assert signal.orders[-1].action == "BUY"