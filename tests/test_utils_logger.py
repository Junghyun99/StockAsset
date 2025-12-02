import os
from src.utils.logger import TradeLogger

def test_logger_file_creation(tmp_path):
    """[기본] 로그 파일 생성 확인"""
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