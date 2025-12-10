import pytest
from unittest.mock import MagicMock
from src.infra.data import YFinanceLoader

# 이 테스트는 외부 API를 호출하므로 네트워크 상태에 따라 실패할 수 있음
# CI/CD에서 너무 자주 실패하면 제외하거나 재시도 로직 필요
def test_yfinance_live_connection():
    """
    [Live] 실제 Yahoo Finance 서버에 접속해서 데이터를 가져올 수 있는지 확인
    (GitHub Actions IP 차단 여부 등을 점검하는 용도)
    """
    # 로거는 Mock 처리 (파일 생성 방지)
    mock_logger = MagicMock()
    loader = YFinanceLoader(mock_logger)
    
    try:
        # SPY 데이터 최근 5일치 요청
        df = loader.fetch_ohlcv(["SPY"], days=5)
        
        # 데이터가 비어있지 않아야 함
        assert not df.empty, "Yahoo Finance returned empty data!"
        assert len(df) >= 1
        
        # VIX 데이터도 확인
        vix = loader.fetch_vix()
        assert isinstance(vix, float)
        assert 0 < vix < 100 # VIX는 보통 0~100 사이
        
    except Exception as e:
        pytest.fail(f"Live Yahoo Finance connection failed: {e}")