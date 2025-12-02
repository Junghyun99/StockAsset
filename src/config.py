# src/config.py
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class Config:
    # 1. 자산군 정의 (하드코딩하지 않고 여기서 관리)
    ASSET_GROUPS = {
        'A': ['SSO', 'QLD'],           # 성장성 (2배 레버리지)
        'B': ['IEF', 'GLD', 'PDBC'],   # 안전성 (국채, 금, 원자재)
        'C': ['SHV']                   # 현금성 (단기채)
    }

    # 2. API 설정
    # 모의투자(False) vs 실전투자(True) 스위치
    IS_LIVE_TRADING = os.getenv("IS_LIVE_TRADING", "False").lower() == "true"
    
    # 한국투자증권
    KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
    KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
    KIS_ACC_NO = os.getenv("KIS_ACC_NO", "") # 계좌번호 (앞 8자리-뒤 2자리)
    
    # 텔레그램
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # 3. 데이터 경로
    DATA_PATH = "docs/data"
    LOG_PATH = "logs"