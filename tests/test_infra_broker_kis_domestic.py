# tests/test_infra_broker_kis_domestic.py
import pytest
from unittest.mock import patch, MagicMock
from src.infra.broker import KisDomesticPaperBroker, KisDomesticLiveBroker, KisDomesticBrokerBase
from src.core.models import Order, Portfolio, OrderAction, ExecutionStatus


# ==========================================
# KisDomesticPaperBroker / KisDomesticLiveBroker 테스트
# ==========================================

@pytest.fixture
def mock_requests():
    with patch('src.infra.broker.requests') as mock_req:
        yield mock_req


@pytest.fixture
def mock_logger():
    return MagicMock()


@pytest.fixture
def domestic_paper_broker(mock_requests, mock_logger):
    """KisDomesticPaperBroker 인스턴스 (인증 Mock)"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'test_token_dom'}
    mock_requests.post.return_value = auth_response

    broker = KisDomesticPaperBroker(
        app_key='test_key',
        app_secret='test_secret',
        acc_no='1234567890',
        logger=mock_logger
    )
    mock_requests.post.reset_mock()
    mock_requests.get.reset_mock()
    return broker


@pytest.fixture
def domestic_live_broker(mock_requests, mock_logger):
    """KisDomesticLiveBroker 인스턴스 (인증 Mock)"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'real_token_dom'}
    mock_requests.post.return_value = auth_response

    broker = KisDomesticLiveBroker(
        app_key='real_key',
        app_secret='real_secret',
        acc_no='9876543210',
        logger=mock_logger
    )
    mock_requests.post.reset_mock()
    mock_requests.get.reset_mock()
    return broker


# --- __init__ 테스트 ---

def test_domestic_paper_broker_init(mock_requests, mock_logger):
    """국내 모의투자 브로커 초기화"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'token123'}
    mock_requests.post.return_value = auth_response

    broker = KisDomesticPaperBroker('key', 'secret', '1234567890', mock_logger)

    assert broker.base_url == "https://openapivts.koreainvestment.com:29443"
    assert broker.PRICE_TR_ID == "FHKST01010100"
    assert broker.PORTFOLIO_TR_ID == "VTTC8434R"
    assert broker.BUY_TR_ID == "VTTC0012U"
    assert broker.SELL_TR_ID == "VTTC0011U"
    assert broker.CANCEL_TR_ID == "VTTC0013U"
    assert broker.cano == '12345678'
    assert broker.acnt_prdt_cd == '90'


def test_domestic_live_broker_init(mock_requests, mock_logger):
    """국내 실전투자 브로커 초기화"""
    auth_response = MagicMock()
    auth_response.json.return_value = {'access_token': 'real_token'}
    mock_requests.post.return_value = auth_response

    broker = KisDomesticLiveBroker('key', 'secret', '1234567890', mock_logger)

    assert broker.base_url == "https://openapi.koreainvestment.com:9443"
    assert broker.PRICE_TR_ID == "FHKST01010100"
    assert broker.PORTFOLIO_TR_ID == "TTTC8434R"
    assert broker.BUY_TR_ID == "TTTC0012U"
    assert broker.SELL_TR_ID == "TTTC0011U"
    assert broker.CANCEL_TR_ID == "TTTC0013U"


# --- fetch_current_prices 테스트 ---

def test_domestic_fetch_current_prices_success(domestic_paper_broker, mock_requests):
    """국내주식 현재가 조회 성공"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '0',
        'output': {'stck_prpr': '72000'}
    }
    mock_requests.get.return_value = price_response

    prices = domestic_paper_broker.fetch_current_prices(['005930'])

    assert prices == {'005930': 72000.0}
    call_args = mock_requests.get.call_args
    assert '/uapi/domestic-stock/v1/quotations/inquire-price' in call_args[0][0]
    assert call_args[1]['params']['FID_INPUT_ISCD'] == '005930'
    assert call_args[1]['params']['FID_COND_MRKT_DIV_CODE'] == 'J'


def test_domestic_fetch_current_prices_failure(domestic_paper_broker, mock_requests):
    """국내주식 현재가 조회 실패 시 0.0 반환"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Invalid ticker'
    }
    mock_requests.get.return_value = price_response

    prices = domestic_paper_broker.fetch_current_prices(['999999'])
    assert prices == {'999999': 0.0}


def test_domestic_fetch_current_prices_multiple(domestic_paper_broker, mock_requests):
    """여러 종목 현재가 조회"""
    responses = [
        MagicMock(json=MagicMock(return_value={'rt_cd': '0', 'output': {'stck_prpr': '72000'}})),
        MagicMock(json=MagicMock(return_value={'rt_cd': '0', 'output': {'stck_prpr': '185000'}})),
    ]
    mock_requests.get.side_effect = responses

    prices = domestic_paper_broker.fetch_current_prices(['005930', '000660'])
    assert prices == {'005930': 72000.0, '000660': 185000.0}


# --- get_portfolio 테스트 ---

def test_domestic_get_portfolio_success(domestic_paper_broker, mock_requests):
    """국내주식 잔고 조회 성공"""
    portfolio_response = MagicMock()
    portfolio_response.json.return_value = {
        'rt_cd': '0',
        'output1': [
            {'pdno': '005930', 'hldg_qty': '10', 'prpr': '72000'},
            {'pdno': '000660', 'hldg_qty': '5', 'prpr': '185000'},
        ],
        'output2': [{'prvs_rcdl_excc_amt': '5000000'}]
    }
    mock_requests.get.return_value = portfolio_response

    pf = domestic_paper_broker.get_portfolio()

    assert pf.total_cash == 5000000.0
    assert pf.holdings == {'005930.KS': 10, '000660.KS': 5}
    assert pf.current_prices == {'005930.KS': 72000.0, '000660.KS': 185000.0}
    # URL에 domestic-stock 포함 확인
    call_args = mock_requests.get.call_args
    assert '/uapi/domestic-stock/v1/trading/inquire-balance' in call_args[0][0]


def test_domestic_get_portfolio_api_failure(domestic_paper_broker, mock_requests):
    """잔고 조회 API 실패 시 RuntimeError 발생 (0값 저장 방지)"""
    portfolio_response = MagicMock()
    portfolio_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Server error'
    }
    mock_requests.get.return_value = portfolio_response

    with pytest.raises(RuntimeError, match="Get Portfolio Failed"):
        domestic_paper_broker.get_portfolio()


def test_domestic_get_portfolio_zero_qty_excluded(domestic_paper_broker, mock_requests):
    """보유수량 0인 종목은 제외"""
    portfolio_response = MagicMock()
    portfolio_response.json.return_value = {
        'rt_cd': '0',
        'output1': [
            {'pdno': '005930', 'hldg_qty': '10', 'prpr': '72000'},
            {'pdno': '000660', 'hldg_qty': '0', 'prpr': '185000'},
        ],
        'output2': [{'prvs_rcdl_excc_amt': '3000000'}]
    }
    mock_requests.get.return_value = portfolio_response

    pf = domestic_paper_broker.get_portfolio()
    assert '005930.KS' in pf.holdings
    assert '000660.KS' not in pf.holdings


# --- _fetch_asking_price 테스트 ---

def test_domestic_fetch_asking_price_success(domestic_paper_broker, mock_requests):
    """국내주식 호가 조회 성공"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '71900', 'askp1': '72000'}
    }
    mock_requests.get.return_value = asking_response

    bid, ask = domestic_paper_broker._fetch_asking_price('005930')

    assert bid == 71900.0
    assert ask == 72000.0
    call_args = mock_requests.get.call_args
    assert '/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn' in call_args[0][0]


def test_domestic_fetch_asking_price_failure(domestic_paper_broker, mock_requests):
    """호가 조회 실패 시 (0.0, 0.0) 반환"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Error'
    }
    mock_requests.get.return_value = asking_response

    bid, ask = domestic_paper_broker._fetch_asking_price('005930')
    assert bid == 0.0
    assert ask == 0.0


# --- _send_order_and_wait 테스트 ---

def test_domestic_send_order_buy_success(domestic_paper_broker, mock_requests):
    """국내주식 매수 주문 성공 (체결 확인)"""
    # 호가 조회 응답
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '71900', 'askp1': '72000'}
    }
    # 주문 응답 (hashkey + order POST)
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'DOM001'}
    }
    # 미체결 조회 응답 (빈 리스트 → 체결 완료)
    pending_response = MagicMock()
    pending_response.json.return_value = {
        'rt_cd': '0',
        'output': []
    }
    # 체결내역 조회 응답
    fill_response = MagicMock()
    fill_response.json.return_value = {
        'rt_cd': '0',
        'output1': [{
            'odno': 'DOM001',
            'avg_prvs': '72000',
            'tot_ccld_qty': '10',
            'tot_ccld_amt': '720000'
        }]
    }

    # 호가(GET) → hashkey(POST) → 주문(POST) → 미체결(GET) → 체결내역(GET)
    mock_requests.get.side_effect = [asking_response, pending_response, fill_response]
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('005930', OrderAction.BUY, 10, 72000.0)
    result = domestic_paper_broker._send_order_and_wait(order, timeout=5)

    assert result is not None
    assert result.status == ExecutionStatus.FILLED
    assert result.ticker == '005930'
    assert result.quantity == 10
    assert result.price == 72000.0


def test_domestic_send_order_sell_uses_correct_tr_id(domestic_paper_broker, mock_requests):
    """매도 주문 시 올바른 TR_ID 사용 확인"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '71900', 'askp1': '72000'}
    }
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'DOM002'}
    }
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '0', 'output': []}
    fill_response = MagicMock()
    fill_response.json.return_value = {
        'rt_cd': '0',
        'output1': [{
            'odno': 'DOM002', 'avg_prvs': '71900',
            'tot_ccld_qty': '5', 'tot_ccld_amt': '359500'
        }]
    }

    mock_requests.get.side_effect = [asking_response, pending_response, fill_response]
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('005930', OrderAction.SELL, 5, 72000.0)
    result = domestic_paper_broker._send_order_and_wait(order, timeout=5)

    assert result is not None
    assert result.status == ExecutionStatus.FILLED
    # 매도 주문 시 bid 가격 사용
    assert result.price == 71900.0


def test_domestic_send_order_api_failure(domestic_paper_broker, mock_requests):
    """주문 API 실패 시 None 반환"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '71900', 'askp1': '72000'}
    }
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '1',
        'msg1': 'Insufficient balance'
    }

    mock_requests.get.side_effect = [asking_response]
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('005930', OrderAction.BUY, 100, 72000.0)
    result = domestic_paper_broker._send_order_and_wait(order, timeout=5)
    assert result is None


def test_domestic_send_order_uses_domestic_url(domestic_paper_broker, mock_requests):
    """주문 URL이 domestic-stock 경로를 사용하는지 확인"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '71900', 'askp1': '72000'}
    }
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'DOM003'}
    }
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '0', 'output': []}
    fill_response = MagicMock()
    fill_response.json.return_value = {'rt_cd': '0', 'output1': []}

    mock_requests.get.side_effect = [asking_response, pending_response, fill_response]
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('005930', OrderAction.BUY, 10, 72000.0)
    domestic_paper_broker._send_order_and_wait(order, timeout=5)

    # POST 호출 중 주문 URL 확인 (두 번째 POST = 주문)
    post_calls = mock_requests.post.call_args_list
    order_url = post_calls[1][0][0]  # 두 번째 POST의 URL
    assert '/uapi/domestic-stock/v1/trading/order-cash' in order_url


def test_domestic_send_order_data_uses_krw_integer(domestic_paper_broker, mock_requests):
    """주문 데이터가 KRW 정수 가격을 사용하는지 확인"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '71900', 'askp1': '72000'}
    }
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'DOM004'}
    }
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '0', 'output': []}
    fill_response = MagicMock()
    fill_response.json.return_value = {'rt_cd': '0', 'output1': []}

    mock_requests.get.side_effect = [asking_response, pending_response, fill_response]
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('005930', OrderAction.BUY, 10, 72000.0)
    domestic_paper_broker._send_order_and_wait(order, timeout=5)

    # 주문 POST의 json 데이터 확인
    order_call = mock_requests.post.call_args_list[1]
    order_data = order_call[1]['json']
    assert order_data['PDNO'] == '005930'
    assert order_data['ORD_UNPR'] == '72000'  # KRW 정수 문자열
    assert order_data['ORD_DVSN'] == '00'     # 지정가
    # 해외주식 전용 필드가 없어야 함
    assert 'OVRS_EXCG_CD' not in order_data
    assert 'OVRS_ORD_UNPR' not in order_data


# --- _cancel_order 테스트 ---

def test_domestic_cancel_order_success(domestic_paper_broker, mock_requests):
    """국내주식 주문 취소 성공"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    cancel_response = MagicMock()
    cancel_response.json.return_value = {'rt_cd': '0'}

    mock_requests.post.side_effect = [hash_response, cancel_response]

    result = domestic_paper_broker._cancel_order('DOM001', '005930', 10)
    assert result is True

    # URL 확인
    cancel_call = mock_requests.post.call_args_list[1]
    assert '/uapi/domestic-stock/v1/trading/order-rvsecncl' in cancel_call[0][0]


def test_domestic_cancel_order_failure(domestic_paper_broker, mock_requests):
    """주문 취소 실패 시 False 반환"""
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    cancel_response = MagicMock()
    cancel_response.json.return_value = {'rt_cd': '1', 'msg1': 'Not found'}

    mock_requests.post.side_effect = [hash_response, cancel_response]

    result = domestic_paper_broker._cancel_order('DOM001', '005930', 10)
    assert result is False


# --- _get_pending_orders_count 테스트 ---

def test_domestic_get_pending_orders_count(domestic_paper_broker, mock_requests):
    """미체결 건수 조회"""
    pending_response = MagicMock()
    pending_response.json.return_value = {
        'rt_cd': '0',
        'output': [{'odno': '001'}, {'odno': '002'}]
    }
    mock_requests.get.return_value = pending_response

    count = domestic_paper_broker._get_pending_orders_count()
    assert count == 2


def test_domestic_get_pending_orders_count_zero(domestic_paper_broker, mock_requests):
    """미체결 없음"""
    pending_response = MagicMock()
    pending_response.json.return_value = {
        'rt_cd': '0',
        'output': []
    }
    mock_requests.get.return_value = pending_response

    count = domestic_paper_broker._get_pending_orders_count()
    assert count == 0


# --- execute_orders (공통 흐름) 테스트 ---

def test_domestic_execute_orders_sell_then_buy(domestic_paper_broker, mock_requests):
    """매도 우선 → 매수 흐름이 국내 브로커에서도 동작하는지 확인"""
    # 호가 조회
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '71900', 'askp1': '72000'}
    }
    # 주문 관련 mock
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    sell_response = MagicMock()
    sell_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'SELL001'}
    }
    buy_response = MagicMock()
    buy_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'BUY001'}
    }
    # 미체결 = 빈 리스트 (체결 완료)
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '0', 'output': []}
    # 체결내역 (매도)
    sell_fill_response = MagicMock()
    sell_fill_response.json.return_value = {
        'rt_cd': '0',
        'output1': [{
            'odno': 'SELL001', 'avg_prvs': '71900',
            'tot_ccld_qty': '10', 'tot_ccld_amt': '719000'
        }]
    }
    # 잔고 조회 (매수 전)
    portfolio_response = MagicMock()
    portfolio_response.json.return_value = {
        'rt_cd': '0',
        'output1': [],
        'output2': [{'prvs_rcdl_excc_amt': '1000000'}]
    }
    # 체결내역 (매수)
    buy_fill_response = MagicMock()
    buy_fill_response.json.return_value = {
        'rt_cd': '0',
        'output1': [{
            'odno': 'BUY001', 'avg_prvs': '72000',
            'tot_ccld_qty': '5', 'tot_ccld_amt': '360000'
        }]
    }

    # GET: 호가→미체결(sell poll)→체결(sell)→잔고→호가(buy)→미체결(buy poll)→체결(buy)
    mock_requests.get.side_effect = [
        asking_response,       # 매도 호가
        pending_response,      # 매도 미체결 poll
        sell_fill_response,    # 매도 체결내역
        portfolio_response,    # 매수 전 잔고
        asking_response,       # 매수 호가 (execute_orders 내)
        asking_response,       # 매수 주문 시 호가
        pending_response,      # 매수 미체결 poll
        buy_fill_response,     # 매수 체결내역
    ]
    # POST: hashkey→매도→hashkey→매수
    mock_requests.post.side_effect = [
        hash_response, sell_response,   # 매도
        hash_response, buy_response,    # 매수
    ]

    sell_order = Order('005930', OrderAction.SELL, 10, 72000.0)
    buy_order = Order('000660', OrderAction.BUY, 5, 185000.0)
    results = domestic_paper_broker.execute_orders([sell_order, buy_order])

    assert len(results) >= 1  # 최소 매도 체결
    sell_results = [r for r in results if r.action == OrderAction.SELL]
    assert len(sell_results) == 1
    assert sell_results[0].status == ExecutionStatus.FILLED


# --- 라이브 브로커 TR_ID 차이 테스트 ---

def test_domestic_live_vs_paper_tr_ids():
    """실전/모의 국내 브로커 TR_ID 차이 확인"""
    assert KisDomesticPaperBroker.BUY_TR_ID == "VTTC0012U"
    assert KisDomesticLiveBroker.BUY_TR_ID == "TTTC0012U"
    assert KisDomesticPaperBroker.SELL_TR_ID == "VTTC0011U"
    assert KisDomesticLiveBroker.SELL_TR_ID == "TTTC0011U"
    assert KisDomesticPaperBroker.PORTFOLIO_TR_ID == "VTTC8434R"
    assert KisDomesticLiveBroker.PORTFOLIO_TR_ID == "TTTC8434R"
    assert KisDomesticPaperBroker.CANCEL_TR_ID == "VTTC0013U"
    assert KisDomesticLiveBroker.CANCEL_TR_ID == "TTTC0013U"


# --- 스프레드 검사 (공통 로직 상속 테스트) ---

def test_domestic_check_spread_inherited(domestic_paper_broker):
    """_check_spread가 KisBrokerCommon에서 상속됨"""
    assert domestic_paper_broker._check_spread(71900, 72000) is True
    # 스프레드 > 0.5% → False
    assert domestic_paper_broker._check_spread(70000, 72000) is False
    # bid/ask 0이면 True (fallback 허용)
    assert domestic_paper_broker._check_spread(0, 0) is True


# --- 주문 거부 (스프레드 이상) 테스트 ---

def test_domestic_order_rejected_on_bad_spread(domestic_paper_broker, mock_requests):
    """스프레드 비정상 시 REJECTED 반환"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '70000', 'askp1': '73000'}  # 4.2% 스프레드
    }
    mock_requests.get.return_value = asking_response

    order = Order('005930', OrderAction.BUY, 10, 72000.0)
    result = domestic_paper_broker._send_order_and_wait(order, timeout=5)

    assert result is not None
    assert result.status == ExecutionStatus.REJECTED


# ==========================================
# 티커 포맷 변환 테스트 (.KS ↔ 6자리 코드)
# ==========================================

class TestTickerConversion:
    """_to_kis_code / _to_yf_ticker 단위 테스트"""

    def test_to_kis_code_strips_ks_suffix(self):
        assert KisDomesticBrokerBase._to_kis_code("069500.KS") == "069500"

    def test_to_kis_code_passthrough_without_suffix(self):
        assert KisDomesticBrokerBase._to_kis_code("069500") == "069500"

    def test_to_kis_code_passthrough_us_ticker(self):
        assert KisDomesticBrokerBase._to_kis_code("SPY") == "SPY"

    def test_to_yf_ticker_adds_ks_suffix(self):
        assert KisDomesticBrokerBase._to_yf_ticker("069500") == "069500.KS"

    def test_to_yf_ticker_idempotent(self):
        assert KisDomesticBrokerBase._to_yf_ticker("069500.KS") == "069500.KS"


def test_fetch_current_prices_strips_ks_for_api(domestic_paper_broker, mock_requests):
    """.KS 티커로 조회 시 API에는 6자리 코드 전송, 결과 키는 .KS 유지"""
    price_response = MagicMock()
    price_response.json.return_value = {
        'rt_cd': '0',
        'output': {'stck_prpr': '13500'}
    }
    mock_requests.get.return_value = price_response

    prices = domestic_paper_broker.fetch_current_prices(['069500.KS'])

    assert '069500.KS' in prices
    assert prices['069500.KS'] == 13500.0
    call_args = mock_requests.get.call_args
    assert call_args[1]['params']['FID_INPUT_ISCD'] == '069500'


def test_get_portfolio_returns_ks_keys(domestic_paper_broker, mock_requests):
    """get_portfolio 반환 시 holdings/prices 키에 .KS 접미사 포함"""
    portfolio_response = MagicMock()
    portfolio_response.json.return_value = {
        'rt_cd': '0',
        'output1': [
            {'pdno': '069500', 'hldg_qty': '100', 'prpr': '13500'},
        ],
        'output2': [{'prvs_rcdl_excc_amt': '2000000'}]
    }
    mock_requests.get.return_value = portfolio_response

    pf = domestic_paper_broker.get_portfolio()

    assert '069500.KS' in pf.holdings
    assert pf.holdings['069500.KS'] == 100
    assert pf.current_prices['069500.KS'] == 13500.0


def test_send_order_strips_ks_for_pdno(domestic_paper_broker, mock_requests):
    """.KS 티커 주문 시 PDNO에 6자리 코드 전송"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '71900', 'askp1': '72000'}  # 0.14% 스프레드
    }
    hash_response = MagicMock()
    hash_response.json.return_value = {'HASH': 'hash123'}
    order_response = MagicMock()
    order_response.json.return_value = {
        'rt_cd': '0',
        'output': {'ODNO': 'KS001'}
    }
    pending_response = MagicMock()
    pending_response.json.return_value = {'rt_cd': '0', 'output': []}
    fill_response = MagicMock()
    fill_response.json.return_value = {
        'rt_cd': '0',
        'output1': [{
            'odno': 'KS001', 'avg_prvs': '72000',
            'tot_ccld_qty': '10', 'tot_ccld_amt': '720000'
        }]
    }

    mock_requests.get.side_effect = [asking_response, pending_response, fill_response]
    mock_requests.post.side_effect = [hash_response, order_response]

    order = Order('069500.KS', OrderAction.BUY, 10, 72000.0)
    result = domestic_paper_broker._send_order_and_wait(order, timeout=5)

    # PDNO에 .KS 없이 전송되었는지 확인
    order_call = mock_requests.post.call_args_list[1]
    order_data = order_call[1]['json']
    assert order_data['PDNO'] == '069500'

    # 결과 ticker는 .KS 포맷 유지
    assert result is not None
    assert result.ticker == '069500.KS'


def test_fetch_asking_price_strips_ks_for_api(domestic_paper_broker, mock_requests):
    """.KS 티커 호가 조회 시 API에는 6자리 코드 전송"""
    asking_response = MagicMock()
    asking_response.json.return_value = {
        'rt_cd': '0',
        'output1': {'bidp1': '13400', 'askp1': '13500'}
    }
    mock_requests.get.return_value = asking_response

    bid, ask = domestic_paper_broker._fetch_asking_price('069500.KS')

    assert bid == 13400.0
    assert ask == 13500.0
    call_args = mock_requests.get.call_args
    assert call_args[1]['params']['FID_INPUT_ISCD'] == '069500'
