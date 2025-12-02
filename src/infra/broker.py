# src/infra/broker.py
from typing import List, Dict
from src.core.interfaces import IBrokerAdapter
from src.core.models import Portfolio, Order

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

    def execute_orders(self, orders: List[Order]) -> bool:
        print("\n=== [MOCK] Executing Orders ===")
        for order in orders:
            print(f" > {order.action} {order.ticker}: {order.quantity} shares @ ${order.price}")
            
            # 가상 잔고 반영
            amount = order.quantity * order.price
            if order.action == "BUY":
                self.cash -= amount
                self.holdings[order.ticker] = self.holdings.get(order.ticker, 0) + order.quantity
            elif order.action == "SELL":
                self.cash += amount
                current_qty = self.holdings.get(order.ticker, 0)
                self.holdings[order.ticker] = max(0, current_qty - order.quantity)
                
        print(f"=== [MOCK] Remaining Cash: ${self.cash:,.2f} ===\n")
        return True

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

    def get_portfolio(self) -> Portfolio:
        # 잔고 조회 API 호출 로직 (생략)
        # response를 파싱하여 Portfolio 객체 생성
        return Portfolio(0, {}, {})

    def execute_orders(self, orders: List[Order]) -> bool:
        # 주문 API 호출 로직 (생략)
        return True