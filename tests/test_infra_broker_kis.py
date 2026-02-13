# tests/test_infra_broker_kis.py
import pytest
import logging
from unittest.mock import patch, MagicMock
from src.infra.broker import KisBroker, MockBroker
from src.core.models import Order, Portfolio, OrderAction, ExecutionStatus, TradeExecution


# ==========================================
# KisBroker 테스트 (외부 API는 모두 Mock)
# ==========================================

@pytest.fixture
def mock_requests():
    """requests 모듈 전체를 Mock"""
    with patch('src.infra.broker.requests') as mock_req:
        yield mock_req


@pytest.fixture
def mock_logger():
    return MagicMock()


@pytest.fixture
def kis_broker(mock_requests, mock_logger):
    """KisBroker 인스턴스 (인증 Mock 포함)"""
    # _auth가 호출될 때 성공적으로 토큰을 반환하도록 설정
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'test_token_123'}
    mock_requests.post.return_value = auth_response

    broker = KisBroker(
        app_key='test_key',
        app_secret='test_secret',
        acc_no='1234567890',
        logger=mock_logger,
        is_real=False
    )
    # post mock 초기화 (auth 호출 후)
    mock_requests.post.reset_mock()
    mock_requests.get.reset_mock()
    return broker


@pytest.fixture
def kis_broker_real(mock_requests, mock_logger):
    """실전 모드 KisBroker"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'real_token_456'}
    mock_requests.post.return_value = auth_response

    broker = KisBroker(
        app_key='real_key',
        app_secret='real_secret',
        acc_no='9876543210',
        logger=mock_logger,
        is_real=True
    )
    mock_requests.post.reset_mock()
    mock_requests.get.reset_mock()
    return broker


# --- __init__ 테스트 ---

def test_kis_broker_init_paper(mock_requests, mock_logger):
    """모의투자 모드 초기화"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'token123'}
    mock_requests.post.return_value = auth_response

    broker = KisBroker('key', 'secret', '1234567890', mock_logger, is_real=False)

    assert broker.base_url == "https://openapivts.koreainvestment.com:29443"
    assert broker.cano == '12345678'
    assert broker.acnt_prdt_cd == '90'
    assert broker.access_token == 'token123'


def test_kis_broker_init_real(mock_requests, mock_logger):
    """실전 모드 초기화"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'real_token'}
    mock_requests.post.return_value = auth_response

    broker = KisBroker('key', 'secret', '1234567890', mock_logger, is_real=True)

    assert broker.base_url == "https://openapi.koreainvestment.com:9443"
    assert broker.access_token == 'real_token'


# --- _auth 테스트 ---

def test_kis_broker_auth_failure(mock_requests, mock_logger):
    """인증 실패 시 예외 발생"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'error': 'invalid credentials'}
    mock_requests.post.return_value = auth_response

    with pytest.raises(Exception, match="Auth Failed"):
        KisBroker('bad_key', 'bad_secret', '1234567890', mock_logger)


def test_kis_broker_auth_network_error(mock_requests, mock_logger):
    """인증 중 네트워크 에러"""
    mock_requests.post.side_effect = Exception("Network Error")

    with pytest.raises(Exception, match="Network Error"):
        KisBroker('key', 'secret', '1234567890', mock_logger)


# --- _get_header / _get_hashkey 테스트 ---

def test_kis_broker_get_header_without_data(kis_broker, mock_requests):
    """데이터 없이 헤더 생성 (GET 요청용)"""
    headers = kis_broker._get_header("FHKST01010100")

    assert headers['authorization'] == 'Bearer test_token_123'
    assert headers['tr_id'] == 'FHKST01010100'
    assert headers['appkey'] == 'test_key'
    assert 'hashkey' not in headers


def test_kis_broker_get_header_with_data(kis_broker, mock_requests):
    """데이터 포함 헤더 생성 (POST 요청용, HashKey 포함)"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'abc123hash'}
    mock_requests.post.return_value = hash_response

    data = {"CANO": "12345678", "PDNO": "SPY"}
    headers = kis_broker._get_header("VTTT1002U", data)

    assert headers['hashkey'] == 'abc123hash'
    assert headers['tr_id'] == 'VTTT1002U'


def test_kis_broker_get_hashkey_failure(kis_broker, mock_requests):
    """HashKey 조회 실패 시 빈 문자열 반환"""
    mock_requests.post.side_effect = Exception("Hash Error")

    result = kis_broker._get_hashkey({"test": "data"})
    assert result == ""


# --- fetch_current_prices 테스트 ---

@patch('src.infra.broker.time.sleep')
def test_kis_broker_fetch_prices_success(mock_sleep, kis_broker, mock_requests):
    """현재가 조회 성공"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '0',
        'output': {'last': '150.50'}
    }
    mock_requests.get.return_value = price_response

    prices = kis_broker.fetch_current_prices(['SPY', 'IEF'])

    assert prices['SPY'] == 150.50
    assert prices['IEF'] == 150.50
    assert mock_requests.get.call_count == 2


@patch('src.infra.broker.time.sleep')
def test_kis_broker_fetch_prices_api_error(mock_sleep, kis_broker, mock_requests):
    """현재가 조회 API 에러 (rt_cd != 0)"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Invalid ticker'
    }
    mock_requests.get.return_value = price_response

    prices = kis_broker.fetch_current_prices(['INVALID'])

    assert prices['INVALID'] == 0.0
    mock_logger = kis_broker.logger
    mock_logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_kis_broker_fetch_prices_exception(mock_sleep, kis_broker, mock_requests):
    """현재가 조회 중 예외 발생"""
    mock_requests.get.side_effect = Exception("Timeout")

    prices = kis_broker.fetch_current_prices(['SPY'])

    assert prices['SPY'] == 0.0
    kis_broker.logger.error.assert_called()


@patch('src.infra.broker.time.sleep')
def test_kis_broker_fetch_prices_real_mode(mock_sleep, kis_broker_real, mock_requests):
    """실전 모드에서 TR_ID가 올바른지 확인"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '0',
        'output': {'last': '200.00'}
    }
    mock_requests.get.return_value = price_response

    kis_broker_real.fetch_current_prices(['SPY'])

    args, kwargs = mock_requests.get.call_args
    # 실전 TR_ID: HHDFS00000300
    assert kwargs['headers']['tr_id'] == 'HHDFS00000300'


# --- get_portfolio 테스트 ---

def test_kis_broker_get_portfolio_success(kis_broker, mock_requests):
    """잔고 조회 성공"""
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

    pf = kis_broker.get_portfolio()

    assert pf.total_cash == 5000.50
    assert pf.holdings['SPY'] == 10
    assert pf.holdings['IEF'] == 5
    assert 'OLD' not in pf.holdings  # 0주는 제외
    assert pf.current_prices['SPY'] == 150.0


def test_kis_broker_get_portfolio_api_failure(kis_broker, mock_requests):
    """잔고 조회 API 실패"""
    fail_response = MagicMock()
    fail_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Session Expired'
    }
    mock_requests.get.return_value = fail_response

    pf = kis_broker.get_portfolio()

    assert pf.total_cash == 0
    assert pf.holdings == {}


def test_kis_broker_get_portfolio_exception(kis_broker, mock_requests):
    """잔고 조회 중 예외 발생"""
    mock_requests.get.side_effect = Exception("Connection Error")

    pf = kis_broker.get_portfolio()

    assert pf.total_cash == 0
    kis_broker.logger.error.assert_called()


def test_kis_broker_get_portfolio_real_mode(kis_broker_real, mock_requests):
    """실전 모드에서 TR_ID 확인"""
    portfolio_response = MagicMock()
    portfolio_response.json.return_value = {
        'rt_cd': '0',
        'output1': [],
        'output2': {'ovrs_ord_psbl_amt': '1000.0'}
    }
    mock_requests.get.return_value = portfolio_response

    kis_broker_real.get_portfolio()

    args, kwargs = mock_requests.get.call_args
    assert kwargs['headers']['tr_id'] == 'TTTS3012R'


# --- _send_order 테스트 ---

def test_kis_broker_send_order_buy_success(kis_broker, mock_requests):
    """매수 주문 전송 성공"""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '0', 'msg1': 'OK'}
    # hashkey도 mock
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = kis_broker._send_order(order)

    assert result is not None
    assert result.ticker == 'SPY'
    assert result.action == OrderAction.BUY
    assert result.quantity == 10
    assert result.status == ExecutionStatus.ORDERED


def test_kis_broker_send_order_sell_success(kis_broker, mock_requests):
    """매도 주문 전송 성공"""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '0', 'msg1': 'OK'}
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash456'}
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.SELL, 5, 150.0)
    result = kis_broker._send_order(order)

    assert result is not None
    assert result.action == OrderAction.SELL


def test_kis_broker_send_order_failure(kis_broker, mock_requests):
    """주문 전송 실패 (API 에러)"""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '1', 'msg1': 'Insufficient balance'}
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash'}
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = kis_broker._send_order(order)

    assert result is None
    kis_broker.logger.error.assert_called()


def test_kis_broker_send_order_exception(kis_broker, mock_requests):
    """주문 전송 중 예외"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash'}
    mock_requests.post.side_effect = [hash_response, Exception("Network Down")]

    order = Order('SPY', OrderAction.BUY, 5, 100.0)
    result = kis_broker._send_order(order)

    assert result is None


def test_kis_broker_send_order_real_mode_tr_ids(kis_broker_real, mock_requests):
    """실전 모드 TR_ID 확인 (매수/매도)"""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '0'}
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'h'}

    # 매수
    mock_requests.post.side_effect = [hash_response, order_response]
    buy_order = Order('SPY', OrderAction.BUY, 1, 100.0)
    kis_broker_real._send_order(buy_order)
    # 두 번째 post call의 headers에서 tr_id 확인
    call_args = mock_requests.post.call_args_list[1]
    assert call_args[1]['headers']['tr_id'] == 'TTTS1002U'

    mock_requests.post.reset_mock()
    mock_requests.post.side_effect = [hash_response, order_response]
    # 매도
    sell_order = Order('SPY', OrderAction.SELL, 1, 100.0)
    kis_broker_real._send_order(sell_order)
    call_args = mock_requests.post.call_args_list[1]
    assert call_args[1]['headers']['tr_id'] == 'TTTS1006U'


# --- execute_orders 테스트 ---

@patch('src.infra.broker.time.sleep')
def test_kis_broker_execute_sell_then_buy(mock_sleep, kis_broker, mock_requests):
    """매도 후 매수 순서 실행"""
    # _send_order와 _wait_for_completion, get_portfolio를 모킹
    with patch.object(kis_broker, '_send_order') as mock_send, \
         patch.object(kis_broker, '_wait_for_completion', return_value=True), \
         patch.object(kis_broker, 'get_portfolio') as mock_get_pf:

        from src.core.models import TradeExecution
        sell_exec = TradeExecution('SPY', OrderAction.SELL, 5, 150.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
        buy_exec = TradeExecution('IEF', OrderAction.BUY, 10, 100.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
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
        executions = kis_broker.execute_orders(orders)

        assert len(executions) == 2
        assert mock_send.call_count == 2


@patch('src.infra.broker.time.sleep')
def test_kis_broker_execute_buy_only(mock_sleep, kis_broker, mock_requests):
    """매수만 있는 경우"""
    with patch.object(kis_broker, '_send_order') as mock_send, \
         patch.object(kis_broker, 'get_portfolio') as mock_get_pf:

        from src.core.models import TradeExecution
        buy_exec = TradeExecution('SPY', OrderAction.BUY, 5, 100.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
        mock_send.return_value = buy_exec
        mock_get_pf.return_value = Portfolio(
            total_cash=50000.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 5, 100.0)]
        executions = kis_broker.execute_orders(orders)

        assert len(executions) == 1


@patch('src.infra.broker.time.sleep')
def test_kis_broker_execute_buy_qty_adjusted(mock_sleep, kis_broker, mock_requests):
    """매수 시 잔고 부족으로 수량 조정"""
    with patch.object(kis_broker, '_send_order') as mock_send, \
         patch.object(kis_broker, 'get_portfolio') as mock_get_pf:

        from src.core.models import TradeExecution
        buy_exec = TradeExecution('SPY', OrderAction.BUY, 1, 100.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
        mock_send.return_value = buy_exec
        # 현금이 적어서 수량이 조정되어야 함
        mock_get_pf.return_value = Portfolio(
            total_cash=200.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 100, 100.0)]  # 100주 요청하지만 돈이 부족
        executions = kis_broker.execute_orders(orders)

        # 수량이 조정되어 실행됨 (200*0.98/102 = 1주)
        assert len(executions) == 1
        kis_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_kis_broker_execute_buy_zero_price(mock_sleep, kis_broker, mock_requests):
    """매수 가격이 0인 경우 스킵"""
    with patch.object(kis_broker, '_send_order') as mock_send, \
         patch.object(kis_broker, 'get_portfolio') as mock_get_pf:

        mock_get_pf.return_value = Portfolio(
            total_cash=10000.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 10, 0.0)]  # 가격 0
        executions = kis_broker.execute_orders(orders)

        assert len(executions) == 0
        mock_send.assert_not_called()


@patch('src.infra.broker.time.sleep')
def test_kis_broker_execute_buy_zero_qty_after_adjust(mock_sleep, kis_broker, mock_requests):
    """수량 조정 후 0이 되면 주문 안 함"""
    with patch.object(kis_broker, '_send_order') as mock_send, \
         patch.object(kis_broker, 'get_portfolio') as mock_get_pf:

        mock_get_pf.return_value = Portfolio(
            total_cash=10.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 10, 500.0)]  # 수량 조정 후 0
        executions = kis_broker.execute_orders(orders)

        assert len(executions) == 0


@patch('src.infra.broker.time.sleep')
def test_kis_broker_execute_sell_timeout(mock_sleep, kis_broker, mock_requests):
    """매도 체결 대기 타임아웃"""
    with patch.object(kis_broker, '_send_order') as mock_send, \
         patch.object(kis_broker, '_wait_for_completion', return_value=False):

        from src.core.models import TradeExecution
        sell_exec = TradeExecution('SPY', OrderAction.SELL, 5, 150.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
        mock_send.return_value = sell_exec

        orders = [Order('SPY', OrderAction.SELL, 5, 150.0)]
        executions = kis_broker.execute_orders(orders)

        # 타임아웃이어도 실행 결과는 반환
        assert len(executions) == 1
        kis_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_kis_broker_execute_send_order_returns_none(mock_sleep, kis_broker, mock_requests):
    """_send_order가 None을 반환하는 경우 (주문 실패)"""
    with patch.object(kis_broker, '_send_order', return_value=None) as mock_send, \
         patch.object(kis_broker, 'get_portfolio') as mock_get_pf:

        mock_get_pf.return_value = Portfolio(
            total_cash=50000.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 5, 100.0)]
        executions = kis_broker.execute_orders(orders)

        assert len(executions) == 0


# --- _wait_for_completion 테스트 ---

@patch('src.infra.broker.time.sleep')
@patch('src.infra.broker.time.time')
def test_kis_broker_wait_completion_success(mock_time, mock_sleep, kis_broker):
    """체결 대기 성공 (미체결 0)"""
    mock_time.side_effect = [0, 1]  # 시작, 루프 1회
    with patch.object(kis_broker, '_get_pending_orders_count', return_value=0):
        result = kis_broker._wait_for_completion(timeout=60)
        assert result is True


@patch('src.infra.broker.time.sleep')
@patch('src.infra.broker.time.time')
def test_kis_broker_wait_completion_timeout(mock_time, mock_sleep, kis_broker):
    """체결 대기 타임아웃"""
    # time.time()이 계속 증가하여 timeout 초과
    mock_time.side_effect = [0, 10, 30, 61]
    with patch.object(kis_broker, '_get_pending_orders_count', return_value=5):
        result = kis_broker._wait_for_completion(timeout=60)
        assert result is False


# --- _get_pending_orders_count 테스트 ---

@patch('src.infra.broker.time.sleep')
def test_kis_broker_pending_orders_found(mock_sleep, kis_broker, mock_requests):
    """미체결 내역 발견"""
    pending_response = MagicMock()
    pending_response.json.return_value = {
        'rt_cd': '0',
        'output': [{'order_id': '1'}, {'order_id': '2'}]
    }
    mock_requests.get.return_value = pending_response

    count = kis_broker._get_pending_orders_count()

    assert count == 2


@patch('src.infra.broker.time.sleep')
def test_kis_broker_pending_orders_none(mock_sleep, kis_broker, mock_requests):
    """미체결 내역 없음 (모든 거래소 조회)"""
    empty_response = MagicMock()
    empty_response.json.return_value = {
        'rt_cd': '0',
        'output': []
    }
    mock_requests.get.return_value = empty_response

    count = kis_broker._get_pending_orders_count()

    assert count == 0
    # NAS, NYS, AMS 3개 거래소 모두 조회
    assert mock_requests.get.call_count == 3


@patch('src.infra.broker.time.sleep')
def test_kis_broker_pending_orders_api_error(mock_sleep, kis_broker, mock_requests):
    """미체결 조회 API 에러"""
    error_response = MagicMock()
    error_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Service unavailable'
    }
    mock_requests.get.return_value = error_response

    count = kis_broker._get_pending_orders_count()

    assert count == 0
    kis_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_kis_broker_pending_orders_exception(mock_sleep, kis_broker, mock_requests):
    """미체결 조회 중 예외"""
    mock_requests.get.side_effect = Exception("Connection Reset")

    count = kis_broker._get_pending_orders_count()

    assert count == 0
    kis_broker.logger.error.assert_called()


# --- _get_exchange_code 테스트 ---

def test_kis_broker_exchange_code_mapping(kis_broker):
    """거래소 코드 매핑 확인"""
    assert kis_broker._get_exchange_code('SPY') == 'AMS'
    assert kis_broker._get_exchange_code('QLD') == 'AMS'
    assert kis_broker._get_exchange_code('SSO') == 'AMS'
    assert kis_broker._get_exchange_code('IEF') == 'NAS'
    assert kis_broker._get_exchange_code('GLD') == 'NYS'
    assert kis_broker._get_exchange_code('PDBC') == 'NAS'
    assert kis_broker._get_exchange_code('SHV') == 'NAS'


def test_kis_broker_exchange_code_default(kis_broker):
    """매핑에 없는 티커는 기본값 NAS"""
    assert kis_broker._get_exchange_code('UNKNOWN') == 'NAS'
    assert kis_broker._get_exchange_code('AAPL') == 'NAS'


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
