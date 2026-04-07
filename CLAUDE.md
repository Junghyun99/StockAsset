# StockAsset - 자동매매 트레이딩 봇

## 프로젝트 개요
시장 국면(Bull/Bear/Crash 등)을 분석하고 변동성 기반으로 포트폴리오를 자동 리밸런싱하는 Python 트레이딩 봇.

## 기술 스택
- Python 3.10
- pandas, yfinance, matplotlib, requests, python-dotenv
- pytest + pytest-cov (테스트)

## 주요 명령어
- 테스트: '.claude/skills/test' 스킬 참조
- 봇 실행: `python src/main.py`
- 의존성 설치: `pip install -r requirements.txt`

## 프로젝트 구조
```
src/
├── main.py          # TradingBot 진입점
├── config.py        # 환경변수 및 자산 그룹 설정
├── core/            # 도메인 로직 (RegimeAnalyzer, VolatilityTargeter, Rebalancer)
├── infra/           # 외부 연동 (YFinance, MockBroker/KisBroker, Slack/Telegram, JSON 저장)
├── utils/           # 유틸리티 (IndicatorCalculator, TradeLogger)
└── backtest/        # 백테스트 프레임워크
tests/               # 테스트 (80% 커버리지 요구)
docs/                # 웹 대시보드 및 데이터 저장
```

## 아키텍처 규칙
- Clean Architecture 패턴: core(도메인) → infra(인프라) 방향으로 의존
- core/interfaces.py에 정의된 추상 인터페이스를 통해 의존성 주입
- 백테스트는 프로덕션 로직을 100% 재사용 (코드 분기 없음)

## 자산 그룹
- A (성장): SSO, QLD (레버리지 ETF)
- B (안전): IEF, GLD, PDBC (채권, 금, 원자재)
- C (현금): SHV (단기 국채)

## 환경변수 (.env)
- `IS_LIVE_TRADING` - 실거래 활성화 여부
- `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACC_NO` - 한국투자증권 API
- `SLACK_WEBHOOK_URL` - Slack 알림

## CI/CD
- GitHub Actions: main 브랜치 push/PR 시 자동 테스트
- 80% 코드 커버리지 필수
- 테스트 실패 시 Slack 알림

## 주의사항
- .env 파일은 절대 커밋하지 않을 것
- 매도 주문을 먼저 실행한 후 매수 진행 (자금 부족 방지)
- YFinance API 실패 시 VIX 기본값 20.0 적용
- 코드 편집할때는 반드시 파일을 먼저 읽어라
