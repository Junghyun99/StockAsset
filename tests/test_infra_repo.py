import pytest
import json
import os
from src.infra.repo import JsonRepository
from src.core.models import MarketData, Portfolio, TradeSignal, MarketRegime, Order

@pytest.fixture
def repo(tmp_path):
    # 임시 디렉토리를 root로 하는 리포지토리 생성
    return JsonRepository(root_path=str(tmp_path))

def test_save_and_load_status(repo):
    # 1. Status 저장 및 덮어쓰기 테스트
    pf = Portfolio(1000, {'A': 10}, {'A': 100})
    
    # 저장
    repo.update_status(MarketRegime.BULL, 0.8, pf)
    
    # 파일 생성 확인
    assert os.path.exists(repo.status_file)
    
    # 내용 확인
    with open(repo.status_file, 'r') as f:
        data = json.load(f)
        assert data['regime'] == "Bull"
        assert data['exposure'] == 0.8
        assert data['total_value'] == 2000.0

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

def test_save_history_only_when_orders_exist(repo):
    # 3. 주문이 있을 때만 History 저장 테스트
    
    # Case A: 주문 없음
    signal_no_order = TradeSignal(0.8, False, [], "No Trade")
    repo.save_trade_history(signal_no_order)
    assert not os.path.exists(repo.history_file) # 파일 생성이 안 되어야 함
    
    # Case B: 주문 있음
    orders = [Order("SPY", "BUY", 1, 100)]
    signal_with_order = TradeSignal(0.8, True, orders, "Trade")
    repo.save_trade_history(signal_with_order)
    
    assert os.path.exists(repo.history_file)
    with open(repo.history_file, 'r') as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]['orders'][0]['ticker'] == "SPY"

# tests/test_infra_repo.py (추가 내용)

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
