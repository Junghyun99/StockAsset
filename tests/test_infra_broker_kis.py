# tests/test_infra_broker_kis.py
import pytest
import logging
from unittest.mock import patch, MagicMock
from src.infra.broker import KisPaperBroker, KisLiveBroker, MockBroker
from src.core.models import Order, Portfolio, OrderAction, ExecutionStatus, TradeExecution


# ==========================================
# KisPaperBroker / KisLiveBroker 테스트 (외부 API는 모두 Mock)
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
def paper_broker(mock_requests, mock_logger):
    """KisPaperBroker 인스턴스 (인증 Mock 포함)"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'test_token_123'}
    mock_requests.post.return_value = auth_response

    broker = KisPaperBroker(
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
    """KisLiveBroker 인스턴스 (인증 Mock 포함)"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'real_token_456'}
    mock_requests.post.return_value = auth_response

    broker = KisLiveBroker(
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

    broker = KisPaperBroker('key', 'secret', '1234567890', mock_logger)

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

    broker = KisLiveBroker('key', 'secret', '1234567890', mock_logger)

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
        KisPaperBroker('bad_key', 'bad_secret', '1234567890', mock_logger)


def test_paper_broker_auth_network_error(mock_requests, mock_logger):
    """인증 중 네트워크 에러"""
    mock_requests.post.side_effect = Exception("Network Error")

    with pytest.raises(Exception, match="Network Error"):
        KisPaperBroker('key', 'secret', '1234567890', mock_logger)


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
    """_send_order: hashkey 실패 시 None 반환 (예외 전파 없음)"""
    # 첫 번째 post(hashkey 요청)에서 예외 발생
    mock_requests.post.side_effect = Exception("Hash service down")

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = paper_broker._send_order(order)

    assert result is None
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
    """주문 전송 실패 (API 에러)"""
    order_response = MagicMock()
    order_response.json.return_value = {'rt_cd': '1', 'msg1': 'Insufficient balance'}
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash'}
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('SPY', OrderAction.BUY, 10, 150.0)
    result = paper_broker._send_order(order)

    assert result is None
    paper_broker.logger.error.assert_called()


def test_paper_broker_send_order_exception(paper_broker, mock_requests):
    """주문 전송 중 예외"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash'}
    mock_requests.post.side_effect = [hash_response, Exception("Network Down")]

    order = Order('SPY', OrderAction.BUY, 5, 100.0)
    result = paper_broker._send_order(order)

    assert result is None


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
    # _send_order와 _wait_for_completion, get_portfolio를 모킹
    with patch.object(paper_broker, '_send_order') as mock_send, \
         patch.object(paper_broker, '_wait_for_completion', return_value=True), \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

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
        executions = paper_broker.execute_orders(orders)

        assert len(executions) == 2
        assert mock_send.call_count == 2


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_only(mock_sleep, paper_broker, mock_requests):
    """매수만 있는 경우"""
    with patch.object(paper_broker, '_send_order') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        from src.core.models import TradeExecution
        buy_exec = TradeExecution('SPY', OrderAction.BUY, 5, 100.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
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
    with patch.object(paper_broker, '_send_order') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        from src.core.models import TradeExecution
        buy_exec = TradeExecution('SPY', OrderAction.BUY, 1, 100.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
        mock_send.return_value = buy_exec
        # 현금이 적어서 수량이 조정되어야 함
        mock_get_pf.return_value = Portfolio(
            total_cash=200.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 100, 100.0)]  # 100주 요청하지만 돈이 부족
        executions = paper_broker.execute_orders(orders)

        # 수량이 조정되어 실행됨 (200*0.98/102 = 1주)
        assert len(executions) == 1
        paper_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_buy_zero_price(mock_sleep, paper_broker, mock_requests):
    """매수 가격이 0인 경우 스킵"""
    with patch.object(paper_broker, '_send_order') as mock_send, \
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
    with patch.object(paper_broker, '_send_order') as mock_send, \
         patch.object(paper_broker, 'get_portfolio') as mock_get_pf:

        mock_get_pf.return_value = Portfolio(
            total_cash=10.0, holdings={}, current_prices={}
        )

        orders = [Order('SPY', OrderAction.BUY, 10, 500.0)]  # 수량 조정 후 0
        executions = paper_broker.execute_orders(orders)

        assert len(executions) == 0


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_sell_timeout(mock_sleep, paper_broker, mock_requests):
    """매도 체결 대기 타임아웃"""
    with patch.object(paper_broker, '_send_order') as mock_send, \
         patch.object(paper_broker, '_wait_for_completion', return_value=False):

        from src.core.models import TradeExecution
        sell_exec = TradeExecution('SPY', OrderAction.SELL, 5, 150.0, 0.0, '2024-01-01', ExecutionStatus.ORDERED)
        mock_send.return_value = sell_exec

        orders = [Order('SPY', OrderAction.SELL, 5, 150.0)]
        executions = paper_broker.execute_orders(orders)

        # 타임아웃이어도 실행 결과는 반환
        assert len(executions) == 1
        paper_broker.logger.warning.assert_called()


@patch('src.infra.broker.time.sleep')
def test_paper_broker_execute_send_order_returns_none(mock_sleep, paper_broker, mock_requests):
    """_send_order가 None을 반환하는 경우 (주문 실패)"""
    with patch.object(paper_broker, '_send_order', return_value=None) as mock_send, \
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
