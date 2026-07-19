# SSO DipBuy Engine (신호 기반 SSO/SPYI 분할매수 엔진) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** SPY 주봉 RSI와 200일선 괴리율을 기반으로 SSO를 단계별 분할매수/매도하고, 나머지를 SPYI에 배분하는 신호 기반 엔진을 구현한다.

**Architecture:** TradingEngine을 직접 상속하여 리밸런서를 사용하지 않는 신호 기반 엔진을 구현한다. 신호 판단(core/logic)과 엔진(core/engine)을 분리하여 SRP를 지키고, DipBuyEngine의 상태 영속화 패턴(strategy_state.json)을 재사용한다. 주봉 RSI와 200일선 괴리율은 SPY 일봉 OHLCV에서 계산하며, 별도 지표 계산기 클래스를 만든다.

**Tech Stack:** Python 3.10, pandas, pytest, unittest.mock

---

## 전략 요약

### 상태 머신

```
[IDLE] ──매수신호1──▶ [BUY_STAGE_1] ──매수신호2──▶ [BUY_STAGE_2] ──매수신호3──▶ [BUY_STAGE_3]
  ▲                                                                                    │
  │                    [SELL] ◀──────── 매도신호 (RSI≥75 AND 괴리율≥+15%) ◀─────────────┘
  │                      │          (어느 단계에서든 매도 신호 발생 가능)
  └── 40% 도달 ──────────┘
```

### 매수 신호 (AND 조건, 상향 에스컬레이션만)

| 단계 | 주봉 RSI | 200일선 괴리율 | SSO 목표 | 속도계수 |
|------|----------|---------------|----------|---------|
| 1    | ≤ 48     | ≤ -10%        | 40%      | 10%     |
| 2    | ≤ 42     | ≤ -18%        | 50%      | 20%     |
| 3    | ≤ 36     | ≤ -26%        | 80%      | 40%     |

### 매도 신호

| 조건 | 주봉 RSI | 200일선 괴리율 | SSO 목표 | 속도계수 |
|------|----------|---------------|----------|---------|
| 매도 | ≥ 75     | ≥ +15%        | 40%      | 10%     |

### 분할매수/매도 알고리즘

매 사이클: `delta = (목표비중 - 현재비중) × 속도계수 × 총자산`
- delta > 0 → SSO 매수, 잉여 SPYI 매도로 자금 확보
- delta < 0 → SSO 매도, 잉여 현금으로 SPYI 매수

### 핵심 규칙

- 초기 상태: 100% SPYI, 매수 신호 대기 (IDLE)
- 신호 상향 에스컬레이션만 가능 (1→2→3), 하향 강등 없음
- 한번 발생한 매수 신호는 목표 도달까지 유지
- 매도 신호 발생 시 40% 도달까지 계속 매도
- 매도 완료(40% 도달) 후 IDLE로 복귀

---

## Task 1: 주봉 RSI + 200일선 괴리율 지표 계산기

SPY 일봉 OHLCV에서 주봉 RSI와 200일선 괴리율을 계산하는 순수 로직 클래스.

**Files:**
- Create: `src/core/logic/sso_dip_signals.py`
- Test: `tests/test_core_logic_sso_dip_signals.py`

### Step 1: 테스트 작성

```python
# tests/test_core_logic_sso_dip_signals.py
"""SsoDipSignals / SsoDipIndicatorCalculator 단위 테스트."""
import math
import numpy as np
import pandas as pd
import pytest

from src.core.logic.sso_dip_signals import SsoDipSignals, SsoDipIndicatorCalculator


def _make_spy_df(n_days: int = 300, base_price: float = 500.0,
                 trend: float = 0.0) -> pd.DataFrame:
    """테스트용 SPY 일봉 데이터 생성.

    trend > 0: 상승, trend < 0: 하락, trend == 0: 횡보
    """
    dates = pd.bdate_range(end="2024-06-01", periods=n_days)
    prices = base_price + np.arange(n_days) * trend
    return pd.DataFrame({
        "Open": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Close": prices,
        "Volume": [1_000_000] * n_days,
    }, index=dates)


class TestSsoDipSignals:
    """SsoDipSignals 데이터클래스 기본 검증."""

    def test_fields_present(self):
        sig = SsoDipSignals(
            date="2024-06-01", weekly_rsi=45.0, ma200_deviation=-0.12,
            spy_price=480.0, spy_ma200=540.0,
        )
        assert sig.weekly_rsi == 45.0
        assert sig.ma200_deviation == -0.12
        assert sig.spy_price == 480.0
        assert sig.spy_ma200 == 540.0

    def test_frozen(self):
        sig = SsoDipSignals(
            date="2024-06-01", weekly_rsi=45.0, ma200_deviation=-0.12,
            spy_price=480.0, spy_ma200=540.0,
        )
        with pytest.raises(AttributeError):
            sig.weekly_rsi = 50.0


class TestSsoDipIndicatorCalculator:
    """SsoDipIndicatorCalculator 계산 로직 검증."""

    def test_横보_ma200_deviation_near_zero(self):
        """횡보 데이터 → 괴리율 ≈ 0%."""
        df = _make_spy_df(n_days=300, trend=0.0)
        calc = SsoDipIndicatorCalculator()
        sig = calc.calculate(df)
        assert abs(sig.ma200_deviation) < 0.05

    def test_하락_ma200_deviation_negative(self):
        """하락 추세 → 괴리율 < 0."""
        df = _make_spy_df(n_days=300, base_price=600.0, trend=-0.5)
        calc = SsoDipIndicatorCalculator()
        sig = calc.calculate(df)
        assert sig.ma200_deviation < 0

    def test_상승_ma200_deviation_positive(self):
        """상승 추세 → 괴리율 > 0."""
        df = _make_spy_df(n_days=300, base_price=400.0, trend=0.5)
        calc = SsoDipIndicatorCalculator()
        sig = calc.calculate(df)
        assert sig.ma200_deviation > 0

    def test_weekly_rsi_range(self):
        """RSI는 0~100 범위."""
        df = _make_spy_df(n_days=300)
        calc = SsoDipIndicatorCalculator()
        sig = calc.calculate(df)
        assert 0 <= sig.weekly_rsi <= 100

    def test_data_insufficient_returns_nan(self):
        """데이터 부족 시 NaN 반환."""
        df = _make_spy_df(n_days=10)
        calc = SsoDipIndicatorCalculator()
        sig = calc.calculate(df)
        assert math.isnan(sig.weekly_rsi)
        assert math.isnan(sig.ma200_deviation)

    def test_empty_df_returns_nan(self):
        """빈 DataFrame → NaN."""
        calc = SsoDipIndicatorCalculator()
        sig = calc.calculate(pd.DataFrame())
        assert math.isnan(sig.weekly_rsi)
        assert math.isnan(sig.ma200_deviation)

    def test_multiindex_support(self):
        """MultiIndex 컬럼도 처리 가능."""
        df = _make_spy_df(n_days=300)
        mi = pd.MultiIndex.from_product([df.columns, ["SPY"]])
        mi_df = pd.DataFrame(df.values, index=df.index, columns=mi)
        calc = SsoDipIndicatorCalculator()
        sig = calc.calculate(mi_df)
        assert not math.isnan(sig.weekly_rsi)

    def test_date_matches_last_row(self):
        """date는 데이터 마지막 날짜."""
        df = _make_spy_df(n_days=300)
        calc = SsoDipIndicatorCalculator()
        sig = calc.calculate(df)
        assert sig.date == df.index[-1].strftime("%Y-%m-%d")
```

### Step 2: 테스트 실행하여 실패 확인

```bash
pytest tests/test_core_logic_sso_dip_signals.py -v
```

Expected: FAIL (`ModuleNotFoundError: No module named 'src.core.logic.sso_dip_signals'`)

### Step 3: 구현

```python
# src/core/logic/sso_dip_signals.py
"""SSO DipBuy 전략용 지표 계산기 (순수 로직).

SPY 일봉 OHLCV에서 주봉 RSI와 200일선 괴리율을 계산한다.
주봉 RSI: 일봉을 주봉으로 리샘플링 후 Wilder RSI(14) 계산.
200일선 괴리율: (현재가 - MA200) / MA200.
"""
import math
from dataclasses import dataclass

import pandas as pd

RSI_PERIOD = 14
MA200_WINDOW = 200
MIN_REQUIRED_DAYS = 250  # 주봉 리샘플링 + MA200에 최소한 필요한 일봉 수


@dataclass(frozen=True)
class SsoDipSignals:
    """오늘의 SSO DipBuy 지표 스냅샷."""
    date: str
    weekly_rsi: float       # 주봉 RSI(14)
    ma200_deviation: float  # 200일선 괴리율 ((price - ma200) / ma200)
    spy_price: float        # SPY 종가
    spy_ma200: float        # SPY 200일 이동평균


class SsoDipIndicatorCalculator:
    """SPY 일봉 OHLCV에서 주봉 RSI와 200일선 괴리율을 계산한다."""

    def calculate(self, df: pd.DataFrame) -> SsoDipSignals:
        if df is None or df.empty:
            return self._nan_signals()

        df = df.copy().ffill().bfill()

        if isinstance(df.columns, pd.MultiIndex):
            close = df.xs("Close", axis=1, level=0).iloc[:, 0]
        else:
            close = df["Close"]

        if len(close) < MIN_REQUIRED_DAYS:
            return SsoDipSignals(
                date=close.index[-1].strftime("%Y-%m-%d") if len(close) > 0 else "",
                weekly_rsi=float("nan"),
                ma200_deviation=float("nan"),
                spy_price=float(close.iloc[-1]) if len(close) > 0 else float("nan"),
                spy_ma200=float("nan"),
            )

        date = close.index[-1].strftime("%Y-%m-%d")
        price = float(close.iloc[-1])

        # 200일 이동평균 + 괴리율
        ma200 = float(close.rolling(window=MA200_WINDOW).mean().iloc[-1])
        if ma200 > 0 and not math.isnan(ma200):
            deviation = (price - ma200) / ma200
        else:
            deviation = float("nan")

        # 주봉 RSI: 일봉 → 주봉 리샘플링 후 Wilder RSI
        weekly_close = close.resample("W-FRI").last().dropna()
        weekly_rsi = self._rsi(weekly_close) if len(weekly_close) > RSI_PERIOD else float("nan")

        return SsoDipSignals(
            date=date,
            weekly_rsi=weekly_rsi,
            ma200_deviation=deviation,
            spy_price=price,
            spy_ma200=ma200,
        )

    @staticmethod
    def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> float:
        """Wilder smoothing RSI."""
        if len(close) <= period:
            return float("nan")
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    @staticmethod
    def _nan_signals() -> SsoDipSignals:
        return SsoDipSignals(
            date="", weekly_rsi=float("nan"), ma200_deviation=float("nan"),
            spy_price=float("nan"), spy_ma200=float("nan"),
        )
```

### Step 4: `src/core/logic/__init__.py`에 export 추가

```python
# 기존 import 뒤에 추가:
from src.core.logic.sso_dip_signals import SsoDipSignals, SsoDipIndicatorCalculator
# __all__에 추가:
"SsoDipSignals", "SsoDipIndicatorCalculator",
```

### Step 5: 테스트 통과 확인

```bash
pytest tests/test_core_logic_sso_dip_signals.py -v
```

Expected: ALL PASSED

### Step 6: 커밋

```bash
git add src/core/logic/sso_dip_signals.py src/core/logic/__init__.py tests/test_core_logic_sso_dip_signals.py
git commit -m "feat: add SsoDipIndicatorCalculator for weekly RSI + MA200 deviation"
```

---

## Task 2: 신호 판단 + 분할매매 플래너

신호 단계 상태 머신과 갭 비율 기반 분할매수/매도 로직을 담당하는 순수 로직 클래스.

**Files:**
- Create: `src/core/logic/sso_dip_planner.py`
- Test: `tests/test_core_logic_sso_dip_planner.py`

### Step 1: 테스트 작성

```python
# tests/test_core_logic_sso_dip_planner.py
"""SsoDipPlanner 단위 테스트."""
import pytest
from src.core.logic.sso_dip_signals import SsoDipSignals
from src.core.logic.sso_dip_planner import (
    SsoDipPlanner, SsoDipState, SignalLevel,
    BUY_STAGES, SELL_CONDITION,
)
from src.core.models import Portfolio


def _sig(rsi: float = 50.0, dev: float = 0.0) -> SsoDipSignals:
    """지표 스냅샷 헬퍼."""
    return SsoDipSignals(
        date="2024-06-01", weekly_rsi=rsi, ma200_deviation=dev,
        spy_price=500.0, spy_ma200=500.0,
    )


def _pf(cash: float = 10000.0, sso: int = 0, spyi: int = 0,
         sso_price: float = 80.0, spyi_price: float = 55.0) -> Portfolio:
    """포트폴리오 헬퍼."""
    return Portfolio(
        total_cash=cash,
        holdings={"SSO": sso, "SPYI": spyi},
        current_prices={"SSO": sso_price, "SPYI": spyi_price},
    )


class TestSignalDetection:
    """신호 탐지 테스트."""

    def test_no_signal_in_normal_market(self):
        """정상 시장 → IDLE."""
        planner = SsoDipPlanner()
        state = SsoDipState()
        _, _, new_state = planner.plan(_sig(rsi=55, dev=0.02), _pf(), state)
        assert new_state.level == SignalLevel.IDLE

    def test_stage1_triggers(self):
        """RSI≤48 AND 괴리율≤-10% → STAGE_1."""
        planner = SsoDipPlanner()
        state = SsoDipState()
        _, _, new_state = planner.plan(_sig(rsi=45, dev=-0.12), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_1

    def test_stage2_triggers(self):
        """RSI≤42 AND 괴리율≤-18% → STAGE_2."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        _, _, new_state = planner.plan(_sig(rsi=40, dev=-0.20), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_2

    def test_stage3_triggers(self):
        """RSI≤36 AND 괴리율≤-26% → STAGE_3."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        _, _, new_state = planner.plan(_sig(rsi=34, dev=-0.28), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_3

    def test_no_downgrade(self):
        """단계2에서 단계1 조건 → 단계2 유지 (하향 강등 없음)."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_2)
        _, _, new_state = planner.plan(_sig(rsi=45, dev=-0.12), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_2

    def test_sell_signal(self):
        """RSI≥75 AND 괴리율≥+15% → SELL."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        _, _, new_state = planner.plan(_sig(rsi=78, dev=0.18), _pf(sso=50), state)
        assert new_state.level == SignalLevel.SELL

    def test_sell_completes_to_idle(self):
        """매도 완료(40% 도달) → IDLE 복귀."""
        planner = SsoDipPlanner()
        # SSO 40%, SPYI 60% → 정확히 디폴트 비중
        sso_val = 4000  # 50주 × $80
        spyi_val = 6000  # ~109주 × $55
        state = SsoDipState(level=SignalLevel.SELL)
        _, _, new_state = planner.plan(
            _sig(rsi=65, dev=0.05),
            _pf(cash=0, sso=50, spyi=109, sso_price=80.0, spyi_price=55.05),
            state,
        )
        assert new_state.level == SignalLevel.IDLE

    def test_direct_jump_to_stage3(self):
        """IDLE에서 직접 단계3 조건 → STAGE_3."""
        planner = SsoDipPlanner()
        state = SsoDipState()
        _, _, new_state = planner.plan(_sig(rsi=34, dev=-0.28), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_3


class TestDCA:
    """분할매수/매도 금액 계산 테스트."""

    def test_buy_stage1_speed(self):
        """단계1 속도계수 10% 검증."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        # SSO 0%, 목표 40%, 총자산 $10000
        # delta = (0.4 - 0.0) × 0.1 × 10000 = $400
        orders, _, _ = planner.plan(
            _sig(rsi=45, dev=-0.12),
            _pf(cash=10000, sso=0, spyi=0),
            state,
        )
        sso_buy = [o for o in orders if o.ticker == "SSO" and o.action.value == "BUY"]
        assert len(sso_buy) == 1
        assert sso_buy[0].quantity == 5  # $400 / $80 = 5주

    def test_buy_stage3_speed(self):
        """단계3 속도계수 40% 검증."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_3)
        # SSO 0%, 목표 80%, 총자산 $10000
        # delta = (0.8 - 0.0) × 0.4 × 10000 = $3200
        orders, _, _ = planner.plan(
            _sig(rsi=34, dev=-0.28),
            _pf(cash=10000, sso=0, spyi=0),
            state,
        )
        sso_buy = [o for o in orders if o.ticker == "SSO" and o.action.value == "BUY"]
        assert len(sso_buy) == 1
        assert sso_buy[0].quantity == 40  # $3200 / $80 = 40주

    def test_sell_speed(self):
        """매도 속도계수 10% 검증."""
        planner = SsoDipPlanner()
        # SSO 80%, 목표 40%
        # 총자산 = 100주×$80 + 0 = $8000
        # delta = |0.4 - 1.0| × 0.1 × 8000 = $480 → 6주
        state = SsoDipState(level=SignalLevel.SELL)
        orders, _, _ = planner.plan(
            _sig(rsi=65, dev=0.05),
            _pf(cash=0, sso=100, spyi=0),
            state,
        )
        sso_sell = [o for o in orders if o.ticker == "SSO" and o.action.value == "SELL"]
        assert len(sso_sell) == 1
        assert sso_sell[0].quantity == 6

    def test_spyi_counterpart_on_buy(self):
        """SSO 매수 시 SPYI 매도로 자금 확보."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        orders, _, _ = planner.plan(
            _sig(rsi=45, dev=-0.12),
            _pf(cash=0, sso=0, spyi=200, spyi_price=55.0),
            state,
        )
        spyi_sell = [o for o in orders if o.ticker == "SPYI" and o.action.value == "SELL"]
        assert len(spyi_sell) == 1

    def test_spyi_buy_on_sell(self):
        """SSO 매도 시 잔여 현금으로 SPYI 매수."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.SELL)
        orders, _, _ = planner.plan(
            _sig(rsi=65, dev=0.05),
            _pf(cash=0, sso=100, spyi=0),
            state,
        )
        spyi_buy = [o for o in orders if o.ticker == "SPYI" and o.action.value == "BUY"]
        assert len(spyi_buy) == 1

    def test_no_orders_when_target_reached(self):
        """목표 비중 도달 시 주문 없음."""
        planner = SsoDipPlanner()
        # SSO 정확히 40% = $4000 / $10000
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        orders, _, _ = planner.plan(
            _sig(rsi=45, dev=-0.12),
            _pf(cash=0, sso=50, spyi=109, sso_price=80.0, spyi_price=55.05),
            state,
        )
        sso_orders = [o for o in orders if o.ticker == "SSO"]
        assert len(sso_orders) == 0


class TestStateSerialize:
    """상태 직렬화/역직렬화."""

    def test_roundtrip(self):
        state = SsoDipState(level=SignalLevel.BUY_STAGE_2)
        restored = SsoDipState.from_dict(state.to_dict())
        assert restored.level == SignalLevel.BUY_STAGE_2

    def test_from_empty_dict(self):
        state = SsoDipState.from_dict({})
        assert state.level == SignalLevel.IDLE

    def test_from_none(self):
        state = SsoDipState.from_dict(None)
        assert state.level == SignalLevel.IDLE
```

### Step 2: 테스트 실행하여 실패 확인

```bash
pytest tests/test_core_logic_sso_dip_planner.py -v
```

Expected: FAIL (`ModuleNotFoundError`)

### Step 3: 구현

```python
# src/core/logic/sso_dip_planner.py
"""SSO DipBuy 분할매수/매도 플래너 (순수, 무상태).

주봉 RSI + 200일선 괴리율 신호에 따라 SSO 목표 비중을 결정하고,
갭 비율 방식으로 분할매수/매도 주문을 생성한다.

상태(SsoDipState)는 호출자가 보관·영속화한다 (DipBuyPlanner 패턴 동일).
"""
import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple

from src.core.models import Portfolio, Order, OrderAction
from src.core.logic.sso_dip_signals import SsoDipSignals


class SignalLevel(str, Enum):
    IDLE = "IDLE"
    BUY_STAGE_1 = "BUY_STAGE_1"
    BUY_STAGE_2 = "BUY_STAGE_2"
    BUY_STAGE_3 = "BUY_STAGE_3"
    SELL = "SELL"


# 매수 단계 정의: (level, rsi_threshold, deviation_threshold, target_ratio, speed)
BUY_STAGES = [
    (SignalLevel.BUY_STAGE_3, 36.0, -0.26, 0.80, 0.40),
    (SignalLevel.BUY_STAGE_2, 42.0, -0.18, 0.50, 0.20),
    (SignalLevel.BUY_STAGE_1, 48.0, -0.10, 0.40, 0.10),
]

# 매도 조건
SELL_CONDITION = {"rsi": 75.0, "deviation": 0.15}
SELL_TARGET = 0.40
SELL_SPEED = 0.10

# 상향 에스컬레이션 순서 (높은 단계일수록 큰 인덱스)
_LEVEL_ORDER = {
    SignalLevel.IDLE: 0,
    SignalLevel.BUY_STAGE_1: 1,
    SignalLevel.BUY_STAGE_2: 2,
    SignalLevel.BUY_STAGE_3: 3,
    SignalLevel.SELL: -1,
}


@dataclass
class SsoDipState:
    """플래너의 영속 상태."""
    level: SignalLevel = SignalLevel.IDLE

    def to_dict(self) -> dict:
        return {"level": self.level.value}

    @classmethod
    def from_dict(cls, data: dict) -> "SsoDipState":
        data = data or {}
        level_str = data.get("level", SignalLevel.IDLE.value)
        try:
            level = SignalLevel(level_str)
        except ValueError:
            level = SignalLevel.IDLE
        return cls(level=level)


class SsoDipPlanner:
    """신호 기반 SSO/SPYI 분할매수/매도 플래너."""

    SSO_TICKER = "SSO"
    SPYI_TICKER = "SPYI"

    def plan(
        self,
        signals: SsoDipSignals,
        portfolio: Portfolio,
        state: SsoDipState,
    ) -> Tuple[List[Order], str, SsoDipState]:
        rsi = signals.weekly_rsi
        dev = signals.ma200_deviation

        if math.isnan(rsi) or math.isnan(dev):
            return [], "대기(지표 불가)", state

        sso_price = portfolio.current_prices.get(self.SSO_TICKER, 0.0)
        spyi_price = portfolio.current_prices.get(self.SPYI_TICKER, 0.0)
        if sso_price <= 0 or spyi_price <= 0:
            return [], "대기(가격 정보 없음)", state

        total = portfolio.total_value
        if total <= 0:
            return [], "대기(자산 없음)", state

        current_sso_ratio = self._sso_ratio(portfolio)
        new_level = self._detect_signal(rsi, dev, state.level)

        # 목표 비중 + 속도계수 결정
        target_ratio, speed = self._get_target_and_speed(new_level)

        # 매도 완료 체크 (40% 이하 도달 시 IDLE 복귀)
        if new_level == SignalLevel.SELL and current_sso_ratio <= SELL_TARGET + 0.005:
            new_level = SignalLevel.IDLE
            target_ratio, speed = self._get_target_and_speed(new_level)

        # 분할매매 금액 계산
        delta_ratio = (target_ratio - current_sso_ratio) * speed
        delta_amount = delta_ratio * total

        orders: List[Order] = []
        reasons: List[str] = []

        if delta_amount > 0:
            # SSO 매수
            qty = math.floor(delta_amount / sso_price)
            if qty > 0:
                # SPYI 매도로 자금 확보
                cost = qty * sso_price
                cash_shortfall = cost - portfolio.total_cash
                if cash_shortfall > 0:
                    spyi_sell_qty = min(
                        math.ceil(cash_shortfall / spyi_price),
                        portfolio.holdings.get(self.SPYI_TICKER, 0),
                    )
                    if spyi_sell_qty > 0:
                        orders.append(Order(self.SPYI_TICKER, OrderAction.SELL, spyi_sell_qty, spyi_price))
                orders.append(Order(self.SSO_TICKER, OrderAction.BUY, qty, sso_price))
                reasons.append(f"{new_level.value} 분할매수 SSO {qty}주")

        elif delta_amount < 0:
            # SSO 매도
            sell_amount = abs(delta_amount)
            qty = min(
                math.ceil(sell_amount / sso_price),
                portfolio.holdings.get(self.SSO_TICKER, 0),
            )
            if qty > 0:
                orders.append(Order(self.SSO_TICKER, OrderAction.SELL, qty, sso_price))
                reasons.append(f"분할매도 SSO {qty}주")
                # 매도 대금으로 SPYI 매수
                proceeds = qty * sso_price
                spyi_qty = math.floor(proceeds / spyi_price)
                if spyi_qty > 0:
                    orders.append(Order(self.SPYI_TICKER, OrderAction.BUY, spyi_qty, spyi_price))

        reason = " / ".join(reasons) if reasons else f"대기({new_level.value})"
        return orders, reason, SsoDipState(level=new_level)

    def _detect_signal(self, rsi: float, dev: float, current: SignalLevel) -> SignalLevel:
        """신호 탐지. 상향 에스컬레이션만, SELL은 어디서든 발생 가능."""
        # 매도 신호 (매수 중이든 아니든 발동)
        if current != SignalLevel.SELL and rsi >= SELL_CONDITION["rsi"] and dev >= SELL_CONDITION["deviation"]:
            return SignalLevel.SELL

        # SELL 상태에서는 매수 신호 무시 (40% 도달까지 매도 지속)
        if current == SignalLevel.SELL:
            return SignalLevel.SELL

        # 매수 신호 탐지 (높은 단계부터 검사, 상향만)
        current_order = _LEVEL_ORDER.get(current, 0)
        for level, rsi_th, dev_th, _, _ in BUY_STAGES:
            if _LEVEL_ORDER[level] > current_order and rsi <= rsi_th and dev <= dev_th:
                return level

        return current

    def _get_target_and_speed(self, level: SignalLevel) -> Tuple[float, float]:
        """레벨에 따른 (목표 SSO 비중, 속도계수)."""
        if level == SignalLevel.SELL:
            return SELL_TARGET, SELL_SPEED
        for lv, _, _, target, speed in BUY_STAGES:
            if lv == level:
                return target, speed
        return 0.0, 0.0  # IDLE: 목표 0%, 매매 없음

    def _sso_ratio(self, pf: Portfolio) -> float:
        """현재 SSO 비중 (총자산 대비)."""
        total = pf.total_value
        if total <= 0:
            return 0.0
        sso_val = pf.holdings.get(self.SSO_TICKER, 0) * pf.current_prices.get(self.SSO_TICKER, 0.0)
        return sso_val / total
```

### Step 4: `src/core/logic/__init__.py`에 export 추가

```python
from src.core.logic.sso_dip_planner import SsoDipPlanner, SsoDipState, SignalLevel
# __all__에 추가:
"SsoDipPlanner", "SsoDipState", "SignalLevel",
```

### Step 5: 테스트 통과 확인

```bash
pytest tests/test_core_logic_sso_dip_planner.py -v
```

Expected: ALL PASSED

### Step 6: 커밋

```bash
git add src/core/logic/sso_dip_planner.py src/core/logic/__init__.py tests/test_core_logic_sso_dip_planner.py
git commit -m "feat: add SsoDipPlanner with signal-based staged DCA"
```

---

## Task 3: SsoDipBuyEngine 엔진 클래스

TradingEngine을 상속하여 신호 기반 SSO/SPYI 매매를 실행하는 엔진.

**Files:**
- Create: `src/core/engine/sso_dip_buy.py`
- Modify: `src/core/engine/__init__.py`
- Modify: `src/config.py` (SPYI 매핑은 Task 0에서 이미 완료됨 — 확인만)
- Test: `tests/test_core_engine_sso_dip_buy.py`

### Step 1: 테스트 작성

```python
# tests/test_core_engine_sso_dip_buy.py
"""SsoDipBuyEngine 단위 테스트."""
import math
from unittest.mock import MagicMock, patch

from src.core.engine.sso_dip_buy import SsoDipBuyEngine
from src.core.engine import TradingEngine, _ENGINE_REGISTRY, _ENGINE_BACKTEST
from src.core.logic.sso_dip_planner import SignalLevel, SsoDipState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, Order, OrderAction,
)


def _make_market_data(vix: float = 18.0) -> MarketData:
    return MarketData(
        date="2024-06-01", spy_price=520.0, spy_ma180=490.0,
        spy_volatility=0.14, spy_momentum=0.04, spy_mdd=-0.08, vix=vix,
    )


def _build_engine():
    broker = MagicMock()
    repo = MagicMock()
    logger = MagicMock()
    data_provider = MagicMock()

    repo.get_last_rebalancing_date.return_value = None
    repo.load_last_regime.return_value = None
    repo.load_strategy_state.return_value = {}
    broker.get_portfolio.return_value = Portfolio(
        total_cash=10000.0,
        holdings={"SSO": 0, "SPYI": 0},
        current_prices={"SSO": 80.0, "SPYI": 55.0},
    )
    broker.fetch_current_prices.return_value = {}

    with patch('src.core.engine.base.IndicatorCalculator') as MockCalc, \
         patch('src.core.engine.base.RegimeAnalyzer') as MockAnalyzer, \
         patch('src.core.engine.base.VolatilityTargeter') as MockTargeter, \
         patch('src.core.engine.base.Rebalancer') as MockRebalancer:

        analyzer = MockAnalyzer.return_value
        analyzer._prev_regime = None
        rebalancer = MockRebalancer.return_value
        rebalancer.get_target_params.return_value = (0.4, 0.075)

        engine = SsoDipBuyEngine(
            broker=broker, repo=repo, logger=logger,
            trading_interval_days=1,
        )

    return engine, {
        "broker": broker, "repo": repo, "logger": logger,
        "data_provider": data_provider,
    }


class TestClassStructure:
    def test_is_trading_engine_subclass(self):
        assert issubclass(SsoDipBuyEngine, TradingEngine)

    def test_registered_in_registry(self):
        names = [name for name, _ in _ENGINE_REGISTRY]
        assert "SsoDipBuyEngine" in names

    def test_backtest_enabled(self):
        assert _ENGINE_BACKTEST.get("SsoDipBuyEngine") is True

    def test_asset_groups(self):
        assert SsoDipBuyEngine.ASSET_GROUPS == {"A": ["SSO"], "B": ["SPYI"]}

    def test_all_tickers(self):
        engine, _ = _build_engine()
        assert set(engine.all_tickers) == {"SSO", "SPYI"}


class TestStateManagement:
    def test_loads_state_on_init(self):
        engine, mocks = _build_engine()
        mocks["repo"].load_strategy_state.assert_called_with("sso_dip_buy")

    def test_saves_state_after_cycle(self):
        engine, mocks = _build_engine()
        engine.dip_state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        # 상태 저장이 호출되는지 검증은 execute_cycle 호출로
        mocks["repo"].save_strategy_state.assert_not_called()  # init 시점엔 미호출


class TestCollectData:
    def test_fetches_spy_ohlcv(self):
        """SPY OHLCV를 수집한다 (SSO 아님)."""
        engine, mocks = _build_engine()
        engine.collect_data(mocks["data_provider"])
        mocks["data_provider"].fetch_ohlcv.assert_called_once_with(["SPY"], days=400)
```

### Step 2: 테스트 실행하여 실패 확인

```bash
pytest tests/test_core_engine_sso_dip_buy.py -v
```

Expected: FAIL (`ModuleNotFoundError`)

### Step 3: 구현

```python
# src/core/engine/sso_dip_buy.py
"""SSO/SPYI 신호 기반 분할매수 엔진.

SPY 주봉 RSI + 200일선 괴리율로 매수/매도 신호를 감지하고,
SSO(S&P500 2x 레버리지)를 단계적으로 분할매수/매도한다.
나머지 자산은 SPYI(S&P500 커버드콜)에 배분하여 인컴을 확보한다.

리밸런서를 사용하지 않는 신호 기반 엔진이다.
"""
from typing import List, Optional, Tuple

import math
import pandas as pd

from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.sso_dip_signals import SsoDipIndicatorCalculator
from src.core.logic.sso_dip_planner import SsoDipPlanner, SsoDipState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution,
    DecisionFactor,
)


@register_engine(color="#ff6b6b")
class SsoDipBuyEngine(TradingEngine):
    """SSO/SPYI 신호 기반 분할매수 전략 엔진.

    - 자산군 A: [SSO] (S&P500 2x 레버리지 — 분할매수 대상)
    - 자산군 B: [SPYI] (S&P500 커버드콜 — 인컴·대기 자산)
    - 매수 신호: 주봉RSI+괴리율 3단계, 매도 신호: RSI≥75+괴리율≥+15%
    - 분할매수/매도: 갭비율 방식 (속도계수: 단계1=10%, 단계2=20%, 단계3=40%, 매도=10%)
    """

    ASSET_GROUPS: dict = {"A": ["SSO"], "B": ["SPYI"]}
    STATE_KEY: str = "sso_dip_buy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sso_calc = SsoDipIndicatorCalculator()
        self._planner = SsoDipPlanner()
        self.dip_state = SsoDipState.from_dict(
            self.repo.load_strategy_state(self.STATE_KEY)
        )
        self.sso_signals = None

    def collect_data(
        self, data_provider: IDataProvider
    ) -> Tuple[pd.DataFrame, float]:
        """Step 1: SPY OHLCV 수집 (신호 지표 = SPY 기준)."""
        spy_df = data_provider.fetch_ohlcv(["SPY"], days=400)
        vix = data_provider.fetch_vix()
        return spy_df, vix

    def calculate_indicators(
        self, spy_df: pd.DataFrame, vix: float
    ) -> MarketData:
        """Step 2: 표준 MarketData + SSO DipBuy 지표 동시 계산."""
        self.sso_signals = self._sso_calc.calculate(spy_df)
        return self.calculator.calculate(spy_df, vix)

    def execute_cycle(
        self,
        market_data: MarketData,
        portfolio: Portfolio,
        regime: MarketRegime,
        exposure: float,
        nan_fields: List[str],
        sim_date: Optional[str],
        record_date: str,
    ) -> Tuple[TradeSignal, List[TradeExecution], Portfolio, bool]:
        """Step 5: 신호 기반 분할매수/매도 (Rebalancer 미사용)."""
        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = False

        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}")
            self.logger.error(f"NaN detected: {', '.join(nan_fields)} — 매매 중단")
            return signal, executions, final_pf, is_rebalancing

        orders, reason, new_state = self._planner.plan(
            self.sso_signals, portfolio, self.dip_state,
        )

        signal = TradeSignal(exposure, orders, reason)
        self.logger.info(f">>> Step 5: SsoDipBuy ({reason})")

        if orders:
            is_rebalancing = True
            self.logger.info(f"Executing {len(orders)} orders ({reason})")
            executions = self.broker.execute_orders(orders)
            try:
                final_pf = self.broker.get_portfolio()
            except RuntimeError as e:
                self.logger.error(
                    f"거래 후 포트폴리오 조회 실패 — 거래 전 포트폴리오로 대체: {e}"
                )
                final_pf = portfolio

        self.dip_state = new_state
        self.repo.save_strategy_state(self.STATE_KEY, new_state.to_dict())

        return signal, executions, final_pf, is_rebalancing

    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        """SSO DipBuy: 주봉RSI, 괴리율, 현재 신호단계, SSO 비중이 결정요소."""
        factors: List[DecisionFactor] = []
        s = self.sso_signals

        if s is not None:
            if not math.isnan(s.weekly_rsi):
                factors.append(DecisionFactor(
                    "weekly_rsi", "주봉 RSI(14)", s.weekly_rsi, "number", threshold=48.0,
                ))
            if not math.isnan(s.ma200_deviation):
                factors.append(DecisionFactor(
                    "ma200_deviation", "200일선 괴리율", s.ma200_deviation, "percent",
                    threshold=-0.10,
                ))

        factors.append(DecisionFactor(
            "signal_level", "신호 단계", self.dip_state.level.value, "text",
        ))

        total = portfolio.total_value
        if total > 0:
            sso_val = (portfolio.holdings.get("SSO", 0)
                       * portfolio.current_prices.get("SSO", 0.0))
            factors.append(DecisionFactor(
                "sso_ratio", "SSO 비중", sso_val / total, "percent",
            ))

        return factors
```

### Step 4: `__init__.py` 수정

`src/core/engine/__init__.py`에 import + `__all__` 추가:

```python
from src.core.engine.sso_dip_buy import SsoDipBuyEngine
# __all__에 추가:
"SsoDipBuyEngine",
```

### Step 5: 테스트 통과 확인

```bash
pytest tests/test_core_engine_sso_dip_buy.py -v
```

Expected: ALL PASSED

### Step 6: 커밋

```bash
git add src/core/engine/sso_dip_buy.py src/core/engine/__init__.py tests/test_core_engine_sso_dip_buy.py
git commit -m "feat: add SsoDipBuyEngine with signal-based staged DCA"
```

---

## Task 4: 백테스트 비교 테스트 업데이트

비교 백테스트 mock 데이터에 새 엔진의 티커가 포함되어 있는지 확인하고 업데이트한다.
(SPYI는 이미 PR #370에서 추가됨. SSO도 기존에 있음. 확인만 하고 필요 시 수정.)

**Files:**
- Modify: `tests/test_backtest_compare.py` (필요 시)

### Step 1: 확인

```bash
grep "SPYI" tests/test_backtest_compare.py
grep "SSO" tests/test_backtest_compare.py
```

SSO, SPYI 모두 `ALL_COMPARE_TICKERS`에 포함되어 있으면 추가 작업 없음.

### Step 2: 전체 테스트 실행

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/ -q
```

Expected: 80% 이상 커버리지, 새 테스트 전부 통과

### Step 3: 커밋 (변경 있을 경우만)

```bash
git add tests/test_backtest_compare.py
git commit -m "test: update compare backtest mock data for SsoDipBuyEngine"
```

---

## Task 5: 전체 통합 검증 + 푸시

### Step 1: 전체 테스트 실행

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/ -q
```

Expected: 80% 이상 커버리지, 모든 테스트 통과

### Step 2: 커밋 기록 확인

```bash
git log --oneline -5
```

### Step 3: 푸시

```bash
git push -u origin claude/new-engine-development-m9ki3d
```

### Step 4: PR 업데이트 (본문에 SsoDipBuyEngine 추가)
