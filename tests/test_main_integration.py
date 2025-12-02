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
         patch('src.main.TelegramNotifier') as MockNotifier, \
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
    """
    [시나리오 1: 기본 동작]
    정상 시장 -> 리밸런싱 불필요 -> 매매 없이 종료
    """
    # 1. Mock 데이터 설정
    # 지표 계산 결과: 정상 시장
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0
    )
    # 국면 분석: 상승장
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    # 비중 계산: 1.0
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0
    # 리밸런서: 매매 필요 없음
    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, False, [], "Hold"
    )
    
    # 2. 봇 실행
    bot = TradingBot()
    bot.run()
    
    # 3. 검증
    # 데이터 수집 호출됨?
    mock_dependencies['loader'].fetch_ohlcv.assert_called()
    # 주문 실행 안 함?
    mock_dependencies['broker'].execute_orders.assert_not_called()
    # 상태 저장함?
    mock_dependencies['repo'].save_daily_summary.assert_called()
    # 텔레그램 "Hold" 메시지 보냄?
    mock_dependencies['notifier'].send_message.assert_called()
    args, _ = mock_dependencies['notifier'].send_message.call_args
    assert "Hold" in args[0]

def test_bot_run_risk_condition_stop(mock_dependencies):
    """
    [시나리오 2: 위험 감지]
    폭락장(MDD/VIX) 감지 시 -> 전략 실행 전에 즉시 중단 및 알림
    """
    # 1. Mock 데이터 설정: VIX 폭등 상황
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.30, 40.0 # MDD -30%, VIX 40
    )
    
    # 2. 봇 실행
    bot = TradingBot()
    bot.run()
    
    # 3. 검증
    # 알림(Alert) 보내야 함
    mock_dependencies['notifier'].send_alert.assert_called()
    # 전략 분석(Regime Analyzer)까지 가면 안 됨
    mock_dependencies['analyzer'].analyze.assert_not_called()
    # 주문 실행도 당연히 안 됨
    mock_dependencies['broker'].execute_orders.assert_not_called()

def test_bot_run_rebalance_execution(mock_dependencies):
    """
    [시나리오 3: 매매 실행]
    리밸런싱 조건 만족 -> 주문 실행 -> 결과 알림
    """
    # 1. 설정: 정상 시장 + 리밸런싱 필요
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0
    )
    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        1.0, True, [MagicMock()], "Rebalance Needed" # 가짜 주문 포함
    )
    mock_dependencies['broker'].execute_orders.return_value = True # 주문 성공 가정
    
    # 2. 실행
    bot = TradingBot()
    bot.run()
    
    # 3. 검증
    # 브로커에게 주문 실행 요청했나?
    mock_dependencies['broker'].execute_orders.assert_called_once()
    # 텔레그램으로 완료 메시지 보냈나?
    mock_dependencies['notifier'].send_message.assert_called()
    # 히스토리 저장했나?
    mock_dependencies['repo'].save_trade_history.assert_called()

def test_bot_crash_handling(mock_dependencies):
    """
    [시나리오 4: 프로그램 예외 발생]
    데이터 수집 중 에러 발생 시 -> 봇이 죽지 않고 Alert 전송
    """
    # 1. 설정: 데이터 수집기에서 강제 에러 발생
    mock_dependencies['loader'].fetch_ohlcv.side_effect = Exception("API Connection Failed")
    
    # 2. 실행
    bot = TradingBot()
    
    # main.py에서는 raise e를 하므로 pytest.raises로 잡아야 함
    with pytest.raises(Exception, match="API Connection Failed"):
        bot.run()
        
    # 3. 검증
    # 에러 발생 시 텔레그램 Alert가 호출되었는지 확인
    mock_dependencies['notifier'].send_alert.assert_called()
    args, _ = mock_dependencies['notifier'].send_alert.call_args
    assert "Crashed" in args[0]