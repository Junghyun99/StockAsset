from src.core.logic.channel_regime import ChannelSnapshot
from src.core.logic.sso_spyi_channel_planner import (
    AssetInput,
    AssetState,
    SsoSpyiChannelPlanner,
    SsoSpyiChannelState,
)
from src.core.models import ExecutionStatus, OrderAction, Portfolio, TradeExecution


def _portfolio(cash=10_000.0, sso=0, spyi=0):
    return Portfolio(
        total_cash=cash,
        holdings={"SSO": sso, "SPYI": spyi},
        current_prices={"SSO": 100.0, "SPYI": 50.0},
    )


def _input(date, rsi, deviation, *, price=100.0, slope=0.0, support=90.0):
    return AssetInput(
        date=date,
        weekly_rsi=rsi,
        ma200_deviation=deviation,
        channel=ChannelSnapshot(
            price=price, mid=100.0, support=support, resistance=110.0,
            slope_pct=slope, is_valid=True,
        ),
    )


def test_buy_signal_confirms_on_two_distinct_trading_dates():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    inputs = {"SSO": _input("2024-01-02", 45, -0.12), "SPYI": _input("2024-01-02", 60, 0)}

    _, _, state = planner.plan(inputs, _portfolio(), state)
    assert state.assets["SSO"].confirmed_level == 0

    inputs["SSO"] = _input("2024-01-03", 45, -0.12)
    orders, _, state = planner.plan(inputs, _portfolio(), state)
    assert state.assets["SSO"].confirmed_level == 1
    assert [order.ticker for order in orders] == ["SSO"]


def test_stronger_second_day_signal_confirms_the_weaker_condition_first():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    inputs = {"SSO": _input("2024-01-02", 45, -0.12), "SPYI": _input("2024-01-02", 60, 0)}
    _, _, state = planner.plan(inputs, _portfolio(), state)
    inputs["SSO"] = _input("2024-01-03", 40, -0.20)
    _, _, state = planner.plan(inputs, _portfolio(), state)

    assert state.assets["SSO"].confirmed_level == 1


def test_buy_signal_clears_after_two_final_daily_off_states():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(confirmed_level=1, daily_signal_date="2024-01-02", daily_signal_level=1)})
    inputs = {"SSO": _input("2024-01-03", 60, 0), "SPYI": _input("2024-01-03", 60, 0)}
    _, _, state = planner.plan(inputs, _portfolio(), state)
    assert state.assets["SSO"].confirmed_level == 1
    inputs["SSO"] = _input("2024-01-04", 60, 0)
    _, _, state = planner.plan(inputs, _portfolio(), state)
    assert state.assets["SSO"].confirmed_level == 0


def test_rejected_buy_retries_next_trading_day_without_resetting_cadence():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(confirmed_level=1)})
    inputs = {"SSO": _input("2024-01-02", 45, -0.12), "SPYI": _input("2024-01-02", 60, 0)}
    first, _, state = planner.plan(inputs, _portfolio(), state)
    assert first
    state = planner.record_fills(state, [])
    inputs["SSO"] = _input("2024-01-03", 45, -0.12)
    retry, _, state = planner.plan(inputs, _portfolio(), state)
    assert retry


def test_partial_buy_retries_the_unfilled_quantity_next_trading_day():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(confirmed_level=1)})
    inputs = {"SSO": _input("2024-01-02", 45, -0.12), "SPYI": _input("2024-01-02", 60, 0)}
    first, _, state = planner.plan(inputs, _portfolio(), state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.BUY, first[0].quantity - 1, 100.0, 0.0,
                       "2024-01-02", ExecutionStatus.PARTIAL)
    ])
    inputs["SSO"] = _input("2024-01-03", 45, -0.12)
    retry, _, _ = planner.plan(inputs, _portfolio(), state)
    assert retry[0].quantity == 1


def test_rejected_channel_exit_retries_next_trading_day_without_entering_lock():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(uptrend_active=True, breach_days=2)})
    inputs = {"SSO": _input("2024-01-02", 60, 0, price=80, support=90), "SPYI": _input("2024-01-02", 60, 0, price=50)}
    first, _, state = planner.plan(inputs, _portfolio(cash=1000, sso=20), state)
    assert first[0].action == OrderAction.SELL
    assert state.assets["SSO"].exit_state.value == "NONE"
    state = planner.record_fills(state, [])
    inputs["SSO"] = _input("2024-01-03", 60, 0, price=80, support=90)
    retry, _, state = planner.plan(inputs, _portfolio(cash=1000, sso=20), state)
    assert retry[0].action == OrderAction.SELL


def test_last_intraday_state_replaces_same_day_confirmation():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    inputs = {"SSO": _input("2024-01-02", 45, -0.12), "SPYI": _input("2024-01-02", 60, 0)}
    _, _, state = planner.plan(inputs, _portfolio(), state)
    inputs["SSO"] = _input("2024-01-02", 60, 0)
    _, _, state = planner.plan(inputs, _portfolio(), state)
    inputs["SSO"] = _input("2024-01-03", 45, -0.12)
    _, _, state = planner.plan(inputs, _portfolio(), state)

    assert state.assets["SSO"].confirmed_level == 0


def test_phase_one_orders_every_five_trading_days():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    inputs = {"SSO": _input("2024-01-02", 45, -0.12), "SPYI": _input("2024-01-02", 60, 0)}
    _, _, state = planner.plan(inputs, _portfolio(), state)
    inputs["SSO"] = _input("2024-01-03", 45, -0.12)
    first, _, state = planner.plan(inputs, _portfolio(), state)
    assert first
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.BUY, first[0].quantity, 100.0, 0.0,
                       "2024-01-03", ExecutionStatus.FILLED)
    ])

    for date in ("2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"):
        inputs["SSO"] = _input(date, 45, -0.12)
        orders, _, state = planner.plan(inputs, _portfolio(), state)
        assert not orders

    inputs["SSO"] = _input("2024-01-10", 45, -0.12)
    orders, _, state = planner.plan(inputs, _portfolio(), state)
    assert [order.ticker for order in orders] == ["SSO"]


def test_last_intraday_channel_recovery_cancels_that_days_breach_count():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    inputs = {"SSO": _input("2024-01-02", 60, 0, price=80, support=90), "SPYI": _input("2024-01-02", 60, 0, price=50)}
    _, _, state = planner.plan(inputs, _portfolio(), state)
    inputs["SSO"] = _input("2024-01-02", 60, 0, price=95, support=90)
    _, _, state = planner.plan(inputs, _portfolio(), state)

    assert state.assets["SSO"].breach_days == 0


def test_sso_cap_forces_sale_to_hysteresis_target_and_blocks_same_day_buy():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(confirmed_level=3)})
    inputs = {"SSO": _input("2024-01-02", 30, -0.30), "SPYI": _input("2024-01-02", 60, 0, price=50)}

    orders, _, state = planner.plan(inputs, _portfolio(cash=0, sso=90, spyi=0), state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.SELL, 20)
    ]
    assert state.assets["SSO"].forced_sale_date == "2024-01-02"
