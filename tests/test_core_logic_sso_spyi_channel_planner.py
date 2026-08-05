from src.core.logic.channel_regime import ChannelSnapshot
from src.core.logic.sso_spyi_channel_planner import (
    AssetInput,
    AssetState,
    CHANNEL_RULES,
    ExitState,
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


def test_buffered_exit_sells_after_two_days_without_uptrend_confirmation():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    first_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=96, support=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    first, _, state = planner.plan(first_inputs, _portfolio(sso=20), state)

    second_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=96, support=100),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    second, _, _ = planner.plan(second_inputs, _portfolio(sso=20), state)

    assert not first
    assert [(order.ticker, order.action, order.quantity) for order in second] == [
        ("SSO", OrderAction.SELL, 10)
    ]


def test_buffered_exit_ignores_prices_between_support_and_sso_margin_line():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(uptrend_active=True)})
    first_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=98, support=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    _, _, state = planner.plan(first_inputs, _portfolio(sso=20), state)
    second_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=98, support=100),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    orders, _, state = planner.plan(second_inputs, _portfolio(sso=20), state)

    assert not orders
    assert state.assets["SSO"].breach_days == 0


def test_channel_exit_margins_are_three_percent_for_sso_and_two_percent_for_spyi():
    assert CHANNEL_RULES["SSO"]["breakdown_margin"] == 0.03
    assert CHANNEL_RULES["SPYI"]["breakdown_margin"] == 0.02


def test_partial_channel_sale_creates_a_reserved_recovery_lot():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(breach_days=2)})
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=80, support=90),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    portfolio = _portfolio(cash=1_000, sso=20)
    portfolio.current_prices["SSO"] = 80
    orders, _, state = planner.plan(inputs, portfolio, state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, orders[0].quantity, 80, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    asset = state.assets["SSO"]
    assert asset.recovery_quantity == 10
    assert asset.recovery_reserved_cash == 800


def test_partial_channel_sale_retries_its_unfilled_exit_quantity_next_day():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(breach_days=2)})
    first_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=80, support=90),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    portfolio = _portfolio(cash=1_000, sso=20)
    portfolio.current_prices["SSO"] = 80
    first, _, state = planner.plan(first_inputs, portfolio, state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, 3, 80, 0.0,
                       "2024-01-02", ExecutionStatus.PARTIAL),
    ])

    second_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=79, support=90),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    portfolio.current_prices["SSO"] = 79
    second, _, state = planner.plan(second_inputs, portfolio, state)

    assert first[0].quantity == 10
    assert state.assets["SSO"].recovery_quantity == 3
    assert [(order.ticker, order.action, order.quantity) for order in second] == [
        ("SSO", OrderAction.SELL, 7)
    ]


def test_campaign_buy_budget_excludes_other_ticker_recovery_reservation():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={
        "SSO": AssetState(confirmed_level=1),
        "SPYI": AssetState(recovery_reserved_cash=5_000),
    })
    inputs = {
        "SSO": _input("2024-01-02", 45, -0.12, price=100, support=90),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    orders, _, _ = planner.plan(inputs, _portfolio(cash=10_000), state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.BUY, 2)
    ]


def test_support_recovery_buys_back_the_reserved_quantity_before_campaign_buys():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={
        "SSO": AssetState(
            exit_state=ExitState.EXIT_LOCK,
            lock_price=100,
            recovery_quantity=10,
            recovery_reserved_cash=800,
        ),
        "SPYI": AssetState(confirmed_level=1),
    })
    portfolio = _portfolio(cash=1_000, sso=10)
    portfolio.current_prices["SSO"] = 85
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=85, support=80),
        "SPYI": _input("2024-01-02", 45, -0.12, price=50, support=45),
    }

    orders, _, state = planner.plan(inputs, portfolio, state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.BUY, 10)
    ]
    assert state.assets["SSO"].pending_recovery_quantity == 10


def test_filled_recovery_buy_clears_the_lot_and_exit_lock():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(
        exit_state=ExitState.EXIT_LOCK,
        recovery_quantity=10,
        recovery_reserved_cash=800,
        pending_recovery_quantity=10,
    )})

    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.BUY, 10, 85, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    asset = state.assets["SSO"]
    assert asset.recovery_quantity == 0
    assert asset.recovery_reserved_cash == 0
    assert asset.pending_recovery_quantity == 0
    assert asset.exit_state == ExitState.NONE


def test_unfilled_recovery_order_retries_on_the_next_trading_day():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(
        exit_state=ExitState.EXIT_LOCK,
        recovery_quantity=10,
        recovery_reserved_cash=800,
        pending_recovery_quantity=10,
        pending_recovery_date="2024-01-02",
    )})
    portfolio = _portfolio(cash=1_000, sso=10)
    portfolio.current_prices["SSO"] = 80
    inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=80, support=75),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }

    orders, _, state = planner.plan(inputs, portfolio, state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.BUY, 10)
    ]
    assert state.assets["SSO"].pending_recovery_date == "2024-01-03"


def test_support_recovery_cancels_an_unfilled_full_exit_intent():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(
        exit_state=ExitState.EXIT_LOCK,
        lock_price=100,
    )})
    portfolio = _portfolio(cash=1_000, sso=10)
    portfolio.current_prices["SSO"] = 91
    falling_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=91, support=95),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    full_exit, _, state = planner.plan(falling_inputs, portfolio, state)

    portfolio.current_prices["SSO"] = 96
    recovery_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=96, support=95),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    _, _, state = planner.plan(recovery_inputs, portfolio, state)

    assert full_exit[0].quantity == 10
    assert state.assets["SSO"].pending_full_exit_date == ""


def test_partial_full_exit_retries_its_remaining_quantity_next_day():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(
        exit_state=ExitState.EXIT_LOCK,
        lock_price=100,
    )})
    portfolio = _portfolio(cash=1_000, sso=10)
    portfolio.current_prices["SSO"] = 91
    first_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=91, support=95),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    first, _, state = planner.plan(first_inputs, portfolio, state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, 3, 91, 0.0,
                       "2024-01-02", ExecutionStatus.PARTIAL),
    ])

    portfolio.current_prices["SSO"] = 90
    second_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=90, support=95),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    second, _, _ = planner.plan(second_inputs, portfolio, state)

    assert first[0].quantity == 10
    assert [(order.ticker, order.action, order.quantity) for order in second] == [
        ("SSO", OrderAction.SELL, 7)
    ]


def test_sso_hard_cap_fill_does_not_reduce_a_pending_channel_full_exit():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(
        exit_state=ExitState.EXIT_LOCK,
        pending_full_exit_date="2024-01-02",
        pending_full_exit_quantity=7,
        forced_sale_date="2024-01-03",
    )})

    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, 2, 90, 0.0,
                       "2024-01-03 10:00:00", ExecutionStatus.FILLED),
    ])

    assert state.assets["SSO"].pending_full_exit_quantity == 7


def test_trailing_full_exit_clears_lock_and_allows_a_future_campaign():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={
        "SSO": AssetState(
            exit_state=ExitState.EXIT_LOCK,
            lock_price=100.0,
            uptrend_active=True,
            campaign_level=2,
            campaign_cash=10_000.0,
            phase=2,
        ),
    })
    portfolio = _portfolio(cash=1_000, sso=10)
    portfolio.current_prices["SSO"] = 91.0
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=91, support=95),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    orders, _, state = planner.plan(inputs, portfolio, state)
    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.SELL, 10),
    ]
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, 10, 91.0, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    asset = state.assets["SSO"]
    assert asset.exit_state == ExitState.NONE
    assert asset.lock_price == 0.0
    assert asset.uptrend_active is False
    assert asset.phase == 0


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
