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


def _core_ready_state(**sso_values):
    return SsoSpyiChannelState(assets={
        "SSO": AssetState(core_target_quantity=5, core_quantity=5, **sso_values),
        "SPYI": AssetState(core_target_quantity=30, core_quantity=30),
    }, core_setup_initialized=True)


def test_first_plan_sets_fixed_core_orders_and_skips_dip_campaign():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(confirmed_level=1)})
    inputs = {
        "SSO": _input("2024-01-02", 45, -0.12, price=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    orders, reason, state = planner.plan(inputs, _portfolio(cash=10_000), state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.BUY, 5),
        ("SPYI", OrderAction.BUY, 30),
    ]
    assert reason == "core position setup"
    assert state.assets["SSO"].core_target_quantity == 5
    assert state.assets["SPYI"].core_target_quantity == 30
    assert state.assets["SSO"].pending_core_quantity == 5
    assert state.assets["SSO"].pending_core_date == "2024-01-02"
    assert state.assets["SPYI"].pending_core_quantity == 30
    assert state.assets["SPYI"].pending_core_date == "2024-01-02"


def test_core_targets_wait_for_both_valid_prices_before_first_initialization():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    portfolio = _portfolio(cash=10_000)
    portfolio.current_prices["SPYI"] = 0
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    orders, _, state = planner.plan(inputs, portfolio, state)

    assert not orders
    assert state.assets["SSO"].core_target_quantity == 0
    assert state.assets["SPYI"].core_target_quantity == 0

    portfolio.current_prices["SPYI"] = 50
    inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=100),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    orders, _, state = planner.plan(inputs, portfolio, state)

    assert [(order.ticker, order.quantity) for order in orders] == [("SSO", 5), ("SPYI", 30)]
    assert state.assets["SSO"].core_target_quantity == 5
    assert state.assets["SPYI"].core_target_quantity == 30


def test_core_targets_wait_for_both_inputs_before_first_initialization():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    portfolio = _portfolio(cash=10_000)

    orders, _, state = planner.plan(
        {"SSO": _input("2024-01-02", 60, 0, price=100)}, portfolio, state
    )

    assert not orders
    assert state.core_setup_initialized is False
    assert state.assets["SSO"].core_target_quantity == 0
    assert state.assets["SPYI"].core_target_quantity == 0

    inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=100),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    orders, _, state = planner.plan(inputs, portfolio, state)

    assert [(order.ticker, order.quantity) for order in orders] == [("SSO", 5), ("SPYI", 30)]
    assert state.core_setup_initialized is True


def test_zero_share_core_targets_do_not_reinitialize_on_a_later_larger_portfolio():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    portfolio = _portfolio(cash=1)
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    first, _, state = planner.plan(inputs, portfolio, state)

    assert not first
    assert state.core_setup_initialized is True
    assert state.assets["SSO"].core_target_quantity == 0
    assert state.assets["SPYI"].core_target_quantity == 0

    portfolio.total_cash = 10_000
    inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=100),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    second, _, state = planner.plan(inputs, portfolio, state)

    assert not second
    assert state.assets["SSO"].core_target_quantity == 0
    assert state.assets["SPYI"].core_target_quantity == 0


def test_core_setup_state_serializes_and_restores():
    state = SsoSpyiChannelState(assets={"SSO": AssetState(
        core_target_quantity=5,
        core_quantity=3,
        pending_core_quantity=2,
        pending_core_date="2024-01-02",
    )}, core_setup_initialized=True)

    restored = SsoSpyiChannelState.from_dict(state.to_dict())

    assert restored.assets["SSO"].core_target_quantity == 5
    assert restored.assets["SSO"].core_quantity == 3
    assert restored.assets["SSO"].pending_core_quantity == 2
    assert restored.assets["SSO"].pending_core_date == "2024-01-02"
    assert restored.core_setup_initialized is True


def test_partial_core_fill_retries_only_remaining_quantity_on_next_trading_day():
    planner = SsoSpyiChannelPlanner()
    portfolio = _portfolio(cash=10_000)
    first_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    first, _, state = planner.plan(first_inputs, portfolio, SsoSpyiChannelState())
    assert [(order.ticker, order.quantity) for order in first] == [("SSO", 5), ("SPYI", 30)]

    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.BUY, 2, 100, 0.0,
                       "2024-01-02", ExecutionStatus.PARTIAL),
        TradeExecution("SPYI", OrderAction.BUY, 30, 50, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    sso = state.assets["SSO"]
    spyi = state.assets["SPYI"]
    assert (sso.core_quantity, sso.pending_core_quantity, sso.pending_core_date) == (2, 3, "2024-01-02")
    assert (spyi.core_quantity, spyi.pending_core_quantity, spyi.pending_core_date) == (30, 0, "")

    same_day, reason, state = planner.plan(first_inputs, portfolio, state)
    assert not same_day
    assert reason == "waiting"

    next_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=100),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    retry, reason, state = planner.plan(next_inputs, portfolio, state)
    assert [(order.ticker, order.quantity) for order in retry] == [("SSO", 3)]
    assert reason == "core position setup"
    assert state.assets["SSO"].pending_core_date == "2024-01-03"


def test_core_fill_does_not_advance_campaign_and_campaign_waits_for_both_cores():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={
        "SSO": AssetState(
            core_target_quantity=5,
            core_quantity=5,
            confirmed_level=1,
            campaign_level=1,
            campaign_cash=1_000,
            phase=1,
            phase_order_count=4,
            last_order_date="2024-01-01",
            trading_days_since_order=3,
        ),
        "SPYI": AssetState(
            core_target_quantity=30,
            core_quantity=0,
            pending_core_quantity=30,
            pending_core_date="2024-01-02",
            confirmed_level=1,
            campaign_level=1,
            campaign_cash=1_000,
            phase=1,
            phase_order_count=4,
            last_order_date="2024-01-01",
            trading_days_since_order=3,
        ),
    }, core_setup_initialized=True)

    incomplete_inputs = {
        "SSO": _input("2024-01-02", 45, -0.12, price=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    blocked, reason, state = planner.plan(incomplete_inputs, _portfolio(), state)

    assert not blocked
    assert reason == "waiting"

    state = planner.record_fills(state, [
        TradeExecution("SPYI", OrderAction.BUY, 30, 50, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    spyi = state.assets["SPYI"]
    assert (spyi.phase, spyi.phase_order_count, spyi.last_order_date, spyi.trading_days_since_order) == (
        1, 4, "2024-01-01", 4,
    )
    assert spyi.core_quantity == 30
    assert spyi.pending_core_quantity == 0


def test_rejected_core_order_waits_until_next_trading_date_to_retry():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={
        "SSO": AssetState(
            core_target_quantity=5,
            pending_core_quantity=5,
            pending_core_date="2024-01-02",
        ),
        "SPYI": AssetState(core_target_quantity=30, core_quantity=30),
    }, core_setup_initialized=True)
    portfolio = _portfolio(cash=10_000)
    same_day_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    state = planner.record_fills(state, [])
    same_day, reason, state = planner.plan(same_day_inputs, portfolio, state)

    assert not same_day
    assert reason == "waiting"
    assert state.assets["SSO"].pending_core_quantity == 5

    retry_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=100),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    retry, _, state = planner.plan(retry_inputs, portfolio, state)

    assert [(order.ticker, order.quantity) for order in retry] == [("SSO", 5)]
    assert state.assets["SSO"].pending_core_date == "2024-01-03"


def test_buy_signal_confirms_on_two_distinct_trading_dates():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state()
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
    state = _core_ready_state(confirmed_level=1)
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
    state = _core_ready_state()
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
        ("SSO", OrderAction.SELL, 8)
    ]


def test_buffered_exit_ignores_prices_between_support_and_sso_margin_line():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(uptrend_active=True)
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


def test_slope_exit_thresholds_are_minus_six_percent_for_sso_and_minus_four_for_spyi():
    assert CHANNEL_RULES["SSO"]["slope_exit_threshold"] == -6.0
    assert CHANNEL_RULES["SPYI"]["slope_exit_threshold"] == -4.0


def test_sso_slope_exit_sells_after_two_days_below_minus_six_percent_without_channel_breach():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state()
    first_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100, support=90, slope=-7),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    first, _, state = planner.plan(first_inputs, _portfolio(sso=20), state)

    second_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=100, support=90, slope=-7),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    second, _, _ = planner.plan(second_inputs, _portfolio(sso=20), state)

    assert not first
    assert [(order.ticker, order.action, order.quantity) for order in second] == [
        ("SSO", OrderAction.SELL, 8)
    ]


def test_intraday_slope_updates_count_only_once_per_trading_date():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100, support=90, slope=-7),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    _, _, state = planner.plan(inputs, _portfolio(sso=20), state)
    _, _, state = planner.plan(inputs, _portfolio(sso=20), state)

    assert state.assets["SSO"].slope_exit_days == 1


def test_filled_slope_exit_does_not_create_a_channel_recovery_lot():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    portfolio = _portfolio(cash=1_000, sso=20)
    first_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100, support=90, slope=-7),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    _, _, state = planner.plan(first_inputs, portfolio, state)
    second_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=100, support=90, slope=-7),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    orders, _, state = planner.plan(second_inputs, portfolio, state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, orders[0].quantity, 100, 0.0,
                       "2024-01-03", ExecutionStatus.FILLED),
    ])

    asset = state.assets["SSO"]
    assert asset.exit_origin == "SLOPE"
    assert asset.slope_exit_latched is True
    assert asset.recovery_quantity == 0
    assert asset.recovery_reserved_cash == 0


def test_slope_exit_takes_precedence_over_simultaneous_channel_exit():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState()
    portfolio = _portfolio(cash=1_000, sso=20)
    first_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=90, support=100, slope=-7),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    _, _, state = planner.plan(first_inputs, portfolio, state)
    second_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=90, support=100, slope=-7),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    orders, _, state = planner.plan(second_inputs, portfolio, state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, orders[0].quantity, 90, 0.0,
                       "2024-01-03", ExecutionStatus.FILLED),
    ])

    asset = state.assets["SSO"]
    assert asset.exit_origin == "SLOPE"
    assert asset.recovery_quantity == 0


def test_slope_exit_support_rebound_releases_lock_without_recovery_buy():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(
        exit_state=ExitState.EXIT_LOCK,
        exit_origin="SLOPE",
        lock_price=100,
    )
    inputs = {
        "SSO": _input("2024-01-04", 60, 0, price=95, support=90, slope=-7),
        "SPYI": _input("2024-01-04", 60, 0, price=50),
    }

    orders, _, state = planner.plan(inputs, _portfolio(sso=10), state)

    assert not orders
    assert state.assets["SSO"].exit_state == ExitState.NONE
    assert state.assets["SSO"].exit_origin == ""


def test_suppressed_slope_exit_resumes_when_the_buy_signal_is_off():
    planner = SsoSpyiChannelPlanner()
    state = SsoSpyiChannelState(assets={"SSO": AssetState(
        exit_state=ExitState.EXIT_SUPPRESSED,
        slope_exit_days=2,
    )})
    inputs = {
        "SSO": _input("2024-01-04", 60, 0, price=88, support=90, slope=-7),
        "SPYI": _input("2024-01-04", 60, 0, price=50),
    }

    orders, _, state = planner.plan(inputs, _portfolio(sso=20), state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.SELL, 10)
    ]
    assert state.assets["SSO"].pending_exit_origin == "SLOPE"


def test_slope_exit_latch_requires_two_days_above_threshold_before_a_new_exit():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(slope_exit_latched=True)
    portfolio = _portfolio(sso=20)

    for date in ("2024-01-02", "2024-01-03"):
        inputs = {
            "SSO": _input(date, 60, 0, price=100, support=90, slope=-7),
            "SPYI": _input(date, 60, 0, price=50),
        }
        orders, _, state = planner.plan(inputs, portfolio, state)
        assert not orders

    for date in ("2024-01-04", "2024-01-05"):
        inputs = {
            "SSO": _input(date, 60, 0, price=100, support=90, slope=-5),
            "SPYI": _input(date, 60, 0, price=50),
        }
        orders, _, state = planner.plan(inputs, portfolio, state)
        assert not orders

    first_new_slope_day = {
        "SSO": _input("2024-01-08", 60, 0, price=100, support=90, slope=-7),
        "SPYI": _input("2024-01-08", 60, 0, price=50),
    }
    first, _, state = planner.plan(first_new_slope_day, portfolio, state)
    second_new_slope_day = {
        "SSO": _input("2024-01-09", 60, 0, price=100, support=90, slope=-7),
        "SPYI": _input("2024-01-09", 60, 0, price=50),
    }
    second, _, _ = planner.plan(second_new_slope_day, portfolio, state)

    assert not first
    assert [(order.ticker, order.action, order.quantity) for order in second] == [
        ("SSO", OrderAction.SELL, 8)
    ]


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
    state = _core_ready_state(confirmed_level=1)
    state.assets["SPYI"].recovery_reserved_cash = 5_000
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
    state = _core_ready_state()
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


def test_channel_partial_exit_sells_half_of_tactical_shares_only():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(breach_days=2)
    state.assets["SSO"].core_quantity = 5
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=80, support=90),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    orders, _, _ = planner.plan(inputs, _portfolio(cash=1_000, sso=25), state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.SELL, 10),
    ]


def test_trailing_full_exit_sells_only_remaining_tactical_shares():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(
        exit_state=ExitState.EXIT_LOCK,
        lock_price=100.0,
    )
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=91, support=95),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    portfolio = _portfolio(cash=1_000, sso=12)
    portfolio.current_prices["SSO"] = 91

    orders, _, _ = planner.plan(inputs, portfolio, state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.SELL, 7),
    ]


def test_sso_hard_cap_uses_total_holding_but_only_sells_tactical_quantity():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state()
    state.assets["SSO"].core_quantity = 9
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    orders, _, state = planner.plan(inputs, _portfolio(cash=0, sso=10, spyi=0), state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.SELL, 1),
    ]
    assert state.assets["SSO"].forced_sale_reason == "core floor prevents 78% target"


def test_core_only_trailing_exit_releases_lock_and_allows_later_campaign_buy():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(exit_state=ExitState.EXIT_LOCK, lock_price=100)
    portfolio = _portfolio(cash=10_000, sso=5)
    portfolio.current_prices["SSO"] = 91
    lock_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=91, support=95),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    orders, _, state = planner.plan(lock_inputs, portfolio, state)

    assert not orders
    assert state.assets["SSO"].exit_state == ExitState.NONE
    assert state.assets["SSO"].pending_full_exit_quantity == 0

    first_signal = {
        "SSO": _input("2024-01-03", 45, -0.12, price=100, support=90),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    _, _, state = planner.plan(first_signal, portfolio, state)
    second_signal = {
        "SSO": _input("2024-01-04", 45, -0.12, price=100, support=90),
        "SPYI": _input("2024-01-04", 60, 0, price=50),
    }
    orders, _, _ = planner.plan(second_signal, portfolio, state)

    assert [(order.ticker, order.action) for order in orders] == [("SSO", OrderAction.BUY)]


def test_channel_exit_keeps_recovery_lock_after_selling_last_tactical_share():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(breach_days=2)
    portfolio = _portfolio(cash=1_000, sso=6)
    portfolio.current_prices["SSO"] = 80
    breach_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=80, support=90),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    orders, _, state = planner.plan(breach_inputs, portfolio, state)
    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.SELL, 1),
    ]
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, 1, 80, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    portfolio.holdings["SSO"] = 5
    portfolio.current_prices["SSO"] = 85
    recovery_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=85, support=80),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    orders, _, state = planner.plan(recovery_inputs, portfolio, state)

    assert state.assets["SSO"].exit_state == ExitState.EXIT_LOCK
    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SSO", OrderAction.BUY, 1),
    ]


def test_sso_hard_cap_does_not_repeat_sale_on_the_same_date():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state()
    inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=100),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }
    portfolio = _portfolio(cash=0, sso=90, spyi=0)

    first, _, state = planner.plan(inputs, portfolio, state)
    second, _, state = planner.plan(inputs, portfolio, state)

    assert first[0].action == OrderAction.SELL
    assert not second
    assert state.assets["SSO"].forced_sale_date == "2024-01-02"


def test_core_floor_cap_blocks_sso_buy_but_allows_spyi_campaign_buy():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(confirmed_level=1)
    state.assets["SSO"].core_quantity = 10
    state.assets["SPYI"].confirmed_level = 1
    portfolio = _portfolio(cash=100, sso=10)
    portfolio.current_prices["SPYI"] = 5
    inputs = {
        "SSO": _input("2024-01-02", 45, -0.12, price=100, support=90),
        "SPYI": _input("2024-01-02", 45, -0.12, price=5, support=4),
    }

    orders, _, state = planner.plan(inputs, portfolio, state)

    assert [(order.ticker, order.action, order.quantity) for order in orders] == [
        ("SPYI", OrderAction.BUY, 1),
    ]
    assert state.assets["SSO"].forced_sale_date == "2024-01-02"
    assert state.assets["SSO"].forced_sale_reason == "core floor prevents 78% target"


def test_channel_recovery_restores_only_the_tactical_shares_sold():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(breach_days=2)
    portfolio = _portfolio(cash=1_000, sso=25)
    portfolio.current_prices["SSO"] = 80
    breach_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=80, support=90),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    exit_orders, _, state = planner.plan(breach_inputs, portfolio, state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, exit_orders[0].quantity, 80, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    portfolio.holdings["SSO"] = 15
    portfolio.current_prices["SSO"] = 85
    recovery_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=85, support=80),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    recovery_orders, _, state = planner.plan(recovery_inputs, portfolio, state)

    assert exit_orders[0].quantity == 10
    assert state.assets["SSO"].core_quantity == 5
    assert [(order.ticker, order.action, order.quantity) for order in recovery_orders] == [
        ("SSO", OrderAction.BUY, 10),
    ]


def test_slope_exit_never_creates_a_recovery_buy_after_support_rebound():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(slope_exit_days=2)
    portfolio = _portfolio(cash=1_000, sso=25)
    portfolio.current_prices["SSO"] = 90
    exit_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=90, support=85, slope=-7),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    exit_orders, _, state = planner.plan(exit_inputs, portfolio, state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, exit_orders[0].quantity, 90, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    portfolio.holdings["SSO"] = 15
    portfolio.current_prices["SSO"] = 90
    rebound_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=90, support=85, slope=-7),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    orders, _, state = planner.plan(rebound_inputs, portfolio, state)

    assert state.assets["SSO"].recovery_quantity == 0
    assert state.assets["SSO"].recovery_reserved_cash == 0
    assert not orders
    assert state.assets["SSO"].exit_state == ExitState.NONE


def test_tactical_full_exit_keeps_core_and_does_not_restart_core_setup():
    planner = SsoSpyiChannelPlanner()
    state = _core_ready_state(exit_state=ExitState.EXIT_LOCK, lock_price=100)
    portfolio = _portfolio(cash=1_000, sso=12)
    portfolio.current_prices["SSO"] = 91
    exit_inputs = {
        "SSO": _input("2024-01-02", 60, 0, price=91, support=95),
        "SPYI": _input("2024-01-02", 60, 0, price=50),
    }

    exit_orders, _, state = planner.plan(exit_inputs, portfolio, state)
    state = planner.record_fills(state, [
        TradeExecution("SSO", OrderAction.SELL, exit_orders[0].quantity, 91, 0.0,
                       "2024-01-02", ExecutionStatus.FILLED),
    ])

    portfolio.holdings["SSO"] = 5
    portfolio.current_prices["SSO"] = 100
    next_inputs = {
        "SSO": _input("2024-01-03", 60, 0, price=100, support=90),
        "SPYI": _input("2024-01-03", 60, 0, price=50),
    }
    orders, reason, state = planner.plan(next_inputs, portfolio, state)

    assert exit_orders[0].quantity == 7
    assert state.core_setup_initialized is True
    assert state.assets["SSO"].core_target_quantity == 5
    assert state.assets["SSO"].core_quantity == 5
    assert not orders
    assert reason == "waiting"
