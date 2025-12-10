import os
import logging
import pytest
from src.utils.logger import TradeLogger

@pytest.fixture
def reset_logger():
    """
    각 테스트 실행 전후로 로거 상태를 초기화하는 픽스처.
    logging 모듈은 싱글톤이라 상태가 유지되므로 필수적임.
    """
    # Setup: 기존 핸들러 제거
    logger = logging.getLogger("SolidQuant")
    logger.handlers = []
    
    yield
    
    # Teardown: 테스트 후 핸들러 제거
    logger.handlers = []

def test_logger_file_creation(tmp_path, reset_logger):
    """[기본] 로그 파일 생성 및 내용 기록 확인"""
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))

    logger.info("Test Info Message")

    # 1. 파일 생성 확인
    files = os.listdir(log_dir)
    assert len(files) == 1
    assert files[0].endswith(".log")

    # 2. 내용 확인
    with open(log_dir / files[0], 'r') as f:
        content = f.read()
        assert "Test Info Message" in content
        assert "[INFO]" in content  # 레벨 태그 확인

def test_logger_levels(tmp_path, reset_logger):
    """[기본] Warning, Error 레벨이 올바르게 기록되는지 확인"""
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))

    logger.warning("This is a warning")
    logger.error("This is an error")

    with open(log_dir / os.listdir(log_dir)[0], 'r') as f:
        content = f.read()
        
        # Warning 확인
        assert "[WARNING]" in content
        assert "This is a warning" in content
        
        # Error 확인
        assert "[ERROR]" in content
        assert "This is an error" in content

def test_logger_console_output(tmp_path, capsys, reset_logger):
    """[기본] 콘솔(Standard Output/Error)에도 로그가 찍히는지 확인"""
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))

    logger.info("Console Test Message")

    # capsys: pytest가 콘솔 출력을 캡처하는 픽스처
    # logging 모듈은 기본적으로 stderr에 출력함
    captured = capsys.readouterr()
    
    # stderr에 메시지가 포함되어 있어야 함
    assert "Console Test Message" in captured.err
    assert "[INFO]" in captured.err

def test_prevent_duplicate_handlers(tmp_path, capsys, reset_logger):
    """[예외/구조] Logger를 여러 번 인스턴스화해도 핸들러가 중복되지 않는지 확인"""
    log_dir = tmp_path / "logs"
    
    # 1. 첫 번째 초기화
    logger1 = TradeLogger(log_dir=str(log_dir))
    
    # 2. 두 번째 초기화 (실수로 또 생성하거나 다른 모듈에서 생성 시)
    logger2 = TradeLogger(log_dir=str(log_dir))
    
    # 3. 로그 남기기
    logger1.info("Duplicate Check")
    
    # 4. 검증: 핸들러 개수가 늘어나지 않아야 함 (FileHandler 1개 + StreamHandler 1개 = 총 2개)
    raw_logger = logging.getLogger("SolidQuant")
    assert len(raw_logger.handlers) == 2
    
    # 5. 검증: 파일에 로그가 한 번만 찍혀야 함
    with open(log_dir / os.listdir(log_dir)[0], 'r') as f:
        content = f.read()
        # "Duplicate Check" 문자가 파일 내에 딱 1번만 등장해야 함
        assert content.count("Duplicate Check") == 1
        
    # 6. 검증: 콘솔에도 한 번만 찍혀야 함
    captured = capsys.readouterr()
    # 문자열 count로 확인 (이스케이프 문자 등이 있을 수 있어 단순 포함 여부보다 count가 정확)
    assert captured.err.count("Duplicate Check") == 1

