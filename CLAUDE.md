# StockAsset - 자동매매 트레이딩 봇

## 프로젝트 개요
시장 국면(Bull/Bear/Crash 등)을 분석하고 변동성 기반으로 포트폴리오를 자동 리밸런싱하는 Python 트레이딩 봇.

## 기술 스택
- Python 3.10
- pandas, yfinance, matplotlib, requests, python-dotenv, PyYAML, pyarrow
- pytest + pytest-cov (테스트)

## 주요 명령어
- 테스트: `.claude/skills/test` 스킬 참조
- 봇 실행: `python src/main.py`
- 의존성 설치: `pip install -r requirements.txt`

## 프로젝트 구조
```
src/
├── main.py              # TradingBot 진입점 (멀티 계정 지원)
├── config.py            # 티커-거래소 매핑
├── strategy_config.py   # 자산 그룹, 리밸런싱 파라미터
├── account_config.py    # accounts.yaml 로더
├── core/
│   ├── engine/          # base, simple, regime, registry
│   ├── logic/           # regime_analyzer, rebalancer, volatility_targeter
│   ├── interfaces.py    # 추상 인터페이스 정의
│   └── models.py        # 도메인 모델 및 Enum
├── infra/
│   ├── broker/          # KIS domestic/overseas/mock 브로커
│   ├── data.py          # YFinanceLoader
│   ├── repo.py          # JsonRepository
│   └── notifier.py      # SlackNotifier
├── utils/               # IndicatorCalculator, TradeLogger
└── backtest/            # 백테스트 프레임워크 (runner, components, cache, fetcher)
tests/                   # 테스트 (80% 커버리지 요구)
docs/                    # 웹 대시보드 및 데이터 저장
accounts.yaml            # 멀티 계정 설정 (accounts.yaml.example 참고)
```

## 아키텍처 규칙
- Clean Architecture 패턴: core(도메인) → infra(인프라) 방향으로 의존
- core/interfaces.py에 정의된 추상 인터페이스를 통해 의존성 주입
- 백테스트는 프로덕션 로직을 100% 재사용 (코드 분기 없음)
- 엔진 레지스트리 패턴: `@register_engine` 데코레이터로 엔진 등록
- 멀티 계정: accounts.yaml → AccountConfig → 계정별 엔진 인스턴스 생성

## 자산 그룹 (strategy_config.py 기준 기본값)
- A (성장): SSO, QLD (레버리지 ETF)
- B (안전): IEF, GLD, DBC (채권, 금, 원자재)
- C (현금): SHV (단기 국채)

## 환경변수 (.env)
- `ACCOUNTS_CONFIG_PATH` - accounts.yaml 경로 (기본값: "accounts.yaml")
- `{PREFIX}_KIS_APP_KEY`, `{PREFIX}_KIS_APP_SECRET`, `{PREFIX}_KIS_ACC_NO` - 계정별 KIS API 인증 (PREFIX는 accounts.yaml의 kis_env_prefix 값)
- `SLACK_WEBHOOK_URL` - Slack 알림
- `KIS_HTTP_TIMEOUT` - KIS REST 호출 타임아웃(초) (기본값: 10)
- `TRADING_INTERVAL_DAYS` - 리밸런싱 주기, 거래일 기준 (기본값: 1)
- `REBALANCE_RATIO_A` - A 그룹 비율 (기본값: 0.5)

## 멀티 계정 설정 (accounts.yaml)
각 계정 항목:
- `id` - 계정 식별자
- `market_type` - "domestic" 또는 "overseas"
- `is_live` - 실거래 여부 (true/false)
- `engine` - 사용할 엔진 이름 (레지스트리 키)
- `kis_env_prefix` - 환경변수 prefix (예: "ACC1" → `ACC1_KIS_APP_KEY`)

## CI/CD
GitHub Actions 워크플로우 6개:
- `python-test.yml` - main 브랜치 Push/PR 시 단위 테스트 (80% 커버리지 필수)
- `broker-live-test.yml` - 수동 실행: KIS 브로커 라이브 API 테스트
- `download-data.yml` - 수동 실행: 백테스트용 시장 데이터 다운로드
- `gdrive-sync.yml` - main Push 또는 수동: Google Drive 백업
- `run-compare-backtest.yml` - 수동 실행: 전략 엔진 비교 백테스트
- `live-trading-domestic.yml` - 평일 KST 10:00 스케줄 + 수동 실행: 국내 계정 라이브 실거래. 한국 공휴일 자동 스킵, 실행 후 docs/data/**/*.json 자동 커밋

테스트 시 `test_infra_broker_kis_domestic_live.py`는 CI에서 제외됨.

## 프론트엔드 정적 파일 버전 관리
JS/CSS 파일을 HTML에서 로드할 때 `?v=YYYYMMDD-N` 쿼리스트링으로 브라우저 캐시를 무효화한다.
- `YYYYMMDD` — 수정 날짜, `N` — 당일 수정 순번 (1부터 시작)
- JS/CSS 수정 시 해당 파일을 참조하는 **모든 HTML**의 `?v=` 값을 함께 갱신한다
- 파일마다 독립 버전 관리 (수정한 파일만 갱신)
- 같은 날 두 번째 수정은 순번만 증가시킨다 (`20260618-1` → `20260618-2`)
- `?v=` 갱신 없이 내용만 바꾸면 사용자가 캐시된 구버전을 볼 수 있으므로 반드시 HTML의 버전도 함께 변경하여 커밋한다
- **ESM(`type="module"`) 사용 시 주의**: 진입 스크립트의 `?v=` 변경으로 `import`된 하위 모듈 캐시는 무효화되지 않는다. ESM 프로젝트는 번들러의 콘텐츠 해시(`[contenthash]`) 방식을 사용해야 한다.

## 주의사항
- .env 파일은 절대 커밋하지 않을 것
- accounts.yaml에는 민감 정보를 넣지 말 것 (KIS 키/계좌번호는 GitHub Secrets의 `{PREFIX}_KIS_*` 환경변수로만 주입)
- 실거래 여부는 accounts.yaml의 `is_live` 필드로 계정별 설정
- 매도 주문을 먼저 실행한 후 매수 진행 (자금 부족 방지)
- YFinance API 실패 시 VIX 기본값 20.0 적용
- 코드 편집할때는 반드시 파일을 먼저 읽어라
