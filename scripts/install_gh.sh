#!/usr/bin/env bash
# GitHub CLI (gh) 설치 스크립트
# 지원 OS: Ubuntu/Debian, Fedora/RHEL/CentOS, macOS, Arch Linux

set -euo pipefail

GH_VERSION="latest"

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

already_installed() {
    if command -v gh &>/dev/null; then
        info "gh $(gh --version | head -n1) 이미 설치되어 있습니다."
        exit 0
    fi
}

install_debian() {
    info "Ubuntu/Debian 환경에서 gh 설치 중..."
    sudo apt-get update -q
    sudo apt-get install -y curl gpg

    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
https://cli.github.com/packages stable main" \
        | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null

    sudo apt-get update -q
    sudo apt-get install -y gh
}

install_fedora() {
    info "Fedora/RHEL/CentOS 환경에서 gh 설치 중..."
    sudo dnf install -y 'dnf-command(config-manager)'
    sudo dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
    sudo dnf install -y gh
}

install_macos() {
    info "macOS 환경에서 gh 설치 중..."
    if ! command -v brew &>/dev/null; then
        error "Homebrew가 설치되어 있지 않습니다. https://brew.sh 를 참고하여 먼저 설치하세요."
    fi
    brew install gh
}

install_arch() {
    info "Arch Linux 환경에서 gh 설치 중..."
    sudo pacman -S --noconfirm github-cli
}

detect_and_install() {
    local os
    os="$(uname -s)"

    case "$os" in
        Darwin)
            install_macos
            ;;
        Linux)
            if [ -f /etc/os-release ]; then
                # shellcheck source=/dev/null
                . /etc/os-release
                case "${ID:-}" in
                    ubuntu|debian|linuxmint|pop)
                        install_debian
                        ;;
                    fedora)
                        install_fedora
                        ;;
                    rhel|centos|rocky|almalinux)
                        install_fedora
                        ;;
                    arch|manjaro)
                        install_arch
                        ;;
                    *)
                        error "지원하지 않는 Linux 배포판입니다: ${ID:-unknown}. 수동으로 설치하세요: https://github.com/cli/cli#installation"
                        ;;
                esac
            else
                error "/etc/os-release 파일을 찾을 수 없습니다. Linux 배포판을 확인할 수 없습니다."
            fi
            ;;
        *)
            error "지원하지 않는 OS입니다: $os"
            ;;
    esac
}

verify_installation() {
    if command -v gh &>/dev/null; then
        info "설치 완료: $(gh --version | head -n1)"
        info "로그인하려면 'gh auth login' 을 실행하세요."
    else
        error "설치 후에도 gh 명령어를 찾을 수 없습니다."
    fi
}

main() {
    already_installed
    detect_and_install
    verify_installation
}

main "$@"
