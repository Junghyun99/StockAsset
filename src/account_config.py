# src/account_config.py
"""멀티 계좌 설정 로더.

`accounts.yaml`을 읽어 계좌별 (id, market_type, is_live, engine_name, KIS 시크릿)을
`AccountConfig` dataclass 리스트로 반환한다. 시크릿 자체는 YAML에 두지 않고
`.env`에 `{prefix}_KIS_APP_KEY`, `{prefix}_KIS_APP_SECRET`, `{prefix}_KIS_ACC_NO`
형식으로 저장하고, YAML에는 prefix만 기술한다.
"""
import os
from dataclasses import dataclass
from typing import List

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AccountConfig:
    id: str
    market_type: str          # "overseas" | "domestic"
    is_live: bool
    engine_name: str          # _ENGINE_REGISTRY 등록 이름
    app_key: str
    app_secret: str
    acc_no: str

    def __post_init__(self):
        mt = (self.market_type or "").lower()
        if mt not in ("overseas", "domestic"):
            raise ValueError(
                f"[accounts.yaml] account '{self.id}': market_type must be "
                f"'overseas' or 'domestic', got '{self.market_type}'"
            )
        self.market_type = mt


def load_accounts(path: str = "accounts.yaml") -> List[AccountConfig]:
    """accounts.yaml을 읽어 AccountConfig 리스트를 반환한다.

    Raises:
        FileNotFoundError: 설정 파일이 없을 때
        ValueError: 필수 필드 누락 또는 .env에 시크릿이 없을 때
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"계좌 설정 파일을 찾을 수 없습니다: {path}. "
            f"'accounts.yaml.example'을 복사해 '{path}'를 생성하세요."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    raw_accounts = data.get("accounts") or []
    if not raw_accounts:
        raise ValueError(f"{path}에 'accounts' 항목이 비어 있습니다.")

    accounts: List[AccountConfig] = []
    seen_ids = set()
    for idx, raw in enumerate(raw_accounts):
        acc_id = raw.get("id")
        if not acc_id:
            raise ValueError(f"{path}[{idx}]: 'id' 필드가 필요합니다.")
        if acc_id in seen_ids:
            raise ValueError(f"{path}: 중복된 계좌 id '{acc_id}'")
        seen_ids.add(acc_id)

        engine_name = raw.get("engine")
        if not engine_name:
            raise ValueError(f"{path}[{acc_id}]: 'engine' 필드가 필요합니다.")

        prefix = raw.get("kis_env_prefix")
        if not prefix:
            raise ValueError(f"{path}[{acc_id}]: 'kis_env_prefix' 필드가 필요합니다.")

        app_key = os.getenv(f"{prefix}_KIS_APP_KEY", "")
        app_secret = os.getenv(f"{prefix}_KIS_APP_SECRET", "")
        acc_no = os.getenv(f"{prefix}_KIS_ACC_NO", "")
        if not (app_key and app_secret and acc_no):
            raise ValueError(
                f"[{acc_id}] .env에 {prefix}_KIS_APP_KEY / "
                f"{prefix}_KIS_APP_SECRET / {prefix}_KIS_ACC_NO 를 모두 설정해야 합니다."
            )

        accounts.append(
            AccountConfig(
                id=acc_id,
                market_type=raw.get("market_type", "overseas"),
                is_live=bool(raw.get("is_live", False)),
                engine_name=engine_name,
                app_key=app_key,
                app_secret=app_secret,
                acc_no=acc_no,
            )
        )

    return accounts
