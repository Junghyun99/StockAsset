import os
import pytest
from src.account_config import AccountConfig, load_accounts


YAML_OK = """
accounts:
  - id: acc1
    market_type: overseas
    is_live: true
    engine: SpyEngine
    kis_env_prefix: ACC1
  - id: acc2
    market_type: domestic
    is_live: false
    engine: DomesticAsset5Engine
    kis_env_prefix: ACC2
"""


@pytest.fixture
def yaml_file(tmp_path):
    p = tmp_path / "accounts.yaml"
    p.write_text(YAML_OK, encoding="utf-8")
    return str(p)


def _set_env(monkeypatch, prefix):
    monkeypatch.setenv(f"{prefix}_KIS_APP_KEY", f"{prefix}_key")
    monkeypatch.setenv(f"{prefix}_KIS_APP_SECRET", f"{prefix}_secret")
    monkeypatch.setenv(f"{prefix}_KIS_ACC_NO", "1234567890")


def test_load_accounts_happy(yaml_file, monkeypatch):
    _set_env(monkeypatch, "ACC1")
    _set_env(monkeypatch, "ACC2")
    accounts = load_accounts(yaml_file)
    assert len(accounts) == 2
    assert accounts[0].id == "acc1"
    assert accounts[0].engine_name == "SpyEngine"
    assert accounts[0].is_live is True
    assert accounts[0].market_type == "overseas"
    assert accounts[0].app_key == "ACC1_key"
    assert accounts[1].market_type == "domestic"
    assert accounts[1].is_live is False


def test_load_accounts_missing_file():
    with pytest.raises(FileNotFoundError):
        load_accounts("/nonexistent/accounts.yaml")


def test_load_accounts_missing_secret(yaml_file, monkeypatch):
    _set_env(monkeypatch, "ACC1")
    # ACC2 시크릿 누락
    monkeypatch.delenv("ACC2_KIS_APP_KEY", raising=False)
    with pytest.raises(ValueError, match="ACC2_KIS_APP_KEY"):
        load_accounts(yaml_file)


def test_load_accounts_duplicate_id(tmp_path, monkeypatch):
    p = tmp_path / "dup.yaml"
    p.write_text(
        """
accounts:
  - {id: a, market_type: overseas, is_live: false, engine: SpyEngine, kis_env_prefix: X}
  - {id: a, market_type: overseas, is_live: false, engine: SpyEngine, kis_env_prefix: X}
""",
        encoding="utf-8",
    )
    _set_env(monkeypatch, "X")
    with pytest.raises(ValueError, match="중복"):
        load_accounts(str(p))


def test_load_accounts_empty(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("accounts: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_accounts(str(p))


def test_account_config_invalid_market_type():
    with pytest.raises(ValueError, match="market_type"):
        AccountConfig(
            id="x", market_type="foo", is_live=False,
            engine_name="SpyEngine", app_key="k", app_secret="s", acc_no="n",
        )


def test_load_accounts_missing_engine(tmp_path, monkeypatch):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "accounts:\n  - {id: a, market_type: overseas, is_live: false, kis_env_prefix: X}\n",
        encoding="utf-8",
    )
    _set_env(monkeypatch, "X")
    with pytest.raises(ValueError, match="engine"):
        load_accounts(str(p))
