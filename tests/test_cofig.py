import os
from unittest.mock import patch
from src.config import Config

def test_asset_groups_integrity():
    """[기본] 자산군 정의가 누락 없이 되어있는지"""
    config = Config()
    assert 'A' in config.ASSET_GROUPS
    assert 'B' in config.ASSET_GROUPS
    assert 'C' in config.ASSET_GROUPS
    assert 'SSO' in config.ASSET_GROUPS['A']

@patch.dict(os.environ, {
    "IS_LIVE_TRADING": "True",
    "KIS_APP_KEY": "test_key",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/test"
})
def test_env_variable_loading():
    """[설정] 환경변수 로드 확인"""
    # Config 클래스는 import 시점에 로드되므로, 
    # 테스트 안에서 인스턴스화하여 값 확인
    config = Config()
    
    # 모의 환경이므로 직접 클래스 변수에 접근하거나
    # Config 구현 방식에 따라 os.getenv 재확인
    assert os.getenv("IS_LIVE_TRADING") == "True"
    
    # 실제 Config 클래스 속성과 매핑되는지 확인 (구현 방식에 따라 다름)
    assert config.IS_LIVE_TRADING is True
    assert config.SLACK_WEBHOOK_URL == "https://hooks.slack.com/services/test"
    assert config.KIS_APP_KEY == "test_key"

def test_default_env_values():
    with patch.dict(os.environ, {}, clear=True):
        config = Config()
        assert config.SLACK_WEBHOOK_URL == ""