# src/infra/broker.py
from typing import List, Dict
from src.core.interfaces import IBrokerAdapter
from src.core.models import Portfolio, Order, TradeExecution
import time
from datetime import datetime

class MockBroker(IBrokerAdapter):
    """
    로컬 테스트용 가상 브로커
    실제 주문을 내지 않고 로그만 출력함
    """
    def __init__(self, initial_cash: float = 10000.0, holdings: Dict[str, float] = None):
        self.cash = initial_cash
        self.holdings = holdings if holdings else {}
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
        sell_orders = [o for o in orders if o.action == "SELL"]
        buy_orders = [o for o in orders if o.action == "BUY"]
        
        # ==========================================
        # Phase 1: 매도 집행 (Sell Execution)
        # ==========================================
        if sell_orders:
            print("[Broker] Sending SELL orders...")
            for order in sell_orders:
                # API로 매도 주문 전송
                res = self._process_order_internal(order)
                executions.append(res)
            
            # [핵심] 매도 체결 확인 루프 (Polling)
            if not self._wait_for_completion(timeout=60):
                print("⚠️ [Warning] Sell orders timed out. Some might be partial/unfilled.")
                # (선택사항) 미체결 주문 취소 로직 추가 가능
                # self._cancel_all_pending_sells()
        
        # ==========================================
        # Phase 2: 잔고 갱신 및 재계산 (Refresh & Recalc)
        # ==========================================
        if sell_orders:
            # 매도가 있었으면 예수금이 변했을 테니, API로 정확한 현재 잔고를 다시 가져옴
            print("[Broker] Refreshing Cash Balance...")
            time.sleep(1) # API 반영 딜레이 고려
            self._refresh_balance_from_api() 
        
        # ==========================================
        # Phase 3: 매수 집행 (Buy Execution)
        # ==========================================
        if buy_orders:
            print("[Broker] Sending BUY orders...")
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
                
                if max_qty < order.quantity:
                    print(f"⚠️ [Safety] Qty Adjusted: {order.ticker} {order.quantity} -> {max_qty} (Budget: ${budget:.2f})")
                    order.quantity = max_qty
                
                if order.quantity > 0:
                    res = self._process_order_internal(order)
                    executions.append(res)
        
        return executions
        
    def _process_order_internal(self, order: Order) -> TradeExecution:
        """단일 주문 처리 및 Mock 잔고 갱신 헬퍼"""
        # 슬리피지 시뮬레이션
        slippage = 1.01 if order.action == "BUY" else 0.99
        exec_price = order.price * slippage
        
        # 수수료 시뮬레이션 (0.1%)
        fee = (exec_price * order.quantity) * 0.001
        
        print(f" > [FILLED] {order.action} {order.ticker}: {order.quantity} @ ${exec_price:.2f} (Fee: ${fee:.2f})")
        
        amount = exec_price * order.quantity
        
        # 잔고 반영
        if order.action == "BUY":
            self.cash -= (amount + fee)
            self.holdings[order.ticker] = self.holdings.get(order.ticker, 0) + order.quantity
        elif order.action == "SELL":
            self.cash += (amount - fee)
            current_qty = self.holdings.get(order.ticker, 0)
            self.holdings[order.ticker] = max(0, current_qty - order.quantity)
            
        return TradeExecution(
            ticker=order.ticker,
            action=order.action,
            quantity=order.quantity,
            price=round(exec_price, 2),
            fee=round(fee, 2),
            date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status="FILLED"
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
                print("[Broker] All sell orders filled!")
                return True
            
            print(f"... Waiting for fills ({pending_orders} pending) ...")
            time.sleep(2) # 2초 간격 polling
            
        return False

    def _get_pending_orders_count(self) -> int:
        # 실제 구현 시: KIS API '주문/체결 > 미체결내역 상세조회' 호출
        # Mock에서는 0 리턴
        return 0 

    def _refresh_balance_from_api(self):
        # 실제 구현 시: KIS API 잔고 조회 후 self.cash 업데이트
        pass


# 실전용 (뼈대 코드)
class KisBroker(IBrokerAdapter):
    """한국투자증권 REST API 구현체"""
    def __init__(self, app_key: str, app_secret: str, acc_no: str, exchange: str = "NAS"):
        self.app_key = app_key
        self.app_secret = app_secret
        self.acc_no = acc_no
        self.exchange = exchange
        self.base_url = "https://openapi.koreainvestment.com:9443" # 실전
        # self.base_url = "https://openapivts.koreainvestment.com:29443" # 모의
        self.access_token = self._auth()

    def _auth(self) -> str:
        """접근 토큰 발급"""
        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        try:
            res = requests.post(url, json=payload)
            data = res.json()
            if 'access_token' not in data:
                raise Exception(f"Auth Failed: {data}")
            return data['access_token']
        except Exception as e:
            self.logger.error(f"[KisBroker] Auth Error: {e}")
            raise e

    def _get_header(self, tr_id: str, data: dict = None) -> dict:
        """API 공통 헤더 생성 (HashKey 포함)"""
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
            headers["hashkey"] = self._get_hashkey(data)
        return headers

    def _get_hashkey(self, data: dict) -> str:
        url = f"{self.base_url}/uapi/hashkey"
        try:
            res = requests.post(url, headers={
                "content-type": "application/json",
                "appkey": self.app_key,
                "appsecret": self.app_secret
            }, json=data)
            return res.json()["HASH"]
        except Exception:
            return ""
    
    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        """
        해외주식 현재가 조회 (반복 호출)
        """
        prices = {}
        # 실전 TR_ID: HHDFS00000300, 모의: FHKST01010100
        tr_id = "HHDFS00000300" if self.is_real else "FHKST01010100"
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
        해외주식 잔고 및 예수금 조회
        """
        # 해외주식 잔고지원 TR_ID (실전: TTTS3012R, 모의: VTTS3012R)
        tr_id = "TTTS3012R" if self.is_real else "VTTS3012R"
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance"
        # 환율구분: 000(전체), 국가: US(미국), 시장: NYSE
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": "NAS", # 대표 시장
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        headers = self._get_header(tr_id)
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            
            if data['rt_cd'] != '0':
                self.logger.error(f"[KisBroker] Get Portfolio Failed: {data.get('msg1')}")
                return Portfolio(0, {}, {})
            # 1. 예수금 (주문가능 외화금액) - output2의 'frcr_dncl_amt_2' (외화예수금) 또는 'ovrs_ord_psbl_amt'(주문가능)
            # 안전하게 주문가능금액 사용
            cash = float(data['output2']['ovrs_ord_psbl_amt'])
            
            # 2. 보유 종목 (output1)
            holdings = {}
            current_prices = {}
            for item in data['output1']:
                # ccls_qty: 체결 수량 (잔고)
                qty = int(item['ovrs_cblc_qty'])
                if qty > 0:
                    ticker = item['ovrs_pdno'] # 티커
                    holdings[ticker] = qty
                    # 잔고 조회 시 현재가도 같이 옴 (now_pric2)
                    current_prices[ticker] = float(item['now_pric2'])
            return Portfolio(
                total_cash=cash,
                holdings=holdings,
                current_prices=current_prices
            )

        except Exception as e:
            self.logger.error(f"[KisBroker] Error getting portfolio: {e}")
            return Portfolio(0, {}, {})

    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]:
        executions = []
        sell_orders = [o for o in orders if o.action == "SELL"]
        buy_orders = [o for o in orders if o.action == "BUY"]
        
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
            # 매도가 있었다면 잔고가 변했을 것이므로 갱신 (API 재호출)
            if sell_orders:
                time.sleep(2) # 정산 대기
                pf = self.get_portfolio()
                current_cash = pf.total_cash
            else:
                # 매도가 없었다면 로컬에 저장된 잔고로는 불안하므로 한번 더 조회 권장
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
                
                if max_qty < order.quantity:
                    self.logger.warning(f"⚠️ Qty Adjusted: {order.ticker} {order.quantity} -> {max_qty}")
                    order.quantity = max_qty
                
                if order.quantity > 0:
                    res = self._send_order(order)
                    if res:
                        executions.append(res)
                        # 메모리상 잔고 차감 (다음 주문을 위해)
                        current_cash -= (res.price * res.quantity)
                    time.sleep(0.2)

        return executions

    def _send_order(self, order: Order) -> Optional[TradeExecution]:
        """실제 주문 API 호출"""
        # 실전: TTTS1002U(매수), TTTS1006U(매도)
        # 모의: VTTT1002U(매수), VTTT1006U(매도)
        
        tr_id = ""
        if self.is_real:
            tr_id = "TTTS1002U" if order.action == "BUY" else "TTTS1006U"
        else:
            tr_id = "VTTT1002U" if order.action == "BUY" else "VTTT1006U"

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        exch = self._get_exchange_code(order.ticker)
        
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
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00" # 00: 지정가 (미국은 보통 지정가 사용)
        }
        
        headers = self._get_header(tr_id, data)
        
        try:
            res = requests.post(url, headers=headers, json=data)
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
                status="ORDERED"
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
        """미체결 내역 조회"""
        # 실전: TTTS3018R, 모의: VTTT3018R
        tr_id = "TTTS3018R" if self.is_real else "VTTT3018R"
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-nccs"
        
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": "NAS",
            "SORT_SQN": "DS",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        headers = self._get_header(tr_id)
        
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data['rt_cd'] == '0':
                # output 리스트의 길이가 미체결 건수
                return len(data['output'])
        except:
            pass
        return 0

    def _get_exchange_code(self, ticker: str) -> str:
        """
        티커별 거래소 코드 매핑
        (한투 API는 NAS, NYS, AMS를 구분해서 넣어야 함)
        """
        # 주요 ETF 매핑
        mapping = {
            'SPY': 'AMS', # AMEX (Arca)
            'QLD': 'AMS', # ProShares는 보통 Arca
            'SSO': 'AMS',
            'IEF': 'NAS', # NASDAQ
            'GLD': 'NYS', # NYSE
            'PDBC': 'NAS',
            'SHV': 'NAS'
        }
        return mapping.get(ticker, 'NAS') # 기본값