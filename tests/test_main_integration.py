import pytest
from unittest.mock import MagicMock, patch
from src.main import TradingBot
from src.core.models import MarketData, MarketRegime, TradeSignal, Order, Portfolio

# ==========================================
# Mock 객체들을 미리 준비하는 Fixture
# ==========================================
@pytest.fixture
def mock_dependencies():
    with patch('src.main.YFinanceLoader') as MockLoader, \
         patch('src.main.JsonRepository') as MockRepo, \
         patch('src.main.SlackNotifier') as MockNotifier, \
         patch('src.main.MockBroker') as MockBrokerCls, \
         patch('src.main.IndicatorCalculator') as MockCalc, \
         patch('src.main.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.main.VolatilityTargeter') as MockTargeter, \
         patch('src.main.Rebalancer') as MockRebalancer:
        
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
        1.0, False, [], "Hold"
    )
    
    bot = TradingBot()
    bot.run()
    
    mock_dependencies['loader'].fetch_ohlcv.assert_called()
    mock_dependencies['repo'].save_daily_summary.assert_called()
    mock_dependencies['notifier'].send_message.assert_called()

def test_bot_run_risk_condition_stop(mock_dependencies):
    """[시나리오 2: 위험 감지]"""
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.30, 40.0
    )
    
    bot = TradingBot()
    bot.run()
    
    mock_dependencies['notifier'].send_alert.assert_called()
    mock_dependencies['analyzer'].analyze.assert_not_called()

def test_bot_run_rebalance_execution(mock_dependencies):
    """[시나리오 3: 매매 실행]"""
    # 1. 설정
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0
    )
    # [수정] 아래 두 줄을 추가하여 Mock이 아닌 실제 값 반환하도록 설정
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0
    
    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, True, [MagicMock()], "Rebalance Needed"
    )
    mock_dependencies['broker'].execute_orders.return_value = True
    
    # 2. 실행
    bot = TradingBot()
    bot.run()
    
    # 3. 검증
    mock_dependencies['broker'].execute_orders.assert_called_once()
    mock_dependencies['notifier'].send_message.assert_called()
    mock_dependencies['repo'].save_trade_history.assert_called()

def test_bot_crash_handling(mock_dependencies):
    """[시나리오 4: 프로그램 예외 발생]"""
    mock_dependencies['loader'].fetch_ohlcv.side_effect = Exception("API Connection Failed")
    
    bot = TradingBot()
    
    with pytest.raises(Exception, match="API Connection Failed"):
        bot.run()
        
    mock_dependencies['notifier'].send_alert.assert_called()

def test_bot_order_execution_failure(mock_dependencies):
    """[예외 시나리오: 주문 실패]"""
    # [수정] 필수 Mock 반환값 설정
    mock_dependencies['calc'].calculate.return_value = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0)
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, True, [MagicMock()], "Go Trade"
    )
    mock_dependencies['broker'].execute_orders.return_value = False
    
    bot = TradingBot()
    bot.run()
    
    mock_dependencies['notifier'].send_alert.assert_called()
    args, _ = mock_dependencies['notifier'].send_alert.call_args
    assert "Failed" in args[0]

def test_bot_current_price_fetch_failure(mock_dependencies):
    """[예외 시나리오: 현재가 조회 실패]"""
    mock_dependencies['calc'].calculate.return_value = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0)
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0
    
    mock_dependencies['loader'].fetch_ohlcv.side_effect = [
        MagicMock(), 
        Exception("Quote Server Error")
    ]
    
    bot = TradingBot()
    
    with pytest.raises(Exception, match="Quote Server Error"):
        bot.run()
    
    mock_dependencies['notifier'].send_alert.assert_called()

def test_bot_repo_save_permission_error(mock_dependencies):
    """[예외 시나리오: 저장 실패]"""
    # [수정] 필수 Mock 반환값 설정
    mock_dependencies['calc'].calculate.return_value = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0)
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, True, [MagicMock()], "Trade Done"
    )
    mock_dependencies['broker'].execute_orders.return_value = True
    mock_dependencies['repo'].save_daily_summary.side_effect = PermissionError("Disk Read-only")
    
    bot = TradingBot()
    
    with pytest.raises(PermissionError):
        bot.run()
        
    mock_dependencies['notifier'].send_message.assert_called()
    mock_dependencies['notifier'].send_alert.assert_called()