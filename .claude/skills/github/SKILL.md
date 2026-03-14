---
name: github
description: GitHub 이슈 등록, 이슈 조회, PR 생성 등 GitHub 작업이 필요할 때 사용합니다. gh CLI를 사용하는 모든 GitHub 상호작용에 적용합니다.
argument-hint: "[action] (예: create-issue, list-issues, create-pr)"
allowed-tools: Bash(gh *)
---

# GitHub 작업 (gh CLI)

`gh` CLI를 사용하여 GitHub 이슈, PR, 릴리즈 등을 관리하는 스킬입니다.

## 사전 확인

```bash
gh auth status          # 인증 상태 확인
gh repo view            # 현재 리포지토리 확인
```

> **이 환경 주의사항:** git remote가 로컬 프록시(`127.0.0.1`)를 통해 GitHub에 연결되므로,
> `gh` 명령 실행 시 아래 환경변수와 `--repo` 플래그가 필요합니다:
> ```bash
> GH_HOST=github.com gh <command> --repo Junghyun99/StockAsset
> ```

---

## 이슈(Issue)

### 이슈 목록 조회
```bash
gh issue list                          # 열린 이슈 목록
gh issue list --state closed           # 닫힌 이슈
gh issue list --label "bug"            # 라벨 필터
gh issue list --assignee "@me"         # 내 이슈
gh issue list --limit 20               # 개수 제한
```

### 이슈 상세 조회
```bash
gh issue view 42                       # 이슈 #42 상세
gh issue view 42 --comments            # 댓글 포함
```

### 이슈 등록
```bash
gh issue create \
  --title "버그: 로그인 실패 오류" \
  --body "재현 방법: ..." \
  --label "bug" \
  --assignee "@me"
```

멀티라인 본문은 HEREDOC 사용:
```bash
gh issue create \
  --title "제목" \
  --body "$(cat <<'EOF'
## 문제 설명
상세 내용

## 재현 방법
1. 단계1
2. 단계2

## 기대 결과
...
EOF
)"
```

### 이슈 수정 / 닫기
```bash
gh issue edit 42 --title "새 제목" --add-label "enhancement"
gh issue close 42
gh issue close 42 --comment "수정 완료"
```

---

## PR (Pull Request)

### PR 목록 조회
```bash
gh pr list                             # 열린 PR
gh pr list --state merged              # 머지된 PR
gh pr list --author "@me"             # 내 PR
gh pr view 10                          # PR #10 상세
gh pr view 10 --comments               # 댓글 포함
```

### PR 생성
```bash
gh pr create \
  --title "feat: 로그인 기능 추가" \
  --body "$(cat <<'EOF'
## Summary
- 변경 사항 요약

## Test plan
- [ ] 단위 테스트 통과
- [ ] 수동 테스트 확인
EOF
)" \
  --base main \
  --head feature/login
```

### PR 머지 / 닫기
```bash
gh pr merge 10 --squash              # squash merge
gh pr merge 10 --merge               # merge commit
gh pr merge 10 --rebase              # rebase
gh pr close 10
```

### PR 체크아웃
```bash
gh pr checkout 10                    # PR 브랜치 로컬 체크아웃
```

---

## 릴리즈(Release)

```bash
gh release list                      # 릴리즈 목록
gh release view v1.0.0               # 특정 릴리즈
gh release create v1.0.0 \
  --title "v1.0.0" \
  --notes "변경 사항..."
```

---

## 워크플로우 / Actions

```bash
gh run list                          # 최근 CI 실행 목록
gh run view 123456                   # 특정 실행 상세
gh run view 123456 --log             # 로그 확인
gh workflow list                     # 워크플로우 목록
gh workflow run deploy.yml           # 수동 트리거
```

---

## 유용한 패턴

### 현재 브랜치로 빠른 PR 생성
```bash
git push -u origin HEAD
gh pr create --fill                  # 커밋 메시지로 자동 채움
```

### 이슈 번호를 PR에 연결
PR 본문에 `Closes #42` 또는 `Fixes #42` 포함 → 머지 시 이슈 자동 닫힘

### API 직접 호출 (gh api)
```bash
gh api repos/{owner}/{repo}/issues   # REST API
gh api graphql -f query='{ viewer { login } }'  # GraphQL
```

## 주의사항
- `gh pr merge` 전에 CI 상태 확인: `gh pr checks 10`
- force push나 브랜치 삭제 같은 파괴적 작업은 사용자 확인 후 진행
- `--fill` 플래그는 커밋 메시지를 그대로 사용하므로 내용 검토 필요
