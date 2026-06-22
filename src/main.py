# src/main.py
import sys
import traceback
import os
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

from typing import List, Tuple

from src.config import Config
from src.strategy_config import StrategyConfig
from src.account_config import AccountConfig, load_accounts
from src.core.engine import TradingEngine  # noqa: F401  (테스트 호환)
from src.core.engine.registry import _ENGINE_REGISTRY, _ENGINE_COLORS, _ENGINE_MARKET_TYPES
from src.utils.logger import TradeLogger
from src.infra.data import YFinanceLoader
from src.infra.broker import (
    KisOverseasPaperBroker,
    KisOverseasLiveBroker,
    KisDomesticPaperBroker,
    KisDomesticLiveBroker,
)
from src.infra.notifier import SlackNotifier
from src.infra.repo import JsonRepository


def _resolve_engine_class(engine_name: str):
    """_ENGINE_REGISTRY에서 이름으로 엔진 클래스를 찾는다."""
    for name, cls in _ENGINE_REGISTRY:
        if name == engine_name:
            return cls
    registered = ", ".join(name for name, _ in _ENGINE_REGISTRY) or "(none)"
    raise ValueError(
        f"알 수 없는 엔진 '{engine_name}'. 등록된 엔진: {registered}"
    )


def _create_broker(acc: AccountConfig, logger):
    """(market_type, is_live) 조합에 따라 KIS 브로커를 생성."""
    args = (acc.app_key, acc.app_secret, acc.acc_no, logger)
    if acc.market_type == "domestic":
        return KisDomesticLiveBroker(*args) if acc.is_live else KisDomesticPaperBroker(*args)
    return KisOverseasLiveBroker(*args) if acc.is_live else KisOverseasPaperBroker(*args)


class AccountRunner:
    """한 계좌에 대한 broker/repo/engine 묶음."""
    def __init__(self, account: AccountConfig, engine, broker, repo):
        self.account = account
        self.engine = engine
        self.broker = broker
        self.repo = repo


class TradingBot:
    def __init__(self):
        # 1. 공용 설정 및 인프라
        self.config = Config()
        self.strategy = StrategyConfig()
        self.logger = TradeLogger(self.config.LOG_PATH)
        self.logger.info("=== Initializing Trading Bot (multi-account) ===")

        self.data_loader = YFinanceLoader(self.logger)
        self.notifier = SlackNotifier(
            self.config.SLACK_WEBHOOK_URL,
            self.logger,
            bot_token=self.config.SLACK_BOT_TOKEN,
            channel_id=self.config.SLACK_CHANNEL_ID,
        )

        # 2. accounts.yaml 로드
        accounts = load_accounts(self.config.ACCOUNTS_CONFIG_PATH)
        self.logger.info(f"Loaded {len(accounts)} account(s) from {self.config.ACCOUNTS_CONFIG_PATH}")

        # 3. 계좌별 러너 구성
        self.runners: List[AccountRunner] = []
        for acc in accounts:
            self.logger.info(
                f"[{acc.id}] engine={acc.engine_name} market={acc.market_type} "
                f"mode={'LIVE' if acc.is_live else 'PAPER'}"
            )
            engine_cls = _resolve_engine_class(acc.engine_name)
            asset_groups = getattr(engine_cls, "ASSET_GROUPS", self.strategy.ASSET_GROUPS)
            ratio_a = getattr(engine_cls, "REBALANCE_RATIO_A", self.strategy.REBALANCE_RATIO_A)

            broker = _create_broker(acc, self.logger)
            repo = JsonRepository(
                os.path.join(self.config.DATA_PATH, acc.id),
                max_summary_records=self.config.MAX_SUMMARY_RECORDS,
                max_history_records=self.config.MAX_HISTORY_RECORDS,
                asset_groups=asset_groups,
            )
            engine = engine_cls(
                asset_groups=asset_groups,
                ratio_a=ratio_a,
                broker=broker,
                repo=repo,
                logger=self.logger,
                trading_interval_days=self.strategy.TRADING_INTERVAL_DAYS,
                notifier=self.notifier,
                is_live_trading=acc.is_live,
            )
            self.runners.append(AccountRunner(acc, engine, broker, repo))

        if not self.runners:
            raise ValueError("등록된 계좌가 없습니다. accounts.yaml을 확인하세요.")

        self._save_accounts_meta()

    def _save_accounts_meta(self):
        """docs/data/accounts.json + accounts_meta.json 생성 (프론트엔드 계좌 목록용)."""
        base = self.config.DATA_PATH
        os.makedirs(base, exist_ok=True)

        accounts_list = [r.account.id for r in self.runners]
        accounts_meta = {
            r.account.id: {
                "market_type": r.account.market_type,
                "engine_name": r.account.engine_name,
                "color": _ENGINE_COLORS.get(r.account.engine_name, "#6c757d"),
                "is_live": r.account.is_live,
            }
            for r in self.runners
        }

        with open(os.path.join(base, "accounts.json"), "w", encoding="utf-8") as f:
            json.dump(accounts_list, f, indent=2)
        with open(os.path.join(base, "accounts_meta.json"), "w", encoding="utf-8") as f:
            json.dump(accounts_meta, f, indent=2, ensure_ascii=False)

    # --- 하위 호환: 기존 테스트/코드가 bot.engine / bot.broker / bot.repo 접근 ---
    @property
    def engine(self):
        return self.runners[0].engine

    @property
    def broker(self):
        return self.runners[0].broker

    @property
    def repo(self):
        return self.runners[0].repo

    def _is_rebalancing_due(self) -> bool:
        """하위 호환 (첫 번째 계좌 기준)."""
        return self.runners[0].engine._is_due(sim_date=None)

    def _run_one_account(self, runner: AccountRunner):
        acc = runner.account
        try:
            daily_dividend = 0.0
            try:
                portfolio = runner.broker.get_portfolio()
                divs = self.data_loader.fetch_daily_dividends(runner.engine.all_tickers)
                daily_dividend = sum(
                    portfolio.holdings.get(t, 0) * div
                    for t, div in divs.items()
                )
            except Exception as e:
                self.logger.warning(f"[{acc.id}] 배당 조회 실패, 0.0으로 처리: {e}")

            runner.engine.run_one_cycle(self.data_loader, daily_dividend=daily_dividend)
        except Exception as e:
            error_msg = f"[{acc.id}] Critical Error:\n{traceback.format_exc()}"
            self.logger.error(error_msg)
            self.notifier.send_alert(f"🔥 [{acc.id}] Bot Crashed!\n{str(e)}")
            raise

    def run(self):
        """모든 계좌를 순차적으로 실행. 한 계좌 실패 시 다른 계좌는 계속 진행."""
        last_exc: Exception | None = None
        for runner in self.runners:
            try:
                self._run_one_account(runner)
            except Exception as e:
                last_exc = e  # 기록만 하고 다음 계좌 진행
        if last_exc is not None:
            # GitHub Actions에 실패 상태를 전달하기 위해 마지막 예외를 재전파
            raise last_exc


if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
