# src/infra/broker/kis_base.py
"""KIS 공통 베이스 — 인증, 헤더, 매도우선 오케스트레이션."""
from typing import List, Dict, Optional
import time
import src.infra.broker as _pkg  # test patch 타깃: src.infra.broker.requests
from datetime import datetime, timedelta

from src.core.interfaces import IBrokerAdapter
from src.core.models import Portfolio, Order, TradeExecution, OrderAction, ExecutionStatus

from . import kis_http
from . import kis_token_cache


class KisBrokerCommon(IBrokerAdapter):
    """한국투자증권 REST API 공통 베이스 클래스.
    인증, 헤더, 해시키, 주문 흐름(매도우선) 등 시장 무관 로직을 담당한다.
    서브클래스(KisOverseasBrokerBase, KisDomesticBrokerBase)에서
    시장별 API 호출 메서드를 반드시 구현해야 한다.
    """
    BASE_URL: str = ""
    PRICE_TR_ID: str = ""
    PORTFOLIO_TR_ID: str = ""
    BUY_TR_ID: str = ""
    SELL_TR_ID: str = ""
    PENDING_TR_ID: str = ""
    FILL_TR_ID: str = ""
    CANCEL_TR_ID: str = ""
    ASKING_PRICE_TR_ID: str = ""

    SPREAD_THRESHOLD_PCT: float = 0.5  # 스프레드 임계값 (%) — 초과 시 주문 보류

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        self.app_key = app_key
        self.app_secret = app_secret
        self.acc_no = acc_no
        self.logger = logger

        # 계좌번호 분리 (앞 8자리, 뒤 2자리)
        self.cano = acc_no[:8]
        self.acnt_prdt_cd = acc_no[8:]

        self.base_url = self.BASE_URL
        self.token_expires_at: Optional[datetime] = None
        self.access_token = self._auth()

    def _auth(self) -> str:
        """접근 토큰 발급 및 만료 시각 저장. 유효한 캐시가 있으면 API 호출 생략."""
        cached = self._load_token_from_cache()
        if cached is not None:
            self.logger.info("[KisBroker] 캐시에서 토큰 로드 (API 호출 생략)")
            self.token_expires_at = datetime.fromisoformat(cached["expires_at"])
            return cached["access_token"]

        self.logger.info("[KisBroker] 새 토큰 발급 중...")
        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        try:
            res = _pkg.requests.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            if 'access_token' not in data:
                raise Exception(f"Auth Failed: {data}")
            expires_in = int(data.get('expires_in', 86400))
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            token = data['access_token']
            self._save_token_to_cache(token, self.token_expires_at)
            return token
        except Exception as e:
            self.logger.error(f"[KisBroker] Auth Error: {e}")
            raise e

    def _load_token_from_cache(self) -> Optional[dict]:
        """인스턴스 메서드 래퍼 — 기존 테스트 patch 호환용."""
        return kis_token_cache.load_token_from_cache(self.app_key, self.logger)

    def _save_token_to_cache(self, token: str, expires_at: datetime) -> None:
        """인스턴스 메서드 래퍼 — 기존 테스트 patch 호환용."""
        kis_token_cache.save_token_to_cache(self.app_key, token, expires_at, self.logger)

    def _ensure_token(self) -> None:
        """토큰 만료 60초 전이면 자동 재발급"""
        if self.token_expires_at is None or datetime.now() >= self.token_expires_at - timedelta(seconds=60):
            self.logger.info("[KisBroker] Access Token 갱신 중...")
            self.access_token = self._auth()

    def _get_header(self, tr_id: str, data: dict = None) -> dict:
        """API 공통 헤더 생성 (HashKey 포함)"""
        self._ensure_token()
        return kis_http.build_header(
            self.base_url,
            self.app_key,
            self.app_secret,
            self.access_token,
            tr_id,
            data,
            self.logger,
        )

    def _get_hashkey(self, data: dict) -> Optional[str]:
        return kis_http.fetch_hashkey(self.base_url, self.app_key, self.app_secret, data, self.logger)

    # --- 추상 메서드 (서브클래스에서 구현 필수) ---

    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        raise NotImplementedError

    def get_portfolio(self) -> Portfolio:
        raise NotImplementedError

    def _send_order_and_wait(self, order: Order, timeout: int = 30) -> Optional[TradeExecution]:
        raise NotImplementedError

    def _fetch_asking_price(self, ticker: str) -> tuple:
        raise NotImplementedError

    def _get_pending_orders_count(self) -> int:
        raise NotImplementedError

    # --- 공통 오케스트레이션 로직 ---

    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]:
        executions = []
        sell_orders = [o for o in orders if o.action == OrderAction.SELL]
        buy_orders = [o for o in orders if o.action == OrderAction.BUY]

        # === 1. 매도 실행 (주문 + 체결 대기 통합) ===
        if sell_orders:
            self.logger.info(f"[KisBroker] Processing {len(sell_orders)} SELL orders...")
            for order in sell_orders:
                res = self._send_order_and_wait(order, timeout=30)
                if res: executions.append(res)
                time.sleep(0.2)  # API 제한 고려

        # === 2. 잔고 갱신 및 매수 재계산 ===
        # 매도 미체결(타임아웃) 시 매수 중단 — 이중 매도 및 자금 부족 방지 (#227)
        sell_timed_out = any(
            e.status == ExecutionStatus.ORDERED
            for e in executions
            if e.action == OrderAction.SELL
        )
        if sell_timed_out:
            self.logger.error("[KisBroker] 매도 미체결 주문 존재 — 매수 중단 (#227)")
            return executions

        if buy_orders:
            if sell_orders:
                time.sleep(2)  # 정산 대기

            # === 3. 매수 실행 (주문 + 체결 대기 통합) ===
            for order in buy_orders:
                # 매수 주문마다 증권사 API로 실제 가용 금액 조회
                pf = self.get_portfolio()
                current_cash = pf.total_cash
                self.logger.info(f"[KisBroker] Available Cash for BUY: {current_cash:,.0f}")

                # 안전 마진 (98%)
                SAFE_MARGIN = 0.98
                budget = current_cash * SAFE_MARGIN

                # 호가 기반 매수가 추정 (ask 가격 사용, 실패 시 2% 버퍼)
                bid, ask = self._fetch_asking_price(order.ticker)
                if not self._check_spread(bid, ask):
                    self.logger.warning(f"[KisBroker] 스프레드 비정상 — {order.ticker} 매수 건너뜀")
                    continue
                estimated_price = ask if ask > 0 else order.price * 1.02
                if estimated_price <= 0: continue

                # 수량 재계산
                max_qty = int(budget / estimated_price)
                actual_qty = min(order.quantity, max_qty)

                if max_qty < order.quantity:
                    self.logger.warning(f"⚠️ Qty Adjusted: {order.ticker} {order.quantity} -> {actual_qty}")

                if actual_qty > 0:
                    adjusted_order = Order(ticker=order.ticker, action=order.action, quantity=actual_qty, price=order.price)
                    res = self._send_order_and_wait(adjusted_order, timeout=30)
                    if res:
                        executions.append(res)
                    time.sleep(0.2)

        return executions

    def _wait_for_completion(self, timeout: int = 60) -> bool:
        """미체결 내역이 없을 때까지 대기"""
        start = time.time()
        while (time.time() - start) < timeout:
            count = self._get_pending_orders_count()
            if count == 0:
                return True
            time.sleep(2)
        return False

    def _check_spread(self, bid: float, ask: float) -> bool:
        """스프레드 정상 여부 반환. bid/ask가 0이면 True (fallback 허용)"""
        if bid <= 0 or ask <= 0:
            return True
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        return spread_pct <= self.SPREAD_THRESHOLD_PCT
