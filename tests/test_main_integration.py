import pytest
import pandas as pd
import numpy as np
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

        # backfill 기본값: 이전 기록 없음 → fill_missing_trading_days가 즉시 반환
        repo.get_last_summary_date.return_value = None

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
    """[시나리오 2: 위험 감지 → CRASH 파이프라인]
    CRASH 시: core 파이프라인 정상 통과 → 매매 중단 → 포지션 포함 알림 → 데이터 저장
    """
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, 0.1, 0.1, -0.30, 40.0
    )
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.CRASH
    mock_dependencies['targeter'].calculate_exposure.return_value = 0.0
    mock_dependencies['rebalancer'].generate_signal.return_value = TradeSignal(
        target_exposure=0.0, orders=[],
        reason="CRASH Detected: Emergency Stop. No Action."
    )

    bot = TradingBot()
    bot.run()

    # 1. core 파이프라인 전체 통과 확인 (dead code 해소)
    mock_dependencies['analyzer'].analyze.assert_called_once()
    mock_dependencies['targeter'].calculate_exposure.assert_called_once()
    mock_dependencies['rebalancer'].generate_signal.assert_called_once()

    # 2. 매매 실행 없음
    mock_dependencies['broker'].execute_orders.assert_not_called()

    # 3. 포지션 정보 포함 알림 전송
    mock_dependencies['notifier'].send_alert.assert_called_once()
    alert_msg = mock_dependencies['notifier'].send_alert.call_args[0][0]
    assert "CRASH Detected" in alert_msg
    assert "현재 포지션" in alert_msg
    assert "사용자 액션 대기" in alert_msg

    # 4. 데이터 저장 (CRASH 날도 기록)
    mock_dependencies['repo'].save_daily_summary.assert_called_once()
    mock_dependencies['repo'].update_status.assert_called_once()

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
        1.0, [MagicMock()], "Rebalance Needed"
    )
    mock_dependencies['broker'].execute_orders.return_value = [MagicMock()] 
    mock_dependencies['broker'].fetch_current_prices.return_value = {
        'SPY': 101.0, 'IEF': 99.0 # 실시간 가격 가정
    }
    
    # 2. 실행
    bot = TradingBot()
    bot.run()
    
    # 3. 검증
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
    # [수정] 필수 Mock 반환값 설정
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
    """[시나리오: NaN 데이터 감지 → CRASH처럼 매매 중단 + 알림]
    변동성 등 핵심 지표가 NaN이면 매매를 중단하고 알림만 전송한다.
    """
    # NaN 변동성을 가진 MarketData
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-01", 100, 90, float('nan'), 0.1, -0.05, 15.0
    )

    bot = TradingBot()
    bot.run()

    # 1. 전략 분석 스킵 (NaN이므로 analyzer/targeter 호출 안 함)
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

def test_bot_repo_save_permission_error(mock_dependencies):
    """[예외 시나리오: 저장 실패]"""
    # [수정] 필수 Mock 반환값 설정
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
# fill_missing_trading_days 테스트
# ==========================================

def _make_spy_df(n_days: int = 300, start: str = "2023-01-01") -> pd.DataFrame:
    """테스트용 SPY OHLCV DataFrame (영업일 기준)"""
    idx = pd.bdate_range(start=start, periods=n_days)
    prices = 400 + np.arange(n_days, dtype=float)
    return pd.DataFrame({
        "Open": prices, "High": prices + 1, "Low": prices - 1,
        "Close": prices, "Volume": 1_000_000,
    }, index=idx)


def test_fill_missing_no_previous_record(mock_dependencies):
    """이전 기록 없으면 backfill 스킵"""
    mock_dependencies['repo'].get_last_summary_date.return_value = None

    bot = TradingBot()
    spy_df = _make_spy_df()
    pf = Portfolio(10000.0, {}, {})

    bot.fill_missing_trading_days(spy_df, pf)

    mock_dependencies['repo'].save_daily_summary.assert_not_called()


def test_fill_missing_no_gap(mock_dependencies):
    """마지막 기록이 오늘(spy_df 마지막 날)이면 backfill 스킵"""
    spy_df = _make_spy_df()
    last_date = spy_df.index[-1].strftime("%Y-%m-%d")
    mock_dependencies['repo'].get_last_summary_date.return_value = last_date

    bot = TradingBot()
    pf = Portfolio(10000.0, {}, {})

    bot.fill_missing_trading_days(spy_df, pf)

    mock_dependencies['repo'].save_daily_summary.assert_not_called()


def test_fill_missing_saves_gap_days(mock_dependencies):
    """spy_df에 5일 갭이 있으면 4일치(오늘 제외)를 save_daily_summary로 저장"""
    spy_df = _make_spy_df(n_days=300)
    # missing_mask: > last_date AND < today(spy_df[-1])
    # 4개 누락 = spy_df[-5]~spy_df[-2] → last_recorded = spy_df[-6]
    gap_days = 4
    last_recorded = spy_df.index[-(gap_days + 2)].strftime("%Y-%m-%d")
    mock_dependencies['repo'].get_last_summary_date.return_value = last_recorded

    # 지표 계산 mock
    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-10", 410.0, 400.0, 0.12, 0.05, -0.02, 18.0
    )
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0

    # VIX fetch (보유 종목 없으므로 1회만 호출됨)
    mock_dependencies['loader'].fetch_ohlcv.return_value = spy_df

    bot = TradingBot()
    pf = Portfolio(10000.0, {}, {})  # 보유 종목 없음

    bot.fill_missing_trading_days(spy_df, pf)

    assert mock_dependencies['repo'].save_daily_summary.call_count == gap_days


def test_fill_missing_invalid_last_date(mock_dependencies):
    """마지막 날짜가 파싱 불가능하면 예외 없이 스킵"""
    mock_dependencies['repo'].get_last_summary_date.return_value = "not-a-date"

    bot = TradingBot()
    spy_df = _make_spy_df()
    pf = Portfolio(10000.0, {}, {})

    # 예외 발생 없이 정상 종료
    bot.fill_missing_trading_days(spy_df, pf)

    mock_dependencies['repo'].save_daily_summary.assert_not_called()


def test_fill_missing_uses_held_ticker_prices(mock_dependencies):
    """보유 종목이 있으면 historical price fetch를 수행"""
    spy_df = _make_spy_df(n_days=300)
    gap_days = 2
    last_recorded = spy_df.index[-(gap_days + 2)].strftime("%Y-%m-%d")
    mock_dependencies['repo'].get_last_summary_date.return_value = last_recorded

    mock_dependencies['calc'].calculate.return_value = MarketData(
        "2024-01-10", 410.0, 400.0, 0.12, 0.05, -0.02, 18.0
    )
    mock_dependencies['analyzer'].analyze.return_value = MarketRegime.BULL
    mock_dependencies['targeter'].calculate_exposure.return_value = 1.0
    mock_dependencies['loader'].fetch_ohlcv.return_value = spy_df

    bot = TradingBot()
    # SSO 1주 보유
    pf = Portfolio(5000.0, {"SSO": 1}, {"SSO": 80.0})

    bot.fill_missing_trading_days(spy_df, pf)

    # VIX fetch + SSO fetch = 2회 fetch_ohlcv 호출
    assert mock_dependencies['loader'].fetch_ohlcv.call_count == 2
    assert mock_dependencies['repo'].save_daily_summary.call_count == gap_days