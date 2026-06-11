# src/utils/logger.py
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from src.core.interfaces import ILogger

KST = timezone(timedelta(hours=9))


class _KSTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=KST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S') + f',{int(record.msecs):03d}'


class TradeLogger(ILogger):
    def __init__(self, log_dir: str = "logs", run_number: str | None = None):
        os.makedirs(log_dir, exist_ok=True)
        suffix = f"_run{run_number}" if run_number else ""
        self.log_file = os.path.join(log_dir, f"{datetime.now(KST).strftime('%Y-%m-%d')}{suffix}.log")

        # 파일별로 독립된 로거 사용 (글로벌 싱글턴 충돌 방지)
        logger_name = f"SolidQuant.{os.path.abspath(self.log_file)}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            fh = logging.FileHandler(self.log_file, encoding='utf-8')
            fh.setFormatter(_KSTFormatter('%(asctime)s [%(levelname)s] %(message)s'))
            self.logger.addHandler(fh)

        # 콘솔 핸들러는 부모 로거에 단 하나만 유지 (여러 파일 로거 생성 시 중복 방지)
        parent = logging.getLogger("SolidQuant")
        if not parent.handlers:
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            parent.addHandler(ch)

        # 슬랙 댓글용 로그 캡처 버퍼. 사이클 시작 시 clear되어 한 사이클 분량만 유지한다.
        self.captured_logs: List[Dict[str, Any]] = []
        self.current_ticker: Optional[str] = None

    def set_ticker_context(self, ticker: Optional[str]) -> None:
        """이후 캡처되는 로그의 소유 종목을 태깅한다 (ticker=None은 공통 영역)."""
        self.current_ticker = ticker

    def get_captured_logs(self, ticker: Optional[str] = None) -> List[str]:
        """캡처된 로그 메시지 목록을 반환한다.

        ticker 지정 시 해당 종목 로그만, None이면 전체 로그를 반환한다.
        """
        if ticker:
            return [item["msg"] for item in self.captured_logs if item["ticker"] == ticker]
        return [item["msg"] for item in self.captured_logs]

    def clear_captured_logs(self) -> None:
        self.captured_logs = []

    def _capture(self, level: str, msg: Any) -> None:
        self.captured_logs.append({
            "ticker": self.current_ticker,
            "level": level,
            "msg": f"{msg}",
        })

    def debug(self, msg: str) -> None:
        self.logger.debug(msg)
        # Debug 로그는 양이 많아 캡처 대상에서 제외

    def info(self, msg: Any):
        self.logger.info(f"{msg}")
        self._capture("INFO", msg)

    def warning(self, msg: Any):
        self.logger.warning(f"{msg}")
        self._capture("WARNING", msg)

    def error(self, msg: Any):
        self.logger.error(f"{msg}")
        self._capture("ERROR", msg)
