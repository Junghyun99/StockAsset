import os
import logging
import re
import pytest
from src.utils.logger import TradeLogger
from datetime import datetime
from unittest.mock import patch

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





def test_logger_encoding(tmp_path, reset_logger):
    """
    [심화] 한글 및 이모지가 깨지지 않고 UTF-8로 저장되는지 확인
    """
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))
    
    special_msg = "테스트 메시지: 한글 및 이모지 🚀 확인"
    logger.info(special_msg)
    
    # 생성된 로그 파일 찾기
    log_file = log_dir / os.listdir(log_dir)[0]
    
    # utf-8로 읽어서 내용 확인
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
        assert special_msg in content

def test_logger_filename_date_format(tmp_path, reset_logger):
    """
    [심화] 로그 파일명이 'YYYY-MM-DD.log' 형식을 따르는지 확인
    """
    log_dir = tmp_path / "logs"
    TradeLogger(log_dir=str(log_dir))
    
    files = os.listdir(log_dir)
    filename = files[0]
    
    # 오늘 날짜 구하기
    expected_date = datetime.now().strftime("%Y-%m-%d")
    expected_filename = f"{expected_date}.log"
    
    assert filename == expected_filename

def test_logger_permission_error(reset_logger):
    """
    [예외] 로그 디렉토리 생성 권한이 없을 때 예외가 발생하는지 확인
    """
    # os.makedirs가 PermissionError를 일으키도록 Mocking
    with patch("os.makedirs", side_effect=PermissionError("Access Denied")):
        # TradeLogger 초기화 시도 -> 에러 발생해야 함
        with pytest.raises(PermissionError):
            TradeLogger(log_dir="/root/protected_logs")


def test_logger_append_mode(tmp_path, reset_logger):
    """
    [운영] 같은 날짜에 로거가 다시 생성되어도, 기존 로그를 덮어쓰지 않고 이어쓰는지 확인
    """
    log_dir = tmp_path / "logs"
    
    # 1. 첫 번째 실행 (오전 9시 가정)
    logger1 = TradeLogger(log_dir=str(log_dir))
    logger1.info("First execution log")
    
    # 로거 핸들러 강제 초기화 (프로그램 재시작 시뮬레이션)
    logging.getLogger("SolidQuant").handlers = []
    
    # 2. 두 번째 실행 (오후 1시 가정)
    logger2 = TradeLogger(log_dir=str(log_dir))
    logger2.info("Second execution log")
    
    # 3. 파일 검증
    log_file = log_dir / os.listdir(log_dir)[0]
    with open(log_file, 'r') as f:
        content = f.read()
        
    # 두 메시지가 모두 존재해야 함
    assert "First execution log" in content
    assert "Second execution log" in content
    # 순서 확인 (첫 번째가 먼저 나와야 함)
    assert content.index("First execution log") < content.index("Second execution log")

def test_logger_format_structure(tmp_path, reset_logger):
    """
    [포맷] 로그 파일의 형식이 '[날짜 시간] [레벨] 메시지' 구조를 따르는지 정규식 검증
    """
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))
    logger.info("Format Test")
    
    log_file = log_dir / os.listdir(log_dir)[0]
    with open(log_file, 'r') as f:
        line = f.readline()
        
    # 정규식 패턴: YYYY-MM-DD HH:MM:SS,mmm [INFO] Message
    # 예: 2024-05-21 10:00:00,123 [INFO] Format Test
    pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[INFO\] Format Test"
    
    assert re.search(pattern, line) is not None, f"Log format mismatch! Line: {line}"

def test_logger_non_string_input(tmp_path, reset_logger):
    """
    [방어] 문자열이 아닌 객체(Dict, List, Exception)를 넣어도 죽지 않고 기록하는지 확인
    """
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))
    
    data_dict = {"price": 100, "ticker": "SPY"}
    
    # 딕셔너리를 직접 로깅 시도 (내부적으로 str() 변환되거나 에러 없이 넘어가야 함)
    try:
        logger.info(data_dict) # type: ignore
    except Exception as e:
        pytest.fail(f"Logger crashed with non-string input: {e}")
        
    log_file = log_dir / os.listdir(log_dir)[0]
    with open(log_file, 'r') as f:
        content = f.read()
        
    # 딕셔너리 내용이 문자열로 잘 찍혔는지 확인
    assert "{'price': 100, 'ticker': 'SPY'}" in content


def test_logger_multiline_message(tmp_path, reset_logger):
    """
    [내용] 줄바꿈(\n)이 포함된 로그(예: Traceback)가 형태를 유지하며 저장되는지 확인
    """
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))
    
    multiline_msg = """Critical Error Occurred:
    Traceback (most recent call last):
      File "main.py", line 10, in <module>
        1 / 0
    ZeroDivisionError: division by zero"""
    
    logger.error(multiline_msg)
    
    log_file = log_dir / os.listdir(log_dir)[0]
    with open(log_file, 'r') as f:
        content = f.read()
    
    # 내용이 그대로 포함되어 있는지 확인
    assert multiline_msg in content
    # 줄바꿈 개수가 유지되는지 확인
    assert content.count('\n') >= 4

def test_logger_large_payload(tmp_path, reset_logger):
    """
    [성능/한계] 매우 긴 문자열(예: 10KB API 응답)을 기록해도 잘리지 않는지 확인
    """
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))
    
    # 10KB 짜리 긴 문자열 생성
    large_msg = "A" * 1024 * 10 
    
    logger.info(large_msg)
    
    log_file = log_dir / os.listdir(log_dir)[0]
    with open(log_file, 'r') as f:
        content = f.read()
        
    # 파일 내용에 긴 문자열이 통째로 들어있는지 확인
    assert large_msg in content

def test_logger_empty_message(tmp_path, reset_logger):
    """
    [방어] 빈 문자열을 로깅했을 때 에러 없이 빈 내용이 기록되는지 확인
    """
    log_dir = tmp_path / "logs"
    logger = TradeLogger(log_dir=str(log_dir))
    
    logger.info("")
    
    log_file = log_dir / os.listdir(log_dir)[0]
    with open(log_file, 'r') as f:
        content = f.read()
    
    # 포맷([INFO])은 찍히고 내용은 비어있어야 함
    assert "[INFO]" in content
    # 로그 포맷 뒷부분에 공백 혹은 개행이 붙어있는지 확인 (정규식 등으로 더 엄밀하게 볼 수도 있음)
    # 여기서는 에러가 안 났다는 것과 파일에 뭔가가 쓰였다는 것을 검증
    assert len(content) > 0