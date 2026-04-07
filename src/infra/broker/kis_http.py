# src/infra/broker/kis_http.py
"""KIS REST 요청 공통 헤더/HashKey 헬퍼."""
from typing import Optional
import src.infra.broker as _pkg  # test patch 타깃: src.infra.broker.requests


def build_header(
    base_url: str,
    app_key: str,
    app_secret: str,
    access_token: str,
    tr_id: str,
    data: Optional[dict] = None,
    logger=None,
) -> dict:
    """API 공통 헤더 생성 (POST 시 HashKey 포함)."""
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",  # 개인
    }
    if data:
        hashkey = fetch_hashkey(base_url, app_key, app_secret, data, logger)
        if hashkey is None:
            raise ValueError("[KisBroker] HashKey 생성 실패로 주문 헤더를 생성할 수 없습니다.")
        headers["hashkey"] = hashkey
    return headers


def fetch_hashkey(base_url: str, app_key: str, app_secret: str, data: dict, logger) -> Optional[str]:
    url = f"{base_url}/uapi/hashkey"
    try:
        res = _pkg.requests.post(
            url,
            headers={
                "content-type": "application/json",
                "appkey": app_key,
                "appsecret": app_secret,
            },
            json=data,
        )
        res.raise_for_status()
        return res.json()["HASH"]
    except Exception as e:
        if logger:
            logger.error(f"[KisBroker] HashKey 생성 실패: {e}")
        return None
