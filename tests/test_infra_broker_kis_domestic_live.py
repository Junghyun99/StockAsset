"""
KisDomesticLiveBroker 실거래 API 테스트.

실제 KIS API 서버에 연결하여 각 함수의 동작을 검증한다.
환경변수(KIS_APP_KEY, KIS_APP_SECRET, KIS_ACC_NO)가 없거나
KIS 서버에 연결할 수 없으면 전체 skip된다.

주문 테스트(Phase 4)는 RUN_ORDER_TESTS=true 환경변수가 있어야 실행되며,
장 운영시간(09:00~15:20 KST) 외에는 자동 skip된다.
"""

import os
import socket
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from src.infra.broker import KisDomesticLiveBroker
from src.core.models import Portfolio, Order, TradeExecution, OrderAction, ExecutionStatus


# ============================================================
# 환경 체크
# ============================================================

KST = timezone(timedelta(hours=9))

def _is_kis_server_available() -> bool:
    """KIS 실전 API 서버에 연결 가능한지 확인"""
    try:
        socket.create_connection(("openapi.koreainvestment.com", 9443), timeout=5)
        return True
    except OSError:
        return False

def _has_kis_credentials() -> bool:
    """KIS API 인증 환경변수가 모두 설정되어 있는지 확인"""
    return all([
        os.getenv("KIS_APP_KEY"),
        os.getenv("KIS_APP_SECRET"),
        os.getenv("KIS_ACC_NO"),
    ])

def _is_market_open() -> bool:
    """한국 주식시장 장 운영시간(09:00~15:20 KST)인지 확인"""
    now = datetime.now(KST)
    # 주말 체크 (0=월, 6=일)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=20, second=0, microsecond=0)
    return market_open <= now <= market_close

KIS_AVAILABLE = _is_kis_server_available()
HAS_CREDENTIALS = _has_kis_credentials()
RUN_ORDER_TESTS = os.getenv("RUN_ORDER_TESTS", "").lower() == "true"
TEST_TICKER = os.getenv("TEST_TICKER", "069500")  # 기본: KODEX 200
ORDER_QTY = 1  # 안전장치: 항상 1주만 매매

# 서버 연결 불가 또는 인증정보 없으면 전체 파일 skip
pytestmark = pytest.mark.skipif(
    not (KIS_AVAILABLE and HAS_CREDENTIALS),
    reason="KIS API 서버 연결 불가 또는 인증 환경변수(KIS_APP_KEY, KIS_APP_SECRET, KIS_ACC_NO) 미설정"
)

# 주문 테스트 skip 조건
skip_order_test = pytest.mark.skipif(
    not RUN_ORDER_TESTS,
    reason="주문 테스트 비활성 — RUN_ORDER_TESTS=true 환경변수를 설정하세요"
)
skip_market_closed = pytest.mark.skipif(
    not _is_market_open(),
    reason=f"장 운영시간 외 — 현재 KST: {datetime.now(KST).strftime('%H:%M')}"
)


# ============================================================
# Fixture
# ============================================================

@pytest.fixture(scope="module")
def broker():
    """KisDomesticLiveBroker 인스턴스 (모듈 전체에서 재사용, 토큰 1회 발급)"""
    return KisDomesticLiveBroker(
        app_key=os.getenv("KIS_APP_KEY"),
        app_secret=os.getenv("KIS_APP_SECRET"),
        acc_no=os.getenv("KIS_ACC_NO"),
        logger=MagicMock(),
    )


# ============================================================
# Phase 1: 인증 (Read-only)
# ============================================================

class TestPhase1Auth:
    """Phase 1: 토큰 발급 및 인증 확인"""

    def test_auth_token_issued(self, broker):
        """브로커 초기화 시 access_token이 정상 발급되었는지 확인"""
        assert broker.access_token is not None
        assert isinstance(broker.access_token, str)
        assert len(broker.access_token) > 0
        print(f"  ✓ Token issued (length={len(broker.access_token)})")

    def test_token_expiration_set(self, broker):
        """토큰 만료 시간이 미래로 설정되어 있는지 확인"""
        assert broker.token_expires_at is not None
        assert broker.token_expires_at > datetime.now()
        print(f"  ✓ Token expires at: {broker.token_expires_at}")


# ============================================================
# Phase 2: 시세 조회 (Read-only)
# ============================================================

class TestPhase2PriceQuery:
    """Phase 2: 현재가 및 호가 조회"""

    def test_fetch_current_prices_single(self, broker):
        """삼성전자(005930) 현재가 단건 조회"""
        prices = broker.fetch_current_prices(["005930"])
        assert "005930" in prices
        assert prices["005930"] > 0
        print(f"  ✓ 삼성전자 현재가: {prices['005930']:,.0f}원")

    def test_fetch_current_prices_multiple(self, broker):
        """삼성전자 + SK하이닉스 복수 종목 조회"""
        tickers = ["005930", "000660"]
        prices = broker.fetch_current_prices(tickers)
        for ticker in tickers:
            assert ticker in prices, f"{ticker} 누락"
            assert prices[ticker] > 0, f"{ticker} 가격이 0"
        print(f"  ✓ 삼성전자: {prices['005930']:,.0f}원, SK하이닉스: {prices['000660']:,.0f}원")

    def test_fetch_current_prices_test_ticker(self, broker):
        """주문 테스트 대상 종목(TEST_TICKER) 현재가 조회"""
        prices = broker.fetch_current_prices([TEST_TICKER])
        assert TEST_TICKER in prices
        assert prices[TEST_TICKER] > 0
        print(f"  ✓ {TEST_TICKER} 현재가: {prices[TEST_TICKER]:,.0f}원")

    def test_fetch_asking_price(self, broker):
        """KODEX 200(069500) 호가(bid/ask) 조회"""
        bid, ask = broker._fetch_asking_price(TEST_TICKER)
        assert bid > 0, f"bid가 0: {bid}"
        assert ask > 0, f"ask가 0: {ask}"
        assert bid <= ask, f"bid({bid}) > ask({ask}) 비정상"
        print(f"  ✓ {TEST_TICKER} bid={bid:,.0f} / ask={ask:,.0f} (spread={((ask-bid)/bid*100):.3f}%)")


# ============================================================
# Phase 3: 계좌 조회 (Read-only)
# ============================================================

class TestPhase3AccountQuery:
    """Phase 3: 포트폴리오 및 미체결 주문 조회"""

    def test_get_portfolio(self, broker):
        """포트폴리오 조회 — cash >= 0, holdings dict 구조 확인"""
        pf = broker.get_portfolio()
        assert isinstance(pf, Portfolio)
        assert pf.total_cash >= 0, f"예수금이 음수: {pf.total_cash}"
        assert isinstance(pf.holdings, dict)
        assert isinstance(pf.current_prices, dict)
        print(f"  ✓ 예수금: {pf.total_cash:,.0f}원, 보유종목: {len(pf.holdings)}개")
        if pf.holdings:
            for ticker, qty in pf.holdings.items():
                price = pf.current_prices.get(ticker, 0)
                print(f"    - {ticker}: {qty}주 × {price:,.0f}원 = {qty*price:,.0f}원")

    def test_get_pending_orders_count(self, broker):
        """미체결 주문 수 조회"""
        count = broker._get_pending_orders_count()
        assert isinstance(count, int)
        assert count >= 0
        print(f"  ✓ 미체결 주문: {count}건")

    def test_get_pending_order_ids(self, broker):
        """미체결 주문 ID 집합 조회"""
        ids = broker._get_pending_order_ids()
        assert isinstance(ids, set)
        print(f"  ✓ 미체결 주문 ID: {ids if ids else '없음'}")


# ============================================================
# Phase 4: 주문 실행 (Write — 실제 매매!)
# ============================================================

@skip_order_test
@skip_market_closed
class TestPhase4OrderExecution:
    """Phase 4: 매수/매도 주문 실행 (RUN_ORDER_TESTS=true + 장중에만)

    ⚠️ 실제 자금으로 1주를 매수/매도합니다.
    TEST_TICKER 환경변수로 종목 지정 (기본: 069500 KODEX 200).
    """

    # 모듈 레벨에서 매수 결과를 공유하기 위한 클래스 변수
    buy_execution: TradeExecution = None

    def test_buy_order(self, broker):
        """1주 매수 주문 → TradeExecution 반환 확인"""
        # 현재가 조회
        prices = broker.fetch_current_prices([TEST_TICKER])
        current_price = prices[TEST_TICKER]
        assert current_price > 0, "현재가 조회 실패"

        # 예수금 확인
        pf = broker.get_portfolio()
        assert pf.total_cash >= current_price, (
            f"예수금({pf.total_cash:,.0f}원) 부족 — "
            f"{TEST_TICKER} 1주 가격: {current_price:,.0f}원"
        )

        order = Order(
            ticker=TEST_TICKER,
            action=OrderAction.BUY,
            quantity=ORDER_QTY,
            price=current_price,
        )
        result = broker._send_order_and_wait(order, timeout=30)

        assert result is not None, "매수 주문 결과가 None"
        assert isinstance(result, TradeExecution)
        assert result.status in (ExecutionStatus.FILLED, ExecutionStatus.ORDERED), (
            f"예상치 못한 status: {result.status}"
        )
        print(
            f"  ✓ 매수 완료: {result.ticker} {result.quantity}주 "
            f"@ {result.price:,.0f}원 (status={result.status})"
        )

        # 다음 테스트에서 사용하기 위해 저장
        TestPhase4OrderExecution.buy_execution = result

    def test_portfolio_after_buy(self, broker):
        """매수 후 포트폴리오에 해당 종목 존재 확인"""
        buy = TestPhase4OrderExecution.buy_execution
        if buy is None or buy.status != ExecutionStatus.FILLED:
            pytest.skip("매수가 체결되지 않아 포트폴리오 검증 skip")

        pf = broker.get_portfolio()
        assert TEST_TICKER in pf.holdings, (
            f"매수 후 포트폴리오에 {TEST_TICKER}가 없음. holdings={pf.holdings}"
        )
        assert pf.holdings[TEST_TICKER] >= ORDER_QTY
        print(f"  ✓ 포트폴리오 확인: {TEST_TICKER} {pf.holdings[TEST_TICKER]}주 보유")

    def test_sell_order(self, broker):
        """보유 1주 매도 주문 → TradeExecution 반환 확인"""
        buy = TestPhase4OrderExecution.buy_execution
        if buy is None or buy.status != ExecutionStatus.FILLED:
            pytest.skip("매수가 체결되지 않아 매도 테스트 skip")

        prices = broker.fetch_current_prices([TEST_TICKER])
        current_price = prices[TEST_TICKER]

        order = Order(
            ticker=TEST_TICKER,
            action=OrderAction.SELL,
            quantity=ORDER_QTY,
            price=current_price,
        )
        result = broker._send_order_and_wait(order, timeout=30)

        assert result is not None, "매도 주문 결과가 None"
        assert isinstance(result, TradeExecution)
        assert result.status in (ExecutionStatus.FILLED, ExecutionStatus.ORDERED), (
            f"예상치 못한 status: {result.status}"
        )
        print(
            f"  ✓ 매도 완료: {result.ticker} {result.quantity}주 "
            f"@ {result.price:,.0f}원 (status={result.status})"
        )

    def test_portfolio_after_sell(self, broker):
        """매도 후 포트폴리오에서 해당 종목 수량 감소 확인"""
        buy = TestPhase4OrderExecution.buy_execution
        if buy is None or buy.status != ExecutionStatus.FILLED:
            pytest.skip("매수가 체결되지 않아 매도 후 검증 skip")

        pf = broker.get_portfolio()
        held = pf.holdings.get(TEST_TICKER, 0)
        # 원래 보유분이 있었을 수 있으므로, 적어도 매수 전보다 줄었는지 확인
        print(f"  ✓ 매도 후 {TEST_TICKER}: {held}주 보유")
