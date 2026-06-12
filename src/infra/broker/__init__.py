# src/infra/broker/__init__.py
"""KIS/Mock 브로커 패키지 — 공개 심볼 re-export."""
import os
# 테스트 patch 대상 — 반드시 submodule import 이전에 선언
import requests  # noqa: F401  patch('src.infra.broker.requests')
import time  # noqa: F401  patch('src.infra.broker.time.sleep')

# KIS REST 호출 타임아웃(초). 응답이 없을 때 무한 대기를 막는다.
# 하드코딩 대신 환경변수(KIS_HTTP_TIMEOUT)로 조정 가능. 기본 10초.
KIS_HTTP_TIMEOUT: float = float(os.getenv("KIS_HTTP_TIMEOUT", "10"))

from .mock import MockBroker
from .kis_base import KisBrokerCommon
from .kis_token_cache import KIS_TOKEN_CACHE_PATH
from .kis_overseas import (
    KisOverseasBrokerBase,
    KisOverseasPaperBroker,
    KisOverseasLiveBroker,
)
from .kis_domestic import (
    KisDomesticBrokerBase,
    KisDomesticPaperBroker,
    KisDomesticLiveBroker,
)

__all__ = [
    "MockBroker",
    "KisBrokerCommon",
    "KIS_TOKEN_CACHE_PATH",
    "KIS_HTTP_TIMEOUT",
    "KisOverseasBrokerBase",
    "KisOverseasPaperBroker",
    "KisOverseasLiveBroker",
    "KisDomesticBrokerBase",
    "KisDomesticPaperBroker",
    "KisDomesticLiveBroker",
]
