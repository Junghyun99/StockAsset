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
