# src/main.py
import sys
import traceback
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.config import Config
from src.core.logic import RegimeAnalyzer, VolatilityTargeter, Rebalancer
from src.core.engine import TradingEngine
from src.utils.calculator import IndicatorCalculator
from src.utils.logger import TradeLogger
from src.infra.data import YFinanceLoader
from src.infra.broker import MockBroker, KisPaperBroker, KisLiveBroker
from src.infra.notifier import SlackNotifier
from src.infra.repo import JsonRepository


class TradingBot:
    def __init__(self):
        # 1. 설정 및 로거 초기화
        self.config = Config()
        self.logger = TradeLogger(self.config.LOG_PATH)

        self.logger.info("=== Initializing Trading Bot ===")

        # 2. 인프라 객체 생성
        self.data_loader = YFinanceLoader(self.logger)
        self.repo = JsonRepository(
            self.config.DATA_PATH,
            max_summary_records=self.config.MAX_SUMMARY_RECORDS,
            max_history_records=self.config.MAX_HISTORY_RECORDS,
        )
        self.notifier = SlackNotifier(self.config.SLACK_WEBHOOK_URL, self.logger)

        # 브로커 선택 (실전 vs 모의)
        if self.config.IS_LIVE_TRADING:
            self.logger.info("Mode: LIVE TRADING (KisLiveBroker)")
            self.broker = KisLiveBroker(
                self.config.KIS_APP_KEY,
                self.config.KIS_APP_SECRET,
                self.config.KIS_ACC_NO,
                self.logger,
            )
        else:
            self.logger.info("Mode: PAPER TRADING (MockBroker)")
            self.broker = MockBroker(initial_cash=10000.0, logger=self.logger)

        # 3. 도메인 서비스 생성
        calculator = IndicatorCalculator()
        self.analyzer = RegimeAnalyzer()
        targeter = VolatilityTargeter(target_vol=0.15)
        rebalancer = Rebalancer(self.config.ASSET_GROUPS, logger=self.logger,
                                ratio_a=self.config.REBALANCE_RATIO_A)

        # 4. 히스테리시스 상태 복원 (프로세스 재시작 시 이전 국면 유지)
        last_regime = self.repo.load_last_regime()
        if last_regime is not None:
            self.analyzer._prev_regime = last_regime
            self.logger.info(f"Restored previous regime: {last_regime.value}")

        # 5. TradingEngine 조립
        all_tickers = sum(self.config.ASSET_GROUPS.values(), [])
        self.engine = TradingEngine(
            calculator=calculator,
            analyzer=self.analyzer,
            targeter=targeter,
            rebalancer=rebalancer,
            broker=self.broker,
            repo=self.repo,
            logger=self.logger,
            all_tickers=all_tickers,
            trading_interval_days=self.config.TRADING_INTERVAL_DAYS,
            notifier=self.notifier,
            is_live_trading=self.config.IS_LIVE_TRADING,
        )

    def run(self):
        try:
            self.engine.run_one_cycle(self.data_loader)
        except Exception as e:
            error_msg = f"Critical Error:\n{traceback.format_exc()}"
            self.logger.error(error_msg)
            self.notifier.send_alert(f"🔥 Bot Crashed!\n{str(e)}")
            raise e  # GitHub Actions 실패 처리를 위해 raise

    def _is_rebalancing_due(self) -> bool:
        """후방 호환성 유지 — engine._is_due()에 위임."""
        return self.engine._is_due(sim_date=None)


if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
