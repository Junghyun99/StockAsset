# 테스트 규칙

## 실행
- 명령어: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/`
- 최소 커버리지: 80%
- CI에서 자동 실행 (GitHub Actions)

## 구조
- 테스트 파일: tests/ 디렉토리에 test_*.py 형식
- 네이밍: test_{module}_{feature}.py (예: test_core_logic.py)
- 외부 API 호출은 반드시 mock 처리 (unittest.mock.patch 사용)
- _live.py 접미사: 실제 API 호출이 필요한 통합 테스트 (CI에서 제외 가능)

## 원칙
- 새 기능 추가 시 반드시 테스트 작성
- 버그 수정 시 해당 버그를 재현하는 테스트 먼저 작성
- infra/ 모듈 테스트는 외부 의존성을 mock으로 격리
