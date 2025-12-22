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
        self.access_token = None

    def _auth(self):
        # 토큰 발급 로직 (생략 - 필요시 구현)
        pass
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

    def get_portfolio(self) -> Portfolio:
        # 잔고 조회 API 호출 로직 (생략)
        # response를 파싱하여 Portfolio 객체 생성
        return Portfolio(0, {}, {})

    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]:
        results = []
        
        # 1. 정렬
        sell_orders = [o for o in orders if o.action == "SELL"]
        buy_orders = [o for o in orders if o.action == "BUY"]
        
        # 2. 매도 루프
        for order in sell_orders:
            res = self._send_api_order(order) # API 호출
            results.append(res)
            time.sleep(0.2) # 주문 간 텀 (API 제한 방지)
            
        # 3. [핵심] 매도 후 잔고 반영 대기
        if sell_orders and buy_orders:
            time.sleep(2) # 2초 정도 대기 (증권사 서버가 매도대금을 예수금으로 잡을 시간)
            
        # 4. 매수 루프
        for order in buy_orders:
            # (옵션) 여기서 현재 예수금을 API로 다시 조회해서 확인 후 주문 낼 수도 있음
            res = self._send_api_order(order)
            results.append(res)
            time.sleep(0.2)
            
        return results