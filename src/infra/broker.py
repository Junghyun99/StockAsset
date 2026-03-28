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


class KisBrokerBase(IBrokerAdapter):
    """한국투자증권 REST API 공통 베이스 클래스.
    서브클래스에서 BASE_URL 및 TR_* 상수를 반드시 정의해야 한다.
    """
    BASE_URL: str = ""
    PRICE_TR_ID: str = ""
    PORTFOLIO_TR_ID: str = ""
    BUY_TR_ID: str = ""
    SELL_TR_ID: str = ""
    PENDING_TR_ID: str = ""

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

    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]:
        executions = []
        sell_orders = [o for o in orders if o.action == OrderAction.SELL]
        buy_orders = [o for o in orders if o.action == OrderAction.BUY]

        # === 1. 매도 실행 ===
        if sell_orders:
            self.logger.info(f"[KisBroker] Processing {len(sell_orders)} SELL orders...")
            for order in sell_orders:
                res = self._send_order(order)
                if res: executions.append(res)
                time.sleep(0.2) # API 제한 고려
            
            # 매도 후 체결 대기 (Polling)
            if not self._wait_for_completion(timeout=60):
                self.logger.warning("[KisBroker] Sell orders timed out or pending.")

        # === 2. 잔고 갱신 및 매수 재계산 ===
        if buy_orders:
            if sell_orders:
                time.sleep(2) # 정산 대기
            pf = self.get_portfolio()
            current_cash = pf.total_cash

            self.logger.info(f"[KisBroker] Available Cash for BUY: ${current_cash:,.2f}")

            # === 3. 매수 실행 ===
            for order in buy_orders:
                # 안전 마진 (98%)
                SAFE_MARGIN = 0.98
                budget = current_cash * SAFE_MARGIN
                
                # 시장가(지정가) 매수 대비 2% 버퍼
                estimated_price = order.price * 1.02
                if estimated_price <= 0: continue
                
                # 수량 재계산
                max_qty = int(budget / estimated_price)
                # 원본 Order 객체를 변경하지 않고 조정된 수량으로 로컬 변수 사용
                actual_qty = min(order.quantity, max_qty)

                if max_qty < order.quantity:
                    self.logger.warning(f"⚠️ Qty Adjusted: {order.ticker} {order.quantity} -> {actual_qty}")

                if actual_qty > 0:
                    # 조정된 수량으로 새 Order 생성 (원본 불변 유지)
                    adjusted_order = Order(ticker=order.ticker, action=order.action, quantity=actual_qty, price=order.price)
                    res = self._send_order(adjusted_order)
                    if res:
                        executions.append(res)
                        # 메모리상 잔고 차감 (다음 주문을 위해)
                        current_cash -= (res.price * res.quantity)
                    time.sleep(0.2)

        return executions

    def _send_order(self, order: Order) -> Optional[TradeExecution]:
        """실제 주문 API 호출"""
        tr_id = self.BUY_TR_ID if order.action == OrderAction.BUY else self.SELL_TR_ID

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        # 주문 API는 전체 거래소 코드 사용 (NASD, NYSE, AMEX)
        exch = self._get_exchange_code(order.ticker, api_type="order")

        # 가격: 시장가인 경우 0 (또는 Limit 가격)
        # 미국주식은 보통 시장가(MKT)를 지원하지 않거나 조건이 까다로움.
        # 전략상 계산된 price(현재가)로 지정가 주문을 내되,
        # Buy는 높게, Sell은 낮게 내서 즉시 체결을 유도하는 것이 일반적임.

        # 주문단가 (소수점 2자리)
        order_price = round(order.price, 2)

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

    def _wait_for_completion(self, timeout: int = 60) -> bool:
        """미체결 내역이 없을 때까지 대기"""
        start = time.time()
        while (time.time() - start) < timeout:
            count = self._get_pending_orders_count()
            if count == 0:
                return True
            time.sleep(2)
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


class KisPaperBroker(KisBrokerBase):
    """한국투자증권 모의투자 브로커 (가상거래 서버)"""
    BASE_URL = "https://openapivts.koreainvestment.com:29443"
    PRICE_TR_ID = "HHDFS00000300"  # 해외주식 현재가 조회 (실전/모의 동일 TR_ID)
    PORTFOLIO_TR_ID = "VTTS3012R"
    BUY_TR_ID = "VTTT1002U"
    SELL_TR_ID = "VTTT1006U"
    PENDING_TR_ID = "VTTS3018R"

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisPaperBroker] Mode: PAPER TRADING (Virtual)")


class KisLiveBroker(KisBrokerBase):
    """한국투자증권 실전투자 브로커 (실거래 서버)"""
    BASE_URL = "https://openapi.koreainvestment.com:9443"
    PRICE_TR_ID = "HHDFS00000300"
    PORTFOLIO_TR_ID = "TTTS3012R"
    BUY_TR_ID = "TTTT1002U"   # 미국 매수 (TTTS는 홍콩용)
    SELL_TR_ID = "TTTT1006U"  # 미국 매도
    PENDING_TR_ID = "TTTS3018R"

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisLiveBroker] Mode: LIVE TRADING")