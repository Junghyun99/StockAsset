# tests/test_backtest_dividends.py
"""배당 재투자 기능 단위 테스트"""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from src.backtest.runner import _calculate_dividend_income
from src.backtest.components import BacktestBroker


# ── 헬퍼 ────────────────────────────────────────────────────────────────────


def _make_dividends_df(tickers, dates, amounts=None):
    """배당 DataFrame 생성 헬퍼.
    amounts: {date_str: {ticker: amount}} 형태. None이면 전부 0.
    """
    df = pd.DataFrame(0.0, index=dates, columns=tickers)
    if amounts:
        for date_str, ticker_amounts in amounts.items():
            ts = pd.Timestamp(date_str)
            if ts in df.index:
                for ticker, amount in ticker_amounts.items():
                    if ticker in df.columns:
                        df.loc[ts, ticker] = amount
    return df


def _make_price_df(tickers, dates):
    """Close price MultiIndex DataFrame 생성"""
    n = len(dates)
    price_data = {t: np.linspace(100, 200, n) for t in tickers}
    columns = pd.MultiIndex.from_product([["Close"], tickers])
    return pd.DataFrame(
        np.column_stack(list(price_data.values())),
        index=dates,
        columns=columns,
    )


# ── _calculate_dividend_income 단위 테스트 ───────────────────────────────


class TestCalculateDividendIncome:

    def _make_broker(self, holdings=None):
        broker = BacktestBroker(initial_cash=10000.0)
        if holdings:
            broker.holdings = holdings
        return broker

    def test_returns_zero_when_dividends_none(self):
        """dividends_df가 None이면 0.0 반환"""
        broker = self._make_broker()
        today = pd.Timestamp("2023-03-15")
        result = _calculate_dividend_income(today, None, broker)
        assert result == 0.0

    def test_returns_zero_when_dividends_empty(self):
        """dividends_df가 빈 DataFrame이면 0.0 반환"""
        broker = self._make_broker()
        today = pd.Timestamp("2023-03-15")
        result = _calculate_dividend_income(today, pd.DataFrame(), broker)
        assert result == 0.0

    def test_returns_zero_when_date_not_in_index(self):
        """배당일이 아닌 날짜는 0.0 반환"""
        dates = pd.date_range("2023-01-01", periods=5)
        divs = _make_dividends_df(["SDY"], dates)
        broker = self._make_broker(holdings={"SDY": 100})
        today = pd.Timestamp("2024-01-01")  # 인덱스에 없는 날짜
        result = _calculate_dividend_income(today, divs, broker)
        assert result == 0.0

    def test_returns_zero_when_no_holdings(self):
        """배당일이지만 보유 주식이 없으면 0.0 반환"""
        dates = pd.date_range("2023-03-15", periods=1)
        divs = _make_dividends_df(["SDY"], dates, {"2023-03-15": {"SDY": 0.5}})
        broker = self._make_broker(holdings={})  # 보유 없음
        today = pd.Timestamp("2023-03-15")
        result = _calculate_dividend_income(today, divs, broker)
        assert result == 0.0

    def test_calculates_shares_times_dividend(self):
        """배당금 = 보유 주수 × 주당 배당금"""
        dates = pd.date_range("2023-03-15", periods=1)
        divs = _make_dividends_df(["SDY"], dates, {"2023-03-15": {"SDY": 0.5}})
        broker = self._make_broker(holdings={"SDY": 100})
        today = pd.Timestamp("2023-03-15")
        result = _calculate_dividend_income(today, divs, broker)
        assert abs(result - 50.0) < 1e-6  # 100주 × $0.5

    def test_sums_multiple_tickers(self):
        """여러 티커의 배당금을 합산"""
        dates = pd.date_range("2023-03-15", periods=1)
        divs = _make_dividends_df(
            ["SDY", "IEF"], dates,
            {"2023-03-15": {"SDY": 0.5, "IEF": 0.3}}
        )
        broker = self._make_broker(holdings={"SDY": 100, "IEF": 50})
        today = pd.Timestamp("2023-03-15")
        result = _calculate_dividend_income(today, divs, broker)
        # 100 × 0.5 + 50 × 0.3 = 50 + 15 = 65
        assert abs(result - 65.0) < 1e-6

    def test_zero_dividend_rows_contribute_nothing(self):
        """배당금이 0인 티커는 합산에 기여하지 않음"""
        dates = pd.date_range("2023-03-15", periods=1)
        # SDY: 0.5, QLD: 0.0 (레버리지 ETF는 배당 없음)
        divs = _make_dividends_df(
            ["SDY", "QLD"], dates,
            {"2023-03-15": {"SDY": 0.5, "QLD": 0.0}}
        )
        broker = self._make_broker(holdings={"SDY": 100, "QLD": 200})
        today = pd.Timestamp("2023-03-15")
        result = _calculate_dividend_income(today, divs, broker)
        assert abs(result - 50.0) < 1e-6  # SDY만

    def test_exception_returns_zero(self):
        """내부 오류 발생 시 0.0 반환 (안전 처리)"""
        bad_df = MagicMock()
        bad_df.empty = False
        bad_df.index.__contains__ = MagicMock(side_effect=RuntimeError("error"))
        broker = self._make_broker()
        today = pd.Timestamp("2023-03-15")
        result = _calculate_dividend_income(today, bad_df, broker)
        assert result == 0.0


# ── BacktestBroker.receive_dividends 단위 테스트 ─────────────────────────


class TestReceiveDividends:

    def test_cash_increases_by_amount(self):
        """receive_dividends 호출 시 cash가 정확히 증가해야 한다"""
        broker = BacktestBroker(initial_cash=10000.0)
        broker.receive_dividends(250.0)
        assert abs(broker.cash - 10250.0) < 1e-6

    def test_zero_amount_no_change(self):
        """amount=0이면 cash 변화 없음"""
        broker = BacktestBroker(initial_cash=10000.0)
        broker.receive_dividends(0.0)
        assert broker.cash == 10000.0

    def test_negative_amount_no_change(self):
        """amount < 0이면 cash 변화 없음 (방어 처리)"""
        broker = BacktestBroker(initial_cash=10000.0)
        broker.receive_dividends(-100.0)
        assert broker.cash == 10000.0

    def test_logger_called_on_positive_amount(self):
        """배당 수령 시 logger.info가 호출되어야 한다"""
        mock_logger = MagicMock()
        broker = BacktestBroker(initial_cash=10000.0, logger=mock_logger)
        broker.receive_dividends(100.0)
        mock_logger.info.assert_called_once()
        assert "Dividend" in mock_logger.info.call_args[0][0]

    def test_logger_not_called_on_zero_amount(self):
        """amount=0이면 logger가 호출되지 않아야 한다"""
        mock_logger = MagicMock()
        broker = BacktestBroker(initial_cash=10000.0, logger=mock_logger)
        broker.receive_dividends(0.0)
        mock_logger.info.assert_not_called()

    def test_multiple_calls_accumulate(self):
        """여러 번 호출하면 누적 합산되어야 한다"""
        broker = BacktestBroker(initial_cash=10000.0)
        broker.receive_dividends(100.0)
        broker.receive_dividends(200.0)
        assert abs(broker.cash - 10300.0) < 1e-6
