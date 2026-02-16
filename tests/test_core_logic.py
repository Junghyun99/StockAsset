# tests/test_core_logic.py
import pytest
from unittest.mock import MagicMock
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.core.models import MarketRegime, Order, OrderAction

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

    # Case 3: Sideways (모멘텀 == 0, 가격 > MA → 중립이므로 SIDEWAYS)
    data_zero_mom = create_market_data(price=110, ma=100, mom=0.0)
    assert analyzer.analyze(data_zero_mom) == MarketRegime.SIDEWAYS


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
    # 로직 내부에서 MIN_VOLATILITY_FLOOR로 보정하므로: 0.15 / 0.001 = 150 -> Cap 1.0
    assert targeter.calculate_exposure(MarketRegime.BULL, 0.0) == 1.0

def test_vol_targeter_min_volatility_floor_boundary():
    """MIN_VOLATILITY_FLOOR 경계값 테스트"""
    targeter = VolatilityTargeter(target_vol=0.15)
    floor = VolatilityTargeter.MIN_VOLATILITY_FLOOR

    # Case 1: 정확히 MIN_VOLATILITY_FLOOR → 보정 적용 (조건: > floor이 아님)
    # vol = 0.001이므로 base_ratio = 0.15 / 0.001 = 150 → Cap 1.0
    assert targeter.calculate_exposure(MarketRegime.BULL, floor) == 1.0

    # Case 2: MIN_VOLATILITY_FLOOR보다 약간 큰 값 → 보정 없이 원래 값 사용
    slightly_above = floor + 1e-6
    result = targeter.calculate_exposure(MarketRegime.BULL, slightly_above)
    expected = min(0.15 / slightly_above, 1.0)
    expected = max(expected, 0.2)
    assert abs(result - expected) < 1e-9

    # Case 3: 음수 변동성 → MIN_VOLATILITY_FLOOR로 보정
    assert targeter.calculate_exposure(MarketRegime.BULL, -0.05) == 1.0

    # Case 4: 상수 값이 0.001인지 확인
    assert VolatilityTargeter.MIN_VOLATILITY_FLOOR == 0.001


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
    assert signal_side.has_orders is True
    assert "비율 재조정" in signal_side.reason and "초과" in signal_side.reason
    
    # Case 2: 하락장 (Threshold 0.10) -> 10% 차이는 초과가 아님(GT). 유지.
    # 로직: diff > threshold. 0.10 > 0.10 is False.
    signal_bear = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BEAR_WEAK)
    assert signal_bear.has_orders is False
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
    assert signal.has_orders is False
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
    
    assert signal.has_orders is True
    
    # 목표 금액: A 250만, B 250만. (현재 각 500만)
    # 따라서 각각 절반씩 매도해야 함 (각 25주 매도)
    spy_order = next(o for o in signal.orders if o.ticker == 'SPY')
    ief_order = next(o for o in signal.orders if o.ticker == 'IEF')
    
    assert spy_order.action == OrderAction.SELL
    assert spy_order.quantity == 25
    assert ief_order.action == OrderAction.SELL
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
    assert signal.has_orders is False
    # 주문이 하나도 없어야 함
    assert len(signal.orders) == 0
    assert "추가 주문 없음" in signal.reason

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
    
    # 비율(50:50) 자체는 틀어지지 않았으므로 리밸런싱 불필요.
    # 하지만 'Exposure'를 맞추기 위해 주문은 생성되어야 함.
    assert "exposure 조정" in signal.reason

    # 로직 검증:
    # Target A = 400만 * 1.0 * 0.5 = 200만
    # Current A = 100만 -> 100만 매수 필요 (10주)
    
    spy_order = next((o for o in signal.orders if o.ticker == 'SPY'), None)
    ief_order = next((o for o in signal.orders if o.ticker == 'IEF'), None)
    
    assert spy_order is not None
    assert spy_order.action == OrderAction.BUY
    assert spy_order.quantity == 10 # 100만원어치 추가 매수
    
    assert ief_order is not None
    assert ief_order.action == OrderAction.BUY
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

def test_rebalancer_sell_rounding_ceil(create_portfolio):
    """
    [매도 절삭 편향 수정 테스트]
    매도 시 math.ceil을 사용하여 목표에 더 가깝게 매도하는지 확인.
    예: 34.8주를 팔아야 할 때 -> 35주 매도 (기존 int()는 34주)
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # SPY 50주 × $33 = $1,650 보유
    pf = create_portfolio(
        holdings={'SPY': 50},
        prices={'SPY': 33.0}
    )

    # 목표 금액 $500 -> 매도 필요: (1650-500)/33 = 34.84주
    # math.ceil(34.84) = 35주 매도
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=500.0)

    assert len(orders) == 1
    assert orders[0].action == OrderAction.SELL
    assert orders[0].quantity == 35  # int()였다면 34

def test_rebalancer_sell_quantity_capped_by_holdings(create_portfolio):
    """
    [매도 수량 상한 테스트]
    매도 수량이 보유 수량을 초과하면 안 된다.
    예: 3주 보유, 목표 금액이 현재가보다 약간 낮으면
    ceil 반올림으로 4주 매도가 계산될 수 있으나, 3주로 제한되어야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # SPY 3주 × $95 = $285 보유
    pf = create_portfolio(
        holdings={'SPY': 3},
        prices={'SPY': 95.0}
    )

    # 목표 금액 $50 -> 매도 필요: (285-50)/95 = 2.47주 -> ceil = 3주 (OK, 보유량과 같음)
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=50.0)
    assert len(orders) == 1
    assert orders[0].action == OrderAction.SELL
    assert orders[0].quantity <= 3

    # 목표 금액 $1 -> 매도 필요: (285-1)/95 = 2.989주 -> ceil = 3주 (보유량과 같으므로 OK)
    orders2 = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=1.0)
    assert orders2[0].quantity <= 3

    # 목표 금액 $0 -> 매도 필요: 285/95 = 3.0주 -> ceil = 3주 (정확히 보유량)
    orders3 = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=0.0)
    assert orders3[0].quantity == 3

    # 핵심: 목표 금액이 음수(이론상 불가하지만 부동소수점 오차 등)
    # -> 매도 필요: (285-(-10))/95 = 3.105주 -> ceil = 4주, 하지만 보유 3주이므로 3주로 제한
    orders4 = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=-10.0)
    assert orders4[0].quantity == 3  # 보유 수량 초과 방지


def test_rebalancer_buy_rounding_floor(create_portfolio):
    """
    [매수 절삭 테스트]
    매수 시 math.floor를 사용하여 자금 초과를 방지하는지 확인.
    예: 30.3주를 사야 할 때 -> 30주 매수 (자금 초과 방지)
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # 현재 SPY 0주, 가격 $33
    pf = create_portfolio(
        holdings={},
        prices={'SPY': 33.0}
    )

    # 목표 금액 $1,000 -> 매수 필요: 1000/33 = 30.30주
    # math.floor(30.30) = 30주 매수
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=1000.0)

    assert len(orders) == 1
    assert orders[0].action == OrderAction.BUY
    assert orders[0].quantity == 30  # 자금 초과 방지

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
    assert signal.orders[0].action == OrderAction.SELL
    assert signal.orders[0].ticker == "SHV"
    
    # 3. 그 뒤에 'BUY' 주문이 와야 함
    assert signal.orders[-1].action == OrderAction.BUY


def test_rebalancer_reason_rebalance_but_no_orders(create_portfolio):
    """
    [케이스 4: 비율 재조정 필요하지만 주문 단위 미달]
    첫 투자(val_risky=0 → needs_rebalance=True)인데,
    주당 가격이 비싸서 매수 수량이 전부 floor → 0주.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups)

    # 현금 50만, 보유 종목 없음 (첫 투자 → needs_rebalance=True)
    # 주당 가격 100만 → target 25만/종목 → floor(0.25) = 0주
    pf = create_portfolio(
        cash=500000,
        holdings={},
        prices={'SPY': 1000000, 'IEF': 1000000}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)

    assert signal.has_orders is False
    assert "단위 미달" in signal.reason


def test_rebalancer_c_group_target_not_negative(create_portfolio):
    """
    [C그룹 음수 방어 테스트]
    target_exposure가 1.0을 초과하는 값이 전달되더라도
    C그룹(SHV) 목표 금액이 음수가 되어서는 안 된다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF'], 'C': ['SHV']}
    rebalancer = Rebalancer(groups)

    pf = create_portfolio(
        cash=0.0,
        holdings={'SPY': 50, 'IEF': 50, 'SHV': 10},
        prices={'SPY': 100, 'IEF': 100, 'SHV': 100}
    )
    # total_value = 11,000
    # target_exposure=1.5 -> A+B 목표 = 11,000 * 1.5 = 16,500 (총자산 초과)
    # target_val_c가 음수가 되면 SHV에 음수 목표가 전달되어 비정상 매도 발생
    signal = rebalancer.generate_signal(pf, target_exposure=1.5, regime=MarketRegime.BULL)

    # C그룹 주문이 있다면, 최대 보유 수량까지만 매도해야 함
    shv_orders = [o for o in signal.orders if o.ticker == 'SHV']
    for o in shv_orders:
        if o.action == OrderAction.SELL:
            assert o.quantity <= 10  # 보유 수량 초과 매도 불가


# ==========================================
# 6. 가격 누락 경고 테스트
# ==========================================

def test_rebalancer_warns_on_missing_price(create_portfolio):
    """
    [가격 누락 경고 테스트]
    보유 종목의 가격 정보가 누락되면 Rebalancer가 ILogger를 통해 경고해야 한다.
    """
    mock_logger = MagicMock()
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, logger=mock_logger)

    # MISSING 종목을 보유하고 있지만 가격 정보가 없음
    pf = create_portfolio(
        cash=1000.0,
        holdings={'SPY': 10, 'MISSING': 5},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    # ILogger.warning이 MISSING 종목에 대해 호출되었는지 확인
    mock_logger.warning.assert_called()
    warning_messages = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert any("MISSING" in msg for msg in warning_messages)


def test_rebalancer_no_warning_when_all_prices_present(create_portfolio):
    """
    [가격 정상 시 경고 미발생 테스트]
    모든 보유 종목의 가격이 있으면 경고가 발생하지 않아야 한다.
    """
    mock_logger = MagicMock()
    groups = {'A': ['SPY'], 'B': ['IEF']}
    rebalancer = Rebalancer(groups, logger=mock_logger)

    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    # 가격 누락 관련 warning이 없어야 함
    warning_messages = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert not any("누락" in msg for msg in warning_messages)


# ==========================================
# 7. Rebalancer 커스텀 임계치 주입 테스트
# ==========================================

def test_rebalancer_custom_threshold_map(create_portfolio):
    """
    [커스텀 임계치 테스트]
    threshold_map을 외부에서 주입하면 해당 임계치가 적용되어야 한다.
    기본 BULL 임계치 0.15에서는 리밸런싱이 발생하지 않는 10% 차이가,
    커스텀 임계치 0.05로 변경하면 리밸런싱이 발생해야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}

    # 차이 10%인 포트폴리오
    pf = create_portfolio(
        holdings={'SPY': 550, 'IEF': 450},
        prices={'SPY': 1000, 'IEF': 1000}
    )

    # Case 1: 기본 임계치 (BULL=0.15) → 10% 차이이므로 리밸런싱 불필요
    rebalancer_default = Rebalancer(groups)
    signal_default = rebalancer_default.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal_default.has_orders is False

    # Case 2: 커스텀 임계치 (BULL=0.05) → 10% 차이이므로 리밸런싱 필요
    custom_thresholds = {
        MarketRegime.BULL: 0.05,
        MarketRegime.SIDEWAYS: 0.05,
        MarketRegime.BEAR_WEAK: 0.10,
        MarketRegime.BEAR_STRONG: 0.10,
    }
    rebalancer_custom = Rebalancer(groups, threshold_map=custom_thresholds)
    signal_custom = rebalancer_custom.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)
    assert signal_custom.has_orders is True
    assert "비율 재조정" in signal_custom.reason


def test_rebalancer_default_threshold_map_unchanged(create_portfolio):
    """
    [기본 임계치 유지 테스트]
    threshold_map을 지정하지 않으면 기존 기본값이 그대로 적용되어야 한다.
    """
    groups = {'A': ['SPY'], 'B': ['IEF']}

    # 기본 임계치가 클래스 상수와 동일한지 확인
    rebalancer = Rebalancer(groups)
    assert rebalancer._threshold_map == Rebalancer.DEFAULT_THRESHOLD_MAP

    # 인스턴스의 threshold_map 수정이 클래스 상수에 영향을 주지 않는지 확인
    rebalancer._threshold_map[MarketRegime.BULL] = 0.99
    assert Rebalancer.DEFAULT_THRESHOLD_MAP[MarketRegime.BULL] == 0.15