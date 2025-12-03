import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class Config:
    def __init__(self):  # <--- [중요] 모든 설정 로직을 이 함수 안으로 넣어야 합니다.
        # 1. 자산군 정의
        self.ASSET_GROUPS = {
            'A': ['SSO', 'QLD'],           # 성장성
            'B': ['IEF', 'GLD', 'PDBC'],   # 안전성
            'C': ['SHV']                   # 현금성
        }

        # 2. API 설정 (인스턴스 생성 시점에 환경변수 읽기)
        # 문자열 "True"/"true"를 Python boolean True로 변환
        self.IS_LIVE_TRADING = os.getenv("IS_LIVE_TRADING", "False").lower() == "true"
        
        # 한국투자증권
        self.KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
        self.KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
        self.KIS_ACC_NO = os.getenv("KIS_ACC_NO", "")
        
        # 텔레그램
        # self.TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
        # self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
        self.SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
        
        # 3. 데이터 경로
        self.DATA_PATH = "docs/data"
        self.LOG_PATH = "logs"