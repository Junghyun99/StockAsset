import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 티커 → 표시명(alias) 매핑. 국내 종목처럼 티커가 숫자 코드인 경우 등록해 두면
# 로그·대시보드에서 alias가 우선 표시된다. 미등록 티커는 티커 그대로 표시된다.
TICKER_ALIASES: dict[str, str] = {
    # 국내 ETF (yfinance 티커 기준)
    '226490.KS' : 'KODEX 코스피',
    '133690.KS' : 'TIGER 미국나스닥100',
    '365780.KS' : 'ACE 국고채10년',
    '305080.KS' : 'TIGER 미국채10년선물',
    '411060.KS' : 'ACE KRX금현물',
}


def ticker_display(ticker: str) -> str:
    """티커의 표시명을 반환한다. alias가 없으면 티커를 그대로 반환."""
    return TICKER_ALIASES.get(ticker, ticker)


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
