# 엔진별 결정요소(DecisionFactor) 자기서술 구조 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 각 전략 엔진이 자신의 핵심 의사결정 요소를 스스로 선언·산출하고, docs 대시보드가 엔진별 분기 없이 그 요소를 렌더링하도록 한다.

**Architecture:** `DecisionFactor` 도메인 모델(자기서술적: key/label/value/format/threshold)을 추가하고, `TradingEngine`에 Template Method 훅 `decision_factors()`를 만들어 서브클래스가 오버라이드한다. `persist()`가 훅 결과를 `JsonRepository`에 넘겨 `status.json`(표시용 전체)과 `summary.json`(시계열용 key:value)에 직렬화한다. 프론트(`ui.js`)는 `decision_factors` 배열을 generic 렌더링하고, 배열이 없는 구버전 status.json은 기존 국면 표시로 폴백한다. repo/프론트는 전략 지식을 갖지 않는다.

**Tech Stack:** Python 3.10 (dataclass), pytest + unittest.mock, vanilla JS (ESM), Bootstrap 5.

**결정요소 소유 매트릭스 (구현 대상):**

| 엔진 | 훅 구현 위치 | 핵심 요소 |
|---|---|---|
| `TradingEngine` (기본) | `base.py` (기본 구현) | 국면, 모멘텀, VIX, MDD, 실현변동성 |
| `FullExposureEngine` + 설정 서브클래스 전부 | `base.py` (오버라이드) | 목표 A비율, 현재 A비율, 상대이탈 vs 임계치 |
| `QldSdyShvEngine`/`QldQqqShvRegimeEngine` | 없음 — 기본 구현 사용 | 국면이 실제 핵심 결정요소 (기본이 정확) |
| `VolManagedEngine` | `volmanaged.py` | 실현변동성 vs 목표, 실효 레버리지, 현금비중 |
| `VolTargetLeverageEngine` | `voltarget.py` | 실현변동성 vs 목표, 실효 레버리지, QLD비중 |
| `DipBuyEngine`(+Gated) | `dip_buy.py` | MA20/60/120 이격, RSI, 무장 트리거 수 |

**주의사항:**
- persist는 NaN 사이클에서 스킵되므로 훅은 정상 데이터 전제로 작성해도 되지만, 방어적으로 NaN 값을 걸러낸다 (`_save_json`의 sanitize가 NaN→null 최종 방어).
- `TradeSignal.target_ratio_a`/`rebalance_threshold`는 유지 (기존 이격도 시계열 소비자 존재). 흡수/deprecate는 후속 작업.
- summary.json의 기존 `spy_*`/`regime` 필드는 비교 차트가 사용하므로 유지.
- JS/CSS 수정 시 CLAUDE.md 규칙대로 참조하는 모든 곳의 `?v=`를 `20260714-1`로 갱신 (ESM이므로 `main.js` 내 `ui.js` import 문자열 포함).

---

### Task 1: `DecisionFactor` 도메인 모델

**Files:**
- Modify: `src/core/models.py` (파일 끝에 추가)
- Test: `tests/test_core_models.py`

**Step 1: Write the failing test** — `tests/test_core_models.py`에 추가:

```python
class TestDecisionFactor(unittest.TestCase):
    def test_기본값(self):
        f = DecisionFactor(key="vix", label="VIX", value=17.2)
        self.assertEqual(f.format, "number")
        self.assertIsNone(f.threshold)

    def test_직렬화(self):
        f = DecisionFactor(key="mdd", label="SPY MDD", value=-0.07,
                           format="percent", threshold=-0.20)
        d = asdict(f)
        self.assertEqual(d, {"key": "mdd", "label": "SPY MDD", "value": -0.07,
                             "format": "percent", "threshold": -0.20})

    def test_텍스트_값(self):
        f = DecisionFactor(key="regime", label="시장 국면", value="Bull", format="text")
        self.assertEqual(f.value, "Bull")
```

(테스트 파일 기존 import 스타일 확인 후 `from dataclasses import asdict`, `DecisionFactor` import 추가)

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_models.py -v -k DecisionFactor`
Expected: FAIL (ImportError: cannot import name 'DecisionFactor')

**Step 3: Write minimal implementation** — `src/core/models.py` (`DayResult` 앞이나 뒤에 추가):

```python
@dataclass(frozen=True)
class DecisionFactor:
    """엔진의 의사결정 핵심 요소 한 항목 (자기서술적 — 프론트가 그대로 렌더링).

    key: 안정적 식별자 (summary 시계열 키로도 사용)
    label: 표시명
    value: 요소 값 (수치 또는 텍스트)
    format: "number" | "percent" | "text" — 프론트 표시 형식
    threshold: 판단 기준값 (있으면 프론트가 기준 대비 강조 표시)
    """
    key: str
    label: str
    value: float | str
    format: str = "number"
    threshold: Optional[float] = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_core_models.py -v`
Expected: PASS (전체)

**Step 5: Commit**

```bash
git add src/core/models.py tests/test_core_models.py
git commit -m "feat: DecisionFactor 도메인 모델 추가"
```

---

### Task 2: JsonRepository 직렬화 (status.json + summary.json)

**Files:**
- Modify: `src/infra/repo.py:62-119` (`save_daily_summary`), `:154-206` (`update_status`)
- Modify: `src/core/interfaces.py:74-91` (`IRepository` 시그니처)
- Test: `tests/test_infra_repo.py`

**Step 1: Write the failing tests** — `tests/test_infra_repo.py`에 추가 (기존 fixture 스타일 재사용):

```python
def test_update_status_decision_factors_저장(self):
    factors = [DecisionFactor("vix", "VIX", 17.2, "number", threshold=30.0),
               DecisionFactor("regime", "시장 국면", "Bull", "text")]
    self.repo.update_status(MarketRegime.BULL, 0.9, self.pf, self.market, "이유",
                            decision_factors=factors)
    with open(self.repo.status_file) as f:
        status = json.load(f)
    saved = status["strategy"]["decision_factors"]
    self.assertEqual(len(saved), 2)
    self.assertEqual(saved[0], {"key": "vix", "label": "VIX", "value": 17.2,
                                "format": "number", "threshold": 30.0})

def test_update_status_decision_factors_미전달시_빈배열(self):
    self.repo.update_status(MarketRegime.BULL, 0.9, self.pf, self.market, "이유")
    with open(self.repo.status_file) as f:
        status = json.load(f)
    self.assertEqual(status["strategy"]["decision_factors"], [])

def test_save_daily_summary_factors_시계열(self):
    factors = [DecisionFactor("group_deviation", "A그룹 상대이탈", 0.03, "percent", 0.075)]
    self.repo.save_daily_summary(self.market, self.signal, self.pf, MarketRegime.BULL,
                                 decision_factors=factors)
    with open(self.repo.summary_file) as f:
        data = json.load(f)
    self.assertEqual(data[-1]["factors"], {"group_deviation": 0.03})

def test_save_daily_summary_factors_NaN은_null로(self):
    factors = [DecisionFactor("x", "X", float("nan"), "number")]
    self.repo.save_daily_summary(self.market, self.signal, self.pf, MarketRegime.BULL,
                                 decision_factors=factors)
    with open(self.repo.summary_file) as f:
        data = json.load(f)
    self.assertIsNone(data[-1]["factors"]["x"])
```

**Step 2: Run** `pytest tests/test_infra_repo.py -v -k decision or factors` → FAIL (unexpected keyword argument)

**Step 3: Implementation**

`src/core/interfaces.py` — import에 `DecisionFactor` 추가, 두 추상 메서드에 옵셔널 파라미터:

```python
    def save_daily_summary(self, market_data: MarketData, signal: TradeSignal,
                           portfolio: Portfolio, regime: MarketRegime,
                           daily_dividend: float = 0.0,
                           date_override: Optional[str] = None,
                           decision_factors: Optional[List[DecisionFactor]] = None) -> None: ...
    ...
    def update_status(self, regime: MarketRegime, exposure: float, portfolio: Portfolio,
                      market_data: MarketData, reason: str,
                      sim_date: Optional[str] = None,
                      rebalancing_date: Optional[str] = None,
                      decision_factors: Optional[List[DecisionFactor]] = None) -> None: ...
```

(참고: `save_daily_summary`의 추상 시그니처엔 `benchmarks`가 빠져있는 기존 불일치가 있음 — 이번엔 `decision_factors`만 추가하고 그대로 둔다)

`src/infra/repo.py`:
- `save_daily_summary(..., benchmarks=None, decision_factors=None)`: record에 추가
  ```python
  # [결정요소 시계열] 엔진이 선언한 key:value 축약본 (라벨/포맷은 status.json에만)
  "factors": {f.key: f.value for f in (decision_factors or [])},
  ```
- `update_status(..., rebalancing_date=None, decision_factors=None)`: `status["strategy"]`에 추가
  ```python
  "decision_factors": [asdict(f) for f in (decision_factors or [])],
  ```

**Step 4: Run** `pytest tests/test_infra_repo.py -v` → PASS

**Step 5: Commit** `git commit -m "feat: repo에 decision_factors 직렬화 추가 (status/summary)"`

---

### Task 3: TradingEngine 기본 훅 + persist 연결

**Files:**
- Modify: `src/core/engine/base.py` (import, `persist()`, 새 메서드 `decision_factors()`)
- Test: `tests/test_core_engine.py`

**Step 1: Write the failing tests** — `tests/test_core_engine.py`에 추가 (기존 엔진 fixture 재사용):

```python
def test_기본_결정요소는_국면_중심(self):
    factors = self.engine.decision_factors(self.market_data, MarketRegime.BULL, 0.9,
                                           self.signal, self.portfolio)
    keys = [f.key for f in factors]
    self.assertEqual(keys[0], "regime")           # 대표 요소 = 국면
    self.assertIn("momentum", keys)
    self.assertIn("vix", keys)
    self.assertIn("mdd", keys)
    self.assertIn("volatility", keys)
    regime_f = factors[0]
    self.assertEqual(regime_f.value, "Bull")
    self.assertEqual(regime_f.format, "text")

def test_persist가_결정요소를_repo에_전달(self):
    # run_one_cycle 통합 경로: mock repo의 update_status/save_daily_summary가
    # decision_factors 키워드를 받는지 검증
    self.engine.run_one_cycle(self.data_provider, sim_date="2026-07-14")
    _, kwargs = self.mock_repo.update_status.call_args
    factors = kwargs["decision_factors"]
    self.assertTrue(factors and factors[0].key == "regime")
    _, kwargs = self.mock_repo.save_daily_summary.call_args
    self.assertEqual(kwargs["decision_factors"], factors)
```

(mock repo가 MagicMock이 아닌 자체 Fake라면 시그니처에 `decision_factors=None` 추가)

**Step 2: Run** `pytest tests/test_core_engine.py -v -k 결정요소` → FAIL (AttributeError: decision_factors)

**Step 3: Implementation** — `src/core/engine/base.py`:

import에 `DecisionFactor` 추가. `persist()` 본문 수정:

```python
        effective_record_date = record_date or sim_date or market_data.date
        rebalancing_date = effective_record_date if is_rebalancing else None
        factors = self.decision_factors(market_data, regime, exposure, signal, final_pf)
        self.repo.save_daily_summary(market_data, signal, final_pf, regime,
                                     daily_dividend=daily_dividend, date_override=record_date,
                                     benchmarks=benchmark_prices,
                                     decision_factors=factors)
        self.repo.save_trade_history(executions, final_pf, signal.reason, sim_date=sim_date)
        self.repo.update_status(
            regime, exposure, final_pf, market_data, signal.reason,
            sim_date=sim_date,
            rebalancing_date=rebalancing_date,
            decision_factors=factors,
        )
```

새 메서드 (Overridable step methods 섹션, `analyze_strategy` 아래):

```python
    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        """이 엔진의 의사결정 핵심 요소 목록 (Step 6에서 저장, 대시보드 표시용).

        첫 항목이 대시보드 카드의 대표(헤드라인) 요소가 된다.
        기본 전략은 국면 판단이 핵심이므로 국면 관련 지표를 반환하며,
        서브클래스는 자기 전략의 실제 결정요소로 오버라이드한다.
        """
        return [
            DecisionFactor("regime", "시장 국면", regime.value, "text"),
            DecisionFactor("momentum", "SPY 모멘텀", market_data.spy_momentum, "percent"),
            DecisionFactor("vix", "VIX", market_data.vix, "number", threshold=30.0),
            DecisionFactor("mdd", "SPY MDD", market_data.spy_mdd, "percent", threshold=-0.20),
            DecisionFactor("volatility", "실현변동성(21d)", market_data.spy_volatility,
                           "percent", threshold=self.targeter.target_vol),
        ]
```

**Step 4: Run** `pytest tests/test_core_engine.py -v` → PASS. 이어서 `pytest tests/ -x -q --ignore=tests/test_infra_broker_kis_domestic_live.py -k "not _live"` 로 다른 Fake repo 시그니처 깨짐 확인·수정.

**Step 5: Commit** `git commit -m "feat: TradingEngine.decision_factors 훅 추가 및 persist 연결"`

---

### Task 4: FullExposureEngine 오버라이드 (이격도 중심)

**Files:**
- Modify: `src/core/engine/base.py` (`FullExposureEngine`)
- Test: `tests/test_full_exposure_engine.py`

**Step 1: Write the failing tests**:

```python
def test_결정요소는_비율_이격_중심(self):
    # A=600, B=400 보유, 목표 0.5 → 현재 A비율 0.6, 상대이탈 0.2
    pf = Portfolio(total_cash=0, holdings={"QLD": 6, "SHV": 4},
                   current_prices={"QLD": 100.0, "SHV": 100.0})
    signal = TradeSignal(1.0, [], "이유", target_ratio_a=0.5, rebalance_threshold=0.075)
    factors = self.engine.decision_factors(self.market_data, MarketRegime.BULL, 1.0, signal, pf)
    by_key = {f.key: f for f in factors}
    self.assertEqual(factors[0].key, "target_ratio_a")       # 대표 요소
    self.assertAlmostEqual(by_key["current_ratio_a"].value, 0.6)
    self.assertAlmostEqual(by_key["group_deviation"].value, 0.2)
    self.assertEqual(by_key["group_deviation"].threshold, 0.075)
    self.assertNotIn("regime", by_key)                        # 국면은 결정요소 아님

def test_위험자산_없으면_이격도_생략(self):
    pf = Portfolio(total_cash=1000, holdings={}, current_prices={})
    signal = TradeSignal(1.0, [], "이유", target_ratio_a=0.5, rebalance_threshold=0.075)
    factors = self.engine.decision_factors(self.market_data, MarketRegime.BULL, 1.0, signal, pf)
    keys = [f.key for f in factors]
    self.assertIn("target_ratio_a", keys)
    self.assertNotIn("group_deviation", keys)
```

**Step 2: Run** → FAIL (기본 구현이 regime 반환)

**Step 3: Implementation** — `FullExposureEngine`에 추가:

```python
    def decision_factors(
        self,
        market_data: MarketData,
        regime: MarketRegime,
        exposure: float,
        signal: TradeSignal,
        portfolio: Portfolio,
    ) -> List[DecisionFactor]:
        """Full Exposure 계열: 국면이 아니라 목표 비율 대비 이격도가 결정요소다."""
        groups = self.rebalancer.groups
        val_a = portfolio.get_group_value(groups.get('A', []))
        val_b = portfolio.get_group_value(groups.get('B', []))
        val_risky = val_a + val_b
        eff_a, threshold = self.rebalancer.get_target_params(regime)
        target_a = signal.target_ratio_a if signal.target_ratio_a is not None else eff_a
        rebalance_threshold = signal.rebalance_threshold \
            if signal.rebalance_threshold is not None else threshold

        factors = [
            DecisionFactor("target_ratio_a", "목표 A그룹 비율", target_a, "percent"),
        ]
        if val_risky > 0:
            current_a = val_a / val_risky
            factors.append(DecisionFactor("current_ratio_a", "현재 A그룹 비율",
                                          current_a, "percent"))
            if target_a > 0:
                rel_dev = abs(current_a - target_a) / target_a
                factors.append(DecisionFactor("group_deviation", "A그룹 상대이탈",
                                              rel_dev, "percent",
                                              threshold=rebalance_threshold))
        factors.append(DecisionFactor("rebalance_threshold", "리밸런싱 임계치",
                                      rebalance_threshold, "percent"))
        return factors
```

**Step 4: Run** `pytest tests/test_full_exposure_engine.py tests/test_spy_engine.py tests/test_qqq_engine.py tests/test_new_engines.py -v` → PASS

**Step 5: Commit** `git commit -m "feat: FullExposureEngine 결정요소를 비율 이격 중심으로 오버라이드"`

---

### Task 5: VolManaged / VolTarget 오버라이드 (변동성→레버리지 중심)

**Files:**
- Modify: `src/core/engine/volmanaged.py`, `src/core/engine/voltarget.py`
- Test: `tests/test_core_engine_volmanaged.py`, `tests/test_core_engine_voltarget.py`

**Step 1: Write the failing tests** (각 테스트 파일의 기존 fixture 재사용):

```python
# test_core_engine_volmanaged.py
def test_결정요소는_변동성_레버리지_중심(self):
    self.engine._applied_L = 1.3
    factors = self.engine.decision_factors(self.market_data, MarketRegime.BULL, 1.0,
                                           self.signal, self.portfolio)
    by_key = {f.key: f for f in factors}
    self.assertEqual(factors[0].key, "realized_vol")
    self.assertEqual(by_key["realized_vol"].threshold, self.engine.TARGET_VOL)
    self.assertAlmostEqual(by_key["effective_leverage"].value, 1.3)
    self.assertIn("cash_weight", by_key)

# test_core_engine_voltarget.py
def test_결정요소는_변동성_레버리지_중심(self):
    self.engine.rebalancer.ratio_a = 0.4   # L = 1.4
    factors = self.engine.decision_factors(self.market_data, MarketRegime.BULL, 1.0,
                                           self.signal, self.portfolio)
    by_key = {f.key: f for f in factors}
    self.assertEqual(factors[0].key, "realized_vol")
    self.assertAlmostEqual(by_key["effective_leverage"].value, 1.4)
    self.assertAlmostEqual(by_key["leveraged_weight"].value, 0.4)
```

**Step 2: Run** → FAIL

**Step 3: Implementation**

`volmanaged.py` (`VolManagedEngine`):

```python
    def decision_factors(self, market_data, regime, exposure, signal, portfolio):
        """변동성 관리: 실현변동성 → 실효 레버리지 사이징이 결정요소다."""
        L = self._applied_L if self._applied_L is not None \
            else exposure + self.rebalancer.ratio_a
        return [
            DecisionFactor("realized_vol", "실현변동성(21d)", market_data.spy_volatility,
                           "percent", threshold=self.TARGET_VOL),
            DecisionFactor("target_vol", "목표 변동성", self.TARGET_VOL, "percent"),
            DecisionFactor("effective_leverage", "실효 레버리지(x)", L, "number"),
            DecisionFactor("cash_weight", "현금 비중", max(1.0 - exposure, 0.0), "percent"),
        ]
```

`voltarget.py` (`VolTargetLeverageEngine`):

```python
    def decision_factors(self, market_data, regime, exposure, signal, portfolio):
        """변동성 타겟: 실현변동성 → QLD/QQQ 블렌드 레버리지가 결정요소다."""
        w = self.rebalancer.ratio_a          # QLD 비중 = L - 1
        return [
            DecisionFactor("realized_vol", "실현변동성(21d)", market_data.spy_volatility,
                           "percent", threshold=self.TARGET_VOL),
            DecisionFactor("target_vol", "목표 변동성", self.TARGET_VOL, "percent"),
            DecisionFactor("effective_leverage", "실효 레버리지(x)", 1.0 + w, "number"),
            DecisionFactor("leveraged_weight", "QLD 비중", w, "percent"),
        ]
```

(타입 힌트/`DecisionFactor` import 추가. 시그니처는 base와 동일하게 명시)

**Step 4: Run** 두 테스트 파일 + `test_core_engine_domestic_volmanaged.py` → PASS

**Step 5: Commit** `git commit -m "feat: VolManaged/VolTarget 결정요소를 변동성-레버리지 중심으로 오버라이드"`

---

### Task 6: DipBuy 오버라이드 (MA 이격/RSI/트리거 상태)

**Files:**
- Modify: `src/core/engine/dip_buy.py` (`DipBuyEngine` — Gated는 상속)
- Test: `tests/test_core_engine_dip_buy.py`

**Step 1: Write the failing test**:

```python
def test_결정요소는_눌림목_지표_중심(self):
    self.engine.dip_signals = DipBuySignals(date="2026-07-14", price=100.0,
                                            ma20=98.0, ma60=95.0, ma120=90.0,
                                            rsi=45.0, ma200=88.0)
    pf = Portfolio(total_cash=0, holdings={"QLD": 1}, current_prices={"QLD": 100.0})
    factors = self.engine.decision_factors(self.market_data, MarketRegime.BULL, 1.0,
                                           self.signal, pf)
    by_key = {f.key: f for f in factors}
    self.assertEqual(factors[0].key, "gap_ma20")
    self.assertAlmostEqual(by_key["gap_ma20"].value, 100.0 / 98.0 - 1.0)
    self.assertAlmostEqual(by_key["rsi"].value, 45.0)
    self.assertEqual(by_key["armed_triggers"].value, "4/4")

def test_지표_NaN이면_해당_요소_생략(self):
    self.engine.dip_signals = DipBuySignals(date="", price=float("nan"),
                                            ma20=float("nan"), ma60=float("nan"),
                                            ma120=float("nan"), rsi=float("nan"))
    pf = Portfolio(total_cash=0, holdings={}, current_prices={})
    factors = self.engine.decision_factors(self.market_data, MarketRegime.BULL, 1.0,
                                           self.signal, pf)
    keys = [f.key for f in factors]
    self.assertEqual(keys, ["armed_triggers"])
```

**Step 2: Run** → FAIL

**Step 3: Implementation** — `DipBuyEngine`에 추가:

```python
    def decision_factors(self, market_data, regime, exposure, signal, portfolio):
        """눌림목 분할매수: MA 이격·RSI·트리거 무장 상태가 결정요소다."""
        factors: List[DecisionFactor] = []
        s = self.dip_signals
        price = portfolio.current_prices.get(self._ticker, 0.0)
        if s is not None:
            if price <= 0 and not math.isnan(s.price):
                price = s.price
            for key, ma, label in (("ma20", s.ma20, "MA20 이격"),
                                   ("ma60", s.ma60, "MA60 이격"),
                                   ("ma120", s.ma120, "MA120 이격")):
                if price > 0 and not math.isnan(ma) and ma > 0:
                    factors.append(DecisionFactor(f"gap_{key}", label,
                                                  price / ma - 1.0, "percent",
                                                  threshold=self.BAND))
            if not math.isnan(s.rsi):
                factors.append(DecisionFactor("rsi", "RSI(14)", s.rsi, "number",
                                              threshold=70.0))
        armed = self.dip_state.armed
        armed_count = sum(1 for v in armed.values() if v)
        factors.append(DecisionFactor("armed_triggers", "무장 트리거",
                                      f"{armed_count}/{len(armed)}", "text"))
        return factors
```

**Step 4: Run** `pytest tests/test_core_engine_dip_buy.py -v` → PASS

**Step 5: Commit** `git commit -m "feat: DipBuy 결정요소를 눌림목 지표 중심으로 오버라이드"`

---

### Task 7: 전체 테스트 + 커버리지 검증

**Step 1:** `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/` (live 테스트는 CI 기준과 동일하게 제외 설정이 conftest에 있으면 그대로)
**Step 2:** 실패/커버리지 미달 시 수정 (특히 Fake repo 시그니처, `test_main_integration.py`)
**Step 3:** Commit (수정분 있으면) `git commit -m "test: decision_factors 도입에 따른 테스트 정비"`

---

### Task 8: 프론트엔드 generic 렌더링

**Files:**
- Modify: `docs/js/ui.js` (`updateSummaryCards` [2] 섹션 교체 + 헬퍼 2개 추가)
- Modify: `docs/index.html:119-131` (시장 국면 카드 → 전략 결정요소 카드), `:951` (`main.js ?v=` 갱신)
- Modify: `docs/js/main.js` (ui.js import의 `?v=` 갱신)

**Step 1: index.html 카드 교체** (기존 `regime-text`/`momentum-score` ID 제거):

```html
                    <!-- Decision Factors (엔진별 핵심 결정요소) -->
                    <div class="col-md-6 col-lg-3">
                        <div class="card h-100 border-0 shadow-sm">
                            <div class="card-body">
                                <h6 class="text-muted"><i class="fas fa-flag me-1"></i>전략 결정요소</h6>
                                <div id="decision-factors">
                                    <h3 class="fw-bold mb-0">-</h3>
                                </div>
                                <div id="trigger-reason" class="mt-1 small text-muted fst-italic"></div>
                            </div>
                        </div>
                    </div>
```

**Step 2: ui.js** — `updateSummaryCards`의 [2]/[2-2] 블록을 `renderDecisionCard(strategy);` 호출로 교체하고 (trigger-reason [2-3] 블록은 유지), 파일에 헬퍼 추가:

```js
/** DecisionFactor 값 포맷팅 (format: percent | number | text) */
function formatFactorValue(f) {
    if (typeof f.value === 'number') {
        if (f.format === 'percent') return (f.value * 100).toFixed(2) + '%';
        if (f.format === 'number') return f.value.toFixed(2);
    }
    return String(f.value ?? '-');
}

/** threshold 위반 여부: 음수 기준(MDD 등)은 이하, 양수 기준(VIX/이격도)은 이상 */
function isFactorBreached(f) {
    if (f.threshold == null || typeof f.value !== 'number') return false;
    return f.threshold < 0 ? f.value <= f.threshold : f.value >= f.threshold;
}

/**
 * 전략 결정요소 카드 렌더링.
 * 엔진이 저장한 decision_factors 배열을 그대로 그린다 (첫 항목 = 대표 요소).
 * 배열이 없는 구버전 status.json은 기존 국면+모멘텀 표시로 폴백.
 */
export function renderDecisionCard(strategy) {
    const container = document.getElementById('decision-factors');
    if (!container) return;

    const factors = strategy.decision_factors;
    if (!Array.isArray(factors) || factors.length === 0) {
        const regime = strategy.regime.replace('_', ' ');
        container.innerHTML =
            `<h3 class="fw-bold mb-0 ${getRegimeColorClass(strategy.regime)}">${regime}</h3>` +
            `<div class="mt-1 text-muted small">모멘텀: ${(strategy.market_score.spy_momentum * 100).toFixed(2)}%</div>`;
        return;
    }

    const [head, ...rest] = factors;
    const headClass = head.key === 'regime'
        ? getRegimeColorClass(String(head.value)) : 'text-dark';
    const headValue = head.key === 'regime'
        ? String(head.value).replace('_', ' ') : formatFactorValue(head);
    const rows = rest.slice(0, 3).map(f =>
        `<div class="d-flex justify-content-between align-items-center small">` +
        `<span class="text-muted">${f.label}</span>` +
        `<span class="fw-bold ${isFactorBreached(f) ? 'text-danger' : ''}">${formatFactorValue(f)}</span>` +
        `</div>`
    ).join('');
    container.innerHTML =
        `<div class="text-muted small">${head.label}</div>` +
        `<h3 class="fw-bold mb-0 ${headClass}">${headValue}</h3>` +
        (rows ? `<div class="mt-1">${rows}</div>` : '');
}
```

**Step 3: 캐시 버전 갱신** (CLAUDE.md 규칙)
- `docs/js/main.js`: `from './ui.js?v=...'` → `?v=20260714-1`
- `docs/index.html`: `js/main.js?v=...` → `?v=20260714-1`
- ui.js를 import하는 다른 파일이 있는지 `grep -rn "ui.js?v" docs/` 로 확인 후 전부 갱신

**Step 4: 수동 검증** — `python3 -m http.server -d docs` 후 index.html 로드, my_isa(구버전 status.json) 폴백 렌더링 확인. 새 포맷은 임시로 status.json에 `decision_factors` 배열을 주입해 확인.

**Step 5: Commit** `git commit -m "feat: 대시보드 전략 결정요소 카드 generic 렌더링 (+캐시 버전 갱신)"`

---

### Task 9: 푸시 + PR

```bash
git push -u origin claude/engine-decision-factors-uff0n0
```

PR 생성: 제목 "엔진별 결정요소(DecisionFactor) 자기서술 구조 도입". 본문에 아키텍처 요약(엔진 훅 → repo pass-through → 프론트 generic 렌더), 엔진별 요소 매트릭스, 하위호환(폴백) 설명 포함.
