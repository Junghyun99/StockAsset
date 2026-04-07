import os
from unittest.mock import patch
from src.config import Config
from src.strategy_config import StrategyConfig

def test_asset_groups_integrity():
    """[기본] 자산군 정의가 누락 없이 되어있는지"""
    strategy = StrategyConfig()
    assert 'A' in strategy.ASSET_GROUPS
    assert 'B' in strategy.ASSET_GROUPS
    assert 'C' in strategy.ASSET_GROUPS
    assert 'SSO' in strategy.ASSET_GROUPS['A']

@patch.dict(os.environ, {
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/test",
    "ACCOUNTS_CONFIG_PATH": "custom_accounts.yaml",
})
def test_env_variable_loading():
    """[설정] 환경변수 로드 확인 (멀티 계좌 전환 후)"""
    config = Config()
    assert config.SLACK_WEBHOOK_URL == "https://hooks.slack.com/services/test"
    assert config.ACCOUNTS_CONFIG_PATH == "custom_accounts.yaml"

def test_default_env_values():
    with patch.dict(os.environ, {}, clear=True):
        config = Config()
        assert config.SLACK_WEBHOOK_URL == ""


def test_config_asset_groups_not_empty():
    """
    [설정] 자산군 설정이 비어있으면 봇이 작동하지 않아야 함
    """
    strategy = StrategyConfig()

    # 1. 자산군이 정의되어 있는지 확인
    assert len(strategy.ASSET_GROUPS) > 0

    # 2. 각 그룹에 최소 1개 이상의 티커가 있는지 확인
    for group_name, tickers in strategy.ASSET_GROUPS.items():
        assert len(tickers) > 0, f"Asset group {group_name} is empty!"

def test_config_ticker_duplication():
    """
    [설정] 동일한 종목이 여러 그룹에 중복 등록되었는지 확인
    (중복되면 자산 가치가 더블 카운팅되어 계산 오류 유발)
    """
    strategy = StrategyConfig()

    all_tickers = []
    for tickers in strategy.ASSET_GROUPS.values():
        all_tickers.extend(tickers)

    # 중복 확인
    assert len(all_tickers) == len(set(all_tickers)), "Duplicate tickers found in ASSET_GROUPS!"