import math

import pandas as pd
import pytest

from src.core.models import Portfolio, OrderAction
from src.core.logic.dip_buy_indicators import DipBuySignals, DipBuyIndicatorCalculator
from src.core.logic.dip_buy_planner import Tranche, DipBuyState, DipBuyPlanner


# ── 헬퍼 ──────────────────────────────────────────────────────────────
def _df(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes,
        "Close": closes, "Volume": [1] * len(closes),
    }, index=idx)


def _signals(price, ma20, ma60, ma120, rsi):
    return DipBuySignals("2024-01-01", price, ma20, ma60, ma120, rsi)


def _pf(cash, qld=0, price=100.0):
    return Portfolio(total_cash=cash, holdings={"QLD": qld}, current_prices={"QLD": price})


def _disarmed():
    return {t: False for t in ("ma20", "ma60", "ma120", "dip")}


# ── 지표 계산기 ────────────────────────────────────────────────────────
def test_moving_averages_computed():
    closes = list(range(1, 201))  # 1..200 선형 증가
    sig = DipBuyIndicatorCalculator().calculate(_df(closes))
    assert sig.price == 200.0
    assert sig.ma20 == pytest.approx(190.5)            # (181+200)/2
    assert sig.ma60 == pytest.approx((141 + 200) / 2)
    assert sig.ma120 == pytest.approx((81 + 200) / 2)
    assert sig.date == "2024-07-18"


def test_rsi_all_gains_is_100():
    sig = DipBuyIndicatorCalculator().calculate(_df(list(range(1, 201))))
    assert sig.rsi == pytest.approx(100.0)


def test_rsi_between_0_and_100_for_mixed():
    closes = [100 + (5 if i % 2 == 0 else -4) * (i % 7) for i in range(200)]
    sig = DipBuyIndicatorCalculator().calculate(_df(closes))
    assert 0.0 <= sig.rsi <= 100.0


def test_insufficient_data_yields_nan():
    sig = DipBuyIndicatorCalculator().calculate(_df(list(range(1, 50))))
    assert math.isnan(sig.ma120)


def test_empty_dataframe_yields_nan_signals():
    sig = DipBuyIndicatorCalculator().calculate(pd.DataFrame())
    assert sig.date == ""
    assert math.isnan(sig.price)
    assert math.isnan(sig.ma20) and math.isnan(sig.rsi)


# ── 상태 직렬화 ────────────────────────────────────────────────────────
def test_state_roundtrip_serialization():
    state = DipBuyState(
        queue=[Tranche(side="BUY", per_day_amount=100.0, remaining_days=4)],
        armed={"ma20": False, "ma60": True, "ma120": True, "dip": True, "sell": True},
    )
    restored = DipBuyState.from_dict(state.to_dict())
    assert restored == state


def test_state_from_empty_dict_defaults():
    state = DipBuyState.from_dict({})
    assert state.queue == []
    assert state.armed == {"ma20": True, "ma60": True, "ma120": True, "dip": True}
    assert state.rsi_was_overbought is False


# ── 트리거 평가 (적재 + 당일 소진 결합 동작) ──────────────────────────────
def test_ma20_touch_buys_10pct_immediately():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=101.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    orders, _, state = planner.plan(sig, _pf(cash=1000.0, price=100.0), DipBuyState())
    buys = [o for o in orders if o.action == OrderAction.BUY]
    assert buys and buys[0].quantity == 1       # floor((1000*0.10)/100)
    assert state.queue == []                     # 1일 분할 → 즉시 소진
    assert state.armed["ma20"] is False


def test_buy_sizing_uses_total_value_not_just_cash():
    planner = DipBuyPlanner(ticker="QLD")
    # 현금 500 + QLD 5주×100=500 → 총자산 1000. MA60 50% = 500/5 = 100/일.
    # (현금 기준이었다면 50% of 500 = 250/5 = 50/일)
    pf = Portfolio(total_cash=500.0, holdings={"QLD": 5}, current_prices={"QLD": 100.0})
    sig = _signals(price=100.0, ma20=130.0, ma60=100.0, ma120=70.0, rsi=50.0)
    _, _, state = planner.plan(sig, pf, DipBuyState())
    t = [x for x in state.queue if x.side == "BUY"][0]
    assert t.per_day_amount == pytest.approx(100.0)


def test_ma60_band_enqueues_50pct_over_5_days():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=100.0, ma20=130.0, ma60=100.0, ma120=70.0, rsi=50.0)
    _, _, state = planner.plan(sig, _pf(cash=1000.0, price=100.0), DipBuyState())
    # 당일 1일치 소진 후 남은 트랜치 (5→4일, per_day=100)
    remaining = [t for t in state.queue if t.side == "BUY"]
    assert len(remaining) == 1
    assert remaining[0].remaining_days == 4
    assert remaining[0].per_day_amount == pytest.approx(100.0)  # 1000*0.50/5


def test_dip_below_ma120_and_rsi_under_30_enqueues_100pct_40_days():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=60.0, ma20=130.0, ma60=110.0, ma120=70.0, rsi=25.0)
    _, _, state = planner.plan(sig, _pf(cash=4000.0, price=100.0), DipBuyState())
    dip = [t for t in state.queue if t.remaining_days == 39][0]
    assert dip.per_day_amount == pytest.approx(100.0)  # 4000*1.0/40


def test_trigger_does_not_refire_while_armed_false():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=101.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    _, _, state = planner.plan(sig, _pf(cash=1000.0, price=100.0), DipBuyState())
    orders2, _, state2 = planner.plan(sig, _pf(cash=900.0, price=100.0), state)
    assert orders2 == []                 # 같은 신호 재발동 없음
    assert state2.armed["ma20"] is False


def test_rearm_when_condition_clears():
    planner = DipBuyPlanner(ticker="QLD")
    sig_in = _signals(price=101.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    _, _, state = planner.plan(sig_in, _pf(cash=1000.0, price=100.0), DipBuyState())
    sig_out = _signals(price=110.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    _, _, state2 = planner.plan(sig_out, _pf(cash=900.0, price=100.0), state)
    assert state2.armed["ma20"] is True


# ── 당일 슬라이스 소진 & 주문 생성 ────────────────────────────────────────
def test_daily_slice_generates_buy_order_and_decrements():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("BUY", 100.0, 5)], armed=_disarmed())
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)
    orders, _, new_state = planner.plan(sig, _pf(cash=1000.0, price=50.0), state)
    buys = [o for o in orders if o.action == OrderAction.BUY]
    assert buys and buys[0].quantity == 2          # floor(100/50)
    assert new_state.queue[0].remaining_days == 4


def test_tranche_removed_when_days_exhausted():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("BUY", 100.0, 1)], armed=_disarmed())
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)
    _, _, new_state = planner.plan(sig, _pf(cash=1000.0, price=50.0), state)
    assert new_state.queue == []


def test_available_cash_param_overrides_total_cash_for_buy_cap():
    """예수금이 0이어도 available_cash(SHV 포함)가 있으면 그만큼 매수 가능."""
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("BUY", 100000.0, 5)], armed=_disarmed())
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)
    pf = Portfolio(total_cash=0.0, holdings={"QLD": 0}, current_prices={"QLD": 100.0})
    orders, _, _ = planner.plan(sig, pf, state, available_cash=300.0)
    buys = [o for o in orders if o.action == OrderAction.BUY]
    assert buys[0].quantity == 3                     # floor(min(100000,300)/100)


def test_sell_target_counts_available_cash():
    """매도 목표 현금비중은 available_cash(예수금+SHV) 기준으로 판정한다.
    이미 목표비중을 채웠으면(현금이 SHV에 있어도) 매도하지 않는다."""
    planner = DipBuyPlanner(ticker="QLD", sell_target_cash_ratio=0.20)
    # 총자산 = available_cash 250 + QLD 1000 = 1250, 목표현금 250, 이미 250 → 매도 없음
    pf = Portfolio(total_cash=0.0, holdings={"QLD": 10}, current_prices={"QLD": 100.0})
    _, _, s1 = planner.plan(_signals(120.0, 90.0, 90.0, 90.0, 80.0), pf, DipBuyState(),
                            available_cash=250.0)
    _, _, s2 = planner.plan(_signals(120.0, 90.0, 90.0, 90.0, 65.0), pf, s1,
                            available_cash=250.0)
    assert [t for t in s2.queue if t.side == "SELL"] == []


def test_buy_capped_by_available_cash():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("BUY", 100000.0, 5)], armed=_disarmed())
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)
    orders, _, _ = planner.plan(sig, _pf(cash=300.0, price=100.0), state)
    buys = [o for o in orders if o.action == OrderAction.BUY]
    assert buys[0].quantity == 3                    # floor(min(100000,300)/100)


def test_sell_order_limited_by_holdings():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("SELL", 1000.0, 5)], armed=_disarmed())
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)
    orders, _, _ = planner.plan(sig, _pf(cash=0.0, qld=2, price=100.0), state)
    sells = [o for o in orders if o.action == OrderAction.SELL]
    assert sells[0].quantity == 2                   # min(ceil(1000/100)=10, 보유 2)


def test_sell_does_not_fire_while_rsi_still_overbought():
    """RSI가 70 위에 있는 동안엔 매도하지 않고 과매수 도달만 기록한다."""
    planner = DipBuyPlanner(ticker="QLD", sell_target_cash_ratio=0.20)
    sig = _signals(price=300.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=80.0)
    orders, _, state = planner.plan(sig, _pf(cash=0.0, qld=10, price=100.0), DipBuyState())
    assert [o for o in orders if o.action == OrderAction.SELL] == []
    assert state.rsi_was_overbought is True
    assert [t for t in state.queue if t.side == "SELL"] == []


def test_sell_fires_on_rsi_crossdown_above_trend():
    """A+B: 과매수 후 RSI 70 하향 돌파 + price>ma120 → 목표 현금비중까지 5일 분할."""
    planner = DipBuyPlanner(ticker="QLD", sell_target_cash_ratio=0.20)
    pf = _pf(cash=0.0, qld=10, price=100.0)   # 총자산 1000, price>ma120
    # 1일차: RSI 80 → 과매수 도달
    _, _, s1 = planner.plan(_signals(120.0, 90.0, 90.0, 90.0, 80.0), pf, DipBuyState())
    # 2일차: RSI 65로 꺾임, price(120)>ma120(90) → 매도 발동
    _, _, s2 = planner.plan(_signals(120.0, 90.0, 90.0, 90.0, 65.0), pf, s1)
    sell = [t for t in s2.queue if t.side == "SELL"][0]
    # 목표 현금 200, 부족분 200 → 5일 분할 40/일, 당일 1일치 소진 후 4일 남음
    assert sell.per_day_amount == pytest.approx(40.0)
    assert sell.remaining_days == 4
    assert s2.rsi_was_overbought is False


def test_sell_does_not_fire_on_crossdown_below_trend():
    """하락장 반등: RSI 70 하향 돌파했지만 price<ma120 → 매도 안 함(데드캣 보호)."""
    planner = DipBuyPlanner(ticker="QLD", sell_target_cash_ratio=0.20)
    pf = _pf(cash=0.0, qld=10, price=100.0)
    _, _, s1 = planner.plan(_signals(80.0, 120.0, 120.0, 120.0, 80.0), pf, DipBuyState())
    # price(80) < ma120(120) → 추세 아래 → 매도 금지, 과매수 플래그만 해제
    _, _, s2 = planner.plan(_signals(80.0, 120.0, 120.0, 120.0, 65.0), pf, s1)
    assert [t for t in s2.queue if t.side == "SELL"] == []
    assert s2.rsi_was_overbought is False


def test_no_orders_when_no_triggers_and_empty_queue():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=200.0, ma20=120.0, ma60=110.0, ma120=100.0, rsi=50.0)
    orders, reason, state = planner.plan(sig, _pf(cash=1000.0, price=100.0), DipBuyState())
    assert orders == []
    assert "대기" in reason
    assert state.queue == []


def test_no_buy_when_cash_zero():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=101.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    orders, _, state = planner.plan(sig, _pf(cash=0.0, price=100.0), DipBuyState())
    assert orders == []
    assert state.armed["ma20"] is False   # 현금 없어도 무장 해제(밴드 이탈 전까지 대기)


def test_invalid_price_returns_unchanged_state():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("BUY", 100.0, 5)], armed=_disarmed())
    sig = _signals(price=100.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    # 대상 티커 가격이 0 → 상태 변경/주문 없이 조기 반환
    pf = Portfolio(total_cash=1000.0, holdings={"QLD": 0}, current_prices={"QLD": 0.0})
    orders, reason, new_state = planner.plan(sig, pf, state)
    assert orders == []
    assert "가격" in reason
    assert new_state is state
    assert new_state.queue[0].remaining_days == 5   # 소진되지 않음


def test_nan_price_returns_unchanged_state():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("BUY", 100.0, 5)], armed=_disarmed())
    sig = _signals(price=100.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    pf = Portfolio(total_cash=1000.0, holdings={"QLD": 0},
                   current_prices={"QLD": float("nan")})
    orders, _, new_state = planner.plan(sig, pf, state)
    assert orders == []
    assert new_state.queue[0].remaining_days == 5


def test_nan_rsi_disables_dip_and_sell():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=60.0, ma20=130.0, ma60=110.0, ma120=70.0, rsi=float("nan"))
    orders, _, state = planner.plan(sig, _pf(cash=1000.0, price=100.0), DipBuyState())
    assert all(t.remaining_days != 39 for t in state.queue)  # dip 미적재
