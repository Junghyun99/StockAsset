# 오즐웅줍(눌림목 분할매수) 알고리즘 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** QLD 단일 종목 대상으로 이동평균선 눌림목·과매도 트리거 시 현금을 분할 투입하고 과열 시 분할 매도하는 새 백테스트 엔진(`DipBuyEngine`)을 추가한다.

**Architecture:** `TradingEngine`(Template Method)을 상속하는 전용 엔진 + `core/logic`의 순수 무상태 컴포넌트(지표 계산기 + 트랜치 플래너). 트랜치 큐/무장 상태는 국면 히스테리시스와 동일하게 `IRepository`로 영속화하여 백테스트=라이브 단일 코드 경로를 유지한다.

**Tech Stack:** Python 3.10, pandas/numpy, pytest. 설계 문서: `docs/plans/2026-06-27-dip-buy-algorithm-design.md`

---

## 공통 규칙

- TDD: 실패 테스트 → 최소 구현 → 통과 → 커밋. (@superpowers:test-driven-development)
- 테스트 실행: `pytest tests/<파일> -v`
- 전체 검증: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/`
- 한글 주석 허용. 클래스 PascalCase, 함수 snake_case.
- 커밋 메시지 말미에 Co-Authored-By / Claude-Session 트레일러는 실제 커밋 시 자동 부여(여기 예시에선 생략).
- **코드 편집 전 반드시 대상 파일을 Read** (CLAUDE.md 규칙).

---

### Task 1: DipBuySignals + DipBuyIndicatorCalculator (지표)

**Files:**
- Create: `src/core/logic/dip_buy_indicators.py`
- Test: `tests/test_core_logic_dip_buy.py`

**Step 1: 실패 테스트 작성** — `tests/test_core_logic_dip_buy.py`

```python
import math
import numpy as np
import pandas as pd
import pytest

from src.core.logic.dip_buy_indicators import DipBuySignals, DipBuyIndicatorCalculator


def _df(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes,
        "Close": closes, "Volume": [1] * len(closes),
    }, index=idx)


def test_moving_averages_computed():
    closes = list(range(1, 201))  # 1..200 선형 증가
    sig = DipBuyIndicatorCalculator().calculate(_df(closes))
    assert sig.price == 200.0
    # 마지막 20개 평균 = (181+200)/2 = 190.5
    assert sig.ma20 == pytest.approx(190.5)
    assert sig.ma60 == pytest.approx((141 + 200) / 2)
    assert sig.ma120 == pytest.approx((81 + 200) / 2)
    assert sig.date == "2024-07-18"


def test_rsi_all_gains_is_100():
    closes = list(range(1, 201))  # 매일 상승 → RSI 100
    sig = DipBuyIndicatorCalculator().calculate(_df(closes))
    assert sig.rsi == pytest.approx(100.0)


def test_insufficient_data_yields_nan():
    sig = DipBuyIndicatorCalculator().calculate(_df(list(range(1, 50))))
    assert math.isnan(sig.ma120)
```

**Step 2: 실패 확인**

Run: `pytest tests/test_core_logic_dip_buy.py -v`
Expected: FAIL (ModuleNotFoundError: dip_buy_indicators)

**Step 3: 최소 구현** — `src/core/logic/dip_buy_indicators.py`

```python
# src/core/logic/dip_buy_indicators.py
from dataclasses import dataclass
import numpy as np
import pandas as pd

RSI_PERIOD = 14


@dataclass(frozen=True)
class DipBuySignals:
    """오늘의 눌림목 지표 스냅샷 (단일 종목 기준)."""
    date: str
    price: float
    ma20: float
    ma60: float
    ma120: float
    rsi: float


class DipBuyIndicatorCalculator:
    """OHLCV에서 MA20/60/120, RSI(14)를 계산한다 (순수 로직)."""

    def calculate(self, df: pd.DataFrame) -> DipBuySignals:
        df = df.copy().ffill().bfill()
        if isinstance(df.columns, pd.MultiIndex):
            close = df.xs("Close", axis=1, level=0).iloc[:, 0]
        else:
            close = df["Close"]

        date = close.index[-1].strftime("%Y-%m-%d")
        price = float(close.iloc[-1])

        def ma(window: int) -> float:
            if len(close) < window:
                return float("nan")
            return float(close.rolling(window=window).mean().iloc[-1])

        return DipBuySignals(
            date=date,
            price=price,
            ma20=ma(20),
            ma60=ma(60),
            ma120=ma(120),
            rsi=self._rsi(close),
        )

    @staticmethod
    def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> float:
        if len(close) <= period:
            return float("nan")
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        # Wilder smoothing (EMA, alpha=1/period)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))
```

**Step 4: 통과 확인**

Run: `pytest tests/test_core_logic_dip_buy.py -v`
Expected: PASS (3 tests)

**Step 5: 커밋**

```bash
git add src/core/logic/dip_buy_indicators.py tests/test_core_logic_dip_buy.py
git commit -m "feat: DipBuyIndicatorCalculator (MA20/60/120, RSI14)"
```

---

### Task 2: Tranche + DipBuyState (직렬화 가능 상태)

**Files:**
- Create: `src/core/logic/dip_buy_planner.py` (이 태스크에서는 상태 dataclass만)
- Test: `tests/test_core_logic_dip_buy.py` (추가)

**Step 1: 실패 테스트 추가**

```python
from src.core.logic.dip_buy_planner import Tranche, DipBuyState


def test_state_roundtrip_serialization():
    state = DipBuyState(
        queue=[Tranche(side="BUY", per_day_amount=100.0, remaining_days=4)],
        armed={"ma20": False, "ma60": True, "ma120": True, "dip": True, "sell": True},
    )
    restored = DipBuyState.from_dict(state.to_dict())
    assert restored == state


def test_state_from_empty_dict_defaults():
    state = DipBuyState.from_dict({})
    assert state.queue == []
    assert state.armed == {"ma20": True, "ma60": True, "ma120": True, "dip": True, "sell": True}
```

**Step 2: 실패 확인**

Run: `pytest tests/test_core_logic_dip_buy.py -k state -v`
Expected: FAIL (ImportError)

**Step 3: 최소 구현** — `src/core/logic/dip_buy_planner.py`

```python
# src/core/logic/dip_buy_planner.py
from dataclasses import dataclass, field, asdict
from typing import Dict, List

TRIGGERS = ("ma20", "ma60", "ma120", "dip", "sell")


@dataclass
class Tranche:
    """분할 트랜치: 트리거 시점에 고정된 1일 슬라이스 금액과 남은 일수."""
    side: str            # "BUY" | "SELL"
    per_day_amount: float
    remaining_days: int


@dataclass
class DipBuyState:
    """플래너의 영속 상태 (큐 + 트리거 무장 플래그)."""
    queue: List[Tranche] = field(default_factory=list)
    armed: Dict[str, bool] = field(default_factory=lambda: {t: True for t in TRIGGERS})

    def to_dict(self) -> dict:
        return {
            "queue": [asdict(t) for t in self.queue],
            "armed": dict(self.armed),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DipBuyState":
        data = data or {}
        queue = [Tranche(**t) for t in data.get("queue", [])]
        armed = {t: True for t in TRIGGERS}
        armed.update(data.get("armed", {}))
        return cls(queue=queue, armed=armed)
```

**Step 4: 통과 확인**

Run: `pytest tests/test_core_logic_dip_buy.py -k state -v`
Expected: PASS

**Step 5: 커밋**

```bash
git add src/core/logic/dip_buy_planner.py tests/test_core_logic_dip_buy.py
git commit -m "feat: DipBuyState/Tranche 직렬화 가능 상태"
```

---

### Task 3: DipBuyPlanner — 트리거 평가 & 무장/재무장

**Files:**
- Modify: `src/core/logic/dip_buy_planner.py`
- Test: `tests/test_core_logic_dip_buy.py` (추가)

설계 트리거(밴드 0.02):
- ma20 밴드 진입 → BUY 현금×0.10, 1일
- ma60 밴드 진입 → BUY 현금×0.50, 5일
- ma120 밴드 진입 → BUY 현금×0.50, 5일
- price < ma120 & rsi < 30 → BUY 현금×1.00, 40일
- rsi > 70 → SELL (목표 현금비중 0.20까지 부족분), 5일
무장: 조건 성립 & armed → 적재 후 disarm. 조건 불성립 → re-arm.

**Step 1: 실패 테스트 추가** — `Portfolio` 사용

```python
from src.core.models import Portfolio
from src.core.logic.dip_buy_planner import DipBuyPlanner


def _signals(price, ma20, ma60, ma120, rsi):
    from src.core.logic.dip_buy_indicators import DipBuySignals
    return DipBuySignals("2024-01-01", price, ma20, ma60, ma120, rsi)


def _pf(cash, qld=0, price=100.0):
    return Portfolio(total_cash=cash, holdings={"QLD": qld}, current_prices={"QLD": price})


def test_ma20_touch_enqueues_10pct_one_day():
    planner = DipBuyPlanner(ticker="QLD")
    # price가 ma20의 +1% (밴드 ±2% 안), 다른 선은 멀리
    sig = _signals(price=101.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    _, _, state = planner.plan(sig, _pf(cash=1000.0), DipBuyState())
    assert len(state.queue) == 1
    t = state.queue[0]
    assert t.side == "BUY" and t.remaining_days == 1
    assert t.per_day_amount == pytest.approx(100.0)  # 1000*0.10/1
    assert state.armed["ma20"] is False


def test_ma60_band_enqueues_50pct_over_5_days():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=100.0, ma20=130.0, ma60=100.0, ma120=70.0, rsi=50.0)
    _, _, state = planner.plan(sig, _pf(cash=1000.0), DipBuyState())
    t = [x for x in state.queue if x.remaining_days == 5][0]
    assert t.per_day_amount == pytest.approx(100.0)  # 1000*0.50/5


def test_dip_below_ma120_and_rsi_under_30_enqueues_100pct_40_days():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=60.0, ma20=130.0, ma60=110.0, ma120=70.0, rsi=25.0)
    _, _, state = planner.plan(sig, _pf(cash=4000.0), DipBuyState())
    dip = [x for x in state.queue if x.remaining_days == 40][0]
    assert dip.per_day_amount == pytest.approx(100.0)  # 4000*1.0/40


def test_trigger_does_not_refire_while_armed_false():
    planner = DipBuyPlanner(ticker="QLD")
    sig = _signals(price=101.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    _, _, state = planner.plan(sig, _pf(cash=1000.0), DipBuyState())
    n_after_first = len([t for t in state.queue if t.remaining_days == 1])
    # 같은 신호 재투입 → 새 트랜치 적재되면 안 됨 (이미 큐의 1일 트랜치는 소진됨)
    _, _, state2 = planner.plan(sig, _pf(cash=900.0), state)
    new_ma20 = [t for t in state2.queue if t.remaining_days == 1]
    assert new_ma20 == []  # 재발동 없음
    assert state2.armed["ma20"] is False


def test_rearm_when_condition_clears():
    planner = DipBuyPlanner(ticker="QLD")
    sig_in = _signals(price=101.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    _, _, state = planner.plan(sig_in, _pf(cash=1000.0), DipBuyState())
    # 밴드 이탈 (price가 ma20 대비 +10%)
    sig_out = _signals(price=110.0, ma20=100.0, ma60=80.0, ma120=70.0, rsi=50.0)
    _, _, state2 = planner.plan(sig_out, _pf(cash=900.0), state)
    assert state2.armed["ma20"] is True
```

**Step 2: 실패 확인**

Run: `pytest tests/test_core_logic_dip_buy.py -k "ma20 or ma60 or dip_below or refire or rearm" -v`
Expected: FAIL (DipBuyPlanner 없음)

**Step 3: 구현 추가** — `dip_buy_planner.py`에 추가

```python
import math
from src.core.models import Portfolio, Order, OrderAction


class DipBuyPlanner:
    """눌림목 트리거 → 트랜치 적재 → 당일 슬라이스 주문 (순수, 무상태).

    상태(DipBuyState)는 호출자가 보관·영속화한다.
    """

    def __init__(self, ticker: str, band: float = 0.02,
                 sell_target_cash_ratio: float = 0.20):
        self.ticker = ticker
        self.band = band
        self.sell_target_cash_ratio = sell_target_cash_ratio

    def plan(self, signals, portfolio: Portfolio, state: "DipBuyState"):
        armed = dict(state.armed)
        queue = list(state.queue)

        triggers = self._evaluate_conditions(signals, portfolio)
        # 적재 + 무장/재무장
        for key, active, make_tranche in triggers:
            if active and armed.get(key, True):
                tranche = make_tranche()
                if tranche is not None:
                    queue.append(tranche)
                armed[key] = False
            elif not active:
                armed[key] = True

        new_state = DipBuyState(queue=queue, armed=armed)
        return [], "", new_state  # 주문 생성은 Task 4에서

    def _in_band(self, price: float, ma: float) -> bool:
        if ma is None or ma <= 0 or math.isnan(ma):
            return False
        return abs(price / ma - 1.0) <= self.band

    def _evaluate_conditions(self, sig, pf: Portfolio):
        cash = pf.total_cash
        rsi_ok = not math.isnan(sig.rsi)

        def buy(ratio, days):
            return lambda: Tranche("BUY", (cash * ratio) / days, days) if cash > 0 else None

        ma120_valid = not math.isnan(sig.ma120) and sig.ma120 > 0
        dip_active = ma120_valid and sig.price < sig.ma120 and rsi_ok and sig.rsi < 30
        sell_active = rsi_ok and sig.rsi > 70

        return [
            ("ma20", self._in_band(sig.price, sig.ma20), buy(0.10, 1)),
            ("ma60", self._in_band(sig.price, sig.ma60), buy(0.50, 5)),
            ("ma120", self._in_band(sig.price, sig.ma120), buy(0.50, 5)),
            ("dip", dip_active, buy(1.00, 40)),
            ("sell", sell_active, self._make_sell_tranche(sig, pf)),
        ]

    def _make_sell_tranche(self, sig, pf: Portfolio):
        def factory():
            price = pf.current_prices.get(self.ticker, 0.0)
            holdings_val = pf.holdings.get(self.ticker, 0) * price
            total = pf.total_cash + holdings_val
            if total <= 0 or holdings_val <= 0:
                return None
            target_cash = total * self.sell_target_cash_ratio
            shortfall = target_cash - pf.total_cash
            if shortfall <= 0:
                return None
            sell_amt = min(shortfall, holdings_val)
            return Tranche("SELL", sell_amt / 5, 5)
        return factory
```

**Step 4: 통과 확인**

Run: `pytest tests/test_core_logic_dip_buy.py -v`
Expected: PASS

**Step 5: 커밋**

```bash
git add src/core/logic/dip_buy_planner.py tests/test_core_logic_dip_buy.py
git commit -m "feat: DipBuyPlanner 트리거 평가 + 무장/재무장"
```

---

### Task 4: DipBuyPlanner — 당일 슬라이스 소진 & 주문 생성

**Files:**
- Modify: `src/core/logic/dip_buy_planner.py` (`plan` 완성)
- Test: `tests/test_core_logic_dip_buy.py` (추가)

**Step 1: 실패 테스트 추가**

```python
def test_daily_slice_generates_buy_order_and_decrements():
    planner = DipBuyPlanner(ticker="QLD")
    # 이미 5일 분할 BUY 트랜치 1개 (per_day 100), price 50 → 2주
    state = DipBuyState(queue=[Tranche("BUY", 100.0, 5)],
                        armed={t: False for t in ("ma20", "ma60", "ma120", "dip", "sell")})
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)  # 트리거 없음(밴드 안이지만 armed False)
    orders, reason, new_state = planner.plan(sig, _pf(cash=1000.0, price=50.0), state)
    buys = [o for o in orders if o.action == OrderAction.BUY]
    assert buys and buys[0].quantity == 2  # floor(100/50)
    assert new_state.queue[0].remaining_days == 4


def test_tranche_removed_when_days_exhausted():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("BUY", 100.0, 1)],
                        armed={t: False for t in ("ma20", "ma60", "ma120", "dip", "sell")})
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)
    _, _, new_state = planner.plan(sig, _pf(cash=1000.0, price=50.0), state)
    assert new_state.queue == []


def test_buy_capped_by_available_cash():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("BUY", 100000.0, 5)],
                        armed={t: False for t in ("ma20", "ma60", "ma120", "dip", "sell")})
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)
    orders, _, _ = planner.plan(sig, _pf(cash=300.0, price=100.0), state)
    buys = [o for o in orders if o.action == OrderAction.BUY]
    assert buys[0].quantity == 3  # floor(min(100000,300)/100)


def test_sell_order_limited_by_holdings():
    planner = DipBuyPlanner(ticker="QLD")
    state = DipBuyState(queue=[Tranche("SELL", 1000.0, 5)],
                        armed={t: False for t in ("ma20", "ma60", "ma120", "dip", "sell")})
    sig = _signals(price=200.0, ma20=200.0, ma60=200.0, ma120=200.0, rsi=50.0)
    orders, _, _ = planner.plan(sig, _pf(cash=0.0, qld=2, price=100.0), state)
    sells = [o for o in orders if o.action == OrderAction.SELL]
    assert sells[0].quantity == 2  # min(ceil(1000/100)=10, 보유 2)
```

**Step 2: 실패 확인**

Run: `pytest tests/test_core_logic_dip_buy.py -k "slice or exhausted or capped or holdings" -v`
Expected: FAIL (plan이 빈 주문 반환)

**Step 3: `plan` 완성** — `return [], "", new_state` 부분을 아래로 교체

```python
        # 당일 슬라이스 합산
        buy_amount = sum(t.per_day_amount for t in queue if t.side == "BUY")
        sell_amount = sum(t.per_day_amount for t in queue if t.side == "SELL")

        # 트랜치 소진
        next_queue = []
        for t in queue:
            t.remaining_days -= 1
            if t.remaining_days > 0:
                next_queue.append(t)
        new_state = DipBuyState(queue=next_queue, armed=armed)

        price = portfolio.current_prices.get(self.ticker, 0.0)
        orders = []
        reasons = []
        if price > 0 and buy_amount > 0:
            capped = min(buy_amount, portfolio.total_cash)
            qty = math.floor(capped / price)
            if qty > 0:
                orders.append(Order(self.ticker, OrderAction.BUY, qty, price))
                reasons.append(f"분할매수 {qty}주")
        if price > 0 and sell_amount > 0:
            held = portfolio.holdings.get(self.ticker, 0)
            qty = min(math.ceil(sell_amount / price), held)
            if qty > 0:
                orders.append(Order(self.ticker, OrderAction.SELL, qty, price))
                reasons.append(f"분할매도 {qty}주")

        reason = " / ".join(reasons) if reasons else "대기(트리거 없음)"
        return orders, reason, new_state
```

> 주의: 매도 우선 실행을 위해 엔진은 기존 정렬 로직을 쓰지 않으므로, 여기서
> SELL을 BUY보다 먼저 리스트에 넣는 것이 안전하다. 위 코드는 BUY를 먼저 넣으므로
> **순서를 SELL → BUY로 바꿔** 배치할 것(테스트는 순서 무관이나 실거래 안전).

**Step 4: 통과 확인**

Run: `pytest tests/test_core_logic_dip_buy.py -v`
Expected: PASS (모든 플래너 테스트)

**Step 5: 커밋**

```bash
git add src/core/logic/dip_buy_planner.py tests/test_core_logic_dip_buy.py
git commit -m "feat: DipBuyPlanner 당일 슬라이스 소진 및 주문 생성"
```

---

### Task 5: logic 패키지 export

**Files:**
- Modify: `src/core/logic/__init__.py`

**Step 1: 구현**

`src/core/logic/__init__.py`에 추가:

```python
from src.core.logic.dip_buy_indicators import DipBuySignals, DipBuyIndicatorCalculator
from src.core.logic.dip_buy_planner import Tranche, DipBuyState, DipBuyPlanner
```

`__all__`에 `"DipBuySignals", "DipBuyIndicatorCalculator", "Tranche", "DipBuyState", "DipBuyPlanner"` 추가.

**Step 2: 검증**

Run: `python -c "from src.core.logic import DipBuyPlanner, DipBuyState, DipBuyIndicatorCalculator; print('ok')"`
Expected: `ok`

**Step 3: 커밋**

```bash
git add src/core/logic/__init__.py
git commit -m "chore: dip-buy 컴포넌트 logic 패키지 export"
```

---

### Task 6: IRepository 상태 저장 포트 + JsonRepository 구현

**Files:**
- Modify: `src/core/interfaces.py` (IRepository에 기본 메서드 추가)
- Modify: `src/infra/repo.py`
- Test: `tests/test_infra_repo.py` (추가)

**Step 1: 실패 테스트 추가** — `tests/test_infra_repo.py`

```python
def test_strategy_state_roundtrip(tmp_path):
    from src.infra.repo import JsonRepository
    repo = JsonRepository(str(tmp_path))
    assert repo.load_strategy_state("dip_buy") == {}
    repo.save_strategy_state("dip_buy", {"queue": [], "armed": {"ma20": False}})
    assert repo.load_strategy_state("dip_buy") == {"queue": [], "armed": {"ma20": False}}
    # 다른 key는 영향 없음
    assert repo.load_strategy_state("other") == {}
```

**Step 2: 실패 확인**

Run: `pytest tests/test_infra_repo.py -k strategy_state -v`
Expected: FAIL (메서드 없음)

**Step 3: 구현**

`src/core/interfaces.py`의 `IRepository`에 (추상 아님, 안전한 기본 — ILogger 캡처 패턴):

```python
    # ── 전략 상태 영속화 (선택적, 기본 안전 degrade) ──────────────
    def load_strategy_state(self, key: str) -> dict:
        """저장된 전략 상태를 반환한다 (기본: 빈 dict)."""
        return {}

    def save_strategy_state(self, key: str, state: dict) -> None:
        """전략 상태를 저장한다 (기본 no-op)."""
        return None
```

`src/infra/repo.py`의 `JsonRepository`에:

```python
    def load_strategy_state(self, key: str) -> dict:
        data = self._load_json(self._strategy_state_file, default={})
        return data.get(key, {})

    def save_strategy_state(self, key: str, state: dict) -> None:
        data = self._load_json(self._strategy_state_file, default={})
        data[key] = state
        self._save_json(self._strategy_state_file, data)
```

`__init__`에 파일 경로 추가:

```python
        self._strategy_state_file = os.path.join(self.root, "strategy_state.json")
```

**Step 4: 통과 확인**

Run: `pytest tests/test_infra_repo.py -k strategy_state -v`
Expected: PASS

**Step 5: 커밋**

```bash
git add src/core/interfaces.py src/infra/repo.py tests/test_infra_repo.py
git commit -m "feat: IRepository 전략 상태 영속화 포트 + JsonRepository 구현"
```

---

### Task 7: DipBuyEngine

**Files:**
- Create: `src/core/engine/dip_buy.py`
- Modify: `src/core/engine/__init__.py`
- Test: `tests/test_core_engine_dip_buy.py`

**Step 1: 실패 테스트 작성** — `tests/test_core_engine_dip_buy.py`

```python
import numpy as np
import pandas as pd
import pytest

from src.core.engine.dip_buy import DipBuyEngine
from src.core.models import Order, OrderAction
from src.infra.broker import MockBroker
from src.infra.repo import JsonRepository
from src.utils.logger import TradeLogger


class _Loader:
    def __init__(self, df, vix=20.0):
        self.df, self._vix = df, vix
    def fetch_ohlcv(self, tickers, days=365):
        return self.df.tail(days)
    def fetch_vix(self):
        return self._vix


def _ramp_then_dip(n=300):
    # 상승 후 급락 → 마지막 종가가 MA20 부근
    up = np.linspace(50, 150, n - 20)
    down = np.linspace(150, 120, 20)
    closes = np.concatenate([up, down])
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [1]*n}, index=idx)


def _make_engine(tmp_path):
    repo = JsonRepository(str(tmp_path), asset_groups={"A": ["QLD"]})
    broker = MockBroker(initial_cash=10000.0)
    logger = TradeLogger(log_dir=str(tmp_path / "logs"))
    return DipBuyEngine(broker=broker, repo=repo, logger=logger,
                        asset_groups={"A": ["QLD"]}, trading_interval_days=1), broker, repo


def test_engine_registered():
    from src.core.engine import _ENGINE_REGISTRY
    names = [n for n, _ in _ENGINE_REGISTRY]
    assert "DipBuyEngine" in names


def test_cycle_runs_and_persists_state(tmp_path):
    engine, broker, repo = _make_engine(tmp_path)
    df = _ramp_then_dip()
    broker.set_prices = getattr(broker, "set_prices", lambda *_: None)
    result = engine.run_one_cycle(_Loader(df), sim_date="2023-10-27")
    # 상태가 strategy_state.json에 저장됨
    saved = repo.load_strategy_state("dip_buy")
    assert "queue" in saved and "armed" in saved
    assert result.signal is not None


def test_state_survives_engine_recreation(tmp_path):
    df = _ramp_then_dip()
    engine, broker, repo = _make_engine(tmp_path)
    engine.run_one_cycle(_Loader(df), sim_date="2023-10-27")
    saved_before = repo.load_strategy_state("dip_buy")
    # 새 엔진 인스턴스(라이브 재시작 모사) → 상태 복원
    engine2 = DipBuyEngine(broker=broker, repo=repo, logger=TradeLogger(log_dir=str(tmp_path/"l2")),
                           asset_groups={"A": ["QLD"]}, trading_interval_days=1)
    assert engine2.dip_state.to_dict()["armed"] == saved_before["armed"]
```

> **주의:** `MockBroker`의 가격 주입 방식은 `tests/test_infra_broker.py`를 먼저 읽고
> 실제 API(`fetch_current_prices`가 무엇을 반환하는지)에 맞춰 `_Loader`/픽스처를
> 조정할 것. 엔진은 `broker.fetch_current_prices(all_tickers)`로 현재가를 얻는다.
> MockBroker가 현재가 0을 반환하면 가격 가드에 걸리므로, 테스트에서 QLD 현재가가
> 양수가 되도록 broker를 설정(또는 BacktestBroker 사용)해야 한다.

**Step 2: 실패 확인**

Run: `pytest tests/test_core_engine_dip_buy.py -v`
Expected: FAIL (DipBuyEngine 없음)

**Step 3: 구현** — `src/core/engine/dip_buy.py`

```python
# src/core/engine/dip_buy.py
"""오즐웅줍 눌림목 분할매수 엔진."""
from typing import List, Optional, Tuple

import pandas as pd

from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.dip_buy_indicators import DipBuyIndicatorCalculator
from src.core.logic.dip_buy_planner import DipBuyPlanner, DipBuyState
from src.core.models import (
    MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution, ExecutionStatus,
)


@register_engine(color="#e45756")
class DipBuyEngine(TradingEngine):
    """QLD 단일 종목 눌림목 분할매수 전략 엔진.

    이동평균선(MA20/60/120) 눌림목과 RSI 과매도/과열을 트리거로
    현금을 분할 투입/회수한다. 트랜치 큐는 strategy_state.json에 영속화된다.
    """

    ASSET_GROUPS: dict = {"A": ["QLD"]}
    BAND: float = 0.02
    SELL_TARGET_CASH_RATIO: float = 0.20
    STATE_KEY: str = "dip_buy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ticker = self.ASSET_GROUPS["A"][0]
        self._dip_calc = DipBuyIndicatorCalculator()
        self._planner = DipBuyPlanner(
            ticker=self._ticker, band=self.BAND,
            sell_target_cash_ratio=self.SELL_TARGET_CASH_RATIO,
        )
        self.dip_state = DipBuyState.from_dict(self.repo.load_strategy_state(self.STATE_KEY))
        self.dip_signals = None

    def collect_data(self, data_provider: IDataProvider) -> Tuple[pd.DataFrame, float]:
        df = data_provider.fetch_ohlcv([self._ticker], days=400)
        vix = data_provider.fetch_vix()
        return df, vix

    def calculate_indicators(self, spy_df: pd.DataFrame, vix: float) -> MarketData:
        # 대시보드/repo 호환용 MarketData (QLD 기준) + 눌림목 지표 동시 계산
        self.dip_signals = self._dip_calc.calculate(spy_df)
        return self.calculator.calculate(spy_df, vix)

    def execute_cycle(self, market_data, portfolio, regime, exposure,
                      nan_fields, sim_date, record_date):
        executions: List[TradeExecution] = []
        final_pf = portfolio
        is_rebalancing = False

        if nan_fields:
            signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}")
            return signal, executions, final_pf, is_rebalancing

        orders, reason, new_state = self._planner.plan(
            self.dip_signals, portfolio, self.dip_state
        )
        self.dip_state = new_state
        self.repo.save_strategy_state(self.STATE_KEY, new_state.to_dict())

        signal = TradeSignal(exposure, orders, reason)
        if orders:
            is_rebalancing = True
            executions = self.broker.execute_orders(orders)
            try:
                final_pf = self.broker.get_portfolio()
            except RuntimeError:
                final_pf = portfolio
        return signal, executions, final_pf, is_rebalancing
```

`src/core/engine/__init__.py`: import + `__all__`에 추가

```python
from src.core.engine.dip_buy import DipBuyEngine
```
(`regime` import 다음 줄에 추가, `__all__`에 `"DipBuyEngine"` 추가)

**Step 4: 통과 확인**

Run: `pytest tests/test_core_engine_dip_buy.py -v`
Expected: PASS (broker 가격 주입을 위 주의사항대로 맞춘 뒤)

**Step 5: 커밋**

```bash
git add src/core/engine/dip_buy.py src/core/engine/__init__.py tests/test_core_engine_dip_buy.py
git commit -m "feat: DipBuyEngine 눌림목 분할매수 엔진 등록"
```

---

### Task 8: 비교 백테스트 연기(smoke) + 전체 검증

**Files:**
- Test: `tests/test_core_engine_dip_buy.py` (백테스트 smoke 추가, 선택)

**Step 1: 백테스트 smoke 테스트(선택)** — `BacktestBroker`/`BacktestDataLoader`로
짧은 기간 `run_one_cycle` 다일 루프가 예외 없이 도는지 확인. (`tests/test_backtest_compare.py`
패턴 참고: 먼저 Read.)

**Step 2: 엔진 레지스트리/커버리지 전체 검증**

Run: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/`
Expected: PASS, 커버리지 ≥ 80%

부족 시 `dip_buy_planner.py`/`dip_buy.py`의 미커버 분기(현금 0, 보유 0, NaN
지표, 매도 트랜치 등)를 채우는 단위 테스트 추가.

**Step 3: 아키텍처 점검**

@arch-check 스킬로 core→infra 의존 방향, 백테스트 재사용, 순환 의존성 확인.

**Step 4: 커밋 & 푸시**

```bash
git add -A
git commit -m "test: dip-buy 엔진 백테스트 smoke 및 커버리지 보강"
git push -u origin claude/investment-algorithm-setup-a8a0bu
```

**Step 5: PR 생성** (ready for review)

---

## 검증 체크리스트

- [ ] `DipBuyEngine`이 `_ENGINE_REGISTRY`에 등록됨
- [ ] MA20/60/120, RSI(14) 값 정확도 테스트 통과
- [ ] 밴드 엣지 트리거(1회 발동) + 재무장 동작
- [ ] 5일/40일 분할 슬라이스 합산·소진, 트랜치 제거
- [ ] 매수 현금 캡, 매도 보유 한도
- [ ] 매도 목표 현금비중 20% 도달까지 분할
- [ ] `strategy_state.json` 저장/복원 라운드트립 (라이브 재시작 모사)
- [ ] `MarketData`/status.json 스키마 무변경
- [ ] 커버리지 ≥ 80%
- [ ] `run-compare-backtest`에서 DipBuyEngine 결과 생성(수동/후속)
