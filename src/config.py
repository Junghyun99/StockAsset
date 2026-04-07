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
        # 멀티 계좌 설정 파일 경로
        self.ACCOUNTS_CONFIG_PATH = os.getenv("ACCOUNTS_CONFIG_PATH", "accounts.yaml")

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
