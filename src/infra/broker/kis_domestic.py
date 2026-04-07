# src/infra/broker/kis_domestic.py
"""KIS 국내주식 브로커."""
from typing import List, Dict, Optional
import time
import src.infra.broker as _pkg  # test patch 타깃: src.infra.broker.requests
from datetime import datetime

from src.core.models import Portfolio, Order, TradeExecution, OrderAction, ExecutionStatus

from .kis_base import KisBrokerCommon
from .kis_order_helpers import poll_order_fill


def _to_kis_code(ticker: str) -> str:
    """yfinance 티커 → KIS 종목코드. '069500.KS' → '069500'"""
    return ticker.removesuffix(".KS")


def _to_yf_ticker(code: str) -> str:
    """KIS 종목코드 → yfinance 티커. '069500' → '069500.KS'"""
    return code if code.endswith(".KS") else code + ".KS"


class KisDomesticBrokerBase(KisBrokerCommon):
    """국내주식 전용 브로커 베이스 클래스."""
    ASKING_PRICE_TR_ID: str = "FHKST01010200"  # 국내주식 호가 조회 (실전/모의 동일)

    # 하위 호환: 기존 테스트가 인스턴스 메서드로 호출할 수 있어 스태틱 래퍼 유지
    @staticmethod
    def _to_kis_code(ticker: str) -> str:
        return _to_kis_code(ticker)

    @staticmethod
    def _to_yf_ticker(code: str) -> str:
        return _to_yf_ticker(code)

    def fetch_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        """국내주식 현재가 조회"""
        prices = {}
        tr_id = self.PRICE_TR_ID
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        for ticker in tickers:
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": _to_kis_code(ticker)
            }
            headers = self._get_header(tr_id)
            try:
                time.sleep(0.1)
                res = _pkg.requests.get(url, headers=headers, params=params)
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
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        headers = self._get_header(tr_id)

        total_cash = 0.0
        all_holdings: Dict[str, int] = {}
        all_prices: Dict[str, float] = {}

        try:
            time.sleep(0.2)
            res = _pkg.requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            if data['rt_cd'] != '0':
                self.logger.warning(f"[KisDomestic] Get Portfolio Failed: {data.get('msg1')}")
                return Portfolio(total_cash=0.0, holdings={}, current_prices={})

            output2_list = data.get('output2', [])
            summary = output2_list[0] if output2_list else {}
            dnca = float(summary.get('dnca_tot_amt', 0) or 0)
            cma = float(summary.get('cma_evlu_amt', 0) or 0)
            total_cash = dnca + cma

            for item in data.get('output1', []):
                qty = int(item.get('hldg_qty', 0) or 0)
                if qty > 0:
                    ticker = _to_yf_ticker(item['pdno'])
                    all_holdings[ticker] = qty
                    all_prices[ticker] = float(item.get('prpr', 0) or 0)

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

        bid, ask = self._fetch_asking_price(order.ticker)

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

        if order.action == OrderAction.BUY:
            order_price = int(ask) if ask > 0 else int(order.price)
        else:
            order_price = int(bid) if bid > 0 else int(order.price)

        data = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": _to_kis_code(order.ticker),
            "ORD_DVSN": "00",
            "ORD_QTY": str(order.quantity),
            "ORD_UNPR": str(order_price),
        }

        try:
            headers = self._get_header(tr_id, data)
            res = _pkg.requests.post(url, headers=headers, json=data)
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
                        status=ExecutionStatus.FILLED,
                        reason=f"ODNO={odno}"
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

            return TradeExecution(
                ticker=order.ticker,
                action=order.action,
                quantity=order.quantity,
                price=float(order_price),
                fee=0.0,
                date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=ExecutionStatus.ORDERED,
                reason=f"ODNO={odno}" if odno else ""
            )

        except Exception as e:
            self.logger.error(f"[KisDomestic] Order Error: {e}")
            return None

    def _poll_order_fill(self, odno: str, timeout: int = 30) -> bool:
        """공용 poll helper 호출 래퍼."""
        return poll_order_fill(
            self._get_pending_order_ids,
            odno,
            timeout,
            self.logger,
            log_prefix="[KisDomestic]",
        )

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
        res = _pkg.requests.get(url, headers=headers, params=params)
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
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": _to_kis_code(ticker),
            "CCLD_DVSN": "01",
            "ORD_GNO_BRNO": "",
            "ODNO": odno,
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        try:
            headers = self._get_header(self.FILL_TR_ID)
            res = _pkg.requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
            if data['rt_cd'] != '0':
                return 0.0, 0, 0.0

            for item in data.get('output1', []):
                if item.get('odno') != odno:
                    continue
                fill_price = float(item.get('avg_prvs', 0) or 0)
                fill_qty = int(item.get('tot_ccld_qty', 0) or 0)
                fill_fee = float(item.get('tot_ccld_amt', 0) or 0) * 0.00015
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
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }
        try:
            headers = self._get_header(self.CANCEL_TR_ID, data)
            res = _pkg.requests.post(url, headers=headers, json=data)
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
            "FID_INPUT_ISCD": _to_kis_code(ticker)
        }
        headers = self._get_header(self.ASKING_PRICE_TR_ID)
        try:
            time.sleep(0.1)
            res = _pkg.requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            if data['rt_cd'] != '0':
                self.logger.warning(f"[KisDomestic] 호가 조회 실패 {ticker}: {data.get('msg1')}")
                return (0.0, 0.0)

            output1 = data.get('output1', {})
            bid = float(output1.get('bidp1', 0) or 0)
            ask = float(output1.get('askp1', 0) or 0)
            return (bid, ask)

        except Exception as e:
            self.logger.warning(f"[KisDomestic] 호가 조회 에러 {ticker}: {e}")
            return (0.0, 0.0)


class KisDomesticPaperBroker(KisDomesticBrokerBase):
    """한국투자증권 모의투자 브로커 — 국내주식 (가상거래 서버)"""
    BASE_URL = "https://openapivts.koreainvestment.com:29443"
    PRICE_TR_ID = "FHKST01010100"
    PORTFOLIO_TR_ID = "VTTC8434R"
    BUY_TR_ID = "VTTC0012U"
    SELL_TR_ID = "VTTC0011U"
    PENDING_TR_ID = "TTTC0084R"
    FILL_TR_ID = "VTTC0081R"
    CANCEL_TR_ID = "VTTC0013U"

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisDomesticPaperBroker] Mode: PAPER TRADING (Virtual)")


class KisDomesticLiveBroker(KisDomesticBrokerBase):
    """한국투자증권 실전투자 브로커 — 국내주식 (실거래 서버)"""
    BASE_URL = "https://openapi.koreainvestment.com:9443"
    PRICE_TR_ID = "FHKST01010100"
    PORTFOLIO_TR_ID = "TTTC8434R"
    BUY_TR_ID = "TTTC0012U"
    SELL_TR_ID = "TTTC0011U"
    PENDING_TR_ID = "TTTC0084R"
    FILL_TR_ID = "TTTC0081R"
    CANCEL_TR_ID = "TTTC0013U"

    def __init__(self, app_key: str, app_secret: str, acc_no: str, logger):
        super().__init__(app_key, app_secret, acc_no, logger)
        self.logger.info("[KisDomesticLiveBroker] Mode: LIVE TRADING")
