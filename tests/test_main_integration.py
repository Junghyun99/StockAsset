import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from src.main import TradingBot
from src.account_config import AccountConfig
from src.core.models import MarketData, MarketRegime, TradeSignal, Order, Portfolio


def _fake_accounts():
    return [AccountConfig(
        id="test_acc",
        market_type="overseas",
        is_live=False,
        engine_name="SpyEngine",
        app_key="k",
        app_secret="s",
        acc_no="1234567890",
    )]


# ==========================================
# Mock 객체들을 미리 준비하는 Fixture
# ==========================================
@pytest.fixture
def mock_dependencies():
    with patch('src.main.load_accounts', return_value=_fake_accounts()), \
         patch('src.main._resolve_engine_class') as MockResolve, \
         patch('src.main.YFinanceLoader') as MockLoader, \
         patch('src.main.JsonRepository') as MockRepo, \
         patch('src.main.SlackNotifier') as MockNotifier, \
         patch('src.main.KisOverseasPaperBroker') as MockBrokerCls, \
         patch('src.core.engine.base.IndicatorCalculator') as MockCalc, \
         patch('src.core.engine.base.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.base.VolatilityTargeter') as MockTargeter, \
         patch('src.core.engine.base.Rebalancer') as MockRebalancer:

        from src.core.engine import TradingEngine as _TE
        MockResolve.return_value = _TE

        # 인스턴스 Mock 생성
        loader = MockLoader.return_value
        repo = MockRepo.return_value
        notifier = MockNotifier.return_value
        broker = MockBrokerCls.return_value
        calc = MockCalc.return_value
        analyzer = MockAnalyzer.return_value
        targeter = MockTargeter.return_value
        rebalancer = MockRebalancer.return_value

        # [중요] 브로커가 반환할 기본 포트폴리오 설정
        broker.get_portfolio.return_value = Portfolio(
            total_cash=10000.0,
            holdings={'SPY': 10},
            current_prices={'SPY': 100.0}
        )

        # 기본값: 이전 리밸런싱 기록 없음 → _is_rebalancing_due() = True
        repo.get_last_rebalancing_date.return_value = None
        repo.load_last_regime.return_value = None  # 상태 복원 없음 (기본값)

        yield {
            'loader': loader,
            'repo': repo,
            'notifier': notifier,
            'broker': broker,
            'calc': calc,
            'analyzer': analyzer,
            'targeter': targeter,
            'rebalancer': rebalancer
        }

# ==========================================
# 테스트 시나리오
# ==========================================

def test_bot_run_happy_path_no_trade(mock_dependencies):
    """[시나리오 1: 기본 동작]"""
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0
    )
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0
    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, [], "Hold"
    )

    bot = TradingBot()
    bot.run()

    mock_dependencies['loader'].fetch_ohlcv.assert_called()
    mock_dependencies['repo'].save_daily_summary.assert_called()
    mock_dependencies['notifier'].send_message.assert_called()


def test_bot_run_risk_condition_stop(mock_dependencies):
    """[시나리오 2: CRASH 감지]
    CRASH 시: 전략 분석 수행 → exposure=0으로 리밸런싱 실행(현금화) → 알림 → 데이터 저장
    """
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.30, 40.0
    )
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.CRASH
    mock_dependencies['targeter'].calculate_exposure.return_value = 0.0

    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        0.0, [MagicMock()], "CRASH 현금화"
    )
    mock_dependencies['broker'].execute_orders.return_value = [MagicMock()]

    bot = TradingBot()
    bot.run()

    # 1. 전략 분석 수행 확인 (데이터 이상 없음 → analyzer/targeter 호출됨)
    mock_dependencies['analyzer'].analyze.assert_called_once()
    mock_dependencies['targeter'].calculate_exposure.assert_called_once()

    # 2. CRASH → exposure=0으로 리밸런싱 실행 (runner.py와 동일)
    mock_dependencies['rebalancer'].generate_signal.assert_called_once()
    mock_dependencies['broker'].execute_orders.assert_called_once()

    # 3. CRASH 알림 전송
    mock_dependencies['notifier'].send_alert.assert_called_once()
    alert_msg = mock_dependencies['notifier'].send_alert.call_args[0][0]
    assert "CRASH Detected" in alert_msg
    assert "현재 포지션" in alert_msg
    assert "현금화 리밸런싱" in alert_msg

    # 4. 데이터 저장 (CRASH 날도 기록)
    mock_dependencies['repo'].save_daily_summary.assert_called_once()
    mock_dependencies['repo'].update_status.assert_called_once()


def test_bot_run_rebalance_execution(mock_dependencies):
    """[시나리오 3: 리밸런싱 날 매매 실행]"""
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0
    )
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, [MagicMock()], "Rebalance Needed"
    )
    mock_dependencies['broker'].execute_orders.return_value = [MagicMock()]
    mock_dependencies['broker'].fetch_current_prices.return_value = {
        'SPY': 101.0, 'IEF': 99.0
    }

    bot = TradingBot()
    bot.run()

    mock_dependencies['broker'].fetch_current_prices.assert_called_once()
    mock_dependencies['broker'].execute_orders.assert_called_once()
    mock_dependencies['notifier'].send_message.assert_called()
    mock_dependencies['repo'].save_trade_history.assert_called()
    mock_dependencies['rebalancer'].generate_signal.assert_called()


def test_bot_crash_handling(mock_dependencies):
    """[시나리오 4: 프로그램 예외 발생]"""
    mock_dependencies['loader'].fetch_ohlcv.side_effect = Exception("API Connection Failed")

    bot = TradingBot()

    with pytest.raises(Exception, match="API Connection Failed"):
        bot.run()

    mock_dependencies['notifier'].send_alert.assert_called()


def test_bot_order_execution_failure(mock_dependencies):
    """[예외 시나리오: 주문 실패]"""
    mock_dependencies['calc'].calculate.return_value = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0)
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, [MagicMock()], "Go Trade"
    )
    mock_dependencies['broker'].execute_orders.return_value = []

    bot = TradingBot()
    bot.run()

    mock_dependencies['notifier'].send_alert.assert_called()
    args, _ = mock_dependencies['notifier'].send_alert.call_args
    assert "NO execution result" in args[0]


def test_bot_current_price_fetch_failure(mock_dependencies):
    """[예외 시나리오: 현재가 조회 실패]"""
    mock_dependencies['calc'].calculate.return_value = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0)
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    mock_dependencies['broker'].fetch_current_prices.side_effect = Exception("Quote Error")

    bot = TradingBot()

    with pytest.raises(Exception, match="Quote Error"):
        bot.run()

    mock_dependencies['notifier'].send_alert.assert_called()


def test_bot_nan_data_treated_as_crash(mock_dependencies):
    """[시나리오: NaN 데이터 감지 → 매매 중단 + 알림]"""
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, float('nan'), 0.1, -0.05, 15.0
    )

    bot = TradingBot()
    bot.run()

    # 1. NaN → analyzer/targeter 스킵
    mock_dependencies['analyzer'].analyze.assert_not_called()
    mock_dependencies['targeter'].calculate_exposure.assert_not_called()

    # 2. 매매 실행 없음
    mock_dependencies['broker'].execute_orders.assert_not_called()

    # 3. NaN 알림 전송
    mock_dependencies['notifier'].send_alert.assert_called_once()
    alert_msg = mock_dependencies['notifier'].send_alert.call_args[0][0]
    assert "Data Quality Alert" in alert_msg
    assert "spy_volatility" in alert_msg

    # 4. 데이터 저장은 정상 수행
    mock_dependencies['repo'].save_daily_summary.assert_called_once()
    mock_dependencies['repo'].update_status.assert_called_once()

def test_bot_restores_prev_regime_from_repo(mock_dependencies):
    """[히스테리시스 상태 복원] 프로세스 재시작 시 이전 국면을 status.json에서 복원한다.
    CRASH로 저장되어 있었으면 analyzer._prev_regime이 CRASH로 설정되어야 한다.
    """
    mock_dependencies['repo'].load_last_regime.return_value = MarketRegime.CRASH

    bot = TradingBot()

    # analyzer._prev_regime이 CRASH로 복원되었는지 확인
    assert bot.engine.analyzer._prev_regime == MarketRegime.CRASH


def test_bot_no_restore_when_no_saved_regime(mock_dependencies):
    """[히스테리시스 상태 복원] status.json이 없거나 regime이 없으면 _prev_regime을 설정하지 않는다."""
    mock_dependencies['repo'].load_last_regime.return_value = None

    bot = TradingBot()

    # load_last_regime이 None이면 _prev_regime 설정 안 함
    # MagicMock에서는 _prev_regime이 설정되지 않은 상태가 됨
    mock_dependencies['repo'].load_last_regime.assert_called_once()


def test_bot_repo_save_permission_error(mock_dependencies):
    """[예외 시나리오: 저장 실패]"""
    mock_dependencies['calc'].calculate.return_value = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0)
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, [MagicMock()], "Trade Done"
    )
    mock_dependencies['broker'].execute_orders.return_value = [MagicMock()]
    mock_dependencies['repo'].save_daily_summary.side_effect = PermissionError("Disk Read-only")

    bot = TradingBot()

    with pytest.raises(PermissionError):
        bot.run()

    mock_dependencies['notifier'].send_message.assert_called()
    mock_dependencies['notifier'].send_alert.assert_called()


# ==========================================
# 리밸런싱 인터벌 분기 테스트
# ==========================================

def test_bot_run_monitoring_day_skips_orders(mock_dependencies):
    """[모니터링 날] _is_rebalancing_due()=False → 주문 없이 기록만"""
    # 오늘 리밸런싱 → TRADING_INTERVAL_DAYS(1)일 미충족 → 모니터링 모드
    recent_date = date.today().strftime("%Y-%m-%d")
    mock_dependencies['repo'].get_last_rebalancing_date.return_value = recent_date

    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-05", 100, 90, 0.1, 0.1, -0.05, 15.0
    )
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    bot = TradingBot()
    bot.run()

    # 리밸런싱 평가 없음
    mock_dependencies['rebalancer'].generate_signal.assert_not_called()
    mock_dependencies['broker'].execute_orders.assert_not_called()

    # 모니터링 메시지 전송
    mock_dependencies['notifier'].send_message.assert_called_once()
    msg = mock_dependencies['notifier'].send_message.call_args[0][0]
    assert "모니터링" in msg

    # 데이터는 기록
    mock_dependencies['repo'].save_daily_summary.assert_called_once()


def test_bot_run_monitoring_does_not_update_rebalancing_date(mock_dependencies):
    """[모니터링 날] update_status에 rebalancing_date=None이 전달됨"""
    recent_date = date.today().strftime("%Y-%m-%d")
    mock_dependencies['repo'].get_last_rebalancing_date.return_value = recent_date

    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-05", 100, 90, 0.1, 0.1, -0.05, 15.0
    )
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    bot = TradingBot()
    bot.run()

    _, kwargs = mock_dependencies['repo'].update_status.call_args
    assert kwargs.get("rebalancing_date") is None


def test_bot_run_rebalancing_day_updates_rebalancing_date(mock_dependencies):
    """[리밸런싱 날] update_status에 오늘 날짜(rebalancing_date)가 전달됨"""
    # 마지막 리밸런싱 = 10일 전 → 인터벌 충족 → 리밸런싱 실행
    old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
    mock_dependencies['repo'].get_last_rebalancing_date.return_value = old_date

    market_data = MarketData("2024-01-10", 100, 90, 0.1, 0.1, -0.05, 15.0)
    mock_dependencies['calc'].calculate.return_value = market_data
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0
    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(1.0, [], "Hold")

    bot = TradingBot()
    bot.run()

    _, kwargs = mock_dependencies['repo'].update_status.call_args
    assert kwargs.get("rebalancing_date") == market_data.date


def test_is_rebalancing_due_first_run(mock_dependencies):
    """최초 실행(리밸런싱 기록 없음) → True"""
    mock_dependencies['repo'].get_last_rebalancing_date.return_value = None
    bot = TradingBot()
    assert bot._is_rebalancing_due() is True


def test_is_rebalancing_due_recent(mock_dependencies):
    """최근 리밸런싱(인터벌 미충족) → False"""
    today = date.today().strftime("%Y-%m-%d")
    mock_dependencies['repo'].get_last_rebalancing_date.return_value = today
    bot = TradingBot()
    assert bot._is_rebalancing_due() is False


def test_is_rebalancing_due_old(mock_dependencies):
    """인터벌(1일) 이상 경과 → True"""
    old = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
    mock_dependencies['repo'].get_last_rebalancing_date.return_value = old
    bot = TradingBot()
    assert bot._is_rebalancing_due() is True


def test_is_rebalancing_due_invalid_date(mock_dependencies):
    """파싱 불가 날짜 → 안전하게 True 반환"""
    mock_dependencies['repo'].get_last_rebalancing_date.return_value = "not-a-date"
    bot = TradingBot()
    assert bot._is_rebalancing_due() is True
