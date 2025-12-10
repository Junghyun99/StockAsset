import pytest
import json
import os
from src.infra.repo import JsonRepository
from src.core.models import MarketData, Portfolio, TradeSignal, MarketRegime, Order, TradeExecution

@pytest.fixture
def repo(tmp_path):
    # 임시 디렉토리를 root로 하는 리포지토리 생성
    return JsonRepository(root_path=str(tmp_path))

@pytest.fixture
def dummy_market_data():
    return MarketData(
            "2024-01-01", 100.0, 90.0, 0.2, 0.1, -0.05, 15.0
                )
@pytest.fixture
def dummy_portfolio():
    return Portfolio(1000.0, {'A': 10}, {'A': 100.0})

def test_save_and_load_status(repo, dummy_portfolio, dummy_market_data):
    # 1. Status 저장 및 덮어쓰기 테스트
    # 저장
    repo.update_status(MarketRegime.BULL, 0.8, dummy_portfolio, dummy_market_data,"Test reason")
    
    # 파일 생성 확인
    assert os.path.exists(repo.status_file)
    
    # 내용 확인
    with open(repo.status_file, 'r') as f:
        data = json.load(f)
        assert data['strategy']['regime'] == "Bull"
        assert data['strategy']['target_exposure'] == 0.8
        assert data['strategy']['market_score']['vix'] == 15.0
        assert data['portfolio']['total_value'] == 2000.0

def test_save_summary_append(repo):
    # 2. Summary 이어쓰기(Append) 테스트
    market = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15)
    signal = TradeSignal(0.8, True, [], "Test")
    pf = Portfolio(1000, {}, {})
    
    # 두 번 저장
    repo.save_daily_summary(market, signal, pf)
    repo.save_daily_summary(market, signal, pf)
    
    # 파일 확인
    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 2 # 데이터가 2건이어야 함
        assert data[0]['date'] == "2024-01-01"

def test_save_history_only_when_orders_exist(repo, dummy_portfolio):
    # Case A: 체결 내역 없음 (빈 리스트)
    # [수정] signal 객체가 아니라 빈 리스트 [] 전달
    repo.save_trade_history([], dummy_portfolio, "No Trade")
    assert not os.path.exists(repo.history_file)
    
    # Case B: 체결 내역 있음
    # [수정] TradeExecution 객체 리스트 생성
    executions = [
        TradeExecution("SPY", "BUY", 1, 100.0, 0.1, "2024-01-01", "FILLED")
    ]
    
    repo.save_trade_history(executions, dummy_portfolio, "Trade Executed")
    assert os.path.exists(repo.history_file)
    with open(repo.history_file, 'r') as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]['executions'][0]['ticker'] == "SPY"
    
    
def test_load_corrupted_json_file(repo):
    """
    [예외 시나리오: 파일 손상]
    저장된 JSON 파일의 내용이 깨져있을 때(Syntax Error),
    프로그램이 죽지 않고 default 값(빈 리스트 등)을 리턴하는지?
    """
    # 1. 고의로 깨진 파일 생성
    with open(repo.status_file, 'w') as f:
        f.write("{ this is broken json ... ")
    
    # 2. 로드 시도
    # JsonRepository._load_json 내부의 try-except 블록이 작동해야 함
    data = repo._load_json(repo.status_file, default={})
    
    # 3. 에러 없이 기본값 리턴 확인
    assert data == {}

def test_repo_directory_creation(tmp_path):
    """
    [예외 시나리오: 폴더 없음]
    저장 경로의 폴더가 없을 때 자동으로 생성하는지?
    """
    new_path = tmp_path / "subdir" / "data"
    # 아직 폴더 없음
    assert not os.path.exists(new_path)
    
    # Repo 초기화 시 자동 생성
    from src.infra.repo import JsonRepository
    repo = JsonRepository(root_path=str(new_path))
    
    assert os.path.exists(new_path)


def test_repo_resilience_empty_file(repo):
    """
    [심화] JSON 파일이 존재하지만 내용이 비어있는 경우(0 byte) 방어
    """
    # 1. 빈 파일 생성
    with open(repo.status_file, 'w') as f:
        pass # create empty file
        
    # 2. 로드 시도
    # JSONDecodeError가 발생하지 않고 기본값({})을 리턴하거나, None을 리턴해야 함
    data = repo._load_json(repo.status_file, default={})
    
    assert data == {}

def test_repo_resilience_malformed_json(repo):
    """
    [심화] JSON 파일 내용이 깨진 경우 방어
    """
    # 1. 깨진 파일 생성
    with open(repo.status_file, 'w') as f:
        f.write("{ 'key': 'value' ... broken") # 닫는 괄호 없음
        
    # 2. 로드 시도
    data = repo._load_json(repo.status_file, default={'fallback': True})
    
    # 3. 기본값(Fallback)으로 복구되는지 확인
    assert data['fallback'] is True



def test_save_summary_large_file_performance(repo, dummy_market_data, dummy_portfolio):
    """
    [성능] summary.json에 데이터가 10,000개 쌓여있어도 정상적으로 Append 되는지 확인
    """
    # 1. 가짜 대용량 데이터 생성 (10,000일치)
    large_data = [
        {
            "date": f"2020-01-{i%30+1:02d}", 
            "total_value": 10000 + i,
            "spy_price": 100 + i
        } 
        for i in range(10000)
    ]
    
    # 파일에 강제 쓰기
    repo._save_json(repo.summary_file, large_data)
    
    # 2. 새로운 데이터 저장 시도 (Append)
    signal = TradeSignal(0.8, True, [], "Performance Test")
    
    # 시간 측정 가능 (선택사항)
    import time
    start = time.time()
    
    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio)
    
    end = time.time()
    
    # 3. 검증
    # 에러 없이 저장되었는지
    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
        assert len(data) == 10001
        
    # 속도 체크 (JSON 파싱 및 쓰기가 1초 이내여야 함)
    # 로컬 디스크 I/O에 따라 다르지만, 10000건 정도는 순식간이어야 함
    assert (end - start) < 1.0

# ... (기존 임포트 및 Fixture 생략) ...

def test_repo_encoding_support(repo, dummy_portfolio, dummy_market_data):
    """
    [인코딩] 한글과 이모지가 포함된 데이터가 깨지지 않고 저장되는지 확인
    """
    # 1. 특수문자가 포함된 사유
    reason_msg = "전략 변경: 하락장 진입 📉 (위험해!)"
    signal = TradeSignal(0.5, True, [], reason_msg)
    
    # 2. 저장
    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio)
    
    # 3. 파일 읽기 (Raw Text 확인)
    with open(repo.summary_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # 4. 검증
    # \uXXXX 형태가 아니라 실제 글자로 저장되어야 함 (ensure_ascii=False 덕분)
    assert "전략 변경" in content
    assert "📉" in content
    assert reason_msg in content

def test_repo_schema_evolution(repo, dummy_market_data, dummy_portfolio):
    """
    [호환성] 기존 파일에 옛날 스키마 데이터가 있어도, 새 데이터가 잘 추가되는지 확인
    """
    # 1. 구버전 데이터 파일 생성 (필드가 적음)
    old_data = [
        {"date": "2020-01-01", "total_value": 100} # 옛날엔 이것만 있었다고 가정
    ]
    repo._save_json(repo.summary_file, old_data)
    
    # 2. 신버전 데이터 저장 (필드가 많음: spy_price, mdd 등)
    signal = TradeSignal(0.8, True, [], "New Version")
    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio)
    
    # 3. 로드 및 검증
    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
        
    assert len(data) == 2
    assert data[0]['total_value'] == 100          # 구버전 데이터 유지
    assert 'spy_price' not in data[0]             # 구버전엔 필드 없음
    assert data[1]['spy_price'] == 100.0          # 신버전엔 필드 있음
    
    # 봇이 죽지 않고 Append에 성공했다는 것이 핵심

def test_repo_nested_directory(tmp_path):
    """
    [환경] 저장 경로가 깊거나(Nested) 존재하지 않아도 자동으로 생성하는지 확인
    """
    # 1. 깊은 경로 지정
    deep_path = tmp_path / "archive" / "strategy_v1" / "data"
    assert not os.path.exists(deep_path)
    
    # 2. Repo 초기화 (이 시점에 폴더 생성 로직 동작)
    repo = JsonRepository(root_path=str(deep_path))
    
    # 3. 폴더 생성 확인
    assert os.path.exists(deep_path)
    
    # 4. 파일 생성 확인
    pf = Portfolio(100, {}, {})
    repo.update_status(MarketRegime.BULL, 1.0, pf, MarketData("date", 100, 100, 0.1, 0.1, 0, 15), "Init")
    
    assert os.path.exists(repo.status_file)

# ... (기존 코드 생략) ...
from datetime import datetime
import numpy as np

def test_repo_serialization_error(repo, dummy_portfolio, dummy_market_data):
    """
    [방어] JSON으로 변환할 수 없는 타입(datetime 객체 등)이 들어왔을 때 동작 확인
    """
    # datetime 객체는 기본 json.dump로 직렬화 불가능 (문자열로 변환 필요)
    # 실수로 변환 안 된 객체를 reason에 넣었다고 가정
    invalid_reason = datetime.now() 
    
    # Python은 동적 타이핑이라 여기까진 에러 안 남
    signal = TradeSignal(0.8, True, [], invalid_reason) 
    
    # 저장 시도 시 TypeError 발생해야 함 (만약 커스텀 인코더를 구현했다면 성공해야 함)
    # 현재 구현은 기본 json.dump를 쓰므로 에러가 나는 것이 정상 동작임 -> 이를 알고 있어야 함
    with pytest.raises(TypeError):
        repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio)

def test_repo_recover_from_corruption(repo, dummy_market_data, dummy_portfolio):
    """
    [복구] 파일이 깨져있을 때(Load 실패), 봇이 멈추지 않고 덮어쓰기로 복구하는지 확인
    """
    # 1. 깨진 파일 생성 (JSON 문법 오류)
    with open(repo.status_file, 'w') as f:
        f.write("{ 'broken': ... ")
    
    # 2. 업데이트 시도
    # _load_json 내부에서 try-except로 잡고 default(None/Empty)를 리턴하므로,
    # save 로직이 멈추지 않고 새로운 내용으로 덮어써야 함.
    try:
        repo.update_status(
            MarketRegime.BULL, 0.5, dummy_portfolio, dummy_market_data, "Recover"
        )
    except Exception as e:
        pytest.fail(f"Repo failed to recover from corrupted file: {e}")
        
    # 3. 파일이 정상적인 JSON으로 복구되었는지 확인
    with open(repo.status_file, 'r') as f:
        data = json.load(f)
        assert data['strategy']['trigger_reason'] == "Recover"

def test_repo_read_only_file(repo, dummy_market_data, dummy_portfolio):
    """
    [OS] 파일이 읽기 전용(Read-only)이라 쓸 수 없을 때, 명확한 에러 발생 확인
    (Linux/Mac 환경 기준)
    """
    import stat
    
    # 1. 파일 생성
    signal = TradeSignal(0.8, True, [], "Test")
    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio)
    
    # 2. 읽기 전용으로 권한 변경 (Write 권한 제거)
    os.chmod(repo.summary_file, stat.S_IREAD)
    
    try:
        # 3. 쓰기 시도 -> PermissionError 발생해야 함
        with pytest.raises(PermissionError):
            repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio)
            
    finally:
        # 테스트 종료 후 권한 복구 (Cleanup) - 안 하면 임시 폴더 삭제 시 에러 날 수 있음
        os.chmod(repo.summary_file, stat.S_IWRITE | stat.S_IREAD)