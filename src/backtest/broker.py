# src/backtest/broker.py
from src.infra.broker import MockBroker
from typing import Dict, List

class BacktestBroker(MockBroker):
    """
    백테스팅용 가상 브로커.
    MockBroker를 상속받되, '현재가'를 외부(백테스터)에서 강제로 설정하는 기능 추가.
    """
    def __init__(self, initial_cash: float):
        super().__init__(initial_cash=initial_cash)
        self._current_prices_snapshot = {} # 그 날의 종가 저장소

    # [중요] 백테스터가 매일매일 그 날의 종가를 주입해줌
    def set_prices(self, prices: Dict[str, float]):
        self._current_prices_snapshot = prices

    # Broker 인터페이스 구현 (오버라이딩)
    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        return {t: self._current_prices_snapshot.get(t, 0.0) for t in tickers}

    def execute_orders(self, orders):
        # 매수/매도 시 self._current_prices_snapshot 가격 기준으로 체결
        # MockBroker의 로직을 그대로 쓰되 price만 snapshot에서 참조하도록 수정하거나
        # execute_orders 로직을 오버라이딩하여 _current_prices_snapshot을 사용하게 함
        return super().execute_orders(orders)