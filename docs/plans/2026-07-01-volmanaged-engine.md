# VolManagedEngine (변동성 관리 QLD/QQQ/SHV 엔진) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실현변동성에 반비례해 0~2x 실효 레버리지를 조절하되 **1x 미만에서는 현금(SHV)으로 이탈**하는 변동성 관리(volatility-managed) 엔진을 새로 추가한다. 목표: QQQ~QLD 사이 수익 + 두 벤치마크를 능가하는 Sharpe.

**Architecture:** 기존 3그룹(A=QLD 2x / B=QQQ 1x / C=SHV 현금) `TradingEngine` 패턴을 따른다. 매 사이클 `L = clamp(TARGET_VOL / 실현변동성, 0, 2)`를 산출하고, 이를 Rebalancer의 `(exposure, ratio_a)`로 매핑한다: `exposure = min(L,1)`(A+B 위험비중, 나머지는 C 현금), `ratio_a = max(L−1,0)`(위험자산 내 QLD 비중). 레버리지 산정은 기존 `VolatilityTargeter`를 클램프로 재사용(순수 실현변동성 기반, 국면 CRASH 오버라이드 미사용). VIX는 국면 CRASH 판정에만 쓰고 레버리지 사이징엔 쓰지 않는다(#350에서 검증: VIX 사이징은 realized 단독보다 나쁨).

**Tech Stack:** Python 3.10, 기존 `TradingEngine`/`Rebalancer`/`VolatilityTargeter`/`RegimeAnalyzer`, pytest.

**설계 근거 (standalone 실측, 2008~2026, 현금 2% 가정):**

| 구성 | CAGR | MDD | Sharpe | avgLev |
|---|---:|---:|---:|---:|
| QQQ B&H | 15.1% | -49.5% | 0.74 | — |
| QLD B&H | 24.3% | -79.7% | 0.71 | — |
| tv=0.22, 현금이탈 허용(min=0) | 20.0% | **-35.5%** | **0.91** | 1.33 |
| tv=0.22, **1x 바닥**(현재 VolTarget 방식) | 20.0% | -50.1% | 0.82 | 1.40 |

핵심: **1x 미만 현금 이탈 허용**이 Sharpe를 0.82→0.91로 끌어올린다(Moreira-Muir 변동성 관리 효과 — 고변동성 구간의 나쁜 위험조정수익을 회피). 결과는 tv 0.12~0.30 전 구간에서 0.85~0.94로 파라미터에 둔감.

**주의(정직):** standalone은 일간리밸/무비용/무배당/현금 2% 가정. 엔진 경로(리밸 임계치·거래비용·정수체결·실제 SHV)에선 Sharpe가 다소 낮아질 것(~0.82~0.87 예상). Task 6에서 프로덕션 엔진 경로로 재검증하여 실제 수치를 확정한다. 단일 표본 과적합 위험 있음(tv는 자유 파라미터).

---

### Task 1: VolManagedEngine 스켈레톤 + 등록

**Files:**
- Create: `src/core/engine/volmanaged.py`
- Modify: `src/core/engine/__init__.py` (import + `__all__`)
- Test: `tests/test_core_engine_volmanaged.py`

**Step 1: 실패하는 등록 테스트 작성**

```python
def test_registered():
    from src.core.engine import _ENGINE_REGISTRY
    assert "VolManagedEngine" in [n for n, _ in _ENGINE_REGISTRY]
```

**Step 2: 테스트 실패 확인**

Run: `pytest tests/test_core_engine_volmanaged.py::test_registered -v`
Expected: FAIL (ImportError / 미등록)

**Step 3: 스켈레톤 구현**

`src/core/engine/volmanaged.py`:
```python
# src/core/engine/volmanaged.py
"""변동성 관리 엔진 (QLD/QQQ/SHV). 실현변동성 역비례로 0~2x 조절, 1x 미만은 현금."""
from typing import List, Tuple

from src.core.engine.base import TradingEngine
from src.core.engine.registry import register_engine
from src.core.logic.volatility_targeter import VolatilityTargeter
from src.core.models import MarketData, MarketRegime


@register_engine(color="#6f42c1")
class VolManagedEngine(TradingEngine):
    """실현변동성에 반비례해 실효 레버리지 L∈[0,2]를 조절하는 변동성 관리 엔진.

    - A=[QLD](2x), B=[QQQ](1x), C=[SHV](현금). L에 따라 3그룹 비중 결정.
    - L = clamp(TARGET_VOL / 실현변동성21d, MIN_LEV, MAX_LEV). 순수 실현변동성 기반.
    - 매핑: exposure=min(L,1)(위험비중, 나머지 C 현금), ratio_a=max(L-1,0)(위험 내 QLD).
      L=0.5→현금50%+QQQ50%, L=1→QQQ100%, L=1.5→QLD50%+QQQ50%, L=2→QLD100%.
    - VIX는 국면 CRASH 판정(RegimeAnalyzer)에만 쓰고 레버리지 사이징엔 쓰지 않는다.
    """

    ASSET_GROUPS: dict = {"A": ["QLD"], "B": ["QQQ"], "C": ["SHV"]}
    REBALANCE_RATIO_A: float = 0.5   # fallback
    TARGET_VOL: float = 0.22
    MIN_LEV: float = 0.0
    MAX_LEV: float = 2.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # targeter를 순수 vol→레버리지 클램프로 재사용(국면 캡/CRASH 오버라이드 비활성)
        self.targeter = VolatilityTargeter(
            target_vol=self.TARGET_VOL,
            min_exposure=self.MIN_LEV,
            max_exposure=self.MAX_LEV,
            regime_max_exposures={},
            crash_exposure=self.MIN_LEV,  # 미사용(analyze에서 BULL로 호출해 우회)
        )
```

`src/core/engine/__init__.py`: import 추가(dip_buy/voltarget 다음 줄)
```python
from src.core.engine.volmanaged import VolManagedEngine
```
그리고 `__all__`에 `"VolManagedEngine"` 추가.

**Step 4: 테스트 통과 확인**

Run: `pytest tests/test_core_engine_volmanaged.py::test_registered -v`
Expected: PASS

**Step 5: 커밋**

```bash
git add src/core/engine/volmanaged.py src/core/engine/__init__.py tests/test_core_engine_volmanaged.py
git commit -m "feat(volmanaged): VolManagedEngine 스켈레톤 + 레지스트리 등록"
```

---

### Task 2: L→(exposure, ratio_a) 매핑 + analyze_strategy 오버라이드

**Files:**
- Modify: `src/core/engine/volmanaged.py`
- Test: `tests/test_core_engine_volmanaged.py`

**Step 1: 실패하는 매핑 테스트 작성**

`_make(tmp_path)` 헬퍼는 `tests/test_core_engine_voltarget.py`를 참고(MockBroker + JsonRepository, groups A/B/C).

```python
import pytest

@pytest.mark.parametrize("vol,exp_exposure,exp_ratio_a", [
    (0.11, 1.0, 1.0),    # 0.22/0.11=2.0 → L=2 → exposure1, ratioA1 (QLD100%)
    (0.22, 1.0, 0.0),    # L=1.0 → exposure1, ratioA0 (QQQ100%)
    (0.44, 0.5, 0.0),    # 0.22/0.44=0.5 → exposure0.5, ratioA0 (QQQ50%+현금50%)
    (0.147, 1.0, 0.5),   # 0.22/0.147≈1.5 → exposure1, ratioA0.5 (QLD50%+QQQ50%)
])
def test_L_to_exposure_ratio_mapping(tmp_path, vol, exp_exposure, exp_ratio_a):
    eng, _, _ = _make(tmp_path)
    exposure, ratio_a = eng._leverage_to_weights(vol)
    assert abs(exposure - exp_exposure) < 1e-2
    assert abs(ratio_a - exp_ratio_a) < 1e-2
```

**Step 2: 실패 확인**

Run: `pytest tests/test_core_engine_volmanaged.py::test_L_to_exposure_ratio_mapping -v`
Expected: FAIL (`_leverage_to_weights` 없음)

**Step 3: 구현**

`volmanaged.py`에 추가:
```python
    def _leverage_to_weights(self, current_vol: float) -> Tuple[float, float]:
        """실현변동성 → (exposure, ratio_a). L=clamp(target/vol). 순수 vol 기반."""
        L = self.targeter.calculate_exposure(MarketRegime.BULL, current_vol)  # CRASH 우회
        exposure = min(L, 1.0)          # 위험비중(A+B); 나머지 1-exposure는 C(현금)
        ratio_a = max(L - 1.0, 0.0)     # 위험자산 내 QLD 비중
        return exposure, ratio_a

    def analyze_strategy(self, market_data: MarketData) -> Tuple[MarketRegime, float, List[str]]:
        """Step 3 오버라이드: 실현변동성 기반 exposure/ratio_a 동적 설정."""
        nan_fields = market_data.nan_fields()
        prev = self.analyzer._prev_regime
        if nan_fields:
            self.logger.error(f"NaN detected in: {', '.join(nan_fields)}. Treating as CRASH.")
            regime, exposure = MarketRegime.CRASH, 0.0
        else:
            regime = self.analyzer.analyze(market_data)
            exposure, ratio_a = self._leverage_to_weights(market_data.spy_volatility)
            self.rebalancer.ratio_a = ratio_a
            self.rebalancer.ratio_b = round(1.0 - ratio_a, 10)
            self.logger.info(
                f">>> VolManaged: vol={market_data.spy_volatility:.2%} "
                f"→ L={exposure + ratio_a:.2f}x (QLD {ratio_a:.0%}, 위험 {exposure:.0%}, "
                f"현금 {1 - exposure:.0%})"
            )
        if prev is not None and regime != prev:
            self.logger.info(f"Regime Change: {prev.value} → {regime.value}")
        return regime, exposure, nan_fields
```

**Step 4: 통과 확인**

Run: `pytest tests/test_core_engine_volmanaged.py -v`
Expected: PASS

**Step 5: 커밋**

```bash
git commit -am "feat(volmanaged): L→(exposure,ratio_a) 매핑 + analyze_strategy"
```

---

### Task 3: 통합 사이클 테스트 (저/고변동성 거동)

**Files:**
- Test: `tests/test_core_engine_volmanaged.py`

**Step 1: 테스트 작성** — `_Loader`/`_series`는 voltarget 테스트에서 재사용.

```python
def test_low_vol_levers_into_qld(tmp_path):
    eng, broker, repo = _make(tmp_path)
    res = eng.run_one_cycle(_Loader(_series(step=0.001), vix=20.0), sim_date="2023-10-27")
    assert res.signal is not None
    assert eng.rebalancer.ratio_a > 0.9   # 저변동성 → QLD 편입

def test_high_vol_moves_to_cash(tmp_path):
    eng, broker, repo = _make(tmp_path)
    # 고변동성 시계열 → exposure<1 → 현금(SHV) 편입
    res = eng.run_one_cycle(_Loader(_series(step=0.03), vix=20.0), sim_date="2023-10-27")
    assert res.exposure < 1.0
```

**Step 2~4:** 실행→통과 확인. 필요 시 `_series` step 값 조정으로 목표 변동성 구간 유도.

**Step 5: 커밋**
```bash
git commit -am "test(volmanaged): 저/고변동성 사이클 거동 검증"
```

---

### Task 4: 프로덕션 엔진 경로 백테스트 검증 (SHV 실데이터)

**Files:**
- Scratch: `scratchpad/verify_volmanaged.py` (커밋 안 함)

**Step 1: SHV 데이터 확보** — `requests`로 Yahoo chart API에서 SHV OHLCV 다운로드(curl_cffi 우회), 기존 `ohlcv_m4.parquet`(QLD/QQQ/SPY/SSO)에 SHV 컬럼 병합. VIX는 단일레벨 'Close'로 flatten(fetch_vix 계약).

**Step 2: 엔진 경로 실행** — `engine_compare.run_engine` 패턴으로 VolManagedEngine을 2008~2026 실행. 벤치 QQQ/QLD B&H와 비교. CAGR/Vol/MDD/Sharpe/avgLev 리포트.

**Step 3: 판정 기준**
- 수익: QQQ(15%) < VolManaged CAGR < QLD(24%) — 중간대 확인
- Sharpe: > QQQ 0.74 목표(엔진 경로 비용 반영 시 ~0.82~0.87 예상). **0.74 미달이면 설계 재검토**(TARGET_VOL 조정 or crash→cash 변형 테스트).

**Step 4:** 결과를 Task 5 docstring 수치로 반영. (자동 대시보드는 `run-compare-backtest` 워크플로우가 SHV 포함 재실행 시 확정.)

---

### Task 5: docstring 수치 확정 + 전체 스위트 + 커밋/PR

**Files:**
- Modify: `src/core/engine/volmanaged.py` (docstring에 Task 4 실측 수치)

**Step 1:** docstring에 검증된 CAGR/MDD/Sharpe/avgLev 기입(정직하게: QQQ 대비 우위 여부, 단일표본·비용 단서 포함).

**Step 2: 전체 스위트 + 커버리지**

Run: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/`
Expected: 신규 테스트 통과, 커버리지 80%+. (실패하는 `test_infra_data_live.py`는 네트워크 라이브 테스트로 무시.)

**Step 3: 커밋 + 푸시 + PR**

```bash
git commit -am "docs(volmanaged): 백테스트 실측 수치 반영"
git push -u origin claude/investment-algorithm-setup-a8a0bu
```
PR 생성(base=main): 설계 근거 표 + 정직한 단서 포함. 대시보드 비교는 워크플로우가 확정.

---

## Remember
- DRY: 기존 VolatilityTargeter/Rebalancer/RegimeAnalyzer 재사용, 새 로직은 매핑뿐.
- YAGNI: crash→cash 변형·target_vol 튜닝은 Task 4 판정이 요구할 때만.
- 정직한 수치: standalone(0.91)이 아니라 **엔진 경로 실측**을 문서에 쓴다.
- 기존 VolTargetLeverageEngine은 비교용으로 그대로 둔다(개조하지 않음).
