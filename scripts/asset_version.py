"""docs/ 정적 자산(JS/CSS) 캐시버스팅 버전 토큰 공용 로직.

ESM 모듈 캐시 키는 쿼리스트링을 포함한 URL 전체다. 따라서 같은 모듈을 서로 다른
`?v=`로 import하면 브라우저가 **별개의 모듈 인스턴스**를 만들고, 모듈 최상위에
선언된 공유 상태(ACCOUNT_ENGINE_NAMES 등)가 갈라진다.

이를 막기 위해 이 프로젝트는 **전역 단일 토큰** 규칙을 쓴다:
docs/ 안의 모든 `?v=` 값은 항상 같아야 한다.

- 검사: python -m scripts.asset_version --check
- 일괄 갱신: python -m scripts.asset_version --bump [YYYYMMDD-N]
"""
import argparse
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# js/main.js?v=20260731-1, ./utils.js?v=20260731-1 등에서 (모듈경로, 토큰)을 뽑는다
_ASSET_REF = re.compile(r"""([\w./-]+\.(?:js|css))\?v=([0-9]{8}-[0-9]+)""")

# 스캔 대상: docs 직하위 HTML + js 디렉토리. data/ 등 산출물은 제외한다.
_SCAN_GLOBS = ("*.html", "js/*.js", "css/*.css")


def _scan_files(docs_dir: Path = DOCS_DIR):
    for pattern in _SCAN_GLOBS:
        yield from sorted(docs_dir.glob(pattern))


def collect_references(docs_dir: Path = DOCS_DIR) -> dict:
    """{모듈 basename: {토큰: [참조 위치 문자열, ...]}} 형태로 수집."""
    refs = defaultdict(lambda: defaultdict(list))
    for path in _scan_files(docs_dir):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for module, token in _ASSET_REF.findall(line):
                name = module.rsplit("/", 1)[-1]
                rel = path.relative_to(docs_dir.parent)
                refs[name][token].append(f"{rel}:{lineno}")
    return refs


def find_violations(docs_dir: Path = DOCS_DIR) -> list:
    """전역 단일 토큰 규칙 위반 목록을 반환한다. 정상이면 빈 리스트."""
    refs = collect_references(docs_dir)
    tokens = {t for by_token in refs.values() for t in by_token}
    if len(tokens) <= 1:
        return []

    violations = []
    for name, by_token in sorted(refs.items()):
        if len(by_token) > 1:
            detail = "; ".join(
                f"{token} ({', '.join(sites)})" for token, sites in sorted(by_token.items())
            )
            violations.append(
                f"{name}: 서로 다른 ?v= 로 참조됨 -> {detail}. "
                f"ESM 모듈이 중복 인스턴스화되어 공유 상태가 갈라진다."
            )

    if not violations:
        violations.append(
            "docs/ 전역 ?v= 토큰이 하나가 아니다: "
            + ", ".join(sorted(tokens))
            + ". `python -m scripts.asset_version --bump` 로 통일할 것."
        )
    return violations


def bump(new_token: str = None, docs_dir: Path = DOCS_DIR) -> tuple:
    """docs/ 안의 모든 ?v= 토큰을 new_token으로 일괄 교체한다."""
    if new_token is None:
        new_token = f"{date.today():%Y%m%d}-1"
    if not re.fullmatch(r"[0-9]{8}-[0-9]+", new_token):
        raise ValueError(f"토큰 형식은 YYYYMMDD-N 이어야 한다: {new_token}")

    changed = []
    for path in _scan_files(docs_dir):
        original = path.read_text(encoding="utf-8")
        updated = _ASSET_REF.sub(lambda m: f"{m.group(1)}?v={new_token}", original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(str(path.relative_to(docs_dir.parent)))
    return new_token, changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="토큰 일관성 검사")
    group.add_argument("--bump", nargs="?", const="", metavar="YYYYMMDD-N",
                       help="전 참조 토큰 일괄 갱신 (생략 시 오늘 날짜-1)")
    args = parser.parse_args(argv)

    if args.check:
        violations = find_violations()
        if violations:
            print("정적 자산 버전 토큰 규칙 위반:", file=sys.stderr)
            for v in violations:
                print(f"  - {v}", file=sys.stderr)
            return 1
        print("OK: docs/ 정적 자산 ?v= 토큰이 전역 단일 값이다.")
        return 0

    token, changed = bump(args.bump or None)
    print(f"토큰 -> {token} ({len(changed)}개 파일 갱신)")
    for c in changed:
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
