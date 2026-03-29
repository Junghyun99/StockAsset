import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 티커별 거래소 단축 코드 (현재가 조회 API용)
# 새 티커 추가 시 이 딕셔너리만 수정하면 됩니다.
TICKER_EXCHANGE_MAP: dict[str, str] = {
    'SPY': 'AMS',
    'QLD': 'AMS',
    'SSO': 'AMS',
    'IEF': 'NAS',
    'GLD': 'NYS',
    'PDBC': 'NAS',
    'SHV': 'NAS',
    'SDY': 'NYS',
    'QQQ': 'NAS',
    'EEM': 'NYS',
    'TLT': 'NAS',
    'EMB': 'NYS',
    'DBC': 'NYS',
}

# 단축 코드 → 주문/잔고/미체결 API용 전체 코드 변환
EXCHANGE_CODE_SHORT_TO_FULL: dict[str, str] = {
    'NAS': 'NASD',
    'NYS': 'NYSE',
    'AMS': 'AMEX',
}

class Config:
    def __init__(self):  # <--- [중요] 모든 설정 로직을 이 함수 안으로 넣어야 합니다.
        # 1. API 설정 (인스턴스 생성 시점에 환경변수 읽기)
        # 문자열 "True"/"true"를 Python boolean True로 변환
        self.IS_LIVE_TRADING = os.getenv("IS_LIVE_TRADING", "False").lower() == "true"
        # 시장 유형: "overseas" (해외주식, 기본) 또는 "domestic" (국내주식)
        self.MARKET_TYPE = os.getenv("MARKET_TYPE", "overseas").lower()
        
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

        # 4. 저장소 크기 제한
        self.MAX_SUMMARY_RECORDS = 200000  # summary.json 최대 레코드 수
        self.MAX_HISTORY_RECORDS = 100000   # history.json 최대 레코드 수
