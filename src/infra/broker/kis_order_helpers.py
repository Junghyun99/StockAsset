# src/infra/broker/kis_order_helpers.py
"""KIS 해외/국내 공용 주문 체결 폴링 헬퍼."""
import time
from typing import Callable, Set


def poll_order_fill(
    get_pending_ids_fn: Callable[[], Set[str]],
    odno: str,
    timeout: int,
    logger,
    log_prefix: str = "[KisBroker]",
) -> bool:
    """미체결 목록에서 해당 ODNO가 사라질 때까지 polling. 체결 여부 반환."""
    start = time.time()
    while (time.time() - start) < timeout:
        try:
            pending_ids = get_pending_ids_fn()
            if odno not in pending_ids:
                return True
        except Exception as e:
            logger.warning(f"{log_prefix} Fill poll error (ODNO={odno}): {e}")
        time.sleep(2)
    return False
