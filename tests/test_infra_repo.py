import pytest
import json
import os
from src.infra.repo import JsonRepository
from src.core.models import MarketData, Portfolio, TradeSignal, MarketRegime, Order, TradeExecution, OrderAction, ExecutionStatus

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

def test_load_last_regime_returns_saved_regime(repo, dummy_portfolio, dummy_market_data):
    """status.json에 저장된 regime을 올바르게 로드하는지 확인."""
    repo.update_status(MarketRegime.CRASH, 0.0, dummy_portfolio, dummy_market_data, "Crash")
    assert repo.load_last_regime() == MarketRegime.CRASH

    repo.update_status(MarketRegime.BULL, 1.0, dummy_portfolio, dummy_market_data, "Bull")
    assert repo.load_last_regime() == MarketRegime.BULL


def test_load_last_regime_returns_none_when_no_file(repo):
    """status.json이 없으면 None을 반환해야 한다."""
    assert repo.load_last_regime() is None


def test_load_last_regime_returns_none_on_corrupted_file(repo):
    """status.json이 깨져있으면 None을 반환해야 한다."""
    with open(repo.status_file, 'w') as f:
        f.write("{ broken json ...")
    assert repo.load_last_regime() is None


def test_load_last_regime_returns_none_on_invalid_regime(repo):
    """status.json의 regime 값이 유효하지 않으면 None을 반환해야 한다."""
    import json
    invalid_status = {"strategy": {"regime": "InvalidRegime"}}
    with open(repo.status_file, 'w') as f:
        json.dump(invalid_status, f)
    assert repo.load_last_regime() is None


def test_load_last_regime_returns_none_on_missing_key(repo):
    """status.json에 strategy.regime 키가 없으면 None을 반환해야 한다."""
    import json
    incomplete_status = {"last_updated": "2024-01-01"}
    with open(repo.status_file, 'w') as f:
        json.dump(incomplete_status, f)
    assert repo.load_last_regime() is None


def test_save_daily_summary_date_override(repo, dummy_portfolio):
    """date_override 전달 시 market.date 대신 override 값이 저장 key로 사용됨."""
    market = MarketData("2024-01-10", 100, 90, 0.1, 0.1, -0.05, 15)  # 전일 미국 거래일
    signal = TradeSignal(0.8, [], "test")

    repo.save_daily_summary(market, signal, dummy_portfolio, MarketRegime.BULL,
                            date_override="2024-01-11")  # 실행일 (오늘)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]['date'] == "2024-01-11"  # market.date("2024-01-10")가 아닌 override값


def test_save_daily_summary_no_override_uses_market_date(repo, dummy_portfolio):
    """date_override 미전달 시 market.date가 저장 key로 사용됨 (백워드 호환)."""
    market = MarketData("2024-01-10", 100, 90, 0.1, 0.1, -0.05, 15)
    signal = TradeSignal(0.8, [], "test")

    repo.save_daily_summary(market, signal, dummy_portfolio, MarketRegime.BULL)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    assert data[0]['date'] == "2024-01-10"


def test_save_daily_summary_records_benchmarks(repo, dummy_portfolio):
    """benchmarks 전달 시 레코드에 그대로 저장된다."""
    market = MarketData("2024-01-10", 100, 90, 0.1, 0.1, -0.05, 15)
    signal = TradeSignal(0.8, [], "test")
    benchmarks = {"KOSPI200": 38500.0, "S&P500": 512.3, "NASDAQ100": 102300.0}

    repo.save_daily_summary(market, signal, dummy_portfolio, MarketRegime.BULL,
                            benchmarks=benchmarks)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    assert data[0]['benchmarks'] == benchmarks


def test_save_daily_summary_benchmarks_default_empty(repo, dummy_portfolio):
    """benchmarks 미전달(백테스트 등) 시 빈 dict로 저장된다."""
    market = MarketData("2024-01-10", 100, 90, 0.1, 0.1, -0.05, 15)
    signal = TradeSignal(0.8, [], "test")

    repo.save_daily_summary(market, signal, dummy_portfolio, MarketRegime.BULL)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    assert data[0]['benchmarks'] == {}


def test_save_summary_upsert_same_date(repo):
    # 같은 날짜로 2번 저장하면 Upsert(덮어쓰기)되어 레코드 1개만 유지
    market = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15)
    signal1 = TradeSignal(0.8, [], "오전 실행")
    signal2 = TradeSignal(0.8, [], "오후 실행")
    pf1 = Portfolio(1000, {}, {})
    pf2 = Portfolio(1200, {}, {})

    repo.save_daily_summary(market, signal1, pf1, MarketRegime.BULL)
    repo.save_daily_summary(market, signal2, pf2, MarketRegime.BULL)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]['date'] == "2024-01-01"
    assert data[0]['reason'] == "오후 실행"   # 마지막 값으로 갱신
    assert data[0]['total_value'] == 1200.0   # 마지막 포트폴리오 반영


def test_save_summary_different_dates_both_kept(repo):
    # 다른 날짜는 각각 append되어 2개 레코드 유지
    market1 = MarketData("2024-01-01", 100, 90, 0.1, 0.1, -0.05, 15)
    market2 = MarketData("2024-01-02", 101, 91, 0.1, 0.1, -0.04, 14)
    signal = TradeSignal(0.8, [], "Test")
    pf = Portfolio(1000, {}, {})

    repo.save_daily_summary(market1, signal, pf, MarketRegime.BULL)
    repo.save_daily_summary(market2, signal, pf, MarketRegime.BULL)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    assert len(data) == 2
    assert data[0]['date'] == "2024-01-01"
    assert data[1]['date'] == "2024-01-02"

def test_save_history_only_when_orders_exist(repo, dummy_portfolio):
    # Case A: 체결 내역 없음 (빈 리스트)
    repo.save_trade_history([], dummy_portfolio, "No Trade")
    assert not os.path.exists(repo.history_file)

    # Case B: 체결 내역 있음
    executions = [
        TradeExecution("SPY", OrderAction.BUY, 1, 100.0, 0.1, "2024-01-01", ExecutionStatus.FILLED)
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



def test_save_summary_large_file_performance(tmp_path, dummy_market_data, dummy_portfolio):
    """
    [성능] summary.json에 데이터가 10,000개 쌓여있어도 정상적으로 Append 되는지 확인
    (크기 제한을 11000으로 설정하여 10001건 전체가 유지되는 것을 검증)
    """
    # max_summary_records를 충분히 크게 설정
    large_repo = JsonRepository(root_path=str(tmp_path), max_summary_records=11000)

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
    large_repo._save_json(large_repo.summary_file, large_data)

    # 2. 새로운 데이터 저장 시도 (Append)
    signal = TradeSignal(0.8, [], "Performance Test")

    # 시간 측정 가능 (선택사항)
    import time
    start = time.time()

    large_repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL)

    end = time.time()

    # 3. 검증
    # 에러 없이 저장되었는지
    with open(large_repo.summary_file, 'r') as f:
        data = json.load(f)
        assert len(data) == 10001

    # 속도 체크 (JSON 파싱 및 쓰기가 1초 이내여야 함)
    # 로컬 디스크 I/O에 따라 다르지만, 10000건 정도는 순식간이어야 함
    assert (end - start) < 1.0


def test_summary_size_limit_applied(tmp_path, dummy_market_data, dummy_portfolio):
    """
    [크기 제한] summary.json이 max_summary_records를 초과하면 오래된 레코드를 잘라내는지 확인
    """
    limit = 5
    repo = JsonRepository(root_path=str(tmp_path), max_summary_records=limit)

    # limit + 2건 저장 → limit건만 남아야 함
    for i in range(limit + 2):
        market = MarketData(f"2024-01-{i+1:02d}", 100 + i, 90, 0.1, 0.1, -0.05, 15)
        signal = TradeSignal(0.8, [], f"Day {i+1}")
        repo.save_daily_summary(market, signal, dummy_portfolio, MarketRegime.BULL)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)

    assert len(data) == limit
    # 최신 데이터가 유지되어야 함
    assert data[-1]['date'] == f"2024-01-{limit+2:02d}"


def test_history_size_limit_applied(tmp_path, dummy_portfolio):
    """
    [크기 제한] history.json이 max_history_records를 초과하면 오래된 레코드를 잘라내는지 확인
    """
    limit = 3
    repo = JsonRepository(root_path=str(tmp_path), max_history_records=limit)

    execution = TradeExecution("SPY", OrderAction.BUY, 1, 100.0, 0.1, "2024-01-01", ExecutionStatus.FILLED)

    for i in range(limit + 1):
        repo.save_trade_history([execution], dummy_portfolio, f"Trade {i+1}")

    with open(repo.history_file, 'r') as f:
        data = json.load(f)

    assert len(data) == limit
    assert data[-1]['reason'] == f"Trade {limit+1}"

# ... (기존 임포트 및 Fixture 생략) ...

def test_repo_encoding_support(repo, dummy_portfolio, dummy_market_data):
    """
    [인코딩] 한글과 이모지가 포함된 데이터가 깨지지 않고 저장되는지 확인
    """
    # 1. 특수문자가 포함된 사유
    reason_msg = "전략 변경: 하락장 진입 📉 (위험해!)"
    signal = TradeSignal(0.5, [], reason_msg)
    
    # 2. 저장
    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BEAR_WEAK)

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
    signal = TradeSignal(0.8, [], "New Version")
    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL)

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
    signal = TradeSignal(0.8, [], invalid_reason)
    
    # 저장 시도 시 TypeError 발생해야 함 (만약 커스텀 인코더를 구현했다면 성공해야 함)
    # 현재 구현은 기본 json.dump를 쓰므로 에러가 나는 것이 정상 동작임 -> 이를 알고 있어야 함
    with pytest.raises(TypeError):
        repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL)

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

@pytest.mark.skipif(os.getuid() == 0, reason="root 사용자는 읽기 전용 파일에도 쓰기 가능")
def test_repo_read_only_file(repo, dummy_market_data, dummy_portfolio):
    """
    [OS] 파일이 읽기 전용(Read-only)이라 쓸 수 없을 때, 명확한 에러 발생 확인
    (Linux/Mac 환경 기준)
    """
    import stat

    # 1. 파일 생성
    signal = TradeSignal(0.8, [], "Test")
    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL)

    # 2. 읽기 전용으로 권한 변경 (Write 권한 제거)
    os.chmod(repo.summary_file, stat.S_IREAD)

    try:
        # 3. 쓰기 시도 -> PermissionError 발생해야 함
        with pytest.raises(PermissionError):
            repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL)

    finally:
        # 테스트 종료 후 권한 복구 (Cleanup) - 안 하면 임시 폴더 삭제 시 에러 날 수 있음
        os.chmod(repo.summary_file, stat.S_IWRITE | stat.S_IREAD)

# ... (기존 코드 생략) ...

def test_get_last_summary_date_returns_none_when_empty(repo):
    """기록 없을 때 None 반환"""
    assert repo.get_last_summary_date() is None


def test_get_last_summary_date_returns_last_date(repo, dummy_portfolio):
    """가장 최근 레코드의 날짜를 반환"""
    for date in ["2024-01-01", "2024-01-03", "2024-01-05"]:
        market = MarketData(date, 100, 90, 0.1, 0.1, -0.05, 15)
        repo.save_daily_summary(market, TradeSignal(1.0, [], "test"), dummy_portfolio, MarketRegime.BULL)

    assert repo.get_last_summary_date() == "2024-01-05"


def test_get_last_summary_date_corrupted_file(repo):
    """JSON 손상 시 None 반환 (예외 없이)"""
    with open(repo.summary_file, 'w') as f:
        f.write("{ broken json ...")
    assert repo.get_last_summary_date() is None


def test_get_last_rebalancing_date_returns_none_when_no_status(repo):
    """status.json 없으면 None 반환"""
    assert repo.get_last_rebalancing_date() is None


def test_get_last_rebalancing_date_after_update(repo, dummy_portfolio, dummy_market_data):
    """리밸런싱 날짜 저장 후 반환 확인"""
    repo.update_status(MarketRegime.BULL, 1.0, dummy_portfolio, dummy_market_data,
                       "Test", rebalancing_date="2024-03-01")
    assert repo.get_last_rebalancing_date() == "2024-03-01"


def test_update_status_preserves_rebalancing_date_when_none(repo, dummy_portfolio, dummy_market_data):
    """rebalancing_date=None 전달 시 기존 날짜가 유지됨"""
    repo.update_status(MarketRegime.BULL, 1.0, dummy_portfolio, dummy_market_data,
                       "Initial", rebalancing_date="2024-03-01")
    repo.update_status(MarketRegime.BULL, 1.0, dummy_portfolio, dummy_market_data,
                       "Monitoring", rebalancing_date=None)
    assert repo.get_last_rebalancing_date() == "2024-03-01"


def test_update_status_overwrites_rebalancing_date(repo, dummy_portfolio, dummy_market_data):
    """새 날짜 전달 시 기존 날짜가 덮어씌워짐"""
    repo.update_status(MarketRegime.BULL, 1.0, dummy_portfolio, dummy_market_data,
                       "First", rebalancing_date="2024-02-01")
    repo.update_status(MarketRegime.BULL, 1.0, dummy_portfolio, dummy_market_data,
                       "Second", rebalancing_date="2024-03-01")
    assert repo.get_last_rebalancing_date() == "2024-03-01"


def test_repo_float_precision(repo, dummy_portfolio, dummy_market_data):
    """
    [데이터] 소수점 단위가 중요한 금융 데이터가 JSON 저장 후에도 정밀도를 유지하는지 확인
    """
    # 1. 미세한 소수점을 가진 데이터 생성
    precise_val = 123.456789123
    dummy_portfolio.total_cash = precise_val
    
    # 2. 저장
    repo.update_status(
        MarketRegime.BULL, 0.5, dummy_portfolio, dummy_market_data, "Precision Test"
    )
    
    # 3. 로드
    with open(repo.status_file, 'r') as f:
        data = json.load(f)
    
    # 4. 검증 (JSON은 부동소수점을 완벽히 보존하지 못할 수 있으므로 approx 사용)
    loaded_cash = data['portfolio']['cash_balance']
    assert loaded_cash == pytest.approx(precise_val, abs=1e-9)

def test_repo_status_overwrite_clean(repo, dummy_portfolio, dummy_market_data):
    """
    [로직] update_status가 파일을 '완전히 새로 쓰는지' 확인 (이전 데이터 잔재 제거)
    """
    # 1. 초기 상태 저장 (Extra Field를 임의로 넣어서 저장했다고 가정)
    initial_data = {"extra_field": "I should be deleted", "portfolio": {}}
    repo._save_json(repo.status_file, initial_data)
    
    # 2. 새로운 상태 업데이트
    repo.update_status(
        MarketRegime.BEAR_WEAK, 0.5, dummy_portfolio, dummy_market_data, "Overwrite"
    )
    
    # 3. 로드 및 검증
    with open(repo.status_file, 'r') as f:
        data = json.load(f)
    
    # 이전 데이터의 흔적이 사라져야 함
    assert "extra_field" not in data
    assert data['strategy']['trigger_reason'] == "Overwrite"

def test_load_json_propagates_keyboard_interrupt(repo, monkeypatch):
    """
    [안전] bare except가 제거된 후 KeyboardInterrupt가 _load_json에서 전파되는지 확인
    실거래 봇에서 Ctrl+C 신호가 무시되지 않아야 함
    """
    import json

    # 파일 생성 (os.path.exists 체크를 통과하도록)
    with open(repo.status_file, 'w') as f:
        f.write("{}")

    # json.load가 KeyboardInterrupt를 발생시키도록 패치
    def raise_keyboard_interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(json, "load", raise_keyboard_interrupt)

    # KeyboardInterrupt가 삼켜지지 않고 전파되어야 함
    with pytest.raises(KeyboardInterrupt):
        repo._load_json(repo.status_file, default={})


def test_load_json_propagates_system_exit(repo, monkeypatch):
    """
    [안전] bare except가 제거된 후 SystemExit이 _load_json에서 전파되는지 확인
    """
    import json

    with open(repo.status_file, 'w') as f:
        f.write("{}")

    def raise_system_exit(*args, **kwargs):
        raise SystemExit(0)

    monkeypatch.setattr(json, "load", raise_system_exit)

    with pytest.raises(SystemExit):
        repo._load_json(repo.status_file, default={})


def test_save_daily_summary_records_dividend(repo, dummy_market_data, dummy_portfolio):
    """daily_dividend가 summary.json 레코드에 저장되는지 확인"""
    import json
    signal = TradeSignal(1.0, [], "test")

    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL,
                            daily_dividend=55.25)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)

    assert data[0]['daily_dividend'] == 55.25


def test_save_daily_summary_persists_rebalance_diagnostics(repo, dummy_market_data, dummy_portfolio):
    """신호의 target_ratio_a·rebalance_threshold가 summary 레코드에 저장돼야 한다."""
    import json
    signal = TradeSignal(1.0, [], "test", target_ratio_a=0.4, rebalance_threshold=0.075)

    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    assert data[0]['target_ratio_a'] == 0.4
    assert data[0]['rebalance_threshold'] == 0.075


def test_save_daily_summary_rebalance_diagnostics_default_none(repo, dummy_market_data, dummy_portfolio):
    """리밸런서를 거치지 않은 신호는 진단값이 None으로 저장된다."""
    import json
    signal = TradeSignal(0.0, [], "데이터 이상")

    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.CRASH)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    assert data[0]['target_ratio_a'] is None
    assert data[0]['rebalance_threshold'] is None


def test_save_daily_summary_default_dividend_zero(repo, dummy_market_data, dummy_portfolio):
    """daily_dividend 미전달 시 기본값 0.0으로 저장되는지 확인"""
    import json
    signal = TradeSignal(1.0, [], "test")

    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)

    assert data[0]['daily_dividend'] == 0.0


def test_repo_simulation_week_trading(repo, dummy_portfolio, dummy_market_data):
    """
    [시나리오] 일주일(7일) 동안 봇이 매일 실행되어 데이터를 쌓는 상황 시뮬레이션
    """
    days = 7
    
    # 1. 7일간의 데이터 누적
    for i in range(days):
        # 날짜를 바꿔가며 데이터 생성
        market_data = MarketData(f"2024-01-0{i+1}", 100+i, 100, 0.1, 0.1, 0, 15)
        signal = TradeSignal(1.0, [], f"Day {i+1}")
        
        # 저장 (Append)
        repo.save_daily_summary(market_data, signal, dummy_portfolio, MarketRegime.BULL)

    # 2. 파일 검증
    with open(repo.summary_file, 'r') as f:
        data = json.load(f)
    
    # 3. 데이터 무결성 확인
    assert len(data) == days # 7개 행이 있어야 함
    assert data[0]['date'] == "2024-01-01" # 첫째 날
    assert data[-1]['date'] == "2024-01-07" # 마지막 날
    assert data[-1]['spy_price'] == 106.0 # 가격 변화 반영 확인

def test_strategy_state_roundtrip(tmp_path):
    from src.infra.repo import JsonRepository
    repo = JsonRepository(str(tmp_path))
    assert repo.load_strategy_state("dip_buy") == {}
    repo.save_strategy_state("dip_buy", {"queue": [], "armed": {"ma20": False}})
    assert repo.load_strategy_state("dip_buy") == {"queue": [], "armed": {"ma20": False}}
    # 다른 key는 영향 없음
    assert repo.load_strategy_state("other") == {}


def test_strategy_state_preserves_other_keys(tmp_path):
    from src.infra.repo import JsonRepository
    repo = JsonRepository(str(tmp_path))
    repo.save_strategy_state("a", {"x": 1})
    repo.save_strategy_state("b", {"y": 2})
    assert repo.load_strategy_state("a") == {"x": 1}
    assert repo.load_strategy_state("b") == {"y": 2}
