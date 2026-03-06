# tests/test_core_engine.py
"""TradingEngine 단위 테스트.

모든 외부 의존성(broker, repo, notifier, data_provider)을 Mock으로 격리하여
TradingEngine의 비즈니스 로직을 검증한다.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from src.core.engine import TradingEngine
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution,
    Order, OrderAction, ExecutionStatus, DayResult
)


# ─────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────

def _make_market_data(nan_vol=False) -> MarketData:
    import math
    return MarketData(
        date="2024-01-10",
        spy_price=450.0,
        spy_ma180=420.0,
        spy_volatility=math.nan if nan_vol else 0.12,
        spy_momentum=0.05,
        spy_mdd=-0.08,
        vix=18.0,
    )


def _make_portfolio(cash=10000.0) -> Portfolio:
    return Portfolio(
        total_cash=cash,
        holdings={"SSO": 10},
        current_prices={"SSO": 100.0},
    )


def _make_engine(
    repo_last_reb=None,
    notifier=None,
    trading_interval_days=5,
    is_live_trading=False,
):
    """공통 TradingEngine Mock 조립."""
    calculator = MagicMock()
    analyzer = MagicMock()
    analyzer._prev_regime = None
    targeter = MagicMock()
    rebalancer = MagicMock()
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    # 기본값 세팅
    repo.get_last_rebalancing_date.return_value = repo_last_reb
    broker.get_portfolio.return_value = _make_portfolio()
    broker.fetch_current_prices.return_value = {}

    engine = TradingEngine(
        calculator=calculator,
        analyzer=analyzer,
        targeter=targeter,
        rebalancer=rebalancer,
        broker=broker,
        repo=repo,
        logger=logger,
        all_tickers=["SSO", "IEF", "SHV"],
        trading_interval_days=trading_interval_days,
        notifier=notifier,
        is_live_trading=is_live_trading,
    )

    return engine, {
        "calculator": calculator,
        "analyzer": analyzer,
        "targeter": targeter,
        "rebalancer": rebalancer,
        "broker": broker,
        "repo": repo,
        "logger": logger,
        "data_provider": data_provider,
    }


# ─────────────────────────────────────────────────────────────────
# 시나리오 1: 정상 리밸런싱 사이클
# ─────────────────────────────────────────────────────────────────

def test_rebalancing_cycle_executes_orders():
    """인터벌 충족 + BULL → 주문 실행, DayResult.is_rebalancing=True"""
    engine, mocks = _make_engine(repo_last_reb=None)  # 최초 실행 → 인터벌 충족
    md = _make_market_data()
    fake_order = Order("SSO", OrderAction.BUY, 5, 100.0)
    fake_exec = TradeExecution("SSO", OrderAction.BUY, 5, 100.0, 0.1, "2024-01-10", ExecutionStatus.FILLED)

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [fake_order], "Rebalance")
    mocks["broker"].execute_orders.return_value = [fake_exec]

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.is_rebalancing is True
    assert result.regime == MarketRegime.BULL
    assert result.executions == [fake_exec]
    mocks["broker"].execute_orders.assert_called_once()
    mocks["repo"].save_daily_summary.assert_called_once()
    mocks["repo"].save_trade_history.assert_called_once()
    mocks["repo"].update_status.assert_called_once()


# ─────────────────────────────────────────────────────────────────
# 시나리오 2: 모니터링 사이클 (인터벌 미충족, non-CRASH)
# ─────────────────────────────────────────────────────────────────

def test_monitoring_cycle_skips_orders():
    """최근 리밸런싱(1일 전) + BULL → 주문 없음, is_rebalancing=False"""
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    engine, mocks = _make_engine(repo_last_reb=yesterday)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.is_rebalancing is False
    assert result.executions == []
    mocks["rebalancer"].generate_signal.assert_not_called()
    mocks["broker"].execute_orders.assert_not_called()
    # 저장은 수행
    mocks["repo"].save_daily_summary.assert_called_once()
    _, kwargs = mocks["repo"].update_status.call_args
    assert kwargs.get("rebalancing_date") is None


# ─────────────────────────────────────────────────────────────────
# 시나리오 3: CRASH 사이클 (인터벌 무관하게 즉시 리밸런싱)
# ─────────────────────────────────────────────────────────────────

def test_crash_bypasses_interval():
    """CRASH 국면은 인터벌(1일 전) 무관하게 리밸런싱 실행."""
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    engine, mocks = _make_engine(repo_last_reb=yesterday)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    mocks["targeter"].calculate_exposure.return_value = 0.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(0.0, [], "CRASH Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.is_rebalancing is True
    mocks["rebalancer"].generate_signal.assert_called_once()


# ─────────────────────────────────────────────────────────────────
# 시나리오 4: NaN 데이터 → 매매 중단
# ─────────────────────────────────────────────────────────────────

def test_nan_data_skips_trade():
    """NaN 필드 감지 → analyzer/targeter 미호출, 주문 없음, exposure=0."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data(nan_vol=True)  # spy_volatility = NaN

    mocks["calculator"].calculate.return_value = md

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.nan_fields == ["spy_volatility"]
    assert result.exposure == 0.0
    assert result.signal.orders == []
    assert result.is_rebalancing is False
    mocks["analyzer"].analyze.assert_not_called()
    mocks["targeter"].calculate_exposure.assert_not_called()
    mocks["broker"].execute_orders.assert_not_called()
    # 저장은 수행
    mocks["repo"].save_daily_summary.assert_called_once()


# ─────────────────────────────────────────────────────────────────
# 시나리오 5: 최초 실행 (last_rebalancing_date=None → is_due=True)
# ─────────────────────────────────────────────────────────────────

def test_first_run_is_always_due():
    """마지막 리밸런싱 기록 없음 → _is_due()=True → 리밸런싱 실행."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.is_rebalancing is True


# ─────────────────────────────────────────────────────────────────
# 시나리오 6: sim_date 전달 → 저장 시 해당 날짜 사용
# ─────────────────────────────────────────────────────────────────

def test_sim_date_passed_to_repo():
    """sim_date='2023-06-01' 전달 시 repo.save_trade_history에 해당 날짜 전달됨."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    engine.run_one_cycle(mocks["data_provider"], sim_date="2023-06-01")

    _, kwargs = mocks["repo"].save_trade_history.call_args
    assert kwargs.get("sim_date") == "2023-06-01"

    _, kwargs = mocks["repo"].update_status.call_args
    assert kwargs.get("sim_date") == "2023-06-01"


# ─────────────────────────────────────────────────────────────────
# 시나리오 7: notifier=None → 알림 없이 정상 동작
# ─────────────────────────────────────────────────────────────────

def test_no_notifier_does_not_raise():
    """notifier=None (백테스트 모드)이어도 예외 없이 사이클 완료."""
    engine, mocks = _make_engine(repo_last_reb=None, notifier=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])  # 예외 없어야 함
    assert isinstance(result, DayResult)


# ─────────────────────────────────────────────────────────────────
# 알림 시나리오
# ─────────────────────────────────────────────────────────────────

def test_nan_sends_alert_with_notifier():
    """NaN 감지 시 notifier.send_alert()가 호출되고 메시지에 'Data Quality Alert' 포함."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier)
    md = _make_market_data(nan_vol=True)

    mocks["calculator"].calculate.return_value = md

    engine.run_one_cycle(mocks["data_provider"])

    notifier.send_alert.assert_called_once()
    msg = notifier.send_alert.call_args[0][0]
    assert "Data Quality Alert" in msg
    assert "spy_volatility" in msg


def test_crash_sends_alert_with_notifier():
    """CRASH 국면 시 notifier.send_alert()가 호출되고 'CRASH Detected' 포함."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.CRASH
    mocks["targeter"].calculate_exposure.return_value = 0.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(0.0, [], "CRASH")

    engine.run_one_cycle(mocks["data_provider"])

    notifier.send_alert.assert_called_once()
    msg = notifier.send_alert.call_args[0][0]
    assert "CRASH Detected" in msg
    assert "현재 포지션" in msg


def test_orders_executed_sends_message():
    """주문 성공 시 notifier.send_message()가 '✅ Orders Executed' 포함하여 호출됨."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier)
    md = _make_market_data()
    fake_order = Order("SSO", OrderAction.BUY, 5, 100.0)
    fake_exec = TradeExecution("SSO", OrderAction.BUY, 5, 100.0, 0.0, "2024-01-10", ExecutionStatus.FILLED)

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [fake_order], "Buy")
    mocks["broker"].execute_orders.return_value = [fake_exec]

    engine.run_one_cycle(mocks["data_provider"])

    calls = [str(c) for c in notifier.send_message.call_args_list]
    assert any("Orders Executed" in c for c in calls)


def test_empty_executions_sends_alert():
    """주문 전송 후 빈 체결 결과 시 notifier.send_alert() '⚠️ NO execution result' 호출."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier)
    md = _make_market_data()
    fake_order = Order("SSO", OrderAction.BUY, 5, 100.0)

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [fake_order], "Buy")
    mocks["broker"].execute_orders.return_value = []  # 빈 체결

    engine.run_one_cycle(mocks["data_provider"])

    notifier.send_alert.assert_called_once()
    msg = notifier.send_alert.call_args[0][0]
    assert "NO execution result" in msg


# ─────────────────────────────────────────────────────────────────
# _is_due() 단위 테스트
# ─────────────────────────────────────────────────────────────────

def test_is_due_no_history():
    """마지막 리밸런싱 없음 → True."""
    engine, mocks = _make_engine(repo_last_reb=None)
    assert engine._is_due(None) is True


def test_is_due_recent_date():
    """1일 전 리밸런싱 (인터벌 5일) → False."""
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    engine, mocks = _make_engine(repo_last_reb=yesterday, trading_interval_days=5)
    assert engine._is_due(None) is False


def test_is_due_old_date():
    """10일 전 리밸런싱 (인터벌 5일) → True."""
    from datetime import date, timedelta
    old = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
    engine, mocks = _make_engine(repo_last_reb=old, trading_interval_days=5)
    assert engine._is_due(None) is True


def test_is_due_with_sim_date():
    """sim_date 기준으로 인터벌 판단 (백테스트 시뮬레이션)."""
    engine, mocks = _make_engine(repo_last_reb="2023-01-01", trading_interval_days=5)
    assert engine._is_due("2023-01-10") is True   # 9일 경과 → True
    assert engine._is_due("2023-01-03") is False  # 2일 경과 → False


def test_is_due_invalid_date_returns_true():
    """파싱 불가 날짜 → 안전하게 True."""
    engine, mocks = _make_engine(repo_last_reb="not-a-date")
    assert engine._is_due(None) is True


# ─────────────────────────────────────────────────────────────────
# rebalancing_date 전달 검증
# ─────────────────────────────────────────────────────────────────

def test_rebalancing_date_set_on_rebalancing_day():
    """리밸런싱 날: update_status에 market_data.date가 rebalancing_date로 전달."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()  # date="2024-01-10"

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    engine.run_one_cycle(mocks["data_provider"])

    _, kwargs = mocks["repo"].update_status.call_args
    assert kwargs.get("rebalancing_date") == "2024-01-10"


def test_rebalancing_date_none_on_monitoring_day():
    """모니터링 날: update_status에 rebalancing_date=None이 전달."""
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    engine, mocks = _make_engine(repo_last_reb=yesterday)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    engine.run_one_cycle(mocks["data_provider"])

    _, kwargs = mocks["repo"].update_status.call_args
    assert kwargs.get("rebalancing_date") is None


def test_rebalancing_date_uses_sim_date_when_provided():
    """sim_date 지정 시 rebalancing_date에 sim_date가 사용됨."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    engine.run_one_cycle(mocks["data_provider"], sim_date="2023-06-01")

    _, kwargs = mocks["repo"].update_status.call_args
    assert kwargs.get("rebalancing_date") == "2023-06-01"


# ─────────────────────────────────────────────────────────────────
# Template Method: step 메서드 호출 순서 검증
# ─────────────────────────────────────────────────────────────────

def test_step_methods_called_in_order():
    """run_one_cycle()이 6개 step 메서드를 순서대로 호출하는지 검증."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    call_order = []
    original_methods = {
        name: getattr(engine, name)
        for name in [
            "collect_data", "calculate_indicators", "analyze_strategy",
            "get_portfolio", "execute_cycle", "persist",
        ]
    }

    def make_tracker(name, fn):
        def wrapper(*a, **kw):
            call_order.append(name)
            return fn(*a, **kw)
        return wrapper

    for name, fn in original_methods.items():
        setattr(engine, name, make_tracker(name, fn))

    engine.run_one_cycle(mocks["data_provider"])

    assert call_order == [
        "collect_data", "calculate_indicators", "analyze_strategy",
        "get_portfolio", "execute_cycle", "persist",
    ]
