"""docs/ 정적 자산 캐시버스팅 토큰 일관성 회귀 테스트.

배경: strategy-view.js가 `utils.js?v=20260727-1`로, main.js가 `utils.js?v=20260723-1`로
import한 탓에 브라우저가 utils.js를 두 번 평가했고, main.js가 loadAccountsMeta()로 채운
ACCOUNT_ENGINE_NAMES를 strategy-view.js가 볼 수 없어 전략 탭이 모든 계좌에서
"지원하지 않습니다"로 렌더링됐다. ESM 모듈 캐시 키가 쿼리스트링을 포함하기 때문이다.
"""
from scripts.asset_version import bump, collect_references, find_violations


def test_docs_자산_버전_토큰이_전역_단일값():
    violations = find_violations()
    assert violations == [], "\n".join(violations)


def test_utils_js는_단일_토큰으로만_import된다():
    """공유 상태(ACCOUNT_ENGINE_NAMES 등)를 가진 모듈이라 중복 인스턴스화가 치명적이다."""
    tokens = collect_references().get("utils.js", {})
    assert len(tokens) == 1, f"utils.js가 여러 토큰으로 참조됨: {sorted(tokens)}"


def test_토큰_불일치를_검사기가_잡아낸다(tmp_path):
    """검사기 자체의 회귀 테스트 - 실제 버그 형태를 재현한다."""
    docs = tmp_path / "docs"
    (docs / "js").mkdir(parents=True)
    (docs / "index.html").write_text(
        '<script type="module" src="js/main.js?v=20260101-1"></script>', encoding="utf-8")
    (docs / "js" / "main.js").write_text(
        "import { A } from './utils.js?v=20260101-1';", encoding="utf-8")
    (docs / "js" / "strategy-view.js").write_text(
        "import { A } from './utils.js?v=20260202-1';", encoding="utf-8")
    (docs / "js" / "utils.js").write_text("export const A = {};", encoding="utf-8")

    violations = find_violations(docs)
    assert len(violations) == 1
    assert "utils.js" in violations[0]

    # bump로 통일하면 위반이 사라진다
    token, changed = bump("20260303-1", docs)
    assert token == "20260303-1"
    assert len(changed) == 3  # utils.js는 참조가 없어 미변경
    assert find_violations(docs) == []
