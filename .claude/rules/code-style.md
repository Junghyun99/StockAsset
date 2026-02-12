# 코드 스타일 규칙

## Python
- Python 3.10 기준으로 작성
- 클래스 기반 설계: 각 컴포넌트는 클래스로 구현
- 타입 힌트 사용 권장 (core/models.py 참고)
- 한글 주석 허용 (프로젝트 전반에서 한글 주석 사용 중)

## 네이밍
- 클래스: PascalCase (예: RegimeAnalyzer, VolatilityTargeter)
- 함수/변수: snake_case (예: calculate_exposure, market_data)
- 상수: UPPER_SNAKE_CASE (예: ASSET_GROUPS, IS_LIVE_TRADING)

## 모듈 구조
- core/: 외부 의존성 없는 순수 도메인 로직
- infra/: 외부 API, 파일 I/O 등 인프라 계층
- utils/: 공통 유틸리티 (로깅, 계산)
- backtest/: 백테스트 전용 코드
