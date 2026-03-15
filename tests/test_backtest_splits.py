# tests/test_backtest_splits.py
"""주식분할 처리 기능 단위 테스트"""
import pytest
import pandas as pd
from unittest.mock import MagicMock
from src.backtest.runner import _apply_stock_splits
from src.backtest.components import BacktestBroker


# ── 헬퍼 ────────────────────────────────────────────────────────────────────


def _make_splits_df(tickers, dates, ratios=None):
    """주식분할 DataFrame 생성 헬퍼.
    ratios: {date_str: {ticker: ratio}} 형태. None이면 전부 0.
    """
    df = pd.DataFrame(0.0, index=dates, columns=tickers)
    if ratios:
        for date_str, ticker_ratios in ratios.items():
            ts = pd.Timestamp(date_str)
            if ts in df.index:
                for ticker, ratio in ticker_ratios.items():
                    if ticker in df.columns:
                        df.loc[ts, ticker] = ratio
    return df


# ── BacktestBroker.apply_stock_split 단위 테스트 ─────────────────────────


class TestApplyStockSplit:

    def _make_broker(self, holdings=None):
        broker = BacktestBroker(initial_cash=10000.0)
        if holdings:
            broker.holdings = holdings
        return broker

    def test_forward_split_doubles_shares(self):
        """2:1 정분할 시 보유 주수가 2배가 되어야 한다"""
        broker = self._make_broker(holdings={"AAPL": 100})
        broker.apply_stock_split("AAPL", 2.0)
        assert broker.holdings["AAPL"] == 200

    def test_reverse_split_halves_shares(self):
        """1:2 역분할(ratio=0.5) 시 보유 주수가 절반이 되어야 한다"""
        broker = self._make_broker(holdings={"AAPL": 100})
        broker.apply_stock_split("AAPL", 0.5)
        assert broker.holdings["AAPL"] == 50

    def test_three_for_one_split(self):
        """3:1 분할 시 보유 주수가 3배가 되어야 한다"""
        broker = self._make_broker(holdings={"TSLA": 50})
        broker.apply_stock_split("TSLA", 3.0)
        assert broker.holdings["TSLA"] == 150

    def test_cash_unchanged_on_split(self):
        """분할 후 현금에는 변화가 없어야 한다"""
        broker = self._make_broker(holdings={"SSO": 100})
        broker.apply_stock_split("SSO", 2.0)
        assert broker.cash == 10000.0

    def test_no_holdings_no_change(self):
        """보유 주식이 없으면 holdings에 변화가 없어야 한다"""
        broker = self._make_broker(holdings={})
        broker.apply_stock_split("AAPL", 2.0)
        assert broker.holdings.get("AAPL", 0) == 0

    def test_ratio_one_no_change(self):
        """ratio=1.0이면 보유 주수 변화 없음"""
        broker = self._make_broker(holdings={"AAPL": 100})
        broker.apply_stock_split("AAPL", 1.0)
        assert broker.holdings["AAPL"] == 100

    def test_ratio_zero_no_change(self):
        """ratio=0이면 아무것도 하지 않음 (방어 처리)"""
        broker = self._make_broker(holdings={"AAPL": 100})
        broker.apply_stock_split("AAPL", 0.0)
        assert broker.holdings["AAPL"] == 100

    def test_negative_ratio_no_change(self):
        """ratio < 0이면 아무것도 하지 않음 (방어 처리)"""
        broker = self._make_broker(holdings={"AAPL": 100})
        broker.apply_stock_split("AAPL", -2.0)
        assert broker.holdings["AAPL"] == 100

    def test_logger_called_on_split(self):
        """분할 적용 시 logger.info가 호출되어야 한다"""
        mock_logger = MagicMock()
        broker = BacktestBroker(initial_cash=10000.0, logger=mock_logger)
        broker.holdings = {"AAPL": 100}
        broker.apply_stock_split("AAPL", 2.0)
        mock_logger.info.assert_called_once()
        assert "Split" in mock_logger.info.call_args[0][0]

    def test_logger_not_called_when_no_holdings(self):
        """보유 주식이 없으면 logger가 호출되지 않아야 한다"""
        mock_logger = MagicMock()
        broker = BacktestBroker(initial_cash=10000.0, logger=mock_logger)
        broker.apply_stock_split("AAPL", 2.0)
        mock_logger.info.assert_not_called()

    def test_other_tickers_unaffected(self):
        """분할 대상이 아닌 티커의 보유 주수는 변화 없음"""
        broker = self._make_broker(holdings={"AAPL": 100, "QLD": 50})
        broker.apply_stock_split("AAPL", 4.0)
        assert broker.holdings["AAPL"] == 400
        assert broker.holdings["QLD"] == 50


# ── _apply_stock_splits 단위 테스트 ─────────────────────────────────────


class TestApplyStockSplitsRunner:

    def _make_broker(self, holdings=None):
        broker = BacktestBroker(initial_cash=10000.0)
        if holdings:
            broker.holdings = holdings
        return broker

    def test_no_op_when_splits_none(self):
        """splits_df가 None이면 holdings 변화 없음"""
        broker = self._make_broker(holdings={"AAPL": 100})
        today = pd.Timestamp("2023-03-15")
        _apply_stock_splits(today, None, broker)
        assert broker.holdings["AAPL"] == 100

    def test_no_op_when_splits_empty(self):
        """splits_df가 빈 DataFrame이면 holdings 변화 없음"""
        broker = self._make_broker(holdings={"AAPL": 100})
        today = pd.Timestamp("2023-03-15")
        _apply_stock_splits(today, pd.DataFrame(), broker)
        assert broker.holdings["AAPL"] == 100

    def test_no_op_when_date_not_in_index(self):
        """분할일이 아닌 날짜는 holdings 변화 없음"""
        dates = pd.date_range("2023-01-01", periods=5)
        splits = _make_splits_df(["AAPL"], dates)
        broker = self._make_broker(holdings={"AAPL": 100})
        today = pd.Timestamp("2024-01-01")
        _apply_stock_splits(today, splits, broker)
        assert broker.holdings["AAPL"] == 100

    def test_applies_split_on_split_date(self):
        """분할일에 보유 주수가 올바르게 조정되어야 한다"""
        dates = pd.date_range("2023-03-15", periods=1)
        splits = _make_splits_df(["AAPL"], dates, {"2023-03-15": {"AAPL": 4.0}})
        broker = self._make_broker(holdings={"AAPL": 50})
        today = pd.Timestamp("2023-03-15")
        _apply_stock_splits(today, splits, broker)
        assert broker.holdings["AAPL"] == 200  # 50 × 4

    def test_applies_multiple_tickers_on_same_date(self):
        """같은 날 여러 티커 분할이 동시에 처리되어야 한다"""
        dates = pd.date_range("2023-03-15", periods=1)
        splits = _make_splits_df(
            ["AAPL", "TSLA"], dates,
            {"2023-03-15": {"AAPL": 2.0, "TSLA": 3.0}}
        )
        broker = self._make_broker(holdings={"AAPL": 100, "TSLA": 50})
        today = pd.Timestamp("2023-03-15")
        _apply_stock_splits(today, splits, broker)
        assert broker.holdings["AAPL"] == 200
        assert broker.holdings["TSLA"] == 150

    def test_zero_ratio_rows_skipped(self):
        """ratio=0인 행은 처리하지 않음 (기본값)"""
        dates = pd.date_range("2023-03-15", periods=1)
        splits = _make_splits_df(["AAPL"], dates)  # 모든 값이 0
        broker = self._make_broker(holdings={"AAPL": 100})
        today = pd.Timestamp("2023-03-15")
        _apply_stock_splits(today, splits, broker)
        assert broker.holdings["AAPL"] == 100

    def test_exception_handled_silently(self):
        """내부 오류 발생 시 예외가 전파되지 않아야 한다"""
        bad_df = MagicMock()
        bad_df.empty = False
        bad_df.index.__contains__ = MagicMock(side_effect=RuntimeError("error"))
        broker = self._make_broker(holdings={"AAPL": 100})
        today = pd.Timestamp("2023-03-15")
        # 예외가 발생하지 않아야 함
        _apply_stock_splits(today, bad_df, broker)
