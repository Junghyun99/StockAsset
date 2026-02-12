# 서브에이전트(스킬) 설계 검토

## 현재 상태

### 기존 스킬 (2개)

| 스킬 | 설명 | 허용 도구 |
|------|------|-----------|
| `/review` | 코드 리뷰 (git diff 기반, 읽기 전용) | `Bash(git *)`, Read, Grep, Glob |
| `/test` | 테스트 실행 및 커버리지 분석 | `Bash(pip install *)`, `Bash(pytest *)`, Read, Grep, Glob |

### 현재 커버되지 않는 영역

1. **백테스트 실행** - `runner.py`가 있지만 스킬로 연동되지 않음
2. **아키텍처 검증** - `/review`에 포함되어 있으나 독립 실행 불가
3. **보안 점검** - `/review`에 부분 포함, 전체 코드베이스 대상 스캔 없음
4. **커버리지 갭 분석** - `/test`가 결과만 보여주고, 누락 테스트 자동 작성은 안 함

---

## 추천 스킬 목록

### 1. `/backtest` - 백테스트 실행 및 분석 (우선순위: 높음)

**근거**: 프로젝트의 핵심 기능인 백테스트(`src/backtest/runner.py`)가 이미 구현되어 있지만, CLI에서 쉽게 실행하고 결과를 분석하는 워크플로우가 없음. 트레이딩 봇에서 전략 검증은 반복적으로 수행하는 작업이므로 스킬로 만들 가치가 높음.

**범위**:
- 날짜 범위, 초기 자본 등 파라미터를 받아 백테스트 실행
- 결과 지표 분석 (CAGR, MDD, 샤프비율 등)
- 국면별(Bull/Bear/Crash) 성과 분석
- 에러 발생 시 원인 분석

**SKILL.md 설계안**:

```yaml
---
name: backtest
description: 백테스트를 실행하고 전략 성과를 분석합니다.
argument-hint: "[start-date] [end-date] (예: 2020-01-01 2023-12-31)"
allowed-tools: Bash(pip install *), Bash(python *), Read, Grep, Glob
---
```

**실행 절차**:
1. 의존성 설치
2. 인자 파싱 (기본값: 최근 3년)
3. `python -c "from src.backtest.runner import run_backtest; run_backtest('start', 'end')"` 실행
4. 출력 결과에서 수익률, CAGR 추출
5. 에러 시 `runner.py`, `components.py` 분석 후 원인 보고

**예상 효과**: 전략 파라미터를 수정한 뒤 `/backtest 2020-01-01 2024-12-31`로 즉시 검증 가능

---

### 2. `/arch-check` - 아키텍처 규칙 검증 (우선순위: 중간)

**근거**: Clean Architecture의 핵심 규칙(core → infra 의존 방향)을 위반하면 백테스트와 프로덕션 로직의 재사용성이 깨짐. `/review`에 포함되어 있지만 변경 사항이 없어도 전체 코드베이스를 대상으로 검증해야 할 때가 있음.

**범위**:
- `core/`에서 `infra/`로의 import 탐지
- `interfaces.py`의 추상 메서드가 infra에서 구현되었는지 확인
- 백테스트 코드가 core 로직을 직접 import하는지 (분기 없이 재사용)
- 순환 의존성 탐지

**SKILL.md 설계안**:

```yaml
---
name: arch-check
description: Clean Architecture 규칙 준수 여부를 검증합니다. core→infra 의존 방향, 인터페이스 구현 등을 점검합니다.
allowed-tools: Read, Grep, Glob
---
```

**실행 절차**:
1. `src/core/` 파일에서 `from src.infra` 또는 `import src.infra` 패턴 검색
2. `interfaces.py`의 ABC 클래스 목록과 `infra/`의 구현체 매칭
3. `backtest/`에서 core 로직 직접 사용 여부 확인
4. 위반 사항을 심각도별로 분류하여 보고

**예상 효과**: 리팩토링 후 아키텍처 무결성을 빠르게 확인. CI pre-commit hook과 연동 가능.

---

### 3. `/security-audit` - 보안 점검 (우선순위: 중간)

**근거**: 트레이딩 봇은 증권사 API 키(`KIS_APP_KEY`, `KIS_APP_SECRET`), 계좌번호(`KIS_ACC_NO`), 웹훅 URL 등 민감 정보를 다룸. 현재 `.env`를 deny로 보호하고 있지만, 코드 내 하드코딩이나 로그 유출을 전체 대상으로 검사하는 수단이 없음.

**범위**:
- 전체 코드베이스에서 하드코딩된 시크릿 패턴 탐지 (API 키, 토큰, URL 등)
- `.gitignore`에 `.env` 포함 여부 확인
- 로그 출력에 민감 정보가 포함되는지 확인
- `requests` 호출에서 HTTPS 사용 여부
- `broker.py`의 인증 토큰 처리 방식 검토

**SKILL.md 설계안**:

```yaml
---
name: security-audit
description: 코드베이스의 보안 취약점을 점검합니다. 시크릿 유출, 인증 처리, API 보안 등을 검사합니다.
allowed-tools: Read, Grep, Glob
---
```

**예상 효과**: 배포 전 보안 체크리스트로 활용. `.env` 실수 커밋 방지.

---

### 4. `/coverage-gap` - 커버리지 갭 분석 및 테스트 제안 (우선순위: 낮음)

**근거**: `/test`는 커버리지 결과를 보여주지만, 누락된 라인에 대해 어떤 테스트를 작성해야 하는지까지는 제안하지 않음. 다만, 이 기능은 `/test` 스킬을 확장하는 것이 더 자연스러울 수 있음.

**대안**: `/test` 스킬의 "커버리지 부족 시" 섹션을 강화하여, 누락 라인을 분석하고 테스트 코드 골격까지 생성하도록 확장.

**별도 스킬이 필요한 경우**:
- 특정 모듈만 집중적으로 커버리지를 올리고 싶을 때
- 테스트 작성이 필요하므로 Write 권한이 필요 (기존 `/test`에는 없음)

```yaml
---
name: coverage-gap
description: 테스트 커버리지가 부족한 영역을 분석하고 테스트 코드를 생성합니다.
argument-hint: "[module-path] (예: src/core/logic.py)"
allowed-tools: Bash(pytest *), Read, Grep, Glob, Write
---
```

---

## 추천하지 않는 스킬

| 스킬 아이디어 | 불필요한 이유 |
|---------------|--------------|
| `/deploy` 또는 `/run` | 실행 명령이 `python src/main.py` 한 줄. 스킬로 만들 복잡도가 없음. settings.json에 이미 허용됨 |
| `/docs` | 문서 생성은 일회성 작업. 반복 워크플로우가 아님 |
| `/refactor` | 범위가 너무 넓고 모호함. 메인 Claude 세션에서 직접 요청하는 것이 더 효과적 |
| `/deps` | pip 기반 단순 프로젝트에서 의존성 관리 스킬은 과잉 |
| `/lint` | Python 린터(flake8, ruff 등)가 설정되어 있지 않음. 린터 도입이 선행되어야 함 |

---

## 구현 우선순위 및 로드맵

```
Phase 1: /backtest (핵심 가치 - 전략 검증 자동화)
Phase 2: /arch-check (아키텍처 보호 - 리팩토링 안전망)
Phase 3: /security-audit (보안 강화 - 배포 전 필수 점검)
Phase 4: /test 확장 또는 /coverage-gap (테스트 품질 향상)
```

---

## 설계 시 고려사항

### allowed-tools 최소 권한 원칙

각 스킬에는 필요한 최소한의 도구만 부여:
- **읽기 전용** 분석 스킬 (`/arch-check`, `/security-audit`): `Read, Grep, Glob`만 허용
- **실행이 필요한** 스킬 (`/backtest`, `/test`): 특정 Bash 패턴만 허용
- **코드 작성** 스킬 (`/coverage-gap`): `Write` 추가 필요

### settings.json 업데이트 필요

`/backtest` 스킬 추가 시 settings.json에 `Bash(python -c *)` 또는 `Bash(python src/backtest/*)` 허용 추가 필요.

### 스킬 vs 메인 세션 판단 기준

| 스킬로 만들어야 할 때 | 메인 세션이 나을 때 |
|----------------------|-------------------|
| 반복적으로 실행하는 워크플로우 | 일회성 분석이나 탐색 |
| 입출력 형식이 명확한 작업 | 범위가 넓고 유동적인 작업 |
| 도구 접근 제한이 필요한 작업 | 전체 도구 접근이 필요한 작업 |
| 매번 같은 절차를 거치는 작업 | 맥락에 따라 접근이 달라지는 작업 |
