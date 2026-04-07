# src/infra/broker/mock.py
from typing import List, Dict, Optional
import time
from datetime import datetime

from src.core.interfaces import IBrokerAdapter, ILogger
from src.core.models import Portfolio, Order, TradeExecution, OrderAction, ExecutionStatus


class MockBroker(IBrokerAdapter):
    """
    로컬 테스트용 가상 브로커
    실제 주문을 내지 않고 로그만 출력함
    """
    def __init__(self, initial_cash: float = 10000.0, holdings: Dict[str, int] = None, logger: Optional[ILogger] = None):
        self.cash = initial_cash
        self.holdings = holdings if holdings else {}
        self.logger = logger

    def get_portfolio(self) -> Portfolio:
        return Portfolio(
            total_cash=self.cash,
            holdings=self.holdings,
            current_prices={}
        )

    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        return {t: 100.0 for t in tickers}

    def execute_orders(self, orders: List[Order]) -> List[TradeExecution]:
        executions = []

        sell_orders = [o for o in orders if o.action == OrderAction.SELL]
        buy_orders = [o for o in orders if o.action == OrderAction.BUY]

        # Phase 1: 매도
        if sell_orders:
            if self.logger: self.logger.info("[Broker] Sending SELL orders...")
            for order in sell_orders:
                res = self._process_order_internal(order)
                executions.append(res)

            if not self._wait_for_completion(timeout=60):
                if self.logger: self.logger.warning("[Broker] Sell orders timed out. Some might be partial/unfilled.")

        # Phase 2: 잔고 갱신
        if sell_orders:
            if self.logger: self.logger.info("[Broker] Refreshing Cash Balance...")
            self._refresh_balance_from_api()

        # Phase 3: 매수
        if buy_orders:
            if self.logger: self.logger.info("[Broker] Sending BUY orders...")
            for order in buy_orders:
                SAFE_MARGIN = 0.98
                current_cash = self.cash
                budget = current_cash * SAFE_MARGIN
                estimated_price = order.price * 1.01

                if estimated_price <= 0: continue

                max_qty = int(budget / estimated_price)
                actual_qty = min(order.quantity, max_qty)

                if max_qty < order.quantity:
                    if self.logger: self.logger.warning(f"[Broker] Qty Adjusted: {order.ticker} {order.quantity} -> {actual_qty} (Budget: ${budget:.2f})")

                if actual_qty > 0:
                    adjusted_order = Order(ticker=order.ticker, action=order.action, quantity=actual_qty, price=order.price)
                    res = self._process_order_internal(adjusted_order)
                    executions.append(res)

        return executions

    def _process_order_internal(self, order: Order) -> TradeExecution:
        """단일 주문 처리 및 Mock 잔고 갱신 헬퍼"""
        slippage = 1.001 if order.action == OrderAction.BUY else 0.999
        exec_price = order.price * slippage

        if order.action == OrderAction.BUY:
            actual_qty = order.quantity
            amount = exec_price * actual_qty
            fee = amount * 0.0025
            self.cash -= (amount + fee)
            self.holdings[order.ticker] = self.holdings.get(order.ticker, 0) + actual_qty
        elif order.action == OrderAction.SELL:
            current_qty = self.holdings.get(order.ticker, 0)
            actual_qty = min(order.quantity, current_qty)
            if actual_qty < order.quantity and self.logger:
                self.logger.warning(
                    f"[QTY ADJUSTED] {order.ticker} SELL: 요청 {order.quantity}주 → 실제 체결 {actual_qty}주 (보유량 부족)"
                )
            amount = exec_price * actual_qty
            fee = amount * 0.0025
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
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            pending_orders = self._get_pending_orders_count()

            if pending_orders == 0:
                if self.logger: self.logger.info("[Broker] All sell orders filled!")
                return True

            if self.logger: self.logger.info(f"[Broker] Waiting for fills ({pending_orders} pending) ...")
            time.sleep(2)

        return False

    def _get_pending_orders_count(self) -> int:
        return 0

    def _refresh_balance_from_api(self):
        time.sleep(1)
