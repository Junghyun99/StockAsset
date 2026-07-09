"""멀티 계좌(2개 이상) 등록 시 TradingBot의 실행 경로를 검증하는 테스트.

기존 test_main_integration.py / test_coverage_gaps.py는 계좌 1개짜리
accounts.yaml만 다루므로, 계좌별 runner 분리·독립 실행·장애 격리·
accounts.json 기록 등 멀티 계좌 고유 동작은 별도로 검증한다.
"""
import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from src.main import TradingBot
from src.account_config import AccountConfig
from src.core.models import Portfolio


def _fake_two_accounts():
    return [
        AccountConfig(
            id="acc1", market_type="overseas", is_live=False,
            engine_name="SpyEngine", app_key="k1", app_secret="s1", acc_no="1111111111",
        ),
        AccountConfig(
            id="acc2", market_type="domestic", is_live=False,
            engine_name="SpyEngine", app_key="k2", app_secret="s2", acc_no="2222222222",
        ),
    ]


@pytest.fixture
def mock_multi_account_deps(tmp_path):
    """acc1(overseas)/acc2(domestic) 2개 계좌로 TradingBot을 구성할 때 필요한 의존성을 mock.

    Config도 함께 mock하여 DATA_PATH/LOG_PATH를 tmp_path로 돌려,
    테스트가 실제 docs/data, logs 디렉토리에 부작용을 남기지 않게 한다.
    """
    with patch('src.main.Config') as MockConfig, \
         patch('src.main.load_accounts', return_value=_fake_two_accounts()), \
         patch('src.main._resolve_engine_class') as MockResolve, \
         patch('src.main.YFinanceLoader') as MockLoader, \
         patch('src.main.JsonRepository') as MockRepoCls, \
         patch('src.main.SlackNotifier') as MockNotifier, \
         patch('src.main.KisOverseasPaperBroker') as MockOverseasBrokerCls, \
         patch('src.main.KisDomesticPaperBroker') as MockDomesticBrokerCls, \
         patch('src.core.engine.base.IndicatorCalculator'), \
         patch('src.core.engine.base.RegimeAnalyzer'), \
         patch('src.core.engine.base.VolatilityTargeter'), \
         patch('src.core.engine.base.Rebalancer'):

        fake_config = MockConfig.return_value
        fake_config.DATA_PATH = str(tmp_path)
        fake_config.LOG_PATH = str(tmp_path / "logs")
        fake_config.ACCOUNTS_CONFIG_PATH = "accounts.yaml"
        fake_config.SLACK_WEBHOOK_URL = ""
        fake_config.SLACK_BOT_TOKEN = ""
        fake_config.SLACK_CHANNEL_ID = ""
        fake_config.MAX_SUMMARY_RECORDS = 100
        fake_config.MAX_HISTORY_RECORDS = 100

        from src.core.engine import TradingEngine as _TE
        MockResolve.return_value = _TE

        # 계좌별로 독립된 broker/repo mock 인스턴스를 사용해 서로 섞이지 않게 한다.
        overseas_broker = MagicMock(name="overseas_broker")
        domestic_broker = MagicMock(name="domestic_broker")
        MockOverseasBrokerCls.return_value = overseas_broker
        MockDomesticBrokerCls.return_value = domestic_broker

        repo_acc1 = MagicMock(name="repo_acc1")
        repo_acc2 = MagicMock(name="repo_acc2")
        MockRepoCls.side_effect = [repo_acc1, repo_acc2]

        for broker in (overseas_broker, domestic_broker):
            broker.get_portfolio.return_value = Portfolio(
                total_cash=10000.0, holdings={}, current_prices={}
            )

        loader = MockLoader.return_value
        loader.fetch_daily_dividends.return_value = {}
        notifier = MockNotifier.return_value

        yield {
            'loader': loader,
            'notifier': notifier,
            'broker_acc1': overseas_broker,
            'broker_acc2': domestic_broker,
            'repo_acc1': repo_acc1,
            'repo_acc2': repo_acc2,
            'tmp_path': tmp_path,
        }


def test_multi_account_creates_separate_runners(mock_multi_account_deps):
    """계좌 2개 등록 시 계좌별로 독립된 runner(broker/repo/engine)가 생성된다."""
    bot = TradingBot()

    assert len(bot.runners) == 2
    assert [r.account.id for r in bot.runners] == ["acc1", "acc2"]

    assert bot.runners[0].broker is mock_multi_account_deps['broker_acc1']
    assert bot.runners[1].broker is mock_multi_account_deps['broker_acc2']
    assert bot.runners[0].repo is mock_multi_account_deps['repo_acc1']
    assert bot.runners[1].repo is mock_multi_account_deps['repo_acc2']
    assert bot.runners[0].engine is not bot.runners[1].engine

    # 계좌별 Slack 알림 구분을 위해 엔진에 계좌 id가 account_label로 주입된다
    assert bot.runners[0].engine.account_label == "acc1"
    assert bot.runners[1].engine.account_label == "acc2"


def test_multi_account_run_executes_all_accounts(mock_multi_account_deps):
    """run() 호출 시 등록된 모든 계좌의 run_one_cycle이 각각 실행된다."""
    bot = TradingBot()
    for runner in bot.runners:
        runner.engine.run_one_cycle = MagicMock()

    bot.run()

    for runner in bot.runners:
        runner.engine.run_one_cycle.assert_called_once()


def test_multi_account_one_failure_does_not_block_other_account(mock_multi_account_deps):
    """한 계좌(acc1)에서 예외가 발생해도 다른 계좌(acc2)는 계속 실행되고,
    마지막에는 발생했던 예외가 재전파된다 (main.py run()의 장애 격리 동작)."""
    bot = TradingBot()
    acc1_runner, acc2_runner = bot.runners

    acc1_runner.engine.run_one_cycle = MagicMock(side_effect=Exception("acc1 broken"))
    acc2_runner.engine.run_one_cycle = MagicMock()

    with pytest.raises(Exception, match="acc1 broken"):
        bot.run()

    # acc1 실패와 무관하게 acc2는 정상 실행된다
    acc2_runner.engine.run_one_cycle.assert_called_once()

    # acc1 실패에 대한 알림이 전송된다
    mock_multi_account_deps['notifier'].send_alert.assert_called_once()
    alert_msg = mock_multi_account_deps['notifier'].send_alert.call_args[0][0]
    assert "acc1" in alert_msg


def test_multi_account_logs_account_marker_before_run(mock_multi_account_deps):
    """계좌 실행 시작 시 로그에 계좌 id가 남아, 여러 계좌 로그가 섞여도 어떤 계좌가
    실행 중인지 구분할 수 있어야 한다. (Step 1 로그보다 먼저, 계좌 순서대로 기록)"""
    bot = TradingBot()
    for runner in bot.runners:
        # run_one_cycle 내부에서 실제로 찍히는 Step 1 로그를 흉내내어 순서를 검증한다.
        runner.engine.run_one_cycle = MagicMock(
            side_effect=lambda *args, **kwargs: bot.logger.info(">>> Step 1: Data Collection")
        )

    bot.run()

    log_content = Path(bot.logger.log_file).read_text(encoding="utf-8")
    lines = [line for line in log_content.splitlines() if "계좌 실행 시작" in line or "Step 1" in line]

    assert len(lines) == 4
    assert "acc1" in lines[0]
    assert "Step 1" in lines[1]
    assert "acc2" in lines[2]
    assert "Step 1" in lines[3]


def test_multi_account_save_accounts_meta_writes_all_accounts(mock_multi_account_deps):
    """_save_accounts_meta()가 등록된 모든 계좌를 accounts.json / accounts_meta.json에 기록한다."""
    TradingBot()  # __init__ 내부에서 _save_accounts_meta()가 자동 호출된다

    tmp_path = mock_multi_account_deps['tmp_path']
    accounts_list = json.loads((tmp_path / "accounts.json").read_text(encoding="utf-8"))
    assert accounts_list == ["acc1", "acc2"]

    accounts_meta = json.loads((tmp_path / "accounts_meta.json").read_text(encoding="utf-8"))
    assert set(accounts_meta.keys()) == {"acc1", "acc2"}
    assert accounts_meta["acc1"]["market_type"] == "overseas"
    assert accounts_meta["acc1"]["is_live"] is False
    assert accounts_meta["acc2"]["market_type"] == "domestic"
