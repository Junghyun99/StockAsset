# src/utils/logger.py
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any
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

    def debug(self, msg: str) -> None:
        self.logger.debug(msg)

    def info(self, msg: Any):
        self.logger.info(f"{msg}")

    def warning(self, msg: Any):
        self.logger.warning(f"{msg}")

    def error(self, msg: Any):
        self.logger.error(f"{msg}")
