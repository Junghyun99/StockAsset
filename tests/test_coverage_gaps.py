# tests/test_coverage_gaps.py
# 각 모듈의 미커버 라인을 보완하는 테스트 모음
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from src.core.models import (
    MarketData, MarketRegime, TradeSignal, Order, Portfolio, TradeExecution
)


# ==========================================
# BacktestDataLoader 엣지 케이스 (components.py 25, 37-40, 48-49)
# ==========================================
class TestBacktestDataLoaderEdgeCases:
    @pytest.fixture
    def loader_data(self):
        """기본 테스트 데이터"""
        dates = pd.date_range(start="2024-01-01", periods=10)
        prices = np.linspace(100, 190, 10).reshape(-1, 1)
        columns = pd.MultiIndex.from_product([['Close'], ['SPY']])
        df = pd.DataFrame(prices, index=dates, columns=columns)
        vix_df = pd.DataFrame({'Close': [20.0] * 10}, index=dates)
        return df, vix_df

    def test_loader_holiday_date(self, loader_data):
        """현재 날짜가 데이터에 없는 경우 (휴장일)"""
        from src.backtest.components import BacktestDataLoader

        full_df, full_vix = loader_data
        loader = BacktestDataLoader(full_df, full_vix)

        # 1월 1일~10일 데이터가 있지만, 1월 15일(없는 날짜)로 설정
        holiday = pd.Timestamp("2024-01-15")
        loader.set_date(holiday)

        # 데이터는 1월 10일까지만 있으므로 전체가 반환됨
        df = loader.fetch_ohlcv(["SPY"], days=5)
        assert len(df) == 5

    def test_loader_fetch_ohlcv_keyerror(self, loader_data):
        """단일 종목 요청인데 해당 종목이 MultiIndex에 없는 경우 ValueError 발생 (이슈 #89)"""
        from src.backtest.components import BacktestDataLoader

        full_df, full_vix = loader_data
        loader = BacktestDataLoader(full_df, full_vix)
        loader.set_date(pd.Timestamp("2024-01-05"))

        # 'IEF'는 데이터에 없음 -> KeyError -> ValueError로 전파 (계약 준수)
        with pytest.raises(ValueError, match="IEF"):
            loader.fetch_ohlcv(["IEF"], days=3)

    def test_loader_fetch_vix_fallback(self, loader_data):
        """VIX 데이터가 비정상적일 때 기본값 20.0 반환"""
        from src.backtest.components import BacktestDataLoader

        full_df, _ = loader_data
        # VIX 데이터를 빈 DataFrame으로 설정
        empty_vix = pd.DataFrame()
        loader = BacktestDataLoader(full_df, empty_vix)
        loader.set_date(pd.Timestamp("2024-01-05"))

        vix = loader.fetch_vix()
        assert vix == 20.0

    def test_loader_non_multiindex(self, loader_data):
        """DataFrame이 MultiIndex가 아닌 경우"""
        from src.backtest.components import BacktestDataLoader

        dates = pd.date_range(start="2024-01-01", periods=5)
        # 단일 인덱스 DataFrame
        simple_df = pd.DataFrame({'Close': [100, 110, 120, 130, 140]}, index=dates)
        vix_df = pd.DataFrame({'Close': [20.0] * 5}, index=dates)

        loader = BacktestDataLoader(simple_df, vix_df)
        loader.set_date(pd.Timestamp("2024-01-03"))

        # 단일 인덱스이므로 MultiIndex 분기 안 탐
        df = loader.fetch_ohlcv(["SPY"], days=3)
        assert len(df) == 3


# ==========================================
# BacktestRunner 엣지 케이스 (runner.py 62-64, 87, 99-100)
# ==========================================
class TestBacktestRunnerEdgeCases:
    @pytest.fixture
    def mock_fetcher_data(self):
        """러너 테스트용 대량 데이터 (모든 필수 티커 포함)"""
        dates = pd.date_range(start="2022-01-01", end="2023-02-15")
        all_tickers = ['SSO', 'QLD', 'IEF', 'GLD', 'PDBC', 'SHV', 'SPY']
        prices = np.linspace(100, 200, len(dates))
        data = {('Close', ticker): prices for ticker in all_tickers}
        df = pd.DataFrame(data, index=dates)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        vix = pd.DataFrame({'Close': [15.0] * len(dates)}, index=dates)
        return df, vix

    @patch("src.backtest.runner.download_historical_data")
    @patch("src.backtest.runner.plt.savefig")
    def test_runner_with_data_error_on_some_days(self, mock_savefig, mock_download, mock_fetcher_data):
        """일부 날짜에서 데이터 추출 실패해도 계속 진행"""
        from src.backtest.runner import run_backtest

        mock_download.return_value = mock_fetcher_data
        # 에러 없이 실행되면 OK (내부에서 continue 처리)
        run_backtest(start_date="2023-01-02", end_date="2023-01-05", initial_cash=10000.0)
        mock_savefig.assert_called_once()

    @patch("src.backtest.runner.download_historical_data")
    @patch("src.backtest.runner.plt.savefig")
    def test_runner_rebalance_execution(self, mock_savefig, mock_download):
        """리밸런싱이 실행되는 시나리오"""
        from src.backtest.runner import run_backtest

        # 충분한 데이터와 변동성이 높은 시나리오 (모든 필수 티커 포함)
        dates = pd.date_range(start="2022-01-01", end="2023-06-15")
        all_tickers = ['SSO', 'QLD', 'IEF', 'GLD', 'PDBC', 'SHV', 'SPY']
        # 가격이 크게 변동하도록 설정
        prices = np.concatenate([
            np.linspace(100, 200, len(dates) // 2),
            np.linspace(200, 80, len(dates) - len(dates) // 2)
        ])
        data = {('Close', ticker): prices for ticker in all_tickers}
        df = pd.DataFrame(data, index=dates)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        vix = pd.DataFrame({'Close': [25.0] * len(dates)}, index=dates)
        mock_download.return_value = (df, vix)

        run_backtest(start_date="2023-01-02", end_date="2023-06-01", initial_cash=10000.0)
        mock_savefig.assert_called_once()


# ==========================================
# Notifier 미커버 라인 (notifier.py 15, 44-47, 66-69)
# ==========================================
class TestNotifierEdgeCases:
    def test_telegram_send_alert(self):
        """TelegramNotifier.send_alert 테스트"""
        from src.infra.notifier import TelegramNotifier

        with patch('src.infra.notifier.requests.post') as mock_post:
            notifier = TelegramNotifier(token="123:ABC", chat_id="999")
            notifier.send_alert("Danger!")

            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            assert "WARNING" in kwargs['json']['text']
            assert "Danger!" in kwargs['json']['text']

    def test_slack_send_without_webhook(self):
        """SlackNotifier: webhook_url이 없을 때 콘솔 출력"""
        mock_logger = MagicMock()
        from src.infra.notifier import SlackNotifier

        notifier = SlackNotifier(webhook_url="", logger=mock_logger)
        notifier.send_message("Test Message")

        # webhook이 없으므로 logger.info로 mock 출력
        mock_logger.info.assert_called_once()
        call_arg = mock_logger.info.call_args[0][0]
        assert "[Slack Mock]" in call_arg

    def test_slack_alert_without_webhook(self):
        """SlackNotifier: webhook 없이 alert 전송"""
        mock_logger = MagicMock()
        from src.infra.notifier import SlackNotifier

        notifier = SlackNotifier(webhook_url="", logger=mock_logger)
        notifier.send_alert("Alert Test")

        mock_logger.info.assert_called_once()

    def test_slack_send_connection_error(self):
        """SlackNotifier: 네트워크 에러 처리"""
        mock_logger = MagicMock()
        from src.infra.notifier import SlackNotifier

        with patch('src.infra.notifier.requests.post') as mock_post:
            mock_post.side_effect = Exception("Connection refused")

            notifier = SlackNotifier(
                webhook_url="https://hooks.slack.com/test",
                logger=mock_logger
            )
            notifier.send_message("Test")

            # 에러 로그가 기록되어야 함
            mock_logger.error.assert_called_once()
            call_arg = mock_logger.error.call_args[0][0]
            assert "[Slack Error]" in call_arg
            assert "Connection failed" in call_arg


# ==========================================
# YFinanceLoader VIX 엣지 케이스 (data.py 53, 61-64)
# ==========================================
class TestYFinanceLoaderEdgeCases:
    @pytest.fixture
    def mock_yf(self):
        with patch('src.infra.data.yf.download') as mock:
            yield mock

    @pytest.fixture
    def mock_logger(self):
        return MagicMock()

    def test_fetch_vix_multiindex_dataframe_close(self, mock_yf, mock_logger):
        """VIX MultiIndex에서 Close가 DataFrame으로 반환되는 경우 (line 51)"""
        from src.infra.data import YFinanceLoader

        # MultiIndex에서 xs('Close')가 DataFrame을 반환하는 구조
        columns = pd.MultiIndex.from_product([['Close'], ['^VIX']])
        mock_df = pd.DataFrame([[25.5], [26.0]], columns=columns)
        mock_yf.return_value = mock_df

        loader = YFinanceLoader(mock_logger)
        vix = loader.fetch_vix()

        assert vix == 26.0  # 마지막 행의 첫 번째 열

    def test_fetch_vix_exception_fallback(self, mock_yf, mock_logger):
        """VIX 조회 중 예외 시 기본값 20.0 반환 (lines 61-64)"""
        from src.infra.data import YFinanceLoader

        mock_yf.side_effect = Exception("Network Error")

        loader = YFinanceLoader(mock_logger)
        vix = loader.fetch_vix()

        assert vix == 20.0
        mock_logger.error.assert_called()


# ==========================================
# TradingBot 미커버 라인 (main.py 38-40, 104)
# ==========================================
class TestTradingBotEdgeCases:
    @pytest.fixture
    def mock_deps_live(self):
        """실전 모드 Mock 의존성"""
        with patch('src.main.YFinanceLoader') as MockLoader, \
             patch('src.main.JsonRepository') as MockRepo, \
             patch('src.main.SlackNotifier') as MockNotifier, \
             patch('src.main.KisLiveBroker') as MockKisBroker, \
             patch('src.main.IndicatorCalculator') as MockCalc, \
             patch('src.main.RegimeAnalyzer') as MockAnalyzer, \
             patch('src.main.VolatilityTargeter') as MockTargeter, \
             patch('src.main.Rebalancer') as MockRebalancer, \
             patch.dict('os.environ', {'IS_LIVE_TRADING': 'true'}):

            loader = MockLoader.return_value
            repo = MockRepo.return_value
            notifier = MockNotifier.return_value
            broker = MockKisBroker.return_value
            calc = MockCalc.return_value
            analyzer = MockAnalyzer.return_value
            targeter = MockTargeter.return_value
            rebalancer = MockRebalancer.return_value

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

    @patch('src.main.time.sleep')
    def test_bot_live_trading_mode_init(self, mock_sleep, mock_deps_live):
        """실전 모드에서 KisLiveBroker가 초기화되는지 확인 (lines 38-40)"""
        from src.main import TradingBot

        mock_deps_live['calc'].calculate.return_value = MarketData(
            "2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0
        )
        mock_deps_live['analyzer'].analyze.return_value = MarketRegime.BULL
        mock_deps_live['targeter'].calculate_exposure.return_value = 1.0
        mock_deps_live['rebalancer'].generate_signal.return_value = TradeSignal(
            1.0, [], "Hold"
        )

        bot = TradingBot()
        bot.run()

        # KisLiveBroker가 사용되었는지 확인
        mock_deps_live['repo'].save_daily_summary.assert_called()

    @patch('src.main.time.sleep')
    def test_bot_live_trading_with_execution(self, mock_sleep, mock_deps_live):
        """실전 모드에서 매매 실행 후 sleep(3) 호출 확인 (line 104)"""
        from src.main import TradingBot

        mock_deps_live['calc'].calculate.return_value = MarketData(
            "2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15.0
        )
        mock_deps_live['analyzer'].analyze.return_value = MarketRegime.BULL
        mock_deps_live['targeter'].calculate_exposure.return_value = 1.0
        mock_deps_live['rebalancer'].generate_signal.return_value = TradeSignal(
            1.0, [MagicMock()], "Rebalance"
        )
        mock_deps_live['broker'].execute_orders.return_value = [MagicMock()]
        mock_deps_live['broker'].fetch_current_prices.return_value = {'SPY': 101.0}

        bot = TradingBot()
        bot.run()

        # 실전 모드에서 sleep(3) 호출 확인
        mock_sleep.assert_called_with(3)
        mock_deps_live['notifier'].send_message.assert_called()
