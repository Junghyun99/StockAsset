import math

import numpy as np
import pandas as pd
import pytest

from src.core.logic.sso_dip_signals import (
    SsoDipSignals,
    SsoDipIndicatorCalculator,
    MIN_REQUIRED_DAYS,
)


# ── 헬퍼 ──────────────────────────────────────────────────────────────
def _make_spy_df(n_days: int = 300, base_price: float = 500.0,
                 trend: float = 0.0) -> pd.DataFrame:
    dates = pd.bdate_range(end="2024-06-01", periods=n_days)
    prices = base_price + np.arange(n_days) * trend
    return pd.DataFrame({
        "Open": prices, "High": prices * 1.01,
        "Low": prices * 0.99, "Close": prices,
        "Volume": [1_000_000] * n_days,
    }, index=dates)


# ── SsoDipSignals 데이터클래스 ─────────────────────────────────────────
class TestSsoDipSignals:
    def test_fields_present(self):
        sig = SsoDipSignals(
            date="2024-06-01", weekly_rsi=50.0,
            ma200_deviation=0.05, price=500.0, ma200=476.19,
        )
        assert sig.date == "2024-06-01"
        assert sig.weekly_rsi == 50.0
        assert sig.ma200_deviation == 0.05
        assert sig.price == 500.0
        assert sig.ma200 == pytest.approx(476.19)

    def test_frozen(self):
        sig = SsoDipSignals(
            date="2024-06-01", weekly_rsi=50.0,
            ma200_deviation=0.0, price=500.0, ma200=500.0,
        )
        with pytest.raises(AttributeError):
            sig.weekly_rsi = 99.0  # type: ignore[misc]


# ── 괴리율 (MA200 deviation) ──────────────────────────────────────────
class TestMa200Deviation:
    def test_flat_data_deviation_near_zero(self):
        """횡보 데이터(trend=0) → 현재가 ≈ MA200 → 괴리율 ≈ 0%."""
        df = _make_spy_df(n_days=300, base_price=500.0, trend=0.0)
        sig = SsoDipIndicatorCalculator().calculate(df)
        assert sig.ma200_deviation == pytest.approx(0.0, abs=1e-6)

    def test_downtrend_deviation_negative(self):
        """하락 추세 → 현재가 < MA200 → 괴리율 < 0."""
        df = _make_spy_df(n_days=300, base_price=600.0, trend=-0.5)
        sig = SsoDipIndicatorCalculator().calculate(df)
        assert sig.ma200_deviation < 0

    def test_uptrend_deviation_positive(self):
        """상승 추세 → 현재가 > MA200 → 괴리율 > 0."""
        df = _make_spy_df(n_days=300, base_price=400.0, trend=0.5)
        sig = SsoDipIndicatorCalculator().calculate(df)
        assert sig.ma200_deviation > 0

    def test_deviation_formula(self):
        """괴리율 = (price - ma200) / ma200 공식 검증."""
        df = _make_spy_df(n_days=300, base_price=400.0, trend=0.5)
        sig = SsoDipIndicatorCalculator().calculate(df)
        expected = (sig.price - sig.ma200) / sig.ma200
        assert sig.ma200_deviation == pytest.approx(expected)


# ── 주봉 RSI ──────────────────────────────────────────────────────────
class TestMdd:
    def test_trailing_252_day_peak_mdd(self):
        dates = pd.date_range("2024-01-01", periods=252, freq="D")
        closes = np.array([100.0] * 251 + [80.0])
        df = pd.DataFrame({"Close": closes}, index=dates)

        sig = SsoDipIndicatorCalculator().calculate(df)

        assert sig.mdd_252 == pytest.approx(-0.20)


class TestWeeklyRsi:
    def test_rsi_in_valid_range(self):
        """주봉 RSI는 항상 0~100 범위."""
        df = _make_spy_df(n_days=300, base_price=500.0, trend=0.1)
        sig = SsoDipIndicatorCalculator().calculate(df)
        assert 0.0 <= sig.weekly_rsi <= 100.0

    def test_rsi_all_gains_is_100(self):
        """매일 상승하는 데이터 → 주봉도 전부 상승 → RSI 100."""
        df = _make_spy_df(n_days=300, base_price=100.0, trend=1.0)
        sig = SsoDipIndicatorCalculator().calculate(df)
        assert sig.weekly_rsi == pytest.approx(100.0)

    def test_rsi_mixed_data_between_bounds(self):
        """등락이 섞인 데이터 → RSI가 0과 100 사이."""
        dates = pd.bdate_range(end="2024-06-01", periods=300)
        prices = 500.0 + np.sin(np.linspace(0, 20 * np.pi, 300)) * 50
        df = pd.DataFrame({
            "Open": prices, "High": prices * 1.01,
            "Low": prices * 0.99, "Close": prices,
            "Volume": [1_000_000] * 300,
        }, index=dates)
        sig = SsoDipIndicatorCalculator().calculate(df)
        assert 0.0 < sig.weekly_rsi < 100.0


# ── 데이터 부족 / 빈 데이터 ──────────────────────────────────────────
class TestInsufficientData:
    def test_insufficient_days_yields_nan(self):
        """MIN_REQUIRED_DAYS 미만 → weekly_rsi, ma200_deviation 모두 NaN."""
        df = _make_spy_df(n_days=MIN_REQUIRED_DAYS - 1, base_price=500.0)
        sig = SsoDipIndicatorCalculator().calculate(df)
        assert math.isnan(sig.weekly_rsi)
        assert math.isnan(sig.ma200_deviation)
        assert sig.price == pytest.approx(500.0)

    def test_empty_dataframe_yields_nan(self):
        """빈 DataFrame → 모든 값 NaN, date 빈 문자열."""
        sig = SsoDipIndicatorCalculator().calculate(pd.DataFrame())
        assert sig.date == ""
        assert math.isnan(sig.weekly_rsi)
        assert math.isnan(sig.ma200_deviation)
        assert math.isnan(sig.price)
        assert math.isnan(sig.ma200)

    def test_none_input_yields_nan(self):
        """None 입력 → 모든 값 NaN."""
        sig = SsoDipIndicatorCalculator().calculate(None)
        assert sig.date == ""
        assert math.isnan(sig.weekly_rsi)


# ── MultiIndex 지원 ──────────────────────────────────────────────────
class TestMultiIndex:
    def test_multiindex_columns(self):
        """yfinance MultiIndex 형식 DataFrame도 정상 처리."""
        df = _make_spy_df(n_days=300, base_price=500.0, trend=0.1)
        # MultiIndex: (metric, ticker) 형태로 변환
        mi = pd.MultiIndex.from_tuples(
            [(c, "SPY") for c in df.columns], names=["Price", "Ticker"]
        )
        df_mi = df.copy()
        df_mi.columns = mi
        sig = SsoDipIndicatorCalculator().calculate(df_mi)
        assert not math.isnan(sig.weekly_rsi)
        assert not math.isnan(sig.ma200_deviation)
        assert sig.price > 0


# ── 날짜 매핑 ────────────────────────────────────────────────────────
class TestDateMapping:
    def test_date_matches_last_row(self):
        """결과의 date는 입력 DataFrame 마지막 행의 날짜와 일치."""
        df = _make_spy_df(n_days=300, base_price=500.0)
        sig = SsoDipIndicatorCalculator().calculate(df)
        expected_date = df.index[-1].strftime("%Y-%m-%d")
        assert sig.date == expected_date

    def test_price_matches_last_close(self):
        """결과의 price는 마지막 종가와 일치."""
        df = _make_spy_df(n_days=300, base_price=500.0, trend=0.0)
        sig = SsoDipIndicatorCalculator().calculate(df)
        assert sig.price == pytest.approx(float(df["Close"].iloc[-1]))
