# src/infra/broker.py
from typing import List, Dict, Optional
from src.core.interfaces import IBrokerAdapter, ILogger
from src.core.models import Portfolio, Order, TradeExecution, OrderAction, ExecutionStatus
from src.config import TICKER_EXCHANGE_MAP, EXCHANGE_CODE_SHORT_TO_FULL
import time
import requests
from datetime import datetime, timedelta

class MockBroker(IBrokerAdapter):
    """
    로컬 테스트용 가상 브로커
    실제 주문을 내지 않고 로그만 출력함
    """
    def __init__(self, initial_cash: float = 10000.0, holdings: Dict[str, int] = None, logger: Optional[ILogger] = None):
        self.cash = initial_cash
        self.holdings = holdings if holdings else {}
        self.logger = logger
        # 현재가는 외부에서 주입받거나, API 호출 시 업데이트된다고 가정
    
    def get_portfolio(self) -> Portfolio:
        # 테스트를 위해 현재가를 임의로 설정 (실제 봇에선 DataProvider가 최신가 제공)
        # 여기서는 main.py에서 DataProvider가 가져온 가격을 주입받는 구조가 아니므로,
        # 편의상 'Mock' 데이터 리턴. 실제로는 API 조회.
        return Portfolio(
            total_cash=self.cash,
            holdings=self.holdings,
            current_prices={} # Mock에서는 비워둠 (로직에서 채워넣거나 외부 주입)
        )
    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        # 테스트를 위해 현재가에 약간의 변동(예: +0.5%)을 줄 수도 있음
        return {t: 100.0 for t in tickers}
    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]:
        executions = []
        
        # 1. 매도/매수 분리
        sell_orders = [o for o in orders if o.action == OrderAction.SELL]
        buy_orders = [o for o in orders if o.action == OrderAction.BUY]
        
        # ==========================================
        # Phase 1: 매도 집행 (Sell Execution)
        # ==========================================
        if sell_orders:
            if self.logger: self.logger.info("[Broker] Sending SELL orders...")
            for order in sell_orders:
                # API로 매도 주문 전송
                res = self._process_order_internal(order)
                executions.append(res)

            # [핵심] 매도 체결 확인 루프 (Polling)
            if not self._wait_for_completion(timeout=60):
                if self.logger: self.logger.warning("[Broker] Sell orders timed out. Some might be partial/unfilled.")
                # (선택사항) 미체결 주문 취소 로직 추가 가능
                # self._cancel_all_pending_sells()
        
        # ==========================================
        # Phase 2: 잔고 갱신 및 재계산 (Refresh & Recalc)
        # ==========================================
        if sell_orders:
            # 매도가 있었으면 예수금이 변했을 테니, API로 정확한 현재 잔고를 다시 가져옴
            if self.logger: self.logger.info("[Broker] Refreshing Cash Balance...")
            self._refresh_balance_from_api()
        
        # ==========================================
        # Phase 3: 매수 집행 (Buy Execution)
        # ==========================================
        if buy_orders:
            if self.logger: self.logger.info("[Broker] Sending BUY orders...")
            for order in buy_orders:
                # 안전 마진: 현금의 98%만 사용 (환율 변동, 수수료, 슬리피지 대비)
                SAFE_MARGIN = 0.98
                current_cash = self.cash
                
                # 버퍼가 적용된 주문 가능 금액
                budget = current_cash * SAFE_MARGIN
                
                # 시장가 매수 가정 (현재가보다 1% 높게 잡음)
                estimated_price = order.price * 1.01
                
                if estimated_price <= 0: continue

                max_qty = int(budget / estimated_price)
                # 원본 Order 객체를 변경하지 않고 조정된 수량으로 로컬 변수 사용
                actual_qty = min(order.quantity, max_qty)

                if max_qty < order.quantity:
                    if self.logger: self.logger.warning(f"[Broker] Qty Adjusted: {order.ticker} {order.quantity} -> {actual_qty} (Budget: ${budget:.2f})")

                if actual_qty > 0:
                    # 조정된 수량으로 새 Order 생성 (원본 불변 유지)
                    adjusted_order = Order(ticker=order.ticker, action=order.action, quantity=actual_qty, price=order.price)
                    res = self._process_order_internal(adjusted_order)
                    executions.append(res)
        
        return executions
        
    def _process_order_internal(self, order: Order) -> TradeExecution:
        """단일 주문 처리 및 Mock 잔고 갱신 헬퍼"""
        # 슬리피지 시뮬레이션
        slippage = 1.01 if order.action == OrderAction.BUY else 0.99
        exec_price = order.price * slippage

        # 잔고 반영 및 실제 체결 수량 결정 (수수료는 actual_qty 확정 후 단일 계산)
        if order.action == OrderAction.BUY:
            actual_qty = order.quantity
            amount = exec_price * actual_qty
            fee = amount * 0.001
            self.cash -= (amount + fee)
            self.holdings[order.ticker] = self.holdings.get(order.ticker, 0) + actual_qty
        elif order.action == OrderAction.SELL:
            current_qty = self.holdings.get(order.ticker, 0)
            actual_qty = min(order.quantity, current_qty)  # 보유량 한도 제한
            if actual_qty < order.quantity and self.logger:
                self.logger.warning(
                    f"[QTY ADJUSTED] {order.ticker} SELL: 요청 {order.quantity}주 → 실제 체결 {actual_qty}주 (보유량 부족)"
                )
            amount = exec_price * actual_qty
            fee = amount * 0.001
            self.cash += (amount - fee)
            self.holdings[order.ticker] = current_qty - actual_qty

        if self.logger:
            self.logger.info(f"[FILLED] {order.action} {order.ticker}: {actual_qty} @ ${exec_price:.2f} (Fee: ${fee:.2f})")

        return TradeExecution(
            ticker=order.ticker,
            action=order.action,
            quantity=actual_qty,
            price=round(exec_price, 2),
            fee=round(fee, 2),
            date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status=ExecutionStatus.FILLED
        )
    def _wait_for_completion(self, timeout: int = 60) -> bool:
        """
        모든 주문이 체결될 때까지 대기하는 함수
        True: 전량 체결, False: 타임아웃(미체결 남음)
        """
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            # 증권사 API: '미체결 내역' 조회
            pending_orders = self._get_pending_orders_count()
            
            if pending_orders == 0:
                if self.logger: self.logger.info("[Broker] All sell orders filled!")
                return True

            if self.logger: self.logger.info(f"[Broker] Waiting for fills ({pending_orders} pending) ...")
            time.sleep(2) # 2초 간격 polling
            
        return False

    def _get_pending_orders_count(self) -> int:
        # 실제 구현 시: KIS API '주문/체결 > 미체결내역 상세조회' 호출
        # Mock에서는 0 리턴
        return 0 

    def _refresh_balance_from_api(self):
        # 실전 브로커에서 오버라이드: API로 정확한 잔고를 가져오기 전 반영 대기
        time.sleep(1) # API 반영 딜레이 고려
        # 실제 구현 시: KIS API 잔고 조회 후 self.cash 업데이트


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

        # URL은 서브클래스 클래스 상수에서 설정
        self.base_url = self.BASE_URL
        self.token_expires_at: Optional[datetime] = None
        self.access_token = self._auth()

    def _auth(self) -> str:
        """접근 토큰 발급 및 만료 시각 저장"""
        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        try:
            res = requests.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            if 'access_token' not in data:
                raise Exception(f"Auth Failed: {data}")
            expires_in = int(data.get('expires_in', 86400))
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            return data['access_token']
        except Exception as e:
            self.logger.error(f"[KisBroker] Auth Error: {e}")
            raise e

    def _ensure_token(self) -> None:
        """토큰 만료 60초 전이면 자동 재발급"""
        if self.token_expires_at is None or datetime.now() >= self.token_expires_at - timedelta(seconds=60):
            self.logger.info("[KisBroker] Access Token 갱신 중...")
            self.access_token = self._auth()

    def _get_header(self, tr_id: str, data: dict = None) -> dict:
        """API 공통 헤더 생성 (HashKey 포함)"""
        self._ensure_token()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P" # 개인
        }
        # 주문 등 POST 요청 시 HashKey 필요
        if data:
            hashkey = self._get_hashkey(data)
            if hashkey is None:
                raise ValueError("[KisBroker] HashKey 생성 실패로 주문 헤더를 생성할 수 없습니다.")
            headers["hashkey"] = hashkey
        return headers

    def _get_hashkey(self, data: dict) -> Optional[str]:
        url = f"{self.base_url}/uapi/hashkey"
        try:
            res = requests.post(url, headers={
                "content-type": "application/json",
                "appkey": self.app_key,
                "appsecret": self.app_secret
            }, json=data)
            res.raise_for_status()
            return res.json()["HASH"]
        except Exception as e:
            self.logger.error(f"[KisBroker] HashKey 생성 실패: {e}")
            return None
    
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
                time.sleep(0.2) # API 제한 고려

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
                time.sleep(2) # 정산 대기

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


class KisOverseasBrokerBase(KisBrokerCommon):
    """해외주식(미국) 전용 브로커 베이스 클래스.
    KisBrokerCommon의 추상 메서드를 해외주식 API로 구현한다.
    """
    ASKING_PRICE_TR_ID: str = "HHDFS76200100"  # 해외주식 호가 조회 (실전/모의 동일)

    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        """
        해외주식 현재가 조회 (반복 호출)
        """
        prices = {}
        tr_id = self.PRICE_TR_ID
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/price"
        for ticker in tickers:
            exch = self._get_exchange_code(ticker)
            params = {
                "AUTH": "",
                "EXCD": exch,
                "SYMB": ticker
            }
            # GET 요청은 HashKey 불필요
            headers = self._get_header(tr_id)
            try:
                # 잦은 호출 방지 (초당 제한 고려)
                time.sleep(0.1) 
                res = requests.get(url, headers=headers, params=params)
                res.raise_for_status()
                data = res.json()

                if data['rt_cd'] == '0': # 성공
                    # last: 현재가
                    price = float(data['output']['last'])
                    prices[ticker] = price
                else:
                    self.logger.warning(f"[KisBroker] Price fetch failed for {ticker}: {data.get('msg1')}")
                    prices[ticker] = 0.0
            except Exception as e:
                self.logger.error(f"[KisBroker] Price fetch error {ticker}: {e}")
                prices[ticker] = 0.0
                
        return prices

    def get_portfolio(self) -> Portfolio:
        """
        해외주식 잔고 및 예수금 조회 (NASD/NYSE/AMEX 전 거래소 통합)
        _get_pending_orders_count()와 동일하게 모든 거래소를 순회하여 누락 없이 수집한다.

        total_cash 는 output2['ovrs_ord_psbl_amt'] (해외주문가능금액) 를 사용한다.
        이 필드는 KIS API가 미체결(pending) 주문의 예약금을 이미 차감한 실제 가용 금액을
        반환하므로, 연속 매수 루프에서 중복 사용을 방지할 수 있다. (#225)
        """
        tr_id = self.PORTFOLIO_TR_ID
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance"

        # 잔고/미체결 API는 전체 거래소 코드(NASD, NYSE, AMEX) 사용
        target_exchanges = ["NASD", "NYSE", "AMEX"]

        total_cash = 0.0
        cash_fetched = False
        all_holdings: Dict[str, int] = {}
        all_prices: Dict[str, float] = {}

        for exch in target_exchanges:
            params = {
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.acnt_prdt_cd,
                "OVRS_EXCG_CD": exch,
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": ""
            }
            headers = self._get_header(tr_id)
            try:
                time.sleep(0.2)  # API 제한 고려
                res = requests.get(url, headers=headers, params=params)
                res.raise_for_status()
                data = res.json()

                if data['rt_cd'] != '0':
                    self.logger.warning(f"[KisBroker] Get Portfolio Failed ({exch}): {data.get('msg1')}")
                    continue

                # 예수금은 최초 성공 응답에서만 가져옴 (거래소 무관하게 계좌 전체 금액 동일)
                if not cash_fetched:
                    total_cash = float(data['output2']['ovrs_ord_psbl_amt'])
                    cash_fetched = True

                # 보유 종목 병합
                for item in data['output1']:
                    qty = int(item['ovrs_cblc_qty'])
                    if qty > 0:
                        ticker = item['ovrs_pdno']
                        all_holdings[ticker] = qty
                        all_prices[ticker] = float(item['now_pric2'])

            except Exception as e:
                self.logger.error(f"[KisBroker] Error getting portfolio ({exch}): {e}")

        return Portfolio(
            total_cash=total_cash,
            holdings=all_holdings,
            current_prices=all_prices
        )

    def _send_order(self, order: Order) -> Optional[TradeExecution]:
        """실제 주문 API 호출"""
        tr_id = self.BUY_TR_ID if order.action == OrderAction.BUY else self.SELL_TR_ID

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        # 주문 API는 전체 거래소 코드 사용 (NASD, NYSE, AMEX)
        exch = self._get_exchange_code(order.ticker, api_type="order")

        # 호가 기반 주문가 결정
        bid, ask = self._fetch_asking_price(order.ticker)

        # 스프레드 이상 시 주문 거부
        if not self._check_spread(bid, ask):
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid * 100
            self.logger.warning(
                f"[KisBroker] 스프레드 비정상 — {order.ticker} "
                f"bid={bid} ask={ask} spread={spread_pct:.2f}% > {self.SPREAD_THRESHOLD_PCT}% — 주문 보류"
            )
            return None

        # 매수: ask(매도호가), 매도: bid(매수호가) 사용. 호가 조회 실패 시 last price fallback
        if order.action == OrderAction.BUY:
            order_price = round(ask, 2) if ask > 0 else round(order.price, 2)
        else:
            order_price = round(bid, 2) if bid > 0 else round(order.price, 2)

        data = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exch,
            "PDNO": order.ticker,
            "ORD_QTY": str(order.quantity),
            "OVRS_ORD_UNPR": str(order_price),
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": "",
            "SLL_TYPE": "00" if order.action == OrderAction.SELL else "",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"  # 00: 지정가 (미국은 보통 지정가 사용)
        }
        
        try:
            headers = self._get_header(tr_id, data)
            res = requests.post(url, headers=headers, json=data)
            res.raise_for_status()
            resp_data = res.json()
            
            if resp_data['rt_cd'] != '0':
                self.logger.error(f"[KisBroker] Order Failed: {resp_data.get('msg1')}")
                return None
            
            self.logger.info(f"[KisBroker] Order Sent: {order.action} {order.ticker} {order.quantity} @ {order_price}")
            
            # 체결 정보 생성 (API는 주문 접수만 알려주므로, 일단 접수된 내용으로 Execution 생성)
            # 정확히 하려면 체결조회 API를 별도로 호출해야 하지만, 여기선 주문접수=성공으로 간주하고 반환
            return TradeExecution(
                ticker=order.ticker,
                action=order.action,
                quantity=order.quantity,
                price=order_price,
                fee=0.0, # 수수료는 체결 조회 전엔 모름
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=ExecutionStatus.ORDERED
            )
            
        except Exception as e:
            self.logger.error(f"[KisBroker] Order Error: {e}")
            return None

    def _send_order_and_wait(self, order: Order, timeout: int = 30) -> Optional[TradeExecution]:
        """주문 전송 후 체결 대기. 체결 시 FILLED, 타임아웃 시 ORDERED(미확인 체결) 반환."""
        tr_id = self.BUY_TR_ID if order.action == OrderAction.BUY else self.SELL_TR_ID
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        exch = self._get_exchange_code(order.ticker, api_type="order")

        # 호가 기반 주문가 결정
        bid, ask = self._fetch_asking_price(order.ticker)

        # 스프레드 이상 시 주문 거부
        if not self._check_spread(bid, ask):
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid * 100
            self.logger.warning(
                f"[KisBroker] 스프레드 비정상 — {order.ticker} "
                f"bid={bid} ask={ask} spread={spread_pct:.2f}% > {self.SPREAD_THRESHOLD_PCT}% — 주문 보류"
            )
            return TradeExecution(
                ticker=order.ticker, action=order.action, quantity=order.quantity,
                price=order.price, fee=0.0,
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=ExecutionStatus.REJECTED
            )

        # 매수: ask(매도호가), 매도: bid(매수호가) 사용. 호가 조회 실패 시 last price fallback
        if order.action == OrderAction.BUY:
            order_price = round(ask, 2) if ask > 0 else round(order.price, 2)
        else:
            order_price = round(bid, 2) if bid > 0 else round(order.price, 2)

        data = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exch,
            "PDNO": order.ticker,
            "ORD_QTY": str(order.quantity),
            "OVRS_ORD_UNPR": str(order_price),
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": "",
            "SLL_TYPE": "00" if order.action == OrderAction.SELL else "",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }

        try:
            headers = self._get_header(tr_id, data)
            res = requests.post(url, headers=headers, json=data)
            res.raise_for_status()
            resp_data = res.json()

            if resp_data['rt_cd'] != '0':
                self.logger.error(f"[KisBroker] Order Failed: {resp_data.get('msg1')}")
                return None

            odno = resp_data.get('output', {}).get('ODNO', '')
            self.logger.info(
                f"[KisBroker] Order Sent: {order.action} {order.ticker} "
                f"{order.quantity} @ {order_price} (ODNO={odno})"
            )

            # 체결 대기 및 실제 체결 정보 조회
            if odno:
                filled = self._poll_order_fill(odno, exch, timeout=timeout)
                if filled:
                    fill_price, fill_qty, fill_fee = self._query_fill_details(odno, order.ticker, exch)
                    actual_price = fill_price if fill_price > 0 else order_price
                    actual_qty = fill_qty if fill_qty > 0 else order.quantity
                    self.logger.info(
                        f"[KisBroker] Order FILLED: {order.ticker} ODNO={odno} "
                        f"price={actual_price} qty={actual_qty} fee={fill_fee}"
                    )
                    return TradeExecution(
                        ticker=order.ticker,
                        action=order.action,
                        quantity=actual_qty,
                        price=actual_price,
                        fee=fill_fee,
                        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        status=ExecutionStatus.FILLED
                    )
                else:
                    self.logger.warning(
                        f"[KisBroker] Order NOT confirmed within {timeout}s: "
                        f"{order.ticker} ODNO={odno} — 미체결 주문 취소 시도"
                    )
                    cancelled = self._cancel_order(odno, exch, order.ticker, order.quantity)
                    if not cancelled:
                        self.logger.error(
                            f"[KisBroker] 주문 취소 실패: {order.ticker} ODNO={odno} — 수동 확인 필요"
                        )

            # 타임아웃 또는 ODNO 미획득 시 ORDERED 반환
            return TradeExecution(
                ticker=order.ticker,
                action=order.action,
                quantity=order.quantity,
                price=order_price,
                fee=0.0,
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=ExecutionStatus.ORDERED
            )

        except Exception as e:
            self.logger.error(f"[KisBroker] Order Error: {e}")
            return None

    def _poll_order_fill(self, odno: str, exch: str, timeout: int = 30) -> bool:
        """미체결 목록에서 해당 ODNO가 사라질 때까지 polling. 체결 여부 반환."""
        start = time.time()
        while (time.time() - start) < timeout:
            try:
                pending_ids = self._get_pending_order_ids(exch)
                if odno not in pending_ids:
                    return True
            except Exception as e:
                self.logger.warning(f"[KisBroker] Fill poll error (ODNO={odno}): {e}")
            time.sleep(2)
        return False

    def _get_pending_order_ids(self, exch: str) -> set:
        """특정 거래소의 미체결 주문번호 집합 반환."""
        tr_id = self.PENDING_TR_ID
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-nccs"
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exch,
            "SORT_SQN": "DS",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }
        headers = self._get_header(tr_id)
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()
        if data['rt_cd'] == '0':
            return {item.get('odno', '') for item in data.get('output', [])}
        return set()

    def _query_fill_details(self, odno: str, ticker: str, exch: str):
        """
        체결내역 조회 API(inquire-ccnl)로 실제 체결가·수량·수수료 반환.
        조회 실패 시 (0.0, 0, 0.0) 반환 → 호출측에서 주문가로 fallback.
        TR_ID: TTTS3035R (실전) / VTTS3035R (모의)
        """
        if not self.FILL_TR_ID:
            return 0.0, 0, 0.0

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-ccnl"
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": ticker,
            "ORD_STRT_DT": today,
            "ORD_END_DT": today,
            "SLL_BUY_DVSN_CD": "00",  # 00: 전체
            "CCLD_NCCS_DVSN": "01",   # 01: 체결만
            "OVRS_EXCG_CD": exch,
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }
        try:
            headers = self._get_header(self.FILL_TR_ID)
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
            if data['rt_cd'] != '0':
                return 0.0, 0, 0.0

            for item in data.get('output', []):
                if item.get('odno') != odno:
                    continue
                fill_price = float(item.get('ft_ccld_unpr3', 0) or 0)
                fill_qty = int(item.get('ft_ccld_qty', 0) or 0)
                fill_fee = float(item.get('ovrs_stck_ccld_fee', 0) or 0)
                return fill_price, fill_qty, fill_fee
        except Exception as e:
            self.logger.warning(f"[KisBroker] Fill detail query error (ODNO={odno}): {e}")
        return 0.0, 0, 0.0

    def _cancel_order(self, odno: str, exch: str, ticker: str, quantity: int) -> bool:
        """미체결 주문 취소. 성공 시 True, 실패 시 False 반환.
        TR_ID: TTTT1004U (실전) / VTTT1004U (모의)
        """
        if not self.CANCEL_TR_ID:
            self.logger.warning("[KisBroker] CANCEL_TR_ID 미설정 — 주문 취소 불가")
            return False

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        data = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exch,
            "PDNO": ticker,
            "ORGN_ODNO": odno,
            "ORD_DVSN": "00",
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": "0",
            "RVSE_CNCL_DVSN_CD": "02",  # 02: 취소
            "ORD_SVR_DVSN_CD": "0",
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": ""
        }
        try:
            headers = self._get_header(self.CANCEL_TR_ID, data)
            res = requests.post(url, headers=headers, json=data)
            res.raise_for_status()
            resp_data = res.json()
            if resp_data['rt_cd'] == '0':
                self.logger.info(f"[KisBroker] Order Cancelled: {ticker} ODNO={odno}")
                return True
            else:
                self.logger.error(
                    f"[KisBroker] Cancel Failed: {ticker} ODNO={odno} — {resp_data.get('msg1')}"
                )
                return False
        except Exception as e:
            self.logger.error(f"[KisBroker] Cancel Error: {ticker} ODNO={odno} — {e}")
            return False

    def _get_pending_orders_count(self) -> int:
        """
        [해외주식] 미체결 내역 조회
        NASD -> NYSE -> AMEX 순으로 조회하며, 미체결이 하나라도 발견되면 즉시 반환합니다.
        (전체 개수 합산보다 존재 여부가 중요함)
        """
        tr_id = self.PENDING_TR_ID
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-nccs"

        # 미체결 API는 전체 거래소 코드(NASD, NYSE, AMEX) 사용
        target_exchanges = ["NASD", "NYSE", "AMEX"]

        for exch in target_exchanges:
            params = {
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.acnt_prdt_cd,
                "OVRS_EXCG_CD": exch,
                "SORT_SQN": "DS",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": ""
            }
            
            headers = self._get_header(tr_id)
            
            try:
                time.sleep(0.2) # API 제한 고려
                
                res = requests.get(url, headers=headers, params=params)
                res.raise_for_status()
                data = res.json()

                if data['rt_cd'] == '0':
                    count = len(data.get('output', []))
                    if count > 0:
                        self.logger.info(f"[KisBroker] Found {count} pending orders in {exch}. Waiting...")
                        return count # [핵심] 발견 즉시 리턴 (다른 거래소 조회 생략)
                else:
                    self.logger.warning(f"[KisBroker] Pending Check Failed ({exch}): {data.get('msg1')}")
                    
            except Exception as e:
                self.logger.error(f"[KisBroker] Pending Check Error ({exch}): {e}")
                
        return 0 # 모든 거래소를 다 봤는데 미체결이 없음
    
    def _fetch_asking_price(self, ticker: str) -> tuple:
        """호가 조회: (best_bid, best_ask) 반환. 실패 시 (0.0, 0.0)"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/inquire-asking-price"
        exch = self._get_exchange_code(ticker)
        params = {
            "AUTH": "",
            "EXCD": exch,
            "SYMB": ticker
        }
        headers = self._get_header(self.ASKING_PRICE_TR_ID)
        try:
            time.sleep(0.1)
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            if data['rt_cd'] != '0':
                self.logger.warning(f"[KisBroker] 호가 조회 실패 {ticker}: {data.get('msg1')}")
                return (0.0, 0.0)

            output2 = data.get('output2', {})
            # REST API 호가 필드명 (소문자): pask1(매도1호가), pbid1(매수1호가)
            self.logger.debug(f"[KisBroker] 호가 응답 {ticker}: {output2}")
            bid = float(output2.get('pbid1', 0) or 0)
            ask = float(output2.get('pask1', 0) or 0)
            return (bid, ask)

        except Exception as e:
            self.logger.warning(f"[KisBroker] 호가 조회 에러 {ticker}: {e}")
            return (0.0, 0.0)

    def _get_exchange_code(self, ticker: str, api_type: str = "price") -> str:
        """
        티커별 거래소 코드 반환 (config.TICKER_EXCHANGE_MAP 참조)
        - api_type="price"  : 현재가 조회 API용 단축 코드 (NAS, NYS, AMS)
        - api_type="order"  : 주문/잔고/미체결 API용 전체 코드 (NASD, NYSE, AMEX)
        새 티커 추가 시 src/config.py의 TICKER_EXCHANGE_MAP만 수정하면 됩니다.
        """
        price_code = TICKER_EXCHANGE_MAP.get(ticker)
        if price_code is None:
            self.logger.warning(
                f"[KisBroker] 알 수 없는 티커 '{ticker}' - 기본 거래소 코드(NAS/NASD) 사용. "
                f"src/config.py의 TICKER_EXCHANGE_MAP에 티커를 추가하세요."
            )
            price_code = 'NAS'
        if api_type == "order":
            return EXCHANGE_CODE_SHORT_TO_FULL.get(price_code, 'NASD')
        return price_code


class KisPaperBroker(KisOverseasBrokerBase):
    """한국투자증권 모의투자 브로커 — 해외주식 (가상거래 서버)"""
    BASE_URL = "https://openapivts.koreainvestment.com:29443"
    PRICE_TR_ID = "HHDFS00000300"  # 해외주식 현재가 조회 (실전/모의 동일 TR_ID)
    PORTFOLIO_TR_ID = "VTTS3012R"
    BUY_TR_ID = "VTTT1002U"
    SELL_TR_ID = "VTTT1006U"
    PENDING_TR_ID = "VTTS3018R"
    FILL_TR_ID = "VTTS3035R"    # 해외주식 체결내역 조회 (모의)
    CANCEL_TR_ID = "VTTT1004U"  # 해외주식 주문 취소 (모의)

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisPaperBroker] Mode: PAPER TRADING (Virtual)")


class KisLiveBroker(KisOverseasBrokerBase):
    """한국투자증권 실전투자 브로커 — 해외주식 (실거래 서버)"""
    BASE_URL = "https://openapi.koreainvestment.com:9443"
    PRICE_TR_ID = "HHDFS00000300"
    PORTFOLIO_TR_ID = "TTTS3012R"
    BUY_TR_ID = "TTTT1002U"    # 미국 매수 (TTTS는 홍콩용)
    SELL_TR_ID = "TTTT1006U"   # 미국 매도
    PENDING_TR_ID = "TTTS3018R"
    FILL_TR_ID = "TTTS3035R"   # 해외주식 체결내역 조회 (실전)
    CANCEL_TR_ID = "TTTT1004U" # 해외주식 주문 취소 (실전)

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisLiveBroker] Mode: LIVE TRADING")


# ============================================================
# 국내주식 브로커
# ============================================================

class KisDomesticBrokerBase(KisBrokerCommon):
    """국내주식 전용 브로커 베이스 클래스.
    KisBrokerCommon의 추상 메서드를 국내주식 KIS API로 구현한다.
    """
    ASKING_PRICE_TR_ID: str = "FHKST01010200"  # 국내주식 호가 조회 (실전/모의 동일)

    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        """국내주식 현재가 조회"""
        prices = {}
        tr_id = self.PRICE_TR_ID
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        for ticker in tickers:
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",  # J: 주식/ETF
                "FID_INPUT_ISCD": ticker          # 종목코드 (6자리)
            }
            headers = self._get_header(tr_id)
            try:
                time.sleep(0.1)
                res = requests.get(url, headers=headers, params=params)
                res.raise_for_status()
                data = res.json()

                if data['rt_cd'] == '0':
                    price = float(data['output']['stck_prpr'])
                    prices[ticker] = price
                else:
                    self.logger.warning(f"[KisDomestic] Price fetch failed for {ticker}: {data.get('msg1')}")
                    prices[ticker] = 0.0
            except Exception as e:
                self.logger.error(f"[KisDomestic] Price fetch error {ticker}: {e}")
                prices[ticker] = 0.0

        return prices

    def get_portfolio(self) -> Portfolio:
        """국내주식 잔고 및 예수금 조회 (KRX 단일 거래소 — 1회 호출)"""
        tr_id = self.PORTFOLIO_TR_ID
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"

        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",          # 시간외단일가 여부
            "OFL_YN": "",                  # 오프라인 여부
            "INQR_DVSN": "02",            # 조회구분 (02: 종목별)
            "UNPR_DVSN": "01",            # 단가구분
            "FUND_STTL_ICLD_YN": "N",     # 펀드결제분 포함 여부
            "FNCG_AMT_AUTO_RDPT_YN": "N", # 융자금액 자동상환 여부
            "PRCS_DVSN": "00",            # 처리구분 (00: 전일매매포함)
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        headers = self._get_header(tr_id)

        total_cash = 0.0
        all_holdings: Dict[str, int] = {}
        all_prices: Dict[str, float] = {}

        try:
            time.sleep(0.2)
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            if data['rt_cd'] != '0':
                self.logger.warning(f"[KisDomestic] Get Portfolio Failed: {data.get('msg1')}")
                return Portfolio(total_cash=0.0, holdings={}, current_prices={})

            # 예수금 (dnca_tot_amt: 예수금총액)
            total_cash = float(data.get('output2', [{}])[0].get('dnca_tot_amt', 0) or 0)

            # 보유 종목
            for item in data.get('output1', []):
                qty = int(item.get('hldg_qty', 0) or 0)
                if qty > 0:
                    ticker = item['pdno']           # 종목코드
                    all_holdings[ticker] = qty
                    all_prices[ticker] = float(item.get('prpr', 0) or 0)  # 현재가

        except Exception as e:
            self.logger.error(f"[KisDomestic] Error getting portfolio: {e}")

        return Portfolio(
            total_cash=total_cash,
            holdings=all_holdings,
            current_prices=all_prices
        )

    def _send_order_and_wait(self, order: Order, timeout: int = 30) -> Optional[TradeExecution]:
        """국내주식 주문 전송 후 체결 대기."""
        tr_id = self.BUY_TR_ID if order.action == OrderAction.BUY else self.SELL_TR_ID
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"

        # 호가 기반 주문가 결정
        bid, ask = self._fetch_asking_price(order.ticker)

        # 스프레드 이상 시 주문 거부
        if not self._check_spread(bid, ask):
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid * 100
            self.logger.warning(
                f"[KisDomestic] 스프레드 비정상 — {order.ticker} "
                f"bid={bid} ask={ask} spread={spread_pct:.2f}% > {self.SPREAD_THRESHOLD_PCT}% — 주문 보류"
            )
            return TradeExecution(
                ticker=order.ticker, action=order.action, quantity=order.quantity,
                price=order.price, fee=0.0,
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=ExecutionStatus.REJECTED
            )

        # 매수: ask(매도호가), 매도: bid(매수호가). 호가 조회 실패 시 last price fallback
        if order.action == OrderAction.BUY:
            order_price = int(ask) if ask > 0 else int(order.price)
        else:
            order_price = int(bid) if bid > 0 else int(order.price)

        data = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": order.ticker,              # 종목코드 (6자리)
            "ORD_DVSN": "00",                  # 00: 지정가
            "ORD_QTY": str(order.quantity),
            "ORD_UNPR": str(order_price),      # KRW 정수
        }

        try:
            headers = self._get_header(tr_id, data)
            res = requests.post(url, headers=headers, json=data)
            res.raise_for_status()
            resp_data = res.json()

            if resp_data['rt_cd'] != '0':
                self.logger.error(f"[KisDomestic] Order Failed: {resp_data.get('msg1')}")
                return None

            odno = resp_data.get('output', {}).get('ODNO', '')
            self.logger.info(
                f"[KisDomestic] Order Sent: {order.action} {order.ticker} "
                f"{order.quantity} @ {order_price} (ODNO={odno})"
            )

            # 체결 대기 및 실제 체결 정보 조회
            if odno:
                filled = self._poll_order_fill(odno, timeout=timeout)
                if filled:
                    fill_price, fill_qty, fill_fee = self._query_fill_details(odno, order.ticker)
                    actual_price = fill_price if fill_price > 0 else float(order_price)
                    actual_qty = fill_qty if fill_qty > 0 else order.quantity
                    self.logger.info(
                        f"[KisDomestic] Order FILLED: {order.ticker} ODNO={odno} "
                        f"price={actual_price} qty={actual_qty} fee={fill_fee}"
                    )
                    return TradeExecution(
                        ticker=order.ticker,
                        action=order.action,
                        quantity=actual_qty,
                        price=actual_price,
                        fee=fill_fee,
                        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        status=ExecutionStatus.FILLED
                    )
                else:
                    self.logger.warning(
                        f"[KisDomestic] Order NOT confirmed within {timeout}s: "
                        f"{order.ticker} ODNO={odno} — 미체결 주문 취소 시도"
                    )
                    cancelled = self._cancel_order(odno, order.ticker, order.quantity)
                    if not cancelled:
                        self.logger.error(
                            f"[KisDomestic] 주문 취소 실패: {order.ticker} ODNO={odno} — 수동 확인 필요"
                        )

            # 타임아웃 또는 ODNO 미획득 시 ORDERED 반환
            return TradeExecution(
                ticker=order.ticker,
                action=order.action,
                quantity=order.quantity,
                price=float(order_price),
                fee=0.0,
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=ExecutionStatus.ORDERED
            )

        except Exception as e:
            self.logger.error(f"[KisDomestic] Order Error: {e}")
            return None

    def _poll_order_fill(self, odno: str, timeout: int = 30) -> bool:
        """미체결 목록에서 해당 ODNO가 사라질 때까지 polling."""
        start = time.time()
        while (time.time() - start) < timeout:
            try:
                pending_ids = self._get_pending_order_ids()
                if odno not in pending_ids:
                    return True
            except Exception as e:
                self.logger.warning(f"[KisDomestic] Fill poll error (ODNO={odno}): {e}")
            time.sleep(2)
        return False

    def _get_pending_order_ids(self) -> set:
        """국내주식 미체결(정정/취소 가능) 주문번호 집합 반환."""
        tr_id = self.PENDING_TR_ID
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "0",
            "INQR_DVSN_2": "0"
        }
        headers = self._get_header(tr_id)
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()
        if data['rt_cd'] == '0':
            return {item.get('odno', '') for item in data.get('output', [])}
        return set()

    def _get_pending_orders_count(self) -> int:
        """국내주식 미체결 건수 조회."""
        try:
            pending_ids = self._get_pending_order_ids()
            count = len(pending_ids)
            if count > 0:
                self.logger.info(f"[KisDomestic] Found {count} pending orders. Waiting...")
            return count
        except Exception as e:
            self.logger.error(f"[KisDomestic] Pending Check Error: {e}")
            return 0

    def _query_fill_details(self, odno: str, ticker: str):
        """국내주식 체결내역 조회 — 실제 체결가·수량·수수료 반환."""
        if not self.FILL_TR_ID:
            return 0.0, 0, 0.0

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "INQR_STRT_DT": today,
            "INQR_END_DT": today,
            "SLL_BUY_DVSN_CD": "00",      # 00: 전체
            "INQR_DVSN": "00",
            "PDNO": ticker,
            "CCLD_DVSN": "01",             # 01: 체결만
            "ORD_GNO_BRNO": "",
            "ODNO": odno,
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        try:
            headers = self._get_header(self.FILL_TR_ID)
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
            if data['rt_cd'] != '0':
                return 0.0, 0, 0.0

            for item in data.get('output1', []):
                if item.get('odno') != odno:
                    continue
                fill_price = float(item.get('avg_prvs', 0) or 0)    # 체결평균가
                fill_qty = int(item.get('tot_ccld_qty', 0) or 0)    # 총체결수량
                fill_fee = float(item.get('tot_ccld_amt', 0) or 0) * 0.00015  # 수수료 추정
                return fill_price, fill_qty, fill_fee
        except Exception as e:
            self.logger.warning(f"[KisDomestic] Fill detail query error (ODNO={odno}): {e}")
        return 0.0, 0, 0.0

    def _cancel_order(self, odno: str, ticker: str, quantity: int) -> bool:
        """국내주식 미체결 주문 취소."""
        if not self.CANCEL_TR_ID:
            self.logger.warning("[KisDomestic] CANCEL_TR_ID 미설정 — 주문 취소 불가")
            return False

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
        data = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": odno,
            "ORD_DVSN": "00",             # 지정가
            "RVSE_CNCL_DVSN_CD": "02",    # 02: 취소
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",        # 전량 취소
        }
        try:
            headers = self._get_header(self.CANCEL_TR_ID, data)
            res = requests.post(url, headers=headers, json=data)
            res.raise_for_status()
            resp_data = res.json()
            if resp_data['rt_cd'] == '0':
                self.logger.info(f"[KisDomestic] Order Cancelled: {ticker} ODNO={odno}")
                return True
            else:
                self.logger.error(
                    f"[KisDomestic] Cancel Failed: {ticker} ODNO={odno} — {resp_data.get('msg1')}"
                )
                return False
        except Exception as e:
            self.logger.error(f"[KisDomestic] Cancel Error: {ticker} ODNO={odno} — {e}")
            return False

    def _fetch_asking_price(self, ticker: str) -> tuple:
        """국내주식 호가 조회: (best_bid, best_ask) 반환. 실패 시 (0.0, 0.0)"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker
        }
        headers = self._get_header(self.ASKING_PRICE_TR_ID)
        try:
            time.sleep(0.1)
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            if data['rt_cd'] != '0':
                self.logger.warning(f"[KisDomestic] 호가 조회 실패 {ticker}: {data.get('msg1')}")
                return (0.0, 0.0)

            output1 = data.get('output1', {})
            # 국내주식 호가: askp1(매도1호가), bidp1(매수1호가)
            bid = float(output1.get('bidp1', 0) or 0)
            ask = float(output1.get('askp1', 0) or 0)
            return (bid, ask)

        except Exception as e:
            self.logger.warning(f"[KisDomestic] 호가 조회 에러 {ticker}: {e}")
            return (0.0, 0.0)


class KisDomesticPaperBroker(KisDomesticBrokerBase):
    """한국투자증권 모의투자 브로커 — 국내주식 (가상거래 서버)"""
    BASE_URL = "https://openapivts.koreainvestment.com:29443"
    PRICE_TR_ID = "FHKST01010100"    # 국내주식 현재가 (실전/모의 동일)
    PORTFOLIO_TR_ID = "VTTC8434R"    # 국내주식 잔고 (모의)
    BUY_TR_ID = "VTTC0012U"         # 국내주식 매수 (모의)
    SELL_TR_ID = "VTTC0011U"        # 국내주식 매도 (모의)
    PENDING_TR_ID = "TTTC0084R"     # 국내주식 미체결 조회
    FILL_TR_ID = "VTTC0081R"        # 국내주식 체결내역 (모의)
    CANCEL_TR_ID = "VTTC0013U"      # 국내주식 주문 취소 (모의)

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisDomesticPaperBroker] Mode: PAPER TRADING (Virtual)")


class KisDomesticLiveBroker(KisDomesticBrokerBase):
    """한국투자증권 실전투자 브로커 — 국내주식 (실거래 서버)"""
    BASE_URL = "https://openapi.koreainvestment.com:9443"
    PRICE_TR_ID = "FHKST01010100"    # 국내주식 현재가 (실전/모의 동일)
    PORTFOLIO_TR_ID = "TTTC8434R"    # 국내주식 잔고 (실전)
    BUY_TR_ID = "TTTC0012U"         # 국내주식 매수 (실전)
    SELL_TR_ID = "TTTC0011U"        # 국내주식 매도 (실전)
    PENDING_TR_ID = "TTTC0084R"     # 국내주식 미체결 조회
    FILL_TR_ID = "TTTC0081R"        # 국내주식 체결내역 (실전)
    CANCEL_TR_ID = "TTTC0013U"      # 국내주식 주문 취소 (실전)

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisDomesticLiveBroker] Mode: LIVE TRADING")