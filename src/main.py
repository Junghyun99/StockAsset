# src/main.py
import sys
import traceback
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.config import Config
from src.strategy_config import StrategyConfig
from src.core.engine import TradingEngine
from src.utils.logger import TradeLogger
from src.infra.data import YFinanceLoader
from src.infra.broker import KisPaperBroker, KisLiveBroker
from src.infra.notifier import SlackNotifier
from src.infra.repo import JsonRepository


class TradingBot:
    def __init__(self):
        # 1. 설정 및 로거 초기화
        self.config = Config()
        self.strategy = StrategyConfig()
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
            self.logger.info("Mode: PAPER TRADING (KisPaperBroker)")
            self.broker = KisPaperBroker(
                self.config.KIS_APP_KEY,
                self.config.KIS_APP_SECRET,
                self.config.KIS_ACC_NO,
                self.logger,
            )

        # 3. TradingEngine 조립 (core 로직은 엔진 내부에서 생성)
        self.engine = TradingEngine(
            asset_groups=self.strategy.ASSET_GROUPS,
            ratio_a=self.strategy.REBALANCE_RATIO_A,
            broker=self.broker,
            repo=self.repo,
            logger=self.logger,
            trading_interval_days=self.strategy.TRADING_INTERVAL_DAYS,
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
