#!/bin/bash
set -euo pipefail

# 원격 환경(Claude Code on the web)에서만 실행
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Resume 감지: transcript_path 파일에 내용이 있으면 이미 진행 중인 세션
session_info=$(cat 2>/dev/null || true)
transcript_path=""
if [ -n "$session_info" ]; then
  transcript_path=$(printf '%s' "$session_info" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('transcript_path',''))" \
    2>/dev/null || true)
fi
if [ -n "$transcript_path" ] && [ -f "$transcript_path" ] && [ -s "$transcript_path" ]; then
  echo "SessionStart: Resume 감지 - 초기화 건너뜀" >&2
  exit 0
fi

echo "SessionStart: 초기 설치 시작..." >&2

# gh CLI 설치 (없는 경우)
if ! command -v gh &>/dev/null; then
  echo "gh CLI 설치 중..." >&2
  if command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y -qq gh 2>/dev/null || {
      # apt에 없으면 GitHub releases에서 직접 설치
      GH_VERSION=$(curl -sL https://api.github.com/repos/cli/cli/releases/latest \
        | grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/') || GH_VERSION="2.45.0"
      curl -sL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
        | tar -xz -C /tmp
      install -m 755 "/tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh
    }
  fi
  if command -v gh &>/dev/null; then
    echo "gh CLI 설치 완료 ($(gh --version | head -1))" >&2
  else
    echo "WARNING: gh CLI 설치 실패 - 일부 기능 제한될 수 있음" >&2
  fi
fi

# Python 의존성 설치
if [ -f "${CLAUDE_PROJECT_DIR}/requirements.txt" ]; then
  echo "Python 패키지 설치 중..." >&2
  python3 -m pip install -q --prefer-binary -r "${CLAUDE_PROJECT_DIR}/requirements.txt"
  echo "Python 패키지 설치 완료" >&2
fi

echo "SessionStart: 초기 설치 완료" >&2
