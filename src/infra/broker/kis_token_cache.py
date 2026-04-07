# src/infra/broker/kis_token_cache.py
"""KIS 접근 토큰 파일 캐시 유틸."""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

# 프로젝트 루트 / .kis_token_cache.json
KIS_TOKEN_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    ".kis_token_cache.json"
)


def load_token_from_cache(app_key: str, logger) -> Optional[dict]:
    """캐시 파일에서 app_key에 해당하는 유효한 토큰을 반환. 없거나 만료면 None."""
    try:
        if not os.path.exists(KIS_TOKEN_CACHE_PATH):
            return None
        with open(KIS_TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        entry = cache.get(app_key)
        if entry is None:
            return None
        expires_at = datetime.fromisoformat(entry["expires_at"])
        if datetime.now() >= expires_at - timedelta(seconds=60):
            logger.info("[KisBroker] 캐시 토큰 만료됨, 재발급 필요")
            return None
        return entry
    except Exception as e:
        logger.warning(f"[KisBroker] 토큰 캐시 로드 실패 (무시): {e}")
        return None


def save_token_to_cache(app_key: str, token: str, expires_at: datetime, logger) -> None:
    """발급된 토큰을 캐시 파일에 저장. 다른 app_key 엔트리는 보존."""
    try:
        cache = {}
        if os.path.exists(KIS_TOKEN_CACHE_PATH):
            with open(KIS_TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
        cache[app_key] = {
            "access_token": token,
            "expires_at": expires_at.isoformat()
        }
        with open(KIS_TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info(f"[KisBroker] 토큰 캐시 저장: {KIS_TOKEN_CACHE_PATH}")
    except Exception as e:
        logger.warning(f"[KisBroker] 토큰 캐시 저장 실패 (무시): {e}")
