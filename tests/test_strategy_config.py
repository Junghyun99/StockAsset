"""StrategyConfig 단위 테스트 — 시나리오별 설정 주입 검증."""
import os
from unittest.mock import patch
from src.strategy_config import StrategyConfig


def test_default_values():
    """[기본] 환경변수 없을 때 하드코딩 기본값 사용."""
    with patch.dict(os.environ, {}, clear=True):
        cfg = StrategyConfig()
    assert cfg.TRADING_INTERVAL_DAYS == 1
    assert cfg.REBALANCE_RATIO_A == 0.5
    assert cfg.ASSET_GROUPS == {
        'A': ['SSO', 'QLD'],
        'B': ['IEF', 'GLD', 'PDBC'],
        'C': ['SHV'],
    }


def test_env_override():
    """[환경변수] 환경변수로 전략 파라미터 오버라이드."""
    with patch.dict(os.environ, {
        "TRADING_INTERVAL_DAYS": "10",
        "REBALANCE_RATIO_A": "0.7",
    }):
        cfg = StrategyConfig()
    assert cfg.TRADING_INTERVAL_DAYS == 10
    assert cfg.REBALANCE_RATIO_A == 0.7


def test_constructor_override_takes_priority_over_env():
    """[시나리오] 생성자 인자가 환경변수보다 우선한다."""
    with patch.dict(os.environ, {
        "TRADING_INTERVAL_DAYS": "10",
        "REBALANCE_RATIO_A": "0.7",
    }):
        cfg = StrategyConfig(trading_interval_days=3, rebalance_ratio_a=0.3)
    assert cfg.TRADING_INTERVAL_DAYS == 3
    assert cfg.REBALANCE_RATIO_A == 0.3


def test_custom_asset_groups():
    """[시나리오] 커스텀 자산군으로 새 인스턴스 생성."""
    custom_groups = {
        'A': ['QQQ'],
        'B': ['TLT'],
        'C': ['BIL'],
    }
    cfg = StrategyConfig(asset_groups=custom_groups)
    assert cfg.ASSET_GROUPS == custom_groups


def test_aggressive_scenario():
    """[시나리오] 공격적 포트폴리오 — A 비율 80%, 인터벌 1일."""
    cfg = StrategyConfig(rebalance_ratio_a=0.8, trading_interval_days=1)
    assert cfg.REBALANCE_RATIO_A == 0.8
    assert cfg.TRADING_INTERVAL_DAYS == 1


def test_conservative_scenario():
    """[시나리오] 보수적 포트폴리오 — A 비율 20%, 인터벌 20일."""
    cfg = StrategyConfig(rebalance_ratio_a=0.2, trading_interval_days=20)
    assert cfg.REBALANCE_RATIO_A == 0.2
    assert cfg.TRADING_INTERVAL_DAYS == 20


def test_independent_instances():
    """[격리] 두 인스턴스가 서로 독립적임을 확인."""
    cfg_a = StrategyConfig(rebalance_ratio_a=0.8)
    cfg_b = StrategyConfig(rebalance_ratio_a=0.2)
    assert cfg_a.REBALANCE_RATIO_A != cfg_b.REBALANCE_RATIO_A
