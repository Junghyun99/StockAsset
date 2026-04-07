# src/infra/broker/kis_overseas.py
"""KIS 해외주식(미국) 브로커."""
from typing import List, Dict, Optional
import time
import src.infra.broker as _pkg  # test patch 타깃: src.infra.broker.requests
from datetime import datetime

from src.core.models import Portfolio, Order, TradeExecution, OrderAction, ExecutionStatus
from src.config import TICKER_EXCHANGE_MAP, EXCHANGE_CODE_SHORT_TO_FULL

from .kis_base import KisBrokerCommon
from .kis_order_helpers import poll_order_fill


class KisOverseasBrokerBase(KisBrokerCommon):
    """해외주식(미국) 전용 브로커 베이스 클래스."""
    ASKING_PRICE_TR_ID: str = "HHDFS76200100"  # 해외주식 호가 조회 (실전/모의 동일)

    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        """해외주식 현재가 조회 (반복 호출)"""
        prices = {}
        tr_id = self.PRICE_TR_ID
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/price"
        for ticker in tickers:
            exch = self._get_exchange_code(ticker)
            params = {"AUTH": "", "EXCD": exch, "SYMB": ticker}
            headers = self._get_header(tr_id)
            try:
                time.sleep(0.1)
                res = _pkg.requests.get(url, headers=headers, params=params)
                res.raise_for_status()
                data = res.json()

                if data['rt_cd'] == '0':
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
        해외주식 잔고 및 예수금 조회 (NASD/NYSE/AMEX 전 거래소 통합).

        total_cash는 output2['ovrs_ord_psbl_amt'] (해외주문가능금액) 사용.
        pending 주문 예약금이 이미 차감된 실제 가용 금액 (#225).
        """
        tr_id = self.PORTFOLIO_TR_ID
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance"

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
                time.sleep(0.2)
                res = _pkg.requests.get(url, headers=headers, params=params)
                res.raise_for_status()
                data = res.json()

                if data['rt_cd'] != '0':
                    self.logger.warning(f"[KisBroker] Get Portfolio Failed ({exch}): {data.get('msg1')}")
                    continue

                if not cash_fetched:
                    total_cash = float(data['output2']['ovrs_ord_psbl_amt'])
                    cash_fetched = True

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
        """실제 주문 API 호출 (체결 대기 없음)"""
        tr_id = self.BUY_TR_ID if order.action == OrderAction.BUY else self.SELL_TR_ID

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        exch = self._get_exchange_code(order.ticker, api_type="order")

        bid, ask = self._fetch_asking_price(order.ticker)

        if not self._check_spread(bid, ask):
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid * 100
            self.logger.warning(
                f"[KisBroker] 스프레드 비정상 — {order.ticker} "
                f"bid={bid} ask={ask} spread={spread_pct:.2f}% > {self.SPREAD_THRESHOLD_PCT}% — 주문 보류"
            )
            return None

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
            res = _pkg.requests.post(url, headers=headers, json=data)
            res.raise_for_status()
            resp_data = res.json()

            if resp_data['rt_cd'] != '0':
                self.logger.error(f"[KisBroker] Order Failed: {resp_data.get('msg1')}")
                return None

            self.logger.info(f"[KisBroker] Order Sent: {order.action} {order.ticker} {order.quantity} @ {order_price}")

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

    def _send_order_and_wait(self, order: Order, timeout: int = 30) -> Optional[TradeExecution]:
        """주문 전송 후 체결 대기. 체결 시 FILLED, 타임아웃 시 ORDERED(미확인 체결) 반환."""
        tr_id = self.BUY_TR_ID if order.action == OrderAction.BUY else self.SELL_TR_ID
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        exch = self._get_exchange_code(order.ticker, api_type="order")

        bid, ask = self._fetch_asking_price(order.ticker)

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
            res = _pkg.requests.post(url, headers=headers, json=data)
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
                        status=ExecutionStatus.FILLED,
                        reason=f"ODNO={odno}"
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

            return TradeExecution(
                ticker=order.ticker,
                action=order.action,
                quantity=order.quantity,
                price=order_price,
                fee=0.0,
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=ExecutionStatus.ORDERED,
                reason=f"ODNO={odno}" if odno else ""
            )

        except Exception as e:
            self.logger.error(f"[KisBroker] Order Error: {e}")
            return None

    def _poll_order_fill(self, odno: str, exch: str, timeout: int = 30) -> bool:
        """공용 poll helper 호출 래퍼."""
        return poll_order_fill(
            lambda: self._get_pending_order_ids(exch),
            odno,
            timeout,
            self.logger,
            log_prefix="[KisBroker]",
        )

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
        res = _pkg.requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()
        if data['rt_cd'] == '0':
            return {item.get('odno', '') for item in data.get('output', [])}
        return set()

    def _query_fill_details(self, odno: str, ticker: str, exch: str):
        """체결내역 조회 — 실제 체결가·수량·수수료 반환. 실패 시 (0.0, 0, 0.0)."""
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
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_NCCS_DVSN": "01",
            "OVRS_EXCG_CD": exch,
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }
        try:
            headers = self._get_header(self.FILL_TR_ID)
            res = _pkg.requests.get(url, headers=headers, params=params)
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
        """미체결 주문 취소. 성공 시 True."""
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
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_SVR_DVSN_CD": "0",
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": ""
        }
        try:
            headers = self._get_header(self.CANCEL_TR_ID, data)
            res = _pkg.requests.post(url, headers=headers, json=data)
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
        NASD -> NYSE -> AMEX 순으로 조회, 발견 즉시 반환.
        """
        tr_id = self.PENDING_TR_ID
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-nccs"

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
                time.sleep(0.2)
                res = _pkg.requests.get(url, headers=headers, params=params)
                res.raise_for_status()
                data = res.json()

                if data['rt_cd'] == '0':
                    count = len(data.get('output', []))
                    if count > 0:
                        self.logger.info(f"[KisBroker] Found {count} pending orders in {exch}. Waiting...")
                        return count
                else:
                    self.logger.warning(f"[KisBroker] Pending Check Failed ({exch}): {data.get('msg1')}")

            except Exception as e:
                self.logger.error(f"[KisBroker] Pending Check Error ({exch}): {e}")

        return 0

    def _fetch_asking_price(self, ticker: str) -> tuple:
        """호가 조회: (best_bid, best_ask) 반환. 실패 시 (0.0, 0.0)"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/inquire-asking-price"
        exch = self._get_exchange_code(ticker)
        params = {"AUTH": "", "EXCD": exch, "SYMB": ticker}
        headers = self._get_header(self.ASKING_PRICE_TR_ID)
        try:
            time.sleep(0.1)
            res = _pkg.requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            if data['rt_cd'] != '0':
                self.logger.warning(f"[KisBroker] 호가 조회 실패 {ticker}: {data.get('msg1')}")
                return (0.0, 0.0)

            output2 = data.get('output2', {})
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


class KisOverseasPaperBroker(KisOverseasBrokerBase):
    """한국투자증권 모의투자 브로커 — 해외주식 (가상거래 서버)"""
    BASE_URL = "https://openapivts.koreainvestment.com:29443"
    PRICE_TR_ID = "HHDFS00000300"
    PORTFOLIO_TR_ID = "VTTS3012R"
    BUY_TR_ID = "VTTT1002U"
    SELL_TR_ID = "VTTT1006U"
    PENDING_TR_ID = "VTTS3018R"
    FILL_TR_ID = "VTTS3035R"
    CANCEL_TR_ID = "VTTT1004U"

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisOverseasPaperBroker] Mode: PAPER TRADING (Virtual)")


class KisOverseasLiveBroker(KisOverseasBrokerBase):
    """한국투자증권 실전투자 브로커 — 해외주식 (실거래 서버)"""
    BASE_URL = "https://openapi.koreainvestment.com:9443"
    PRICE_TR_ID = "HHDFS00000300"
    PORTFOLIO_TR_ID = "TTTS3012R"
    BUY_TR_ID = "TTTT1002U"
    SELL_TR_ID = "TTTT1006U"
    PENDING_TR_ID = "TTTS3018R"
    FILL_TR_ID = "TTTS3035R"
    CANCEL_TR_ID = "TTTT1004U"

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisOverseasLiveBroker] Mode: LIVE TRADING")
