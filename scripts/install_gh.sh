#!/usr/bin/env bash
# GitHub CLI (gh) 설치 스크립트
# GitHub Releases에서 최신 바이너리를 직접 다운로드하여 설치합니다.
# 지원 OS: Linux (amd64/arm64), macOS (amd64/arm64)

set -euo pipefail

INSTALL_DIR="/usr/local/bin"
GH_RELEASES_API="https://api.github.com/repos/cli/cli/releases/latest"
GH_DOWNLOAD_BASE="https://github.com/cli/cli/releases/download"

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

already_installed() {
    if command -v gh &>/dev/null; then
        info "gh $(gh --version | head -n1) 이미 설치되어 있습니다."
        exit 0
    fi
}

# GitHub API로 최신 버전 태그 조회 (v2.x.x 형식)
fetch_latest_version() {
    local version
    version="$(curl -fsSL "$GH_RELEASES_API" \
        | grep '"tag_name"' \
        | sed 's/.*"tag_name": *"v\([^"]*\)".*/\1/')"

    if [ -z "$version" ]; then
        error "최신 버전을 가져오지 못했습니다. 네트워크 상태를 확인하세요."
    fi

    echo "$version"
}

# OS / 아키텍처 감지 → gh 릴리즈 파일명 형식에 맞게 변환
detect_platform() {
    local os arch

    case "$(uname -s)" in
        Linux)  os="linux"  ;;
        Darwin) os="macOS"  ;;
        *)      error "지원하지 않는 OS: $(uname -s)" ;;
    esac

    case "$(uname -m)" in
        x86_64|amd64) arch="amd64" ;;
        arm64|aarch64) arch="arm64" ;;
        *)             error "지원하지 않는 아키텍처: $(uname -m)" ;;
    esac

    echo "${os}_${arch}"
}

install_gh() {
    local version platform os ext tmpdir tarball

    version="$(fetch_latest_version)"
    platform="$(detect_platform)"
    os="${platform%%_*}"   # linux 또는 macOS

    # 파일 확장자: macOS → .zip, Linux → .tar.gz
    if [ "$os" = "macOS" ]; then
        ext="zip"
    else
        ext="tar.gz"
    fi

    local filename="gh_${version}_${platform}.${ext}"
    local url="${GH_DOWNLOAD_BASE}/v${version}/${filename}"

    info "최신 버전: v${version}"
    info "다운로드: ${url}"

    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' EXIT

    curl -fsSL "$url" -o "${tmpdir}/${filename}"

    # 압축 해제
    if [ "$ext" = "zip" ]; then
        unzip -q "${tmpdir}/${filename}" -d "$tmpdir"
    else
        tar -xzf "${tmpdir}/${filename}" -C "$tmpdir"
    fi

    # 추출된 디렉토리 안의 bin/gh 를 INSTALL_DIR 로 복사
    local gh_bin
    gh_bin="$(find "$tmpdir" -type f -name "gh" | head -n1)"

    if [ -z "$gh_bin" ]; then
        error "압축 파일 안에서 gh 바이너리를 찾을 수 없습니다."
    fi

    if [ -w "$INSTALL_DIR" ]; then
        cp "$gh_bin" "${INSTALL_DIR}/gh"
        chmod +x "${INSTALL_DIR}/gh"
    else
        sudo cp "$gh_bin" "${INSTALL_DIR}/gh"
        sudo chmod +x "${INSTALL_DIR}/gh"
    fi

    info "gh를 ${INSTALL_DIR}/gh 에 설치했습니다."
}

verify_installation() {
    if command -v gh &>/dev/null; then
        info "설치 완료: $(gh --version | head -n1)"
        info "로그인하려면 'gh auth login' 을 실행하세요."
    else
        error "설치 후에도 gh 명령어를 찾을 수 없습니다. ${INSTALL_DIR} 이 PATH에 포함되어 있는지 확인하세요."
    fi
}

main() {
    already_installed
    install_gh
    verify_installation
}

main "$@"
