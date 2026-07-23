# tests/test_infra_broker_kis.py
import pytest
import logging
from unittest.mock import patch, MagicMock
from src.infra.broker import KisOverseasPaperBroker, KisOverseasLiveBroker, MockBroker
from src.core.models import Order, Portfolio, OrderAction, ExecutionStatus, TradeExecution


# ==========================================
# KisOverseasPaperBroker / KisOverseasLiveBroker 테스트 (외부 API는 모두 Mock)
# ==========================================

@pytest.fixture(autouse=True)
def mock_token_cache():
    """토큰 캐시 파일 I/O를 Mock하여 테스트 간 캐시 간섭 방지"""
    with patch('src.infra.broker.KisBrokerCommon._load_token_from_cache', return_value=None), \
         patch('src.infra.broker.KisBrokerCommon._save_token_to_cache'):
        yield


@pytest.fixture
def mock_requests():
    """requests 모듈 전체를 Mock"""
    with patch('src.infra.broker.requests') as mock_req:
        yield mock_req


@pytest.fixture
def mock_logger():
    return MagicMock()


@pytest.fixture
def paper_broker(mock_requests, mock_logger):
    """KisOverseasPaperBroker 인스턴스 (인증 Mock 포함)"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'test_token_123'}
    mock_requests.post.return_value = auth_response

    broker = KisOverseasPaperBroker(
        app_key='test_key',
        app_secret='test_secret',
        acc_no='1234567890',
        logger=mock_logger
    )
    # post mock 초기화 (auth 호출 후)
    mock_requests.post.reset_mock()
    mock_requests.get.reset_mock()
    return broker


@pytest.fixture
def live_broker(mock_requests, mock_logger):
    """KisOverseasLiveBroker 인스턴스 (인증 Mock 포함)"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'real_token_456'}
    mock_requests.post.return_value = auth_response

    broker = KisOverseasLiveBroker(
        app_key='real_key',
        app_secret='real_secret',
        acc_no='9876543210',
        logger=mock_logger
    )
    mock_requests.post.reset_mock()
    mock_requests.get.reset_mock()
    return broker


# --- __init__ 테스트 ---

def test_kis_paper_broker_init(mock_requests, mock_logger):
    """모의투자 브로커 초기화"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'token123'}
    mock_requests.post.return_value = auth_response

    broker = KisOverseasPaperBroker('key', 'secret', '1234567890', mock_logger)

    assert broker.base_url == "https://openapivts.koreainvestment.com:29443"
    assert broker.PRICE_TR_ID == "HHDFS00000300"
    assert broker.PORTFOLIO_TR_ID == "VTTS3012R"
    assert broker.cano == '12345678'
    assert broker.acnt_prdt_cd == '90'
    assert broker.access_token == 'token123'


def test_kis_live_broker_init(mock_requests, mock_logger):
    """실전투자 브로커 초기화"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'real_token'}
    mock_requests.post.return_value = auth_response

    broker = KisOverseasLiveBroker('key', 'secret', '1234567890', mock_logger)

    assert broker.base_url == "https://openapi.koreainvestment.com:9443"
    assert broker.PRICE_TR_ID == "HHDFS00000300"
    assert broker.PORTFOLIO_TR_ID == "TTTS3012R"
    assert broker.access_token == 'real_token'


# --- _auth 테스트 ---

def test_paper_broker_auth_failure(mock_requests, mock_logger):
    """인증 실패 시 예외 발생"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'error': 'invalid credentials'}
    mock_requests.post.return_value = auth_response

    with pytest.raises(Exception, match="Auth Failed"):
        KisOverseasPaperBroker('bad_key', 'bad_secret', '1234567890', mock_logger)


def test_paper_broker_auth_network_error(mock_requests, mock_logger):
    """인증 중 네트워크 에러"""
    mock_requests.post.side_effect = Exception("Network Error")

    with pytest.raises(Exception, match="Network Error"):
        KisOverseasPaperBroker('key', 'secret', '1234567890', mock_logger)


# --- _get_header / _get_hashkey 테스트 ---

def test_paper_broker_get_header_without_data(paper_broker, mock_requests):
    """데이터 없이 헤더 생성 (GET 요청용)"""
    headers = paper_broker._get_header("HHDFS00000300")

    assert headers['authorization'] == 'Bearer test_token_123'
    assert headers['tr_id'] == 'HHDFS00000300'
    assert headers['appkey'] == 'test_key'
    assert 'hashkey' not in headers


def test_paper_broker_get_header_with_data(paper_broker, mock_requests):
    """데이터 포함 헤더 생성 (POST 요청용, HashKey 포함)"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'abc123hash'}
    mock_requests.post.return_value = hash_response

    data = {"CANO": "12345678", "PDNO": "SPY"}
    headers = paper_broker._get_header("VTTT1002U", data)

    assert headers['hashkey'] == 'abc123hash'
    assert headers['tr_id'] == 'VTTT1002U'


def test_paper_broker_get_hashkey_failure(paper_broker, mock_requests):
    """HashKey 조회 실패 시 None 반환 및 에러 로깅"""
    mock_requests.post.side_effect = Exception("Hash Error")

    result = paper_broker._get_hashkey({"test": "data"})
    assert result is None
    paper_broker.logger.error.assert_called_once()
    call_args = paper_broker.logger.error.call_args[0][0]
    assert "HashKey 생성 실패" in call_args


def test_paper_broker_get_hashkey_failure_logs_error_message(paper_broker, mock_requests):
    """HashKey 조회 실패 시 원인 예외 메시지가 로그에 포함됨"""
    mock_requests.post.side_effect = Exception("Connection timeout")

    paper_broker._get_hashkey({"test": "data"})

    call_args = paper_broker.logger.error.call_args[0][0]
    assert "Connection timeout" in call_args


def test_paper_broker_get_header_raises_on_hashkey_failure(paper_broker, mock_requests):
    """_get_header: hashkey 생성 실패 시 ValueError 발생"""
    mock_requests.post.side_effect = Exception("Hash Error")

    with pytest.raises(ValueError, match="HashKey 생성 실패"):
        paper_broker._get_header("VTTT1002U", {"CANO": "12345678"})


def test_paper_broker_send_order_fails_gracefully_on_hashkey_error(paper_broker, mock_requests):
    """_send_order: hashkey 실패를 ERROR 결과로 보존한다."""
    # 첫 번째 post(hashkey 요청)에서 예외 발생
    mock_requests.post.side_effect = Exception("Hash service down")

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = paper_broker._send_order(order)

    assert result.status == ExecutionStatus.ERROR
    assert "주문 헤더" in result.reason
    paper_broker.logger.error.assert_called()


# --- fetch_current_prices 테스트 ---

@patch('src.infra.broker.time.sleep')
def test_paper_broker_fetch_prices_success(mock_sleep, paper_broker, mock_requests):
    """현재가 조회 성공"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '0',
        'output': {'last': '150.50'}
    }
    mock_requests.get.return_value = price_response

    prices = paper_broker.fetch_current_prices(['SPY', 'IEF'])

    assert prices['SPY'] == 150.50
    assert prices['IEF'] == 150.50
    assert mock_requests.get.call_count == 2


@patch('src.infra.broker.time.sleep')
def test_paper_broker_fetch_prices_api_error(mock_sleep, paper_broker, mock_requests):
    """현재가 조회 API 에러 (rt_cd != 0)"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Invalid ticker'
    }
    mock_requests.get.return_value = price_response

    prices = paper_broker.fetch_current_prices(['INVALID'])

    assert prices['INVALID'] == 0.0
    mock_logger = paper_broker.logger
    mock_logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_fetch_prices_exception(mock_sleep, paper_broker, mock_requests):
    """현재가 조회 중 예외 발생"""
    mock_requests.get.side_effect = Exception("Timeout")

    prices = paper_broker.fetch_current_prices(['SPY'])

    assert prices['SPY'] == 0.0
    paper_broker.logger.error.assert_called()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_fetch_prices_real_mode(mock_sleep, live_broker, mock_requests):
    """실전 모드에서 TR_ID가 올바른지 확인"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '0',
        'output': {'last': '200.00'}
    }
    mock_requests.get.return_value = price_response

    live_broker.fetch_current_prices(['SPY'])

    args, kwargs = mock_requests.get.call_args
    # 실전 TR_ID: HHDFS00000300
    assert kwargs['headers']['tr_id'] == 'HHDFS00000300'


@patch('src.infra.broker.time.sleep')
def test_paper_broker_fetch_prices_uses_overseas_tr_id(mock_sleep, paper_broker, mock_requests):
    """모의투자 모드에서 해외주식 TR_ID(HHDFS00000300)를 사용하는지 확인.
    FHKST01010100(국내주식)이 아닌 HHDFS00000300(해외주식)이어야 한다."""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '0',
        'output': {'last': '150.00'}
    }
    mock_requests.get.return_value = price_response

    paper_broker.fetch_current_prices(['SPY'])

    args, kwargs = mock_requests.get.call_args
    # 모의투자도 해외주식 현재가 TR_ID는 실전과 동일: HHDFS00000300
    assert kwargs['headers']['tr_id'] == 'HHDFS00000300'


# --- get_portfolio 테스트 ---

@patch('src.infra.broker.time.sleep')
def test_paper_broker_get_portfolio_success(mock_sleep, paper_broker, mock_requests):
    """잔고 조회 성공 — NAS/NYS/AMS 3개 거래소 모두 호출"""
    portfolio_response = MagicMock()
    portfolio_response.json.return_value = {
        'rt_cd': '0',
        'output1': [
            {'ovrs_pdno': 'SPY', 'ovrs_cblc_qty': '10', 'now_pric2': '150.0'},
            {'ovrs_pdno': 'IEF', 'ovrs_cblc_qty': '5', 'now_pric2': '100.0'},
            {'ovrs_pdno': 'OLD', 'ovrs_cblc_qty': '0', 'now_pric2': '50.0'},  # 0주 -> 제외
        ],
        'output2': {'ovrs_ord_psbl_amt': '5000.50'}
    }
    mock_requests.get.return_value = portfolio_response

    pf = paper_broker.get_portfolio()

    assert pf.total_cash == 5000.50
    assert pf.holdings['SPY'] == 10
    assert pf.holdings['IEF'] == 5
    assert 'OLD' not in pf.holdings  # 0주는 제외
    assert pf.current_prices['SPY'] == 150.0
    # NAS, NYS, AMS 3개 거래소 모두 조회
    assert mock_requests.get.call_count == 3


@patch('src.infra.broker.time.sleep')
def test_paper_broker_get_portfolio_api_failure(mock_sleep, paper_broker, mock_requests):
    """잔고 조회 API 실패 — 모든 거래소 실패 시 빈 포트폴리오 반환"""
    fail_response = MagicMock()
    fail_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Session Expired'
    }
    mock_requests.get.return_value = fail_response

    pf = paper_broker.get_portfolio()

    assert pf.total_cash == 0
    assert pf.holdings == {}
    # 각 거래소별 warning 로그 확인
    assert paper_broker.logger.warning.call_count == 3


@patch('src.infra.broker.time.sleep')
def test_paper_broker_get_portfolio_exception(mock_sleep, paper_broker, mock_requests):
    """잔고 조회 중 예외 발생"""
    mock_requests.get.side_effect = Exception("Connection Error")

    pf = paper_broker.get_portfolio()

    assert pf.total_cash == 0
    paper_broker.logger.error.assert_called()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_get_portfolio_real_mode(mock_sleep, live_broker, mock_requests):
    """실전 모드에서 TR_ID 확인"""
    portfolio_response = MagicMock()
    portfolio_response.json.return_value = {
        'rt_cd': '0',
        'output1': [],
        'output2': {'ovrs_ord_psbl_amt': '1000.0'}
    }
    mock_requests.get.return_value = portfolio_response

    live_broker.get_portfolio()

    args, kwargs = mock_requests.get.call_args
    assert kwargs['headers']['tr_id'] == 'TTTS3012R'


@patch('src.infra.broker.time.sleep')
def test_paper_broker_get_portfolio_merges_all_exchanges(mock_sleep, paper_broker, mock_requests):
    """NAS/NYS/AMS 거래소별 보유종목이 정상 병합되는지 확인"""
    # NAS: IEF, SHV
    nas_response = MagicMock()
    nas_response.json.return_value = {
        'rt_cd': '0',
        'output1': [
            {'ovrs_pdno': 'IEF', 'ovrs_cblc_qty': '5', 'now_pric2': '100.0'},
            {'ovrs_pdno': 'SHV', 'ovrs_cblc_qty': '3', 'now_pric2': '110.0'},
        ],
        'output2': {'ovrs_ord_psbl_amt': '8000.0'}
    }
    # NYS: GLD
    nys_response = MagicMock()
    nys_response.json.return_value = {
        'rt_cd': '0',
        'output1': [
            {'ovrs_pdno': 'GLD', 'ovrs_cblc_qty': '2', 'now_pric2': '180.0'},
        ],
        'output2': {'ovrs_ord_psbl_amt': '8000.0'}  # 동일 계좌 잔고 (무시됨)
    }
    # AMS: SSO, QLD
    ams_response = MagicMock()
    ams_response.json.return_value = {
        'rt_cd': '0',
        'output1': [
            {'ovrs_pdno': 'SSO', 'ovrs_cblc_qty': '10', 'now_pric2': '55.0'},
            {'ovrs_pdno': 'QLD', 'ovrs_cblc_qty': '8', 'now_pric2': '75.0'},
        ],
        'output2': {'ovrs_ord_psbl_amt': '8000.0'}  # 동일 계좌 잔고 (무시됨)
    }
    mock_requests.get.side_effect = [nas_response, nys_response, ams_response]

    pf = paper_broker.get_portfolio()

    # 예수금은 최초(NAS) 응답에서만 가져옴
    assert pf.total_cash == 8000.0
    # 전 거래소 보유종목 병합 확인
    assert pf.holdings == {'IEF': 5, 'SHV': 3, 'GLD': 2, 'SSO': 10, 'QLD': 8}
    assert pf.current_prices['GLD'] == 180.0
    assert pf.current_prices['SSO'] == 55.0
    assert mock_requests.get.call_count == 3


@patch('src.infra.broker.time.sleep')
def test_paper_broker_get_portfolio_partial_exchange_failure(mock_sleep, paper_broker, mock_requests):
    """일부 거래소 실패 시 성공한 거래소 결과만 반환"""
    # NAS: 성공
    nas_response = MagicMock()
    nas_response.json.return_value = {
        'rt_cd': '0',
        'output1': [{'ovrs_pdno': 'IEF', 'ovrs_cblc_qty': '5', 'now_pric2': '100.0'}],
        'output2': {'ovrs_ord_psbl_amt': '3000.0'}
    }
    # NYS: API 오류
    nys_response = MagicMock()
    nys_response.json.return_value = {'rt_cd': '1', 'msg1': 'Market Closed'}
    # AMS: 성공
    ams_response = MagicMock()
    ams_response.json.return_value = {
        'rt_cd': '0',
        'output1': [{'ovrs_pdno': 'SSO', 'ovrs_cblc_qty': '10', 'now_pric2': '55.0'}],
        'output2': {'ovrs_ord_psbl_amt': '3000.0'}
    }
    mock_requests.get.side_effect = [nas_response, nys_response, ams_response]

    pf = paper_broker.get_portfolio()

    # NAS와 AMS 성공 결과만 포함
    assert pf.total_cash == 3000.0
    assert pf.holdings == {'IEF': 5, 'SSO': 10}
    # NYS 실패에 대한 warning 로그 1회
    assert paper_broker.logger.warning.call_count == 1


@patch('src.infra.broker.time.sleep')
def test_paper_broker_get_portfolio_cash_not_duplicated(mock_sleep, paper_broker, mock_requests):
    """예수금이 3개 거래소 합산이 아닌 최초 성공 응답에서만 가져오는지 확인"""
    # 모든 거래소가 동일한 cash를 반환하더라도 첫 번째 것만 사용
    response = MagicMock()
    response.json.return_value = {
        'rt_cd': '0',
        'output1': [],
        'output2': {'ovrs_ord_psbl_amt': '1000.0'}
    }
    mock_requests.get.return_value = response

    pf = paper_broker.get_portfolio()

    # 1000 * 3 = 3000이 아닌 1000이어야 함
    assert pf.total_cash == 1000.0


@patch('src.infra.broker.time.sleep')
def test_paper_broker_get_portfolio_uses_order_possible_amount(mock_sleep, paper_broker, mock_requests):
    """[#225] total_cash는 ovrs_ord_psbl_amt(해외주문가능금액) — 미체결 예약금 차감 후 가용 금액

    시나리오:
    - 계좌 잔고: $10,000
    - 종목 A 지정가 매수 주문 $3,000 접수 후 미체결 상태
    - KIS API는 ovrs_ord_psbl_amt로 예약금 차감 후 가용 금액($7,000)을 반환
    - total_cash는 $7,000이어야 하며, $10,000(전체 잔고)이 아님을 검증
    """
    response = MagicMock()
    # KIS API가 미체결 예약금($3,000)을 차감한 주문가능금액 $7,000 반환
    response.json.return_value = {
        'rt_cd': '0',
        'output1': [],
        'output2': {'ovrs_ord_psbl_amt': '7000.0'}  # 전체 잔고 $10,000 - 예약금 $3,000
    }
    mock_requests.get.return_value = response

    pf = paper_broker.get_portfolio()

    # total_cash는 전체 잔고($10,000)가 아닌 주문가능금액($7,000)이어야 함
    assert pf.total_cash == 7000.0


# --- _send_order 테스트 ---

def test_paper_broker_send_order_buy_success(paper_broker, mock_requests):
    """매수 주문 전송 성공"""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '0', 'msg1': 'OK'}
    # hashkey도 mock
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = paper_broker._send_order(order)

    assert result is not None
    assert result.ticker == 'SPY'
    assert result.action == OrderAction.BUY
    assert result.quantity == 10
    assert result.status == ExecutionStatus.ORDERED


def test_paper_broker_send_order_sell_success(paper_broker, mock_requests):
    """매도 주문 전송 성공"""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '0', 'msg1': 'OK'}
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash456'}
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.SELL, 5, 150.0)
    result = paper_broker._send_order(order)

    assert result is not None
    assert result.action == OrderAction.SELL


def test_paper_broker_send_order_failure(paper_broker, mock_requests):
    """주문 전송 API 거부를 REJECTED 결과로 보존한다."""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '1', 'msg1': 'Insufficient balance'}
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash'}
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = paper_broker._send_order(order)

    assert result.status == ExecutionStatus.REJECTED
    assert result.reason == "Insufficient balance"
    paper_broker.logger.error.assert_called()


def test_paper_broker_send_order_exception(paper_broker, mock_requests):
    """주문 전송 중 예외를 ERROR 결과로 보존한다."""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash'}
    mock_requests.post.side_effect = [hash_response, Exception("Network Down")]

    order = Order('SPY', OrderAction.BUY, 5, 100.0)
    result = paper_broker._send_order(order)

    assert result.status == ExecutionStatus.ERROR
    assert result.reason == "Network Down"


def test_paper_broker_send_order_real_mode_tr_ids(live_broker, mock_requests):
    """실전 모드 TR_ID 확인 (매수/매도)"""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '0'}
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'h'}

    # 매수
    mock_requests.post.side_effect = [hash_response, order_response]
    buy_order = Order('SPY', OrderAction.BUY, 1, 100.0)
    live_broker._send_order(buy_order)
    # 두 번째 post call의 headers에서 tr_id 확인
    call_args = mock_requests.post.call_args_list[1]
    assert call_args[1]['headers']['tr_id'] == 'TTTT1002U'

    mock_requests.post.reset_mock()
    mock_requests.post.side_effect = [hash_response, order_response]
    # 매도
    sell_order = Order('SPY', OrderAction.SELL, 1, 100.0)
    live_broker._send_order(sell_order)
    call_args = mock_requests.post.call_args_list[1]
    assert call_args[1]['headers']['tr_id'] == 'TTTT1006U'


# --- execute_orders 테스트 ---

@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_sell_then_buy(mock_sleep, paper_broker, mock_requests):
    """매도 후 매수 순서 실행"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf, \
         patch.object(paper_broker, '_fetch_asking_price', return_value=(100.0, 100.3)):

        from src.core.models import TradeExecution
        sell_exec = TradeExecution('SPY', OrderAction.SELL, 5, 150.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        buy_exec = TradeExecution('IEF', OrderAction.BUY, 10, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        mock_send.side_effect = [sell_exec, buy_exec]

        mock_get_pf.return_value = Portfolio(
            total_cash=10000.0,
            holdings={'SPY': 5},
            current_prices={'SPY': 150.0}
        )

        orders = [
            Order('SPY', OrderAction.SELL, 5, 150.0),
            Order('IEF', OrderAction.BUY, 10, 100.0),
        ]
        executions = paper_broker.execute_orders(orders)

        assert len(executions) == 2
        assert mock_send.call_count == 2


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_only(mock_sleep, paper_broker, mock_requests):
    """매수만 있는 경우"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf, \
         patch.object(paper_broker, '_fetch_asking_price', return_value=(100.0, 100.3)):

        from src.core.models import TradeExecution
        buy_exec = TradeExecution('SPY', OrderAction.BUY, 5, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        mock_send.return_value = buy_exec
        mock_get_pf.return_value = Portfolio(
            total_cash=50000.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 5, 100.0)]
        executions = paper_broker.execute_orders(orders)

        assert len(executions) == 1


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_qty_adjusted(mock_sleep, paper_broker, mock_requests):
    """매수 시 잔고 부족으로 수량 조정"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf, \
         patch.object(paper_broker, '_fetch_asking_price', return_value=(100.0, 100.3)):

        from src.core.models import TradeExecution
        buy_exec = TradeExecution('SPY', OrderAction.BUY, 1, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        mock_send.return_value = buy_exec
        # 현금이 적어서 수량이 조정되어야 함
        mock_get_pf.return_value = Portfolio(
            total_cash=200.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 100, 100.0)]  # 100주 요청하지만 돈이 부족
        executions = paper_broker.execute_orders(orders)

        # 수량이 조정되어 실행됨 (200*0.98/101 = 1주)
        assert len(executions) == 1
        paper_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_zero_price(mock_sleep, paper_broker, mock_requests):
    """매수 가격이 0인 경우 스킵"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        mock_get_pf.return_value = Portfolio(
            total_cash=10000.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 10, 0.0)]  # 가격 0
        executions = paper_broker.execute_orders(orders)

        assert len(executions) == 0
        mock_send.assert_not_called()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_zero_qty_after_adjust(mock_sleep, paper_broker, mock_requests):
    """수량 조정 후 0이 되면 주문 안 함"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        mock_get_pf.return_value = Portfolio(
            total_cash=10.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 10, 500.0)]  # 수량 조정 후 0
        executions = paper_broker.execute_orders(orders)

        assert len(executions) == 0


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_sell_timeout(mock_sleep, paper_broker, mock_requests):
    """매도 체결 대기 타임아웃 시 ORDERED 반환"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send:
        from src.core.models import TradeExecution
        # _send_order_and_wait 자체가 타임아웃 시 ORDERED 반환
        sell_exec = TradeExecution('SPY', OrderAction.SELL, 5, 150.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
        mock_send.return_value = sell_exec

        orders = [Order('SPY', OrderAction.SELL, 5, 150.0)]
        executions = paper_broker.execute_orders(orders)

        # 타임아웃이어도 실행 결과는 반환
        assert len(executions) == 1


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_sell_then_buy_calls_sleep2(mock_sleep, paper_broker, mock_requests):
    """매도 후 매수 시 정산 대기 sleep(2) 호출 확인"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        from src.core.models import TradeExecution
        sell_exec = TradeExecution('SPY', OrderAction.SELL, 5, 150.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        buy_exec = TradeExecution('IEF', OrderAction.BUY, 10, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        mock_send.side_effect = [sell_exec, buy_exec]
        mock_get_pf.return_value = Portfolio(
            total_cash=10000.0, holdings={}, current_prices={}
        )

        orders = [
            Order('SPY', OrderAction.SELL, 5, 150.0),
            Order('IEF', OrderAction.BUY, 10, 100.0),
        ]
        paper_broker.execute_orders(orders)

        # 매도가 있으므로 sleep(2) 호출되어야 함
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert 2 in sleep_calls, "매도+매수 시 sleep(2)가 호출되어야 합니다"


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_only_no_sleep2(mock_sleep, paper_broker, mock_requests):
    """매수만 있는 경우 정산 대기 sleep(2) 미호출 확인"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        from src.core.models import TradeExecution
        buy_exec = TradeExecution('IEF', OrderAction.BUY, 10, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        mock_send.return_value = buy_exec
        mock_get_pf.return_value = Portfolio(
            total_cash=10000.0, holdings={}, current_prices={}
        )

        orders = [Order('IEF', OrderAction.BUY, 10, 100.0)]
        paper_broker.execute_orders(orders)

        # 매도가 없으므로 sleep(2) 호출되지 않아야 함
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert 2 not in sleep_calls, "매수만 있을 때 sleep(2)는 호출되면 안 됩니다"


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_send_order_returns_none(mock_sleep, paper_broker, mock_requests):
    """_send_order_and_wait가 None을 반환하는 경우 (주문 실패)"""
    with patch.object(paper_broker, '_send_order_and_wait', return_value=None) as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        mock_get_pf.return_value = Portfolio(
            total_cash=50000.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 5, 100.0)]
        executions = paper_broker.execute_orders(orders)

        assert len(executions) == 0


# --- _wait_for_completion 테스트 ---

@patch('src.infra.broker.time.sleep')
@patch('src.infra.broker.time.time')
def test_paper_broker_wait_completion_success(mock_time, mock_sleep, paper_broker):
    """체결 대기 성공 (미체결 0)"""
    mock_time.side_effect = [0, 1]  # 시작, 루프 1회
    with patch.object(paper_broker, '_get_pending_orders_count', return_value=0):
        result = paper_broker._wait_for_completion(timeout=60)
        assert result is True


@patch('src.infra.broker.time.sleep')
@patch('src.infra.broker.time.time')
def test_paper_broker_wait_completion_timeout(mock_time, mock_sleep, paper_broker):
    """체결 대기 타임아웃"""
    # time.time()이 계속 증가하여 timeout 초과
    mock_time.side_effect = [0, 10, 30, 61]
    with patch.object(paper_broker, '_get_pending_orders_count', return_value=5):
        result = paper_broker._wait_for_completion(timeout=60)
        assert result is False


# --- _get_pending_orders_count 테스트 ---

@patch('src.infra.broker.time.sleep')
def test_paper_broker_pending_orders_found(mock_sleep, paper_broker, mock_requests):
    """미체결 내역 발견"""
    pending_response = MagicMock()
    pending_response.json.return_value = {
        'rt_cd': '0',
        'output': [{'order_id': '1'}, {'order_id': '2'}]
    }
    mock_requests.get.return_value = pending_response

    count = paper_broker._get_pending_orders_count()

    assert count == 2


@patch('src.infra.broker.time.sleep')
def test_paper_broker_pending_orders_none(mock_sleep, paper_broker, mock_requests):
    """미체결 내역 없음 (모든 거래소 조회)"""
    empty_response = MagicMock()
    empty_response.json.return_value = {
        'rt_cd': '0',
        'output': []
    }
    mock_requests.get.return_value = empty_response

    count = paper_broker._get_pending_orders_count()

    assert count == 0
    # NAS, NYS, AMS 3개 거래소 모두 조회
    assert mock_requests.get.call_count == 3


@patch('src.infra.broker.time.sleep')
def test_paper_broker_pending_orders_api_error(mock_sleep, paper_broker, mock_requests):
    """미체결 조회 API 에러"""
    error_response = MagicMock()
    error_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Service unavailable'
    }
    mock_requests.get.return_value = error_response

    count = paper_broker._get_pending_orders_count()

    assert count == 0
    paper_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_pending_orders_exception(mock_sleep, paper_broker, mock_requests):
    """미체결 조회 중 예외"""
    mock_requests.get.side_effect = Exception("Connection Reset")

    count = paper_broker._get_pending_orders_count()

    assert count == 0
    paper_broker.logger.error.assert_called()


# --- _get_exchange_code 테스트 ---

def test_paper_broker_exchange_code_mapping(paper_broker):
    """거래소 코드 매핑 확인"""
    assert paper_broker._get_exchange_code('SPY') == 'AMS'
    assert paper_broker._get_exchange_code('QLD') == 'AMS'
    assert paper_broker._get_exchange_code('SSO') == 'AMS'
    assert paper_broker._get_exchange_code('IEF') == 'NAS'
    assert paper_broker._get_exchange_code('GLD') == 'NYS'
    assert paper_broker._get_exchange_code('PDBC') == 'NAS'
    assert paper_broker._get_exchange_code('SHV') == 'NAS'


def test_paper_broker_exchange_code_default(paper_broker):
    """매핑에 없는 티커는 기본값 NAS"""
    assert paper_broker._get_exchange_code('UNKNOWN') == 'NAS'
    assert paper_broker._get_exchange_code('AAPL') == 'NAS'


def test_paper_broker_exchange_code_unknown_logs_warning(paper_broker):
    """매핑에 없는 티커 사용 시 경고 로그 출력"""
    paper_broker._get_exchange_code('UNKNOWN_TICKER')
    paper_broker.logger.warning.assert_called_once()
    call_args = paper_broker.logger.warning.call_args[0][0]
    assert 'UNKNOWN_TICKER' in call_args
    assert 'TICKER_EXCHANGE_MAP' in call_args


def test_paper_broker_exchange_code_order_mapping(paper_broker):
    """order api_type 시 전체 코드 반환"""
    assert paper_broker._get_exchange_code('SPY', api_type='order') == 'AMEX'
    assert paper_broker._get_exchange_code('IEF', api_type='order') == 'NASD'
    assert paper_broker._get_exchange_code('GLD', api_type='order') == 'NYSE'
    assert paper_broker._get_exchange_code('UNKNOWN', api_type='order') == 'NASD'


# --- MockBroker 추가 테스트 ---

def test_mock_broker_fetch_current_prices():
    """MockBroker.fetch_current_prices가 항상 100.0을 반환"""
    broker = MockBroker(initial_cash=1000.0)
    prices = broker.fetch_current_prices(['SPY', 'IEF', 'GLD'])

    assert prices == {'SPY': 100.0, 'IEF': 100.0, 'GLD': 100.0}


@patch('src.infra.broker.time.sleep')
def test_mock_broker_wait_for_completion(mock_sleep):
    """MockBroker._wait_for_completion은 항상 True (미체결 0)"""
    broker = MockBroker(initial_cash=1000.0)
    result = broker._wait_for_completion(timeout=5)
    assert result is True


def test_mock_broker_buy_price_zero():
    """매수 가격이 0인 경우 스킵"""
    broker = MockBroker(initial_cash=1000.0)
    orders = [Order('SPY', OrderAction.BUY, 10, 0.0)]
    executions = broker.execute_orders(orders)
    assert len(executions) == 0


# --- #222 execute_orders 매수 로직 개선 테스트 ---

@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_calls_send_order_and_wait(mock_sleep, paper_broker, mock_requests):
    """[#222] 매수 주문 시 _send_order_and_wait이 호출되어야 함"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf, \
         patch.object(paper_broker, '_fetch_asking_price', return_value=(100.0, 100.3)):

        buy_exec = TradeExecution('SPY', OrderAction.BUY, 5, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        mock_send.return_value = buy_exec
        mock_get_pf.return_value = Portfolio(total_cash=50000.0, holdings={}, current_prices={})

        paper_broker.execute_orders([Order('SPY', OrderAction.BUY, 5, 100.0)])

        mock_send.assert_called_once()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_ordered_status_on_timeout(mock_sleep, paper_broker, mock_requests):
    """[#222] 매수 체결 대기 타임아웃 시 ORDERED 상태로 반환"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf, \
         patch.object(paper_broker, '_fetch_asking_price', return_value=(100.0, 100.3)):

        # _send_order_and_wait 자체가 타임아웃 시 ORDERED 반환
        buy_exec = TradeExecution('SPY', OrderAction.BUY, 5, 100.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
        mock_send.return_value = buy_exec
        mock_get_pf.return_value = Portfolio(total_cash=50000.0, holdings={}, current_prices={})

        executions = paper_broker.execute_orders([Order('SPY', OrderAction.BUY, 5, 100.0)])

        assert len(executions) == 1
        assert executions[0].status == ExecutionStatus.ORDERED


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_calls_get_portfolio_per_order(mock_sleep, paper_broker, mock_requests):
    """[#222] 매수 주문마다 get_portfolio()를 호출하여 실제 가용 금액 조회"""
    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        buy_exec_spy = TradeExecution('SPY', OrderAction.BUY, 5, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        buy_exec_ief = TradeExecution('IEF', OrderAction.BUY, 3, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
        mock_send.side_effect = [buy_exec_spy, buy_exec_ief]
        mock_get_pf.return_value = Portfolio(total_cash=50000.0, holdings={}, current_prices={})

        orders = [
            Order('SPY', OrderAction.BUY, 5, 100.0),
            Order('IEF', OrderAction.BUY, 3, 100.0),
        ]
        paper_broker.execute_orders(orders)

        # 매수 주문 2건이면 get_portfolio도 2번 호출되어야 함
        assert mock_get_pf.call_count == 2


# --- _ensure_token / 토큰 만료 처리 테스트 ---

from datetime import datetime, timedelta


def test_auth_stores_token_expires_at(mock_requests, mock_logger):
    """_auth 호출 시 token_expires_at이 설정됨"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'tok', 'expires_in': 3600}
    mock_requests.post.return_value = auth_response

    broker = KisOverseasPaperBroker('k', 's', '1234567890', mock_logger)

    assert broker.token_expires_at is not None
    # 약 3600초 후 만료 (오차 5초 허용)
    expected = datetime.now() + timedelta(seconds=3600)
    assert abs((broker.token_expires_at - expected).total_seconds()) < 5


def test_auth_uses_default_expires_in_when_missing(mock_requests, mock_logger):
    """expires_in 필드 없을 때 기본값 86400초 적용"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'tok'}
    mock_requests.post.return_value = auth_response

    broker = KisOverseasPaperBroker('k', 's', '1234567890', mock_logger)

    expected = datetime.now() + timedelta(seconds=86400)
    assert abs((broker.token_expires_at - expected).total_seconds()) < 5


def test_ensure_token_refreshes_when_expired(paper_broker, mock_requests):
    """토큰이 만료된 경우 _ensure_token이 _auth를 재호출"""
    # 토큰을 이미 만료된 상태로 설정
    paper_broker.token_expires_at = datetime.now() - timedelta(seconds=1)

    new_auth_response = MagicMock()
    new_auth_response.json.return_value = {'access_token': 'new_token', 'expires_in': 86400}
    mock_requests.post.return_value = new_auth_response

    paper_broker._ensure_token()

    assert paper_broker.access_token == 'new_token'
    paper_broker.logger.info.assert_any_call("[KisBroker] Access Token 갱신 중...")


def test_ensure_token_refreshes_within_60s_buffer(paper_broker, mock_requests):
    """만료 59초 전이면 미리 갱신"""
    paper_broker.token_expires_at = datetime.now() + timedelta(seconds=59)

    new_auth_response = MagicMock()
    new_auth_response.json.return_value = {'access_token': 'refreshed_token', 'expires_in': 86400}
    mock_requests.post.return_value = new_auth_response

    paper_broker._ensure_token()

    assert paper_broker.access_token == 'refreshed_token'


def test_ensure_token_does_not_refresh_when_valid(paper_broker, mock_requests):
    """유효한 토큰은 갱신하지 않음"""
    paper_broker.token_expires_at = datetime.now() + timedelta(seconds=3600)
    original_token = paper_broker.access_token

    paper_broker._ensure_token()

    assert paper_broker.access_token == original_token
    mock_requests.post.assert_not_called()


def test_get_header_triggers_token_refresh_when_expired(paper_broker, mock_requests):
    """_get_header 호출 시 토큰이 만료됐으면 자동 갱신 후 헤더에 새 토큰 반영"""
    paper_broker.token_expires_at = datetime.now() - timedelta(seconds=1)

    new_auth_response = MagicMock()
    new_auth_response.json.return_value = {'access_token': 'fresh_token', 'expires_in': 86400}
    mock_requests.post.return_value = new_auth_response

    headers = paper_broker._get_header("HHDFS00000300")

    assert headers['authorization'] == 'Bearer fresh_token'


# --- raise_for_status 검증 테스트 (Issue #213) ---

def test_auth_raise_for_status_on_http_error(mock_requests, mock_logger):
    """_auth: HTTP 에러 응답(500 등) 시 예외가 전파됨"""
    auth_response = MagicMock()
    auth_response.raise_for_status.side_effect = Exception("500 Server Error")
    mock_requests.post.return_value = auth_response

    with pytest.raises(Exception, match="500 Server Error"):
        KisOverseasPaperBroker('key', 'secret', '1234567890', mock_logger)


def test_get_hashkey_raise_for_status_on_http_error(paper_broker, mock_requests):
    """_get_hashkey: HTTP 에러 응답 시 None 반환 및 에러 로깅"""
    hash_response = MagicMock()
    hash_response.raise_for_status.side_effect = Exception("429 Too Many Requests")
    mock_requests.post.return_value = hash_response

    result = paper_broker._get_hashkey({"test": "data"})

    assert result is None
    paper_broker.logger.error.assert_called()


@patch('src.infra.broker.time.sleep')
def test_fetch_prices_raise_for_status_on_http_error(mock_sleep, paper_broker, mock_requests):
    """fetch_current_prices: HTTP 에러 응답 시 해당 티커 가격 0.0 반환"""
    price_response = MagicMock()
    price_response.raise_for_status.side_effect = Exception("503 Service Unavailable")
    mock_requests.get.return_value = price_response

    prices = paper_broker.fetch_current_prices(['SPY'])

    assert prices['SPY'] == 0.0
    paper_broker.logger.error.assert_called()


@patch('src.infra.broker.time.sleep')
def test_get_portfolio_raise_for_status_on_http_error(mock_sleep, paper_broker, mock_requests):
    """get_portfolio: HTTP 에러 응답 시 에러 로깅 후 빈 포트폴리오 반환"""
    portfolio_response = MagicMock()
    portfolio_response.raise_for_status.side_effect = Exception("500 Internal Server Error")
    mock_requests.get.return_value = portfolio_response

    pf = paper_broker.get_portfolio()

    assert pf.total_cash == 0.0
    assert pf.holdings == {}
    paper_broker.logger.error.assert_called()


def test_send_order_raise_for_status_on_http_error(paper_broker, mock_requests):
    """_send_order: HTTP 에러 응답을 ERROR 결과로 보존하고 로깅한다."""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    order_response = MagicMock()
    order_response.raise_for_status.side_effect = Exception("429 Rate Limit Exceeded")
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = paper_broker._send_order(order)

    assert result.status == ExecutionStatus.ERROR
    assert "429 Rate Limit" in result.reason
    paper_broker.logger.error.assert_called()


@patch('src.infra.broker.time.sleep')
def test_pending_orders_raise_for_status_on_http_error(mock_sleep, paper_broker, mock_requests):
    """_get_pending_orders_count: HTTP 에러 응답 시 에러 로깅 후 0 반환"""
    pending_response = MagicMock()
    pending_response.raise_for_status.side_effect = Exception("500 Server Error")
    mock_requests.get.return_value = pending_response

    count = paper_broker._get_pending_orders_count()

    assert count == 0
    paper_broker.logger.error.assert_called()


# ==========================================
# FILL_TR_ID 상수 테스트
# ==========================================

def test_paper_broker_fill_tr_id(paper_broker):
    """모의투자 브로커 체결내역 TR_ID 확인"""
    assert paper_broker.FILL_TR_ID == "VTTS3035R"


def test_live_broker_fill_tr_id(live_broker):
    """실전투자 브로커 체결내역 TR_ID 확인"""
    assert live_broker.FILL_TR_ID == "TTTS3035R"


# ==========================================
# _get_pending_order_ids 테스트
# ==========================================

@patch('src.infra.broker.time.sleep')
def test_get_pending_order_ids_success(mock_sleep, paper_broker, mock_requests):
    """미체결 주문번호 집합 반환 성공"""
    pending_response = MagicMock()
    pending_response.json.return_value = {
        'rt_cd': '0',
        'output': [
            {'odno': 'ORD001', 'pdno': 'SPY'},
            {'odno': 'ORD002', 'pdno': 'IEF'},
        ]
    }
    mock_requests.get.return_value = pending_response

    result = paper_broker._get_pending_order_ids("NASD")

    assert result == {'ORD001', 'ORD002'}


@patch('src.infra.broker.time.sleep')
def test_get_pending_order_ids_empty(mock_sleep, paper_broker, mock_requests):
    """미체결 주문 없을 때 빈 집합 반환"""
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '0', 'output': []}
    mock_requests.get.return_value = pending_response

    result = paper_broker._get_pending_order_ids("NASD")

    assert result == set()


@patch('src.infra.broker.time.sleep')
def test_get_pending_order_ids_api_error(mock_sleep, paper_broker, mock_requests):
    """API 오류 시 빈 집합 반환"""
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '1', 'msg1': 'Error'}
    mock_requests.get.return_value = pending_response

    result = paper_broker._get_pending_order_ids("NASD")

    assert result == set()


# ==========================================
# _poll_order_fill 테스트
# ==========================================

@patch('src.infra.broker.time.sleep')
def test_poll_order_fill_filled_immediately(mock_sleep, paper_broker, mock_requests):
    """첫 번째 polling에서 ODNO가 미체결 목록에 없으면 즉시 True 반환"""
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '0', 'output': []}
    mock_requests.get.return_value = pending_response

    result = paper_broker._poll_order_fill('ORD001', 'NASD', timeout=10)

    assert result is True


@patch('src.infra.broker.time.time')
@patch('src.infra.broker.time.sleep')
def test_poll_order_fill_timeout(mock_sleep, mock_time, paper_broker, mock_requests):
    """타임아웃 시 False 반환"""
    # time.time() 첫 호출: start=0, 이후: 0, 31, 31 (timeout=30 초과)
    mock_time.side_effect = [0, 0, 31]
    pending_response = MagicMock()
    pending_response.json.return_value = {
        'rt_cd': '0',
        'output': [{'odno': 'ORD001'}]
    }
    mock_requests.get.return_value = pending_response

    result = paper_broker._poll_order_fill('ORD001', 'NASD', timeout=30)

    assert result is False


@patch('src.infra.broker.time.sleep')
def test_poll_order_fill_filled_after_retry(mock_sleep, paper_broker, mock_requests):
    """두 번째 polling에서 ODNO가 사라져 True 반환"""
    still_pending = MagicMock()
    still_pending.json.return_value = {
        'rt_cd': '0',
        'output': [{'odno': 'ORD001'}]
    }
    now_filled = MagicMock()
    now_filled.json.return_value = {'rt_cd': '0', 'output': []}
    mock_requests.get.side_effect = [still_pending, now_filled]

    result = paper_broker._poll_order_fill('ORD001', 'NASD', timeout=30)

    assert result is True


@patch('src.infra.broker.time.sleep')
def test_poll_order_fill_warning_on_exception(mock_sleep, paper_broker, mock_requests):
    """polling 중 예외 발생 시 warning 로깅 후 계속 시도"""
    mock_requests.get.side_effect = [Exception("Network Error"), MagicMock(**{
        'json.return_value': {'rt_cd': '0', 'output': []}
    })]

    result = paper_broker._poll_order_fill('ORD001', 'NASD', timeout=30)

    assert result is True
    paper_broker.logger.warning.assert_called()


# ==========================================
# _query_fill_details 테스트
# ==========================================

def test_query_fill_details_no_fill_tr_id(paper_broker):
    """FILL_TR_ID 미설정 시 즉시 (0.0, 0, 0.0) 반환"""
    paper_broker.FILL_TR_ID = ""

    result = paper_broker._query_fill_details('ORD001', 'SPY', 'NASD')

    assert result == (0.0, 0, 0.0)


@patch('src.infra.broker.time.sleep')
def test_query_fill_details_success(mock_sleep, paper_broker, mock_requests):
    """체결내역 조회 성공 — 실제 체결가/수량/수수료 반환"""
    fill_response = MagicMock()
    fill_response.json.return_value = {
        'rt_cd': '0',
        'output': [
            {'odno': 'ORD001', 'ft_ccld_unpr3': '151.25', 'ft_ccld_qty': '10', 'ovrs_stck_ccld_fee': '0.50'},
            {'odno': 'ORD002', 'ft_ccld_unpr3': '200.00', 'ft_ccld_qty': '5', 'ovrs_stck_ccld_fee': '0.30'},
        ]
    }
    mock_requests.get.return_value = fill_response

    price, qty, fee = paper_broker._query_fill_details('ORD001', 'SPY', 'NASD')

    assert price == 151.25
    assert qty == 10
    assert fee == 0.50


@patch('src.infra.broker.time.sleep')
def test_query_fill_details_odno_not_found(mock_sleep, paper_broker, mock_requests):
    """ODNO가 체결내역에 없을 때 (0.0, 0, 0.0) 반환"""
    fill_response = MagicMock()
    fill_response.json.return_value = {
        'rt_cd': '0',
        'output': [{'odno': 'ORD999', 'ft_ccld_unpr3': '100.00', 'ft_ccld_qty': '1', 'ovrs_stck_ccld_fee': '0.1'}]
    }
    mock_requests.get.return_value = fill_response

    result = paper_broker._query_fill_details('ORD001', 'SPY', 'NASD')

    assert result == (0.0, 0, 0.0)


@patch('src.infra.broker.time.sleep')
def test_query_fill_details_api_error(mock_sleep, paper_broker, mock_requests):
    """체결내역 API 오류 시 (0.0, 0, 0.0) 반환"""
    fill_response = MagicMock()
    fill_response.json.return_value = {'rt_cd': '1', 'msg1': 'Error'}
    mock_requests.get.return_value = fill_response

    result = paper_broker._query_fill_details('ORD001', 'SPY', 'NASD')

    assert result == (0.0, 0, 0.0)


@patch('src.infra.broker.time.sleep')
def test_query_fill_details_exception(mock_sleep, paper_broker, mock_requests):
    """체결내역 조회 중 예외 발생 시 warning 로깅 후 (0.0, 0, 0.0) 반환"""
    mock_requests.get.side_effect = Exception("Timeout")

    result = paper_broker._query_fill_details('ORD001', 'SPY', 'NASD')

    assert result == (0.0, 0, 0.0)
    paper_broker.logger.warning.assert_called()


# ==========================================
# _send_order_and_wait 테스트
# ==========================================

@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_filled_with_actual_price(mock_sleep, paper_broker, mock_requests):
    """주문 전송 후 체결 완료 — 실제 체결가로 FILLED TradeExecution 반환"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}

    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'ORD123'}
    }

    # _get_pending_order_ids: 빈 집합 (이미 체결됨)
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '0', 'output': []}

    # _query_fill_details: 실제 체결가
    fill_response = MagicMock()
    fill_response.json.return_value = {
        'rt_cd': '0',
        'output': [
            {'odno': 'ORD123', 'ft_ccld_unpr3': '152.50', 'ft_ccld_qty': '10', 'ovrs_stck_ccld_fee': '0.75'}
        ]
    }

    # 호가 조회 응답 (_fetch_asking_price가 먼저 호출됨)
    # 스프레드 0.5% 이하: bid=150.10, ask=150.50 → spread≈0.266%
    asking_price_response = MagicMock()
    asking_price_response.json.return_value = {
        'rt_cd': '0',
        'output2': {'pbid1': '150.10', 'pask1': '150.50'}
    }

    # hashkey POST → order POST 순서로 side_effect 설정
    mock_requests.post.side_effect = [hash_response, order_response]
    mock_requests.get.side_effect = [asking_price_response, pending_response, fill_response]

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = paper_broker._send_order_and_wait(order, timeout=30)

    assert result is not None
    assert result.status == ExecutionStatus.FILLED
    assert result.price == 152.50
    assert result.quantity == 10
    assert result.fee == 0.75


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_timeout_returns_ordered(mock_sleep, paper_broker, mock_requests):
    """체결 대기 타임아웃 시 ORDERED(미확인 체결) 반환"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}

    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'ORD456'}
    }
    mock_requests.post.return_value = hash_response

    # _poll_order_fill을 직접 mock하여 항상 False 반환
    with patch.object(paper_broker, '_poll_order_fill', return_value=False):
        mock_requests.post.return_value = order_response
        mock_requests.post.side_effect = None
        # hash + order POST mock
        mock_requests.post.side_effect = [hash_response, order_response]

        order = Order('SPY', OrderAction.BUY, 10, 150.0)
        result = paper_broker._send_order_and_wait(order, timeout=1)

    assert result is not None
    assert result.status == ExecutionStatus.ORDERED
    assert result.price == 150.0
    paper_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_no_odno_returns_ordered(mock_sleep, paper_broker, mock_requests):
    """ODNO 미반환 시 ORDERED 반환 (polling 건너뜀)"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}

    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {}  # ODNO 없음
    }
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.BUY, 5, 200.0)
    result = paper_broker._send_order_and_wait(order, timeout=30)

    assert result is not None
    assert result.status == ExecutionStatus.ORDERED
    assert result.quantity == 5


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_api_failure_returns_rejected(mock_sleep, paper_broker, mock_requests):
    """주문 API 거부 시 REJECTED와 사유를 반환한다."""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}

    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '1', 'msg1': 'Insufficient balance'}
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = paper_broker._send_order_and_wait(order, timeout=30)

    assert result.status == ExecutionStatus.REJECTED
    assert result.reason == "Insufficient balance"
    paper_broker.logger.error.assert_called()


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_fill_details_fallback_to_order_price(mock_sleep, paper_broker, mock_requests):
    """체결내역 조회 실패 시 주문가로 fallback하여 FILLED 반환"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}

    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'ORD789'}
    }
    mock_requests.post.side_effect = [hash_response, order_response]

    with patch.object(paper_broker, '_poll_order_fill', return_value=True), \
         patch.object(paper_broker, '_query_fill_details', return_value=(0.0, 0, 0.0)):
        order = Order('IEF', OrderAction.SELL, 3, 99.50)
        result = paper_broker._send_order_and_wait(order, timeout=30)

    assert result is not None
    assert result.status == ExecutionStatus.FILLED
    assert result.price == 99.50  # 주문가로 fallback
    assert result.quantity == 3   # 주문 수량으로 fallback


# --- _cancel_order 테스트 (#227) ---

def test_cancel_order_success(paper_broker, mock_requests):
    """주문 취소 성공"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash_cancel'}

    cancel_response = MagicMock()
    cancel_response.json.return_value = {'rt_cd': '0', 'output': {}}
    mock_requests.post.side_effect = [hash_response, cancel_response]

    result = paper_broker._cancel_order('ORD001', 'NASD', 'SPY', 5)

    assert result is True
    paper_broker.logger.info.assert_called()


def test_cancel_order_api_failure(paper_broker, mock_requests):
    """주문 취소 API 오류 응답"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash_cancel'}

    cancel_response = MagicMock()
    cancel_response.json.return_value = {'rt_cd': '1', 'msg1': '취소 불가'}
    mock_requests.post.side_effect = [hash_response, cancel_response]

    result = paper_broker._cancel_order('ORD002', 'NASD', 'SPY', 5)

    assert result is False
    paper_broker.logger.error.assert_called()


def test_cancel_order_network_exception(paper_broker, mock_requests):
    """주문 취소 중 네트워크 예외"""
    mock_requests.post.side_effect = Exception("Connection error")

    result = paper_broker._cancel_order('ORD003', 'NASD', 'SPY', 5)

    assert result is False
    paper_broker.logger.error.assert_called()


def test_cancel_order_no_cancel_tr_id(paper_broker):
    """CANCEL_TR_ID 미설정 시 False 반환"""
    paper_broker.CANCEL_TR_ID = ""

    result = paper_broker._cancel_order('ORD004', 'NASD', 'SPY', 5)

    assert result is False
    paper_broker.logger.warning.assert_called()


# --- _send_order_and_wait 타임아웃 시 취소 테스트 (#227) ---

@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_timeout_calls_cancel(mock_sleep, paper_broker, mock_requests):
    """타임아웃 시 _cancel_order 호출"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}

    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '0', 'output': {'ODNO': 'ORD999'}}
    mock_requests.post.side_effect = [hash_response, order_response]

    with patch.object(paper_broker, '_poll_order_fill', return_value=False), \
         patch.object(paper_broker, '_cancel_order', return_value=True) as mock_cancel:
        order = Order('SPY', OrderAction.SELL, 5, 150.0)
        result = paper_broker._send_order_and_wait(order, timeout=30)

    mock_cancel.assert_called_once_with('ORD999', 'AMEX', 'SPY', 5)
    assert result is not None
    assert result.status == ExecutionStatus.CANCELLED


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_timeout_cancel_fails_logs_error(mock_sleep, paper_broker, mock_requests):
    """타임아웃 후 취소 실패 시 error 로그"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}

    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '0', 'output': {'ODNO': 'ORD999'}}
    mock_requests.post.side_effect = [hash_response, order_response]

    with patch.object(paper_broker, '_poll_order_fill', return_value=False), \
         patch.object(paper_broker, '_cancel_order', return_value=False):
        order = Order('SPY', OrderAction.SELL, 5, 150.0)
        paper_broker._send_order_and_wait(order, timeout=30)

    paper_broker.logger.error.assert_called()


# --- execute_orders 매도 타임아웃 시 매수 차단 테스트 (#227) ---

@patch('src.infra.broker.time.sleep')
def test_execute_orders_sell_timeout_blocks_buy(mock_sleep, paper_broker, mock_requests):
    """매도 ORDERED(타임아웃) 시 매수 실행 차단"""
    sell_exec = TradeExecution('SPY', OrderAction.SELL, 5, 150.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
    buy_exec = TradeExecution('IEF', OrderAction.BUY, 10, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)

    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:
        mock_send.side_effect = [sell_exec, buy_exec]
        mock_get_pf.return_value = Portfolio(total_cash=10000.0, holdings={}, current_prices={})

        orders = [
            Order('SPY', OrderAction.SELL, 5, 150.0),
            Order('IEF', OrderAction.BUY, 10, 100.0),
        ]
        executions = paper_broker.execute_orders(orders)

    # 매수 주문은 실행되지 않아야 함
    assert len(executions) == 1
    assert executions[0].action == OrderAction.SELL
    assert mock_send.call_count == 1  # 매도만 호출됨
    paper_broker.logger.error.assert_called()


@patch('src.infra.broker.time.sleep')
def test_execute_orders_sell_filled_proceeds_to_buy(mock_sleep, paper_broker, mock_requests):
    """매도 FILLED 시 정상적으로 매수 진행"""
    sell_exec = TradeExecution('SPY', OrderAction.SELL, 5, 150.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)
    buy_exec = TradeExecution('IEF', OrderAction.BUY, 10, 100.0, 0.0, '2024-01-01', ExecutionStatus.FILLED)

    with patch.object(paper_broker, '_send_order_and_wait') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf, \
         patch.object(paper_broker, '_fetch_asking_price', return_value=(100.0, 100.3)):
        mock_send.side_effect = [sell_exec, buy_exec]
        mock_get_pf.return_value = Portfolio(total_cash=10000.0, holdings={}, current_prices={})

        orders = [
            Order('SPY', OrderAction.SELL, 5, 150.0),
            Order('IEF', OrderAction.BUY, 10, 100.0),
        ]
        executions = paper_broker.execute_orders(orders)

    # 매도 FILLED → 매수도 정상 실행
    assert len(executions) == 2
    assert mock_send.call_count == 2


# ==========================================
# 호가 조회 및 스프레드 체크 테스트
# ==========================================

@patch('src.infra.broker.time.sleep')
def test_fetch_asking_price_success(mock_sleep, paper_broker, mock_requests):
    """호가 조회 성공 시 (bid, ask) 반환"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output2': {'pbid1': '149.50', 'pask1': '150.50'}
    }
    mock_requests.get.return_value = asking_response

    bid, ask = paper_broker._fetch_asking_price('SPY')

    assert bid == 149.50
    assert ask == 150.50


@patch('src.infra.broker.time.sleep')
def test_fetch_asking_price_failure(mock_sleep, paper_broker, mock_requests):
    """호가 조회 API 실패 시 (0.0, 0.0) 반환"""
    error_response = MagicMock()
    error_response.json.return_value = {'rt_cd': '1', 'msg1': '조회 실패'}
    mock_requests.get.return_value = error_response

    bid, ask = paper_broker._fetch_asking_price('SPY')

    assert bid == 0.0
    assert ask == 0.0
    paper_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_fetch_asking_price_exception(mock_sleep, paper_broker, mock_requests):
    """호가 조회 중 예외 발생 시 (0.0, 0.0) 반환"""
    mock_requests.get.side_effect = Exception("Network error")

    bid, ask = paper_broker._fetch_asking_price('SPY')

    assert bid == 0.0
    assert ask == 0.0
    paper_broker.logger.warning.assert_called()


def test_check_spread_normal(paper_broker):
    """스프레드 0.5% 이하 → True"""
    # bid=100, ask=100.4 → spread = 0.4%
    assert paper_broker._check_spread(100.0, 100.4) is True


def test_check_spread_abnormal(paper_broker):
    """스프레드 0.5% 초과 → False"""
    # bid=100, ask=101 → spread = 0.995%
    assert paper_broker._check_spread(100.0, 101.0) is False


def test_check_spread_zero_bid_ask(paper_broker):
    """bid/ask가 0이면 True (fallback 허용)"""
    assert paper_broker._check_spread(0.0, 0.0) is True
    assert paper_broker._check_spread(0.0, 100.0) is True
    assert paper_broker._check_spread(100.0, 0.0) is True


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_uses_ask_for_buy(mock_sleep, paper_broker, mock_requests):
    """매수 주문 시 ask 가격을 주문가로 사용"""
    # 스프레드 정상: bid=150.10, ask=150.50 → spread≈0.266%
    with patch.object(paper_broker, '_fetch_asking_price', return_value=(150.10, 150.50)):
        hash_response = MagicMock()
        hash_response.json.return_value = {'HASH': 'hash123'}
        order_response = MagicMock()
        order_response.json.return_value = {'rt_cd': '0', 'output': {}}
        mock_requests.post.side_effect = [hash_response, order_response]

        order = Order('SPY', OrderAction.BUY, 10, 149.0)
        result = paper_broker._send_order_and_wait(order, timeout=30)

    # 주문가가 ask(150.50)로 설정되었는지 확인
    assert result is not None
    call_data = mock_requests.post.call_args_list[-1]
    sent_data = call_data.kwargs.get('json') or call_data[1].get('json')
    assert sent_data['OVRS_ORD_UNPR'] == '150.5'


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_uses_bid_for_sell(mock_sleep, paper_broker, mock_requests):
    """매도 주문 시 bid 가격을 주문가로 사용"""
    # 스프레드 정상: bid=150.10, ask=150.50 → spread≈0.266%
    with patch.object(paper_broker, '_fetch_asking_price', return_value=(150.10, 150.50)):
        hash_response = MagicMock()
        hash_response.json.return_value = {'HASH': 'hash123'}
        order_response = MagicMock()
        order_response.json.return_value = {'rt_cd': '0', 'output': {}}
        mock_requests.post.side_effect = [hash_response, order_response]

        order = Order('SPY', OrderAction.SELL, 5, 151.0)
        result = paper_broker._send_order_and_wait(order, timeout=30)

    # 주문가가 bid(150.10)로 설정되었는지 확인
    assert result is not None
    call_data = mock_requests.post.call_args_list[-1]
    sent_data = call_data.kwargs.get('json') or call_data[1].get('json')
    assert sent_data['OVRS_ORD_UNPR'] == '150.1'


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_fallback_to_last(mock_sleep, paper_broker, mock_requests):
    """호가 조회 실패 시 last price fallback"""
    with patch.object(paper_broker, '_fetch_asking_price', return_value=(0.0, 0.0)):
        hash_response = MagicMock()
        hash_response.json.return_value = {'HASH': 'hash123'}
        order_response = MagicMock()
        order_response.json.return_value = {'rt_cd': '0', 'output': {}}
        mock_requests.post.side_effect = [hash_response, order_response]

        order = Order('SPY', OrderAction.BUY, 10, 150.0)
        result = paper_broker._send_order_and_wait(order, timeout=30)

    # last price(150.0) fallback
    assert result is not None
    call_data = mock_requests.post.call_args_list[-1]
    sent_data = call_data.kwargs.get('json') or call_data[1].get('json')
    assert sent_data['OVRS_ORD_UNPR'] == '150.0'


@patch('src.infra.broker.time.sleep')
def test_send_order_and_wait_skipped_on_wide_spread(mock_sleep, paper_broker, mock_requests):
    """스프레드 비정상이라는 의도된 보류는 SKIPPED로 반환한다."""
    # bid=100, ask=102 → spread ≈ 1.98% > 0.5%
    with patch.object(paper_broker, '_fetch_asking_price', return_value=(100.0, 102.0)):
        order = Order('SPY', OrderAction.BUY, 10, 150.0)
        result = paper_broker._send_order_and_wait(order, timeout=30)

    assert result is not None
    assert result.status == ExecutionStatus.SKIPPED
    paper_broker.logger.warning.assert_called()
    # POST는 호출되지 않아야 함 (주문 전송 안 함)
    mock_requests.post.assert_not_called()


@patch('src.infra.broker.time.sleep')
def test_execute_orders_buy_qty_uses_ask(mock_sleep, paper_broker, mock_requests):
    """매수 수량 계산이 ask 가격 기반"""
    buy_exec = TradeExecution('SPY', OrderAction.BUY, 5, 150.50, 0.0, '2024-01-01', ExecutionStatus.FILLED)

    # 스프레드 정상: bid=150.10, ask=150.50 → spread≈0.266%
    with patch.object(paper_broker, '_send_order_and_wait', return_value=buy_exec) as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf, \
         patch.object(paper_broker, '_fetch_asking_price', return_value=(150.10, 150.50)):
        mock_get_pf.return_value = Portfolio(total_cash=1000.0, holdings={}, current_prices={})

        orders = [Order('SPY', OrderAction.BUY, 100, 149.0)]
        executions = paper_broker.execute_orders(orders)

    assert len(executions) == 1
    # 예산: 1000 * 0.98 = 980, estimated_price = ask(150.50)
    # max_qty = int(980 / 150.50) = 6
    sent_order = mock_send.call_args[0][0]
    assert sent_order.quantity == 6
