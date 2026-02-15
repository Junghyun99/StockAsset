---
name: code-improvement
description: 저장소의 열려 있는 이슈 중 중요도가 높은 것을 선택하여 코드를 개선합니다.
allowed-tools:
  - Bash(gh issue list *)
  - Bash(gh issue view *)
  - Bash(gh issue edit *)
  - Bash(gh issue close *)
  - Bash(gh auth status *)
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git add *)
  - Bash(git commit *)
  - Bash(git checkout *)
  - Bash(pytest *)
  - Read
  - Edit
  - Write
  - Grep
  - Glob
argument-hint: "[이슈 번호] (생략 시 가장 중요한 이슈를 자동 선택)"
---

# 코드 개선 (Issue 기반)

저장소의 열려 있는 GitHub 이슈 중 중요도가 높은 것을 하나 선택하고, 이슈 내용을 분석하여 코드를 직접 개선합니다.

## 실행 절차

### 1단계: GitHub 인증 및 이슈 조회

gh cli를 사용하기 위해 환경변수를 설정합니다.

```bash
export GITHUB_TOKEN=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
```

인자로 이슈 번호가 주어진 경우:
- 해당 이슈를 직접 조회합니다: `gh issue view <번호>`

인자가 없는 경우:
- 열려 있는 이슈 목록을 가져옵니다:
```bash
gh issue list --state open --limit 20 --json number,title,labels,createdAt,body
```

### 2단계: 이슈 우선순위 결정

인자가 없는 경우 아래 기준으로 가장 중요한 이슈 하나를 선택합니다:

#### 우선순위 기준 (높은 순)
1. **라벨 기반 우선순위**:
   - `priority: high`, `critical` → 최우선
   - `bug` → 높음
   - `design`, `maintenance` → 보통
   - `enhancement`, `clarification` → 낮음
2. **오래된 이슈 우선**: 생성일이 오래된 이슈에 가중치 부여
3. **심각도 키워드**: 이슈 본문에 "Critical", "심각", "버그", "오류" 등의 키워드가 포함된 경우 가중치 부여

선택한 이슈를 사용자에게 보여주고 진행 여부를 확인합니다:

```
## 선택된 이슈

| 항목 | 내용 |
|------|------|
| 번호 | #N |
| 제목 | 이슈 제목 |
| 라벨 | bug, priority: high |
| 생성일 | YYYY-MM-DD |

### 이슈 내용 요약
{이슈 본문 요약}

이 이슈를 기반으로 코드를 개선하시겠습니까?
```

### 3단계: 이슈 분석 및 영향 범위 파악

선택된 이슈의 본문을 상세히 분석합니다:
- 이슈에 언급된 파일 경로, 함수명, 클래스명을 추출
- Grep/Glob으로 관련 코드 위치를 탐색
- 해당 파일의 전체 내용을 읽어 컨텍스트를 파악
- 관련 테스트 파일이 있는지 확인

### 4단계: 개선 계획 수립

코드 수정 전 개선 계획을 사용자에게 제시합니다:

```
## 개선 계획

### 수정 대상 파일
| # | 파일 | 변경 내용 |
|---|------|----------|
| 1 | src/core/analyzer.py | 경계값 처리 추가 |
| 2 | tests/test_core_logic.py | 테스트 케이스 추가 |

### 수정 방향
- {구체적인 수정 방향 설명}

### 주의사항
- {수정 시 주의할 점}
```

사용자의 승인을 받은 후 다음 단계로 진행합니다.

### 5단계: 코드 개선 실행

승인된 계획에 따라 코드를 수정합니다:

#### 수정 원칙
- **최소 변경 원칙**: 이슈 해결에 필요한 최소한의 변경만 수행
- **아키텍처 준수**: Clean Architecture 규칙 (core → infra 의존 방향) 유지
- **네이밍 규칙**: PascalCase(클래스), snake_case(함수/변수), UPPER_SNAKE_CASE(상수)
- **기존 패턴 유지**: 프로젝트의 기존 코드 스타일과 패턴을 따름
- **.env 파일 수정 금지**: 환경변수 파일은 절대 수정하지 않음

#### 테스트 작성
- 버그 수정 시: 해당 버그를 재현하는 테스트를 먼저 작성
- 기능 개선 시: 새 기능에 대한 테스트를 함께 작성
- 외부 API 호출은 반드시 mock 처리

### 6단계: 테스트 실행 및 검증

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/
```

- 기존 테스트가 모두 통과하는지 확인
- 새로 작성한 테스트가 통과하는지 확인
- 커버리지 80% 이상 유지 확인
- 테스트 실패 시 코드를 수정하고 다시 실행

### 7단계: 결과 보고

## 출력 형식

```
## 코드 개선 결과

### 해결한 이슈
- 이슈: #N - {제목}
- 라벨: {라벨}

### 변경 사항

| # | 파일 | 변경 내용 |
|---|------|----------|
| 1 | src/core/analyzer.py | 경계값 처리 추가 |
| 2 | tests/test_core_logic.py | 테스트 케이스 3개 추가 |

### 테스트 결과
- 전체 테스트: N개 통과
- 커버리지: N%
- 신규 테스트: N개

### 변경 상세
{각 파일별 변경 내용 상세 설명}
```

## 주의사항

- 코드 수정 전 반드시 사용자 승인을 받습니다
- .env 파일은 읽거나 수정하지 않습니다
- 이슈 범위를 넘어서는 추가 리팩토링은 하지 않습니다
- 테스트가 실패하면 코드를 수정하여 통과시킵니다
- 이슈를 자동으로 닫지 않습니다 (사용자가 PR 머지 후 닫도록 안내)
