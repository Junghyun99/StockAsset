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