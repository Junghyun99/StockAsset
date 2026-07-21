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
    Order, OrderAction, ExecutionStatus, DayResult,
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
    is_active=True,
    dividend_rate_provider=None,
    dividend_settlement=None,
):
    """공통 TradingEngine Mock 조립."""
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = repo_last_reb
    repo.load_last_regime.return_value = None  # 상태 복원 없음 (기본값)
    broker.get_portfolio.return_value = _make_portfolio()
    broker.fetch_current_prices.return_value = {}

    with patch('src.core.engine.base.IndicatorCalculator') as MockCalc, \
         patch('src.core.engine.base.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.base.VolatilityTargeter') as MockTargeter, \
         patch('src.core.engine.base.Rebalancer') as MockRebalancer:

        calculator = MockCalc.return_value
        analyzer = MockAnalyzer.return_value
        analyzer._prev_regime = None
        targeter = MockTargeter.return_value
        rebalancer = MockRebalancer.return_value
        rebalancer.get_target_params.return_value = (0.5, 0.075)

        engine = TradingEngine(
            asset_groups={'A': ['SSO', 'QLD'], 'B': ['IEF', 'GLD'], 'C': ['SHV']},
            broker=broker,
            repo=repo,
            logger=logger,
            trading_interval_days=trading_interval_days,
            notifier=notifier,
            is_live_trading=is_live_trading,
            is_active=is_active,
            dividend_rate_provider=dividend_rate_provider,
            dividend_settlement=dividend_settlement,
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
    # NaN 시 step 6 전체 스킵 — summary/status 모두 저장 안 함
    mocks["repo"].save_daily_summary.assert_not_called()
    mocks["repo"].update_status.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# 시나리오 5: 보유 종목 가격 조회 실패 → 매매 중단
# ─────────────────────────────────────────────────────────────────

def test_zero_price_holding_skips_trade():
    """보유 종목(SSO 10주) 가격이 0.0 → 리밸런싱 중단, 알림 발송."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier)
    md = _make_market_data()

    # SSO 보유 중인데 가격이 0.0 (fetch 실패)
    portfolio_with_zero = Portfolio(
        total_cash=10000.0,
        holdings={"SSO": 10},
        current_prices={"SSO": 0.0},
    )
    mocks["broker"].get_portfolio.return_value = portfolio_with_zero
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 0.0}

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.is_rebalancing is False
    assert result.signal.orders == []
    assert "SSO" in result.signal.reason
    mocks["rebalancer"].generate_signal.assert_not_called()
    mocks["broker"].execute_orders.assert_not_called()
    notifier.send_alert.assert_called_once()
    mocks["repo"].save_daily_summary.assert_called_once()


def test_zero_price_holding_missing_from_prices():
    """보유 종목(SSO 10주) 가격이 current_prices에 아예 없음 → 리밸런싱 중단."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier)
    md = _make_market_data()

    # SSO 보유 중인데 current_prices에 가격 정보 없음
    portfolio_missing_price = Portfolio(
        total_cash=10000.0,
        holdings={"SSO": 10},
        current_prices={},  # SSO 가격 누락
    )
    mocks["broker"].get_portfolio.return_value = portfolio_missing_price
    mocks["broker"].fetch_current_prices.return_value = {}

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.is_rebalancing is False
    assert result.signal.orders == []
    mocks["rebalancer"].generate_signal.assert_not_called()
    notifier.send_alert.assert_called_once()


def test_zero_price_non_holding_does_not_abort():
    """보유하지 않은 종목(QLD 0주)의 가격이 0.0 → 정상 리밸런싱 진행."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    # SSO만 보유(정상 가격), QLD는 미보유 → QLD 가격 0.0이어도 무관
    portfolio_partial = Portfolio(
        total_cash=10000.0,
        holdings={"SSO": 10},  # QLD 미보유
        current_prices={"SSO": 100.0, "QLD": 0.0},
    )
    mocks["broker"].get_portfolio.return_value = portfolio_partial
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 100.0, "QLD": 0.0}

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    # 보유 종목(SSO)은 가격 정상 → 리밸런싱 실행돼야 함
    assert result.is_rebalancing is True
    mocks["rebalancer"].generate_signal.assert_called_once()


# ─────────────────────────────────────────────────────────────────
# 시나리오 5b: 비활성 계좌 (is_active=False) → 조회만, 매매 스킵
# ─────────────────────────────────────────────────────────────────

def test_inactive_account_skips_trading():
    """is_active=False → 인터벌 충족·BULL이어도 매매/신호생성 스킵, 저장은 수행."""
    engine, mocks = _make_engine(repo_last_reb=None, is_active=False)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    result = engine.run_one_cycle(mocks["data_provider"])

    # 매매·신호 생성 모두 스킵
    mocks["rebalancer"].generate_signal.assert_not_called()
    mocks["broker"].execute_orders.assert_not_called()
    assert result.is_rebalancing is False
    assert result.executions == []
    assert result.signal.orders == []
    assert "비활성" in result.signal.reason


def test_inactive_account_still_queries_and_persists_summary():
    """비활성이어도 포트폴리오 조회는 하고 summary/status는 저장(최신 자산평가 유지).
    단, 매매 내역(save_trade_history)은 executions가 비어 실질적으로 기록 안 됨."""
    engine, mocks = _make_engine(repo_last_reb=None, is_active=False)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    engine.run_one_cycle(mocks["data_provider"])

    # 조회는 수행
    mocks["broker"].get_portfolio.assert_called()
    # 저장(자산평가/상태) 수행
    mocks["repo"].save_daily_summary.assert_called_once()
    mocks["repo"].update_status.assert_called_once()
    # save_trade_history는 빈 executions로 호출되어 실제 기록은 남지 않음
    _, s_kwargs = mocks["repo"].save_daily_summary.call_args
    assert s_kwargs.get("executions") == []


def test_inactive_account_persists_target_ratio_for_factors():
    """비활성 신호에도 target_ratio_a/rebalance_threshold가 채워져 결정요소가 비지 않는다."""
    engine, mocks = _make_engine(repo_last_reb=None, is_active=False)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    result = engine.run_one_cycle(mocks["data_provider"])

    # _make_engine의 rebalancer.get_target_params → (0.5, 0.075)
    assert result.signal.target_ratio_a == 0.5
    assert result.signal.rebalance_threshold == 0.075


def test_inactive_account_sends_notification():
    """비활성 계좌도 매 실행 시 조회 완료 알림을 보낸다."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier, is_active=False)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    engine.run_one_cycle(mocks["data_provider"])

    calls = [str(c) for c in notifier.send_message.call_args_list]
    assert any("비활성" in c for c in calls)


def test_inactive_account_nan_sends_alert_and_skips_persist():
    """비활성 계좌라도 NaN 데이터 시 alert 발송 + Step 6 저장 스킵(활성 경로와 동일)."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier, is_active=False)
    md = _make_market_data(nan_vol=True)  # spy_volatility = NaN

    mocks["calculator"].calculate.return_value = md

    engine.run_one_cycle(mocks["data_provider"])

    notifier.send_alert.assert_called_once()
    msg = notifier.send_alert.call_args[0][0]
    assert "Data Quality Alert (비활성)" in msg
    assert "spy_volatility" in msg
    # NaN → 저장 스킵
    mocks["repo"].save_daily_summary.assert_not_called()
    mocks["repo"].update_status.assert_not_called()


def test_inactive_account_zero_price_holding_sends_alert():
    """비활성 계좌에서 보유 종목 가격 조회 실패(0가격) 시 왜곡 경고 alert 발송."""
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier, is_active=False)
    md = _make_market_data()

    # SSO 보유 중인데 가격이 0.0 (fetch 실패)
    portfolio_with_zero = Portfolio(
        total_cash=10000.0,
        holdings={"SSO": 10},
        current_prices={"SSO": 0.0},
    )
    mocks["broker"].get_portfolio.return_value = portfolio_with_zero
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 0.0}

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0

    result = engine.run_one_cycle(mocks["data_provider"])

    notifier.send_alert.assert_called_once()
    msg = notifier.send_alert.call_args[0][0]
    assert "Price Data Alert (비활성)" in msg
    assert "SSO" in result.signal.reason
    # 매매는 여전히 없음
    mocks["broker"].execute_orders.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# 시나리오 6: 최초 실행 (last_rebalancing_date=None → is_due=True)
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


def test_is_due_stale_future_date_returns_true():
    """이전 실행의 last_rebalancing_date가 sim_date보다 미래 → stale 데이터이므로 True."""
    engine, mocks = _make_engine(repo_last_reb="2025-12-30", trading_interval_days=5)
    # sim_date가 last_rebalancing_date보다 ~1094일 이전
    assert engine._is_due("2023-01-02") is True


# ─────────────────────────────────────────────────────────────────
# rebalancing_date 전달 검증
# ─────────────────────────────────────────────────────────────────

def test_rebalancing_date_set_on_rebalancing_day():
    """리밸런싱 날: update_status에 오늘 실행일(record_date, KST 기준)이 rebalancing_date로 전달.
    (market_data.date는 전일 미국 거래일이므로 실행일과 다름)
    """
    from datetime import datetime, timezone, timedelta
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()  # date="2024-01-10" (전일 미국 거래일)

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    engine.run_one_cycle(mocks["data_provider"])

    _, kwargs = mocks["repo"].update_status.call_args
    # sim_date=None → record_date = 오늘 KST 실행일 (market_data.date가 아님)
    kst_today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    assert kwargs.get("rebalancing_date") == kst_today


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


def test_record_date_used_as_date_override_in_summary():
    """sim_date 지정 시 save_daily_summary에 date_override=sim_date가 전달됨.
    (market_data.date 대신 실행일이 저장 key로 사용되어야 함)
    """
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()  # date="2024-01-10" (전일 미국 거래일)

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    engine.run_one_cycle(mocks["data_provider"], sim_date="2023-06-01")

    _, kwargs = mocks["repo"].save_daily_summary.call_args
    # sim_date가 date_override로 전달되어야 함
    assert kwargs.get("date_override") == "2023-06-01"


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


def test_day_result_expected_dividend_default_zero():
    """DayResult 생성 시 daily_dividend 기본값이 0.0인지 확인"""
    result = DayResult(
        market_data=MarketData("2024-01-01", 100.0, 90.0, 0.12, 0.05, -0.05, 18.0),
        regime=MarketRegime.BULL,
        exposure=1.0,
        signal=TradeSignal(1.0, [], "test"),
        executions=[],
        final_pf=Portfolio(1000.0, {}, {}),
        is_rebalancing=False,
        nan_fields=[],
    )
    assert result.expected_dividend == 0.0


def test_day_result_expected_dividend_set():
    """DayResult에 daily_dividend 값을 설정할 수 있는지 확인"""
    result = DayResult(
        market_data=MarketData("2024-01-01", 100.0, 90.0, 0.12, 0.05, -0.05, 18.0),
        regime=MarketRegime.BULL,
        exposure=1.0,
        signal=TradeSignal(1.0, [], "test"),
        executions=[],
        final_pf=Portfolio(1000.0, {}, {}),
        is_rebalancing=False,
        nan_fields=[],
        expected_dividend=42.5,
    )
    assert result.expected_dividend == 42.5


def test_run_one_cycle_calculates_settles_and_persists_expected_dividend():
    """run_one_cycle(daily_dividend=X) 전달 시 repo.save_daily_summary에 X가 전달되는지 확인"""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")
    mocks["broker"].execute_orders.return_value = []

    result = engine.run_one_cycle(mocks["data_provider"])

    assert mocks["repo"].save_daily_summary.call_args.kwargs["expected_dividend"] == 0.0
    assert result.expected_dividend == 0.0


def test_run_one_cycle_uses_zero_expected_dividend_without_ports():
    """DayResult.daily_dividend에 전달된 값이 반영되는지 확인"""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")
    mocks["broker"].execute_orders.return_value = []

    result = engine.run_one_cycle(mocks["data_provider"])

    assert result.expected_dividend == 0.0


# ─────────────────────────────────────────────────────────────────
# 결정요소 (decision_factors)
# ─────────────────────────────────────────────────────────────────

def test_run_one_cycle_calculates_settles_and_persists_expected_dividend_from_holdings():
    """Holdings times per-share rates are settled before the trading step."""
    rate_provider = MagicMock()
    settlement = MagicMock()
    rate_provider.get_dividend_rates.return_value = {"SSO": 1.25}
    engine, mocks = _make_engine(
        repo_last_reb=None,
        dividend_rate_provider=rate_provider,
        dividend_settlement=settlement,
    )
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    call_order = []
    original_execute_cycle = engine.execute_cycle
    settlement.receive_dividend.side_effect = lambda amount: call_order.append("settle")

    def execute_cycle(*args, **kwargs):
        call_order.append("execute")
        return original_execute_cycle(*args, **kwargs)

    engine.execute_cycle = execute_cycle
    result = engine.run_one_cycle(mocks["data_provider"])

    rate_provider.get_dividend_rates.assert_called_once()
    assert rate_provider.get_dividend_rates.call_args.args[0] == ["SSO"]
    settlement.receive_dividend.assert_called_once_with(12.5)
    assert call_order == ["settle", "execute"]
    assert mocks["repo"].save_daily_summary.call_args.kwargs["expected_dividend"] == 12.5
    assert result.expected_dividend == 12.5


def test_run_one_cycle_continues_with_zero_expected_dividend_when_rate_provider_fails():
    """Rate-provider failures warn and do not abort the cycle."""
    rate_provider = MagicMock()
    settlement = MagicMock()
    rate_provider.get_dividend_rates.side_effect = RuntimeError("provider unavailable")
    engine, mocks = _make_engine(
        repo_last_reb=None,
        dividend_rate_provider=rate_provider,
        dividend_settlement=settlement,
    )
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    result = engine.run_one_cycle(mocks["data_provider"])

    settlement.receive_dividend.assert_not_called()
    mocks["logger"].warning.assert_called_once()
    assert result.expected_dividend == 0.0


def test_run_one_cycle_credits_applied_dividend_to_portfolio_before_execute_cycle():
    """The Step 5 portfolio includes cash actually credited by settlement."""
    rate_provider = MagicMock()
    settlement = MagicMock()
    rate_provider.get_dividend_rates.return_value = {"SSO": 1.25}
    settlement.receive_dividend.return_value = 10.0
    engine, mocks = _make_engine(
        repo_last_reb=None,
        dividend_rate_provider=rate_provider,
        dividend_settlement=settlement,
    )
    md = _make_market_data()
    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    seen_portfolios = []
    original_execute_cycle = engine.execute_cycle

    def execute_cycle(*args, **kwargs):
        seen_portfolios.append(args[1])
        return original_execute_cycle(*args, **kwargs)

    engine.execute_cycle = execute_cycle
    engine.run_one_cycle(mocks["data_provider"])

    assert seen_portfolios[0].total_cash == 10010.0


def test_default_decision_factors_are_regime_centric():
    """기본 엔진의 결정요소는 국면 중심 (대표 요소 = regime)."""
    engine, mocks = _make_engine(repo_last_reb=None)
    mocks["targeter"].target_vol = 0.15
    md = _make_market_data()
    signal = TradeSignal(0.9, [], "Bull (모니터링)")

    factors = engine.decision_factors(md, MarketRegime.BULL, 0.9, signal, _make_portfolio())

    keys = [f.key for f in factors]
    assert keys[0] == "regime"  # 대표(헤드라인) 요소
    assert {"momentum", "vix", "mdd", "volatility"} <= set(keys)
    assert factors[0].value == "Bull"
    assert factors[0].format == "text"
    by_key = {f.key: f for f in factors}
    assert by_key["vix"].threshold == 30.0
    assert by_key["mdd"].threshold == -0.20
    assert by_key["volatility"].threshold == 0.15


def test_persist_passes_decision_factors_to_repo():
    """run_one_cycle 통합 경로: persist가 결정요소를 repo 저장 2종에 전달."""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    engine.run_one_cycle(mocks["data_provider"], sim_date="2026-07-14")

    _, kwargs = mocks["repo"].update_status.call_args
    factors = kwargs["decision_factors"]
    assert factors and factors[0].key == "regime"
    _, kwargs = mocks["repo"].save_daily_summary.call_args
    assert kwargs["decision_factors"] == factors


# ─────────────────────────────────────────────────────────────────
# 거래 후 포트폴리오 조회 실패 → 거래 기록은 반드시 저장
# ─────────────────────────────────────────────────────────────────

def test_post_trade_portfolio_failure_still_persists_executions():
    """거래 실행 후 get_portfolio() 실패해도 Step 6(persist)는 반드시 실행되어야 한다.

    거래 기록이 손실되면 실제 체결된 주문이 history.json에서 사라지는 치명적 버그.
    대신 거래 전 포트폴리오를 final_pf로 사용해 저장을 완료해야 한다.
    """
    notifier = MagicMock()
    engine, mocks = _make_engine(repo_last_reb=None, notifier=notifier)
    md = _make_market_data()
    fake_order = Order("SSO", OrderAction.BUY, 5, 100.0)
    fake_exec = TradeExecution("SSO", OrderAction.BUY, 5, 100.0, 0.1, "2024-01-10", ExecutionStatus.FILLED)
    pre_trade_portfolio = _make_portfolio(cash=10000.0)

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [fake_order], "Rebalance")
    mocks["broker"].execute_orders.return_value = [fake_exec]
    # 첫 번째 get_portfolio (Step 4) 성공, 두 번째 (거래 후) 실패
    mocks["broker"].get_portfolio.side_effect = [pre_trade_portfolio, RuntimeError("KIS API 500")]

    result = engine.run_one_cycle(mocks["data_provider"])

    # 예외가 전파되지 않아야 한다
    assert isinstance(result, DayResult)
    # 거래 기록이 포함된 채로 Step 6가 실행되어야 한다
    mocks["repo"].save_trade_history.assert_called_once()
    call_args = mocks["repo"].save_trade_history.call_args
    saved_executions = call_args.args[0] if call_args.args else call_args.kwargs.get("executions", [])
    assert saved_executions == [fake_exec]
    # 거래 전 포트폴리오가 final_pf로 사용된다
    assert result.final_pf.total_cash == pre_trade_portfolio.total_cash
    # 알림이 발송된다
    alert_msgs = [str(c) for c in notifier.send_alert.call_args_list]
    assert any("거래 후 포트폴리오 조회 실패" in m for m in alert_msgs)


# ─────────────────────────────────────────────────────────────────
# 벤치마크 현재가 조회 (보유 종목과 같은 브로커·같은 시점)
# ─────────────────────────────────────────────────────────────────

def _benchmark_engine(broker_prices, benchmarks):
    broker = MagicMock()
    repo = MagicMock()
    repo.load_last_regime.return_value = None
    broker.fetch_current_prices.return_value = broker_prices
    engine = TradingEngine(
        asset_groups={'A': ['SSO'], 'B': ['SHV']},
        broker=broker,
        repo=repo,
        logger=MagicMock(),
        benchmarks=benchmarks,
    )
    return engine


def test_fetch_benchmark_prices_maps_logical_names():
    """브로커 응답(티커 키)을 논리명으로 매핑한다."""
    engine = _benchmark_engine(
        {'EWY': 80.0, 'SPY': 500.0, 'QQQ': 400.0},
        {'KOSPI200': 'EWY', 'S&P500': 'SPY', 'NASDAQ100': 'QQQ'},
    )
    assert engine._fetch_benchmark_prices() == {
        'KOSPI200': 80.0, 'S&P500': 500.0, 'NASDAQ100': 400.0,
    }


def test_fetch_benchmark_prices_filters_nonpositive():
    """0 이하 가격(조회 실패)은 제외한다."""
    engine = _benchmark_engine(
        {'EWY': 0.0, 'SPY': 500.0, 'QQQ': -1.0},
        {'KOSPI200': 'EWY', 'S&P500': 'SPY', 'NASDAQ100': 'QQQ'},
    )
    assert engine._fetch_benchmark_prices() == {'S&P500': 500.0}


def test_fetch_benchmark_prices_empty_when_no_benchmarks():
    """벤치마크 미설정 시 빈 dict, 브로커 호출도 하지 않는다."""
    engine = _benchmark_engine({'SPY': 500.0}, {})
    assert engine._fetch_benchmark_prices() == {}
    engine.broker.fetch_current_prices.assert_not_called()


def test_fetch_benchmark_prices_exception_returns_empty():
    """브로커 예외 시 빈 dict (매매 사이클 차단 안 함)."""
    engine = _benchmark_engine({}, {'S&P500': 'SPY'})
    engine.broker.fetch_current_prices.side_effect = RuntimeError("boom")
    assert engine._fetch_benchmark_prices() == {}


def test_get_portfolio_stashes_benchmark_prices():
    """get_portfolio가 벤치마크 현재가를 _benchmark_prices에 저장한다."""
    engine = _benchmark_engine(
        {'SSO': 100.0, 'EWY': 80.0, 'SPY': 500.0, 'QQQ': 400.0},
        {'KOSPI200': 'EWY', 'S&P500': 'SPY', 'NASDAQ100': 'QQQ'},
    )
    engine.get_portfolio()
    assert engine._benchmark_prices == {
        'KOSPI200': 80.0, 'S&P500': 500.0, 'NASDAQ100': 400.0,
    }


# ─────────────────────────────────────────────────────────────────
# 고아 종목 자동 청산 (Orphan Holdings Liquidation)
# ─────────────────────────────────────────────────────────────────

def test_get_portfolio_fetches_orphan_prices():
    """get_portfolio는 엔진 그룹 외 보유 종목의 가격도 조회한다"""
    engine, mocks = _make_engine()
    pf_with_orphan = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    mocks["broker"].get_portfolio.return_value = pf_with_orphan

    def fake_fetch(tickers):
        prices = {"SSO": 101.0, "QLD": 50.0, "IEF": 90.0, "GLD": 180.0, "SHV": 110.0, "AAPL": 155.0}
        return {t: prices[t] for t in tickers if t in prices}
    mocks["broker"].fetch_current_prices.side_effect = fake_fetch

    result = engine.get_portfolio()

    assert result.current_prices["AAPL"] == 155.0
    assert result.current_prices["SSO"] == 101.0


def test_detect_orphan_holdings_finds_unknown_tickers():
    """엔진 그룹에 없는 보유 종목을 고아로 감지한다"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5, "TSLA": 3, "IEF": 2},
        current_prices={"SSO": 100.0, "AAPL": 150.0, "TSLA": 200.0, "IEF": 90.0},
    )
    orphans = engine._detect_orphan_holdings(pf)
    assert sorted(orphans) == ["AAPL", "TSLA"]


def test_detect_orphan_holdings_ignores_zero_qty():
    """보유 수량이 0인 종목은 고아로 감지하지 않는다"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 0},
        current_prices={"SSO": 100.0},
    )
    orphans = engine._detect_orphan_holdings(pf)
    assert orphans == []


def test_detect_orphan_holdings_empty_when_all_managed():
    """모든 보유 종목이 엔진 그룹에 속하면 빈 리스트"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "IEF": 5},
        current_prices={"SSO": 100.0, "IEF": 90.0},
    )
    orphans = engine._detect_orphan_holdings(pf)
    assert orphans == []


def test_liquidate_orphans_sells_all_and_refreshes_portfolio():
    """고아 종목을 전량 매도하고 포트폴리오를 갱신한다"""
    engine, mocks = _make_engine(is_live_trading=False)
    orphan_pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    updated_pf = Portfolio(
        total_cash=5750.0,
        holdings={"SSO": 10},
        current_prices={"SSO": 100.0},
    )

    fake_exec = TradeExecution("AAPL", OrderAction.SELL, 5, 150.0, 0.5, "2024-01-10", ExecutionStatus.FILLED)
    mocks["broker"].execute_orders.return_value = [fake_exec]
    mocks["broker"].get_portfolio.return_value = updated_pf
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 101.0}

    execs, result_pf = engine._liquidate_orphans(orphan_pf, ["AAPL"])

    sell_orders = mocks["broker"].execute_orders.call_args[0][0]
    assert len(sell_orders) == 1
    assert sell_orders[0].ticker == "AAPL"
    assert sell_orders[0].action == OrderAction.SELL
    assert sell_orders[0].quantity == 5
    assert sell_orders[0].price == 150.0
    assert execs == [fake_exec]
    assert result_pf.total_cash == 5750.0


def test_liquidate_orphans_skips_zero_price():
    """가격 조회 실패(0원) 종목은 매도하지 않는다"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"AAPL": 5},
        current_prices={"AAPL": 0.0},
    )

    execs, result_pf = engine._liquidate_orphans(pf, ["AAPL"])

    mocks["broker"].execute_orders.assert_not_called()
    assert execs == []
    assert result_pf is pf


def test_execute_cycle_liquidates_orphans_before_rebalancing():
    """execute_cycle은 고아 종목을 먼저 매도한 뒤 리밸런싱을 진행한다"""
    engine, mocks = _make_engine(repo_last_reb=None)
    pf_before = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    pf_after_orphan_sell = Portfolio(
        total_cash=5750.0,
        holdings={"SSO": 10},
        current_prices={"SSO": 100.0},
    )
    orphan_exec = TradeExecution("AAPL", OrderAction.SELL, 5, 150.0, 0.5, "2024-01-10", ExecutionStatus.FILLED)
    rebal_order = Order("SSO", OrderAction.BUY, 3, 100.0)
    rebal_exec = TradeExecution("SSO", OrderAction.BUY, 3, 100.0, 0.1, "2024-01-10", ExecutionStatus.FILLED)

    mocks["broker"].execute_orders.side_effect = [[orphan_exec], [rebal_exec]]
    mocks["broker"].get_portfolio.return_value = pf_after_orphan_sell
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 100.0}
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [rebal_order], "첫 투자: 50:50 비율로 진입")
    mocks["rebalancer"].get_target_params.return_value = (0.5, 0.075)

    md = _make_market_data()
    signal, execs, final_pf, is_rebal = engine.execute_cycle(
        md, pf_before, MarketRegime.BULL, 1.0, [], None, "2024-01-10"
    )

    assert len(execs) == 2
    assert execs[0].ticker == "AAPL"
    assert execs[1].ticker == "SSO"
    assert is_rebal is True


def test_execute_cycle_orphan_only_on_monitoring_day():
    """모니터링 날에도 고아 매도는 실행하되, is_rebalancing은 False"""
    engine, mocks = _make_engine(repo_last_reb="2024-01-10", trading_interval_days=5)
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    pf_after = Portfolio(total_cash=5750.0, holdings={"SSO": 10}, current_prices={"SSO": 100.0})
    orphan_exec = TradeExecution("AAPL", OrderAction.SELL, 5, 150.0, 0.5, "2024-01-10", ExecutionStatus.FILLED)
    mocks["broker"].execute_orders.return_value = [orphan_exec]
    mocks["broker"].get_portfolio.return_value = pf_after
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 100.0}
    mocks["rebalancer"].get_target_params.return_value = (0.5, 0.075)

    md = _make_market_data()
    signal, execs, final_pf, is_rebal = engine.execute_cycle(
        md, pf, MarketRegime.BULL, 1.0, [], "2024-01-11", "2024-01-11"
    )

    assert len(execs) == 1
    assert execs[0].ticker == "AAPL"
    assert is_rebal is False
    assert "모니터링" in signal.reason


def test_execute_cycle_skips_orphan_on_nan():
    """NaN 데이터 이상 시 고아 매도도 스킵한다"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    mocks["rebalancer"].get_target_params.return_value = (0.5, 0.075)

    md = _make_market_data()
    signal, execs, final_pf, is_rebal = engine.execute_cycle(
        md, pf, MarketRegime.BULL, 1.0, ["spy_volatility"], None, "2024-01-10"
    )

    mocks["broker"].execute_orders.assert_not_called()
    assert execs == []
    assert "NaN" in signal.reason
