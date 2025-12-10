# src/utils/logger.py
import logging
import os
from datetime import datetime

class TradeLogger:
    def __init__(self, log_dir: str = "logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.log_file = os.path.join(log_dir, f"{datetime.now().strftime('%Y-%m-%d')}.log")
        
        self.logger = logging.getLogger("SolidQuant")
        self.logger.setLevel(logging.INFO)
        
        # 중복 핸들러 방지
        if not self.logger.handlers:
            # 1. 파일 핸들러
            fh = logging.FileHandler(self.log_file, encoding='utf-8')
            fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
            self.logger.addHandler(fh)
            
            # 2. 콘솔 핸들러 (GitHub Actions 로그용)
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            self.logger.addHandler(ch)

    def info(self, msg: Any):
        self.logger.info(f"{msg}")

    def warning(self, msg: Any):
        self.logger.warning(f"{msg}")

    def error(self, msg: Any):
        self.logger.error(f"{msg}")