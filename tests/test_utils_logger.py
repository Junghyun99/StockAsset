import os
import logging
from src.utils.logger import TradeLogger

def test_logger_file_creation(tmp_path):
    """[기본] 로그 파일 생성 확인"""
    
    # [수정] 테스트 시작 전, 기존 'SolidQuant' 로거의 핸들러를 초기화해야 함
    # 이유: 로거는 싱글톤이라 이전 테스트의 설정이 남아있을 수 있음
    existing_logger = logging.getLogger("SolidQuant")
    existing_logger.handlers = [] 

    # 임시 폴더에 로거 생성
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))
    
    logger.info("Test Log Message")
    
    # 파일 생성 확인
    files = os.listdir(log_dir)
    assert len(files) == 1
    assert files[0].endswith(".log")
    
    # 내용 확인
    with open(log_dir / files[0], 'r') as f:
        content = f.read()
        assert "Test Log Message" in content