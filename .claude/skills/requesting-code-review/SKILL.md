---
name: requesting-code-review
description: Use when completing tasks, implementing major features, or before merging - supports quick self-review and full subagent-based review
---

# Requesting Code Review

Dispatch superpowers:code-reviewer subagent to catch issues before they cascade.

**Core principle:** Review early, review often.

## 빠른 자체 리뷰 (Quick Self-Review)

서브에이전트 없이 직접 수행하는 빠른 리뷰입니다. 작은 변경이나 전체 리뷰 전 사전 점검에 사용합니다.

**읽기 전용 — 코드를 직접 수정하지 않습니다.**

### 실행 절차

1. `git diff`로 변경 사항 수집 (스테이징/언스테이징 모두)
2. 인자가 있으면 해당 브랜치 대비, 없으면 main 대비 diff 확인
3. 각 변경 파일을 읽고 아래 체크리스트 점검

### 리뷰 체크리스트

#### 버그 및 로직 오류
- 경계값 처리 누락 (off-by-one, None 체크, 빈 리스트 등)
- 잘못된 조건문, 무한 루프 가능성
- 타입 불일치, 잘못된 반환값

#### 보안
- 하드코딩된 비밀번호, API 키, 토큰
- .env 파일이 커밋에 포함되지 않았는지 확인
- SQL 인젝션, 커맨드 인젝션 가능성

#### 아키텍처 규칙 준수
- **core/ → infra/ 의존 방향**: core 모듈이 infra를 import하지 않는지 확인
- **인터페이스 사용**: `core/interfaces.py`에 정의된 추상 인터페이스를 통해 의존성 주입이 되는지 확인
- 백테스트가 프로덕션 로직을 재사용하는지 확인 (코드 분기 없음)

#### 코드 스타일
- 클래스: PascalCase, 함수/변수: snake_case, 상수: UPPER_SNAKE_CASE
- Python 3.10 호환성
- 타입 힌트 사용 여부

#### 테스트
- 새로운 기능에 대한 테스트가 추가되었는지 확인
- 외부 API 호출이 mock 처리되었는지 확인
- 테스트가 `tests/` 디렉토리에 `test_*.py` 형식으로 작성되었는지 확인

### 결과 출력 형식

```
## 코드 리뷰 결과

### 요약
- 변경 파일: N개
- 발견된 이슈: N개 (심각: N, 경고: N, 제안: N)

### 이슈 목록

#### [심각] 파일명:라인번호 - 이슈 제목
설명과 수정 제안

#### [경고] 파일명:라인번호 - 이슈 제목
설명과 수정 제안

#### [제안] 파일명:라인번호 - 이슈 제목
설명과 수정 제안

### 잘된 점
- 긍정적인 피드백
```

**더 깊은 리뷰가 필요하면** 아래 Full Subagent Review를 진행하세요.

## When to Request Review

**Mandatory:**
- After each task in subagent-driven development
- After completing major feature
- Before merge to main

**Optional but valuable:**
- Quick self-review for small changes (see 빠른 자체 리뷰 above)
- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing complex bug

## How to Request

**1. Get git SHAs:**
```bash
BASE_SHA=$(git rev-parse HEAD~1)  # or origin/main
HEAD_SHA=$(git rev-parse HEAD)
```

**2. Dispatch code-reviewer subagent:**

Use Task tool with superpowers:code-reviewer type, fill template at `code-reviewer.md`

**Placeholders:**
- `{WHAT_WAS_IMPLEMENTED}` - What you just built
- `{PLAN_OR_REQUIREMENTS}` - What it should do
- `{BASE_SHA}` - Starting commit
- `{HEAD_SHA}` - Ending commit
- `{DESCRIPTION}` - Brief summary

**3. Act on feedback:**
- Fix Critical issues immediately
- Fix Important issues before proceeding
- Note Minor issues for later
- Push back if reviewer is wrong (with reasoning)

## Example

```
[Just completed Task 2: Add verification function]

You: Let me request code review before proceeding.

BASE_SHA=$(git log --oneline | grep "Task 1" | head -1 | awk '{print $1}')
HEAD_SHA=$(git rev-parse HEAD)

[Dispatch superpowers:code-reviewer subagent]
  WHAT_WAS_IMPLEMENTED: Verification and repair functions for conversation index
  PLAN_OR_REQUIREMENTS: Task 2 from docs/plans/deployment-plan.md
  BASE_SHA: a7981ec
  HEAD_SHA: 3df7661
  DESCRIPTION: Added verifyIndex() and repairIndex() with 4 issue types

[Subagent returns]:
  Strengths: Clean architecture, real tests
  Issues:
    Important: Missing progress indicators
    Minor: Magic number (100) for reporting interval
  Assessment: Ready to proceed

You: [Fix progress indicators]
[Continue to Task 3]
```

## Integration with Workflows

**Subagent-Driven Development:**
- Review after EACH task
- Catch issues before they compound
- Fix before moving to next task

**Executing Plans:**
- Review after each batch (3 tasks)
- Get feedback, apply, continue

**Ad-Hoc Development:**
- Review before merge
- Review when stuck

## Red Flags

**Never:**
- Skip review because "it's simple"
- Ignore Critical issues
- Proceed with unfixed Important issues
- Argue with valid technical feedback

**If reviewer wrong:**
- Push back with technical reasoning
- Show code/tests that prove it works
- Request clarification

See template at: requesting-code-review/code-reviewer.md
