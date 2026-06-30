# 변동성 타겟 레버리지 엔진 (QLD/QQQ 블렌드) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실현 변동성에 반비례해 QLD(2x)/QQQ(1x) 비중을 조절(실효 레버리지 1~2x)하는 변동성 타겟 엔진을 추가한다. 평온기엔 레버리지업, 폭락기엔 디레버리지.

**Architecture:** 기존 `VolatilityTargeter`에 레버리지 모드(`crash_exposure` 파라미터)를 추가해 출력 범위를 1~2x로 확장하고, `FullExposureEngine`(exposure=1.0 고정)을 상속한 `VolTargetLeverageEngine`이 매 사이클 `ratio_a`(=QLD 비중=레버리지−1)를 동적으로 설정한다. 주문 생성·턴오버 throttle은 기존 `Rebalancer`를 그대로 재사용한다.

**Tech Stack:** Python 3.10, pytest. 설계 배경/검증: 대화 로그 + 백테스트(σ=0.30 → Sharpe 0.83, MDD -55% vs 고정 2x -80%).

---

## 배경 (왜 이 설계인가)

- `VolatilityTargeter.calculate_exposure(regime, vol)` = `clamp(target_vol/vol, min_exposure, regime_cap)` + `CRASH→0`.
- 현재는 출력이 [0.2, 1.0]뿐이라 **레버리지(>1x)를 못 냄.** `crash_exposure` 파라미터만 추가하면(기본 0.0=기존동작) `min_exposure=1.0, max_exposure=2.0, regime_max_exposures={}, crash_exposure=1.0`으로 구성해 **L∈[1,2] 레버리지 타겟터**가 된다.
- `exposure=1.0`(FullExposure, 항상 풀투자) + `Rebalancer`의 `ratio_a=w`(QLD 비중) → 자동으로 QLD `w` / QQQ `1-w` 배분. `w = L - 1`.
- `Rebalancer`의 임계치 기반 리밸런싱이 **일별 미세 조정 턴오버를 throttle**해준다(공짜 이점).

## 공통 규칙
- TDD: 실패 테스트 → 최소 구현 → 통과 → 커밋.
- 테스트: `pytest tests/<file> -v`. 전체: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/ --ignore=tests/test_infra_broker_kis_domestic_live.py --ignore=tests/test_infra_data_live.py`
- 코드 편집 전 대상 파일 Read (CLAUDE.md 규칙).

---

### Task 1: VolatilityTargeter에 `crash_exposure` 파라미터 추가 (레버리지 모드 가능화)

**Files:**
- Modify: `src/core/logic/volatility_targeter.py`
- Test: `tests/test_core_logic.py` (또는 신규 `tests/test_volatility_targeter.py`)

**Step 1: 실패 테스트 작성**

```python
from src.core.logic.volatility_targeter import VolatilityTargeter
from src.core.models import MarketRegime

def test_crash_exposure_default_zero():
    vt = VolatilityTargeter(target_vol=0.15)
    assert vt.calculate_exposure(MarketRegime.CRASH, 0.20) == 0.0   # 기존 동작 불변

def test_leverage_mode_range_1_to_2():
    # 레버리지 모드: 출력 1.0~2.0
    vt = VolatilityTargeter(target_vol=0.30, min_exposure=1.0, max_exposure=2.0,
                            regime_max_exposures={}, crash_exposure=1.0)
    assert vt.calculate_exposure(MarketRegime.BULL, 0.15) == 2.0   # 0.30/0.15=2.0 (상한)
    assert vt.calculate_exposure(MarketRegime.BULL, 0.60) == 1.0   # 0.30/0.60=0.5 → 하한 1.0
    assert vt.calculate_exposure(MarketRegime.BULL, 0.30) == 1.0   # 0.30/0.30=1.0
    assert vt.calculate_exposure(MarketRegime.CRASH, 0.80) == 1.0  # CRASH도 1.0(현금화 아님)
    # 중간값: 0.30/0.20 = 1.5
    assert abs(vt.calculate_exposure(MarketRegime.BULL, 0.20) - 1.5) < 1e-9
```

**Step 2: 실패 확인** — `pytest tests/test_volatility_targeter.py -v` → FAIL (crash_exposure 미지원)

**Step 3: 구현** — `VolatilityTargeter.__init__`에 `crash_exposure: float = 0.0` 추가, `calculate_exposure`의 CRASH 분기를 `return self.crash_exposure`로 변경.

```python
    def __init__(self, target_vol: float = 0.15,
                 min_exposure: float = DEFAULT_MIN_EXPOSURE,
                 regime_max_exposures: Optional[Dict[MarketRegime, float]] = None,
                 max_exposure: float = DEFAULT_MAX_EXPOSURE,
                 crash_exposure: float = 0.0):
        ...
        self.crash_exposure = crash_exposure

    def calculate_exposure(self, regime, current_vol):
        if regime == MarketRegime.CRASH:
            return self.crash_exposure
        ...
```

**Step 4: 통과 확인** — PASS

**Step 5: 커밋**
```bash
git add src/core/logic/volatility_targeter.py tests/test_volatility_targeter.py
git commit -m "feat: VolatilityTargeter에 crash_exposure 추가 (레버리지 모드 가능화)"
```

---

### Task 2: VolTargetLeverageEngine — 레버리지→ratio_a 매핑

**Files:**
- Create: `src/core/engine/voltarget.py`
- Modify: `src/core/engine/__init__.py`
- Test: `tests/test_core_engine_voltarget.py`

**Step 1: 실패 테스트 작성**

```python
import numpy as np, pandas as pd
from src.core.engine.voltarget import VolTargetLeverageEngine
from src.core.models import MarketRegime
from src.infra.broker.mock import MockBroker
from src.infra.repo import JsonRepository
from src.utils.logger import TradeLogger

def _make(tmp_path):
    groups = {"A": ["QLD"], "B": ["QQQ"]}
    repo = JsonRepository(str(tmp_path), asset_groups=groups)
    broker = MockBroker(initial_cash=10000.0)
    eng = VolTargetLeverageEngine(broker=broker, repo=repo,
                                  logger=TradeLogger(log_dir=str(tmp_path/"l")),
                                  asset_groups=groups, trading_interval_days=1)
    return eng, broker, repo

def test_registered():
    from src.core.engine import _ENGINE_REGISTRY
    assert "VolTargetLeverageEngine" in [n for n, _ in _ENGINE_REGISTRY]

def test_low_vol_levers_up(tmp_path):
    eng, _, _ = _make(tmp_path)
    # target_vol=0.30, vol=0.15 → L=2.0 → ratio_a(QLD)=1.0
    eng._set_leverage_ratio(MarketRegime.BULL, 0.15)
    assert abs(eng.rebalancer.ratio_a - 1.0) < 1e-9

def test_high_vol_delevers(tmp_path):
    eng, _, _ = _make(tmp_path)
    # vol=0.60 → L=clamp(0.5,1,2)=1.0 → ratio_a(QLD)=0.0 (전부 QQQ)
    eng._set_leverage_ratio(MarketRegime.BULL, 0.60)
    assert abs(eng.rebalancer.ratio_a - 0.0) < 1e-9

def test_mid_vol_blend(tmp_path):
    eng, _, _ = _make(tmp_path)
    # vol=0.20 → L=1.5 → ratio_a=0.5
    eng._set_leverage_ratio(MarketRegime.BULL, 0.20)
    assert abs(eng.rebalancer.ratio_a - 0.5) < 1e-9
```

**Step 2: 실패 확인** — FAIL (모듈 없음)

**Step 3: 구현** — `src/core/engine/voltarget.py`

```python
# src/core/engine/voltarget.py
"""변동성 타겟 레버리지 엔진 (QLD/QQQ 블렌드)."""
from typing import List, Optional, Tuple
import pandas as pd

from src.core.engine.base import FullExposureEngine
from src.core.engine.registry import register_engine
from src.core.interfaces import IDataProvider
from src.core.logic.volatility_targeter import VolatilityTargeter
from src.core.models import MarketData, MarketRegime, Portfolio, TradeSignal, TradeExecution


@register_engine(color="#20c997")
class VolTargetLeverageEngine(FullExposureEngine):
    """실현 변동성에 반비례해 QLD(2x)/QQQ(1x) 비중을 조절하는 변동성 타겟 엔진.

    - 자산군 A: [QLD] (2x), B: [QQQ] (1x). 항상 100% 투자(현금 미보유).
    - 실효 레버리지 L = clamp(TARGET_VOL / 실현변동성, 1.0, 2.0); QLD 비중 = L − 1.
      평온기 → 2x(QLD↑), 폭락기 → 1x(QQQ↑). CRASH도 현금화가 아니라 1x로 디레버리지.
    - 변동성/국면은 QQQ(=나스닥100 1x) 기준으로 산출(레버리지로 왜곡 안 됨).
    - 주문 생성·턴오버 throttle은 기존 Rebalancer 재사용(ratio_a를 매 사이클 동적 설정).
    """

    ASSET_GROUPS: dict = {"A": ["QLD"], "B": ["QQQ"]}
    REBALANCE_RATIO_A: float = 0.5         # 초기값(매 사이클 동적 갱신)
    TARGET_VOL: float = 0.30
    MIN_LEVERAGE: float = 1.0
    MAX_LEVERAGE: float = 2.0
    SIGNAL_TICKER: str = "QQQ"             # 변동성/국면 신호 기준(1x 나스닥)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lev = VolatilityTargeter(
            target_vol=self.TARGET_VOL,
            min_exposure=self.MIN_LEVERAGE,
            max_exposure=self.MAX_LEVERAGE,
            regime_max_exposures={},        # 레버리지 모드: 국면 디리스크 캡 비활성
            crash_exposure=self.MIN_LEVERAGE,  # CRASH도 1x로 디레버리지(현금화 아님)
        )

    def collect_data(self, data_provider: IDataProvider) -> Tuple[pd.DataFrame, float]:
        """변동성/국면 신호를 QQQ(1x 나스닥)에서 산출."""
        df = data_provider.fetch_ohlcv([self.SIGNAL_TICKER], days=400)
        vix = data_provider.fetch_vix()
        return df, vix

    def _set_leverage_ratio(self, regime: MarketRegime, current_vol: float) -> float:
        """변동성→레버리지→QLD 비중(ratio_a) 동적 설정. 반환: 실효 레버리지 L."""
        L = self._lev.calculate_exposure(regime, current_vol)
        w = min(max(L - 1.0, 0.0), 1.0)             # QLD 비중
        self.rebalancer.ratio_a = w
        self.rebalancer.ratio_b = round(1.0 - w, 10)
        return L

    def execute_cycle(self, market_data, portfolio, regime, exposure,
                      nan_fields, sim_date, record_date):
        if not nan_fields:
            L = self._set_leverage_ratio(regime, market_data.spy_volatility)
            self.logger.info(f">>> VolTarget: vol={market_data.spy_volatility:.2%} "
                             f"→ leverage={L:.2f}x (QLD {self.rebalancer.ratio_a:.0%})")
        return super().execute_cycle(market_data, portfolio, regime, exposure,
                                     nan_fields, sim_date, record_date)
```

`src/core/engine/__init__.py`: import + `__all__`에 `VolTargetLeverageEngine` 추가.

**Step 4: 통과 확인** — PASS

**Step 5: 커밋**
```bash
git add src/core/engine/voltarget.py src/core/engine/__init__.py tests/test_core_engine_voltarget.py
git commit -m "feat: VolTargetLeverageEngine (QLD/QQQ 변동성 타겟 레버리지)"
```

---

### Task 3: 통합 사이클 테스트 (run_one_cycle)

**Files:**
- Test: `tests/test_core_engine_voltarget.py` (추가)

**Step 1: 실패→통과 테스트**

```python
class _Loader:
    def __init__(self, df, vix=20.0): self.df, self._vix = df, vix
    def fetch_ohlcv(self, tickers, days=365): return self.df.tail(days)
    def fetch_vix(self): return self._vix

def _series(n=300, vol="low"):
    rng = np.random.default_rng(0)
    step = 0.005 if vol == "low" else 0.04
    rets = rng.normal(0.0004, step, n)
    closes = 100 * np.cumprod(1 + rets)
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [1]*n}, index=idx)

def test_cycle_runs_and_invests(tmp_path):
    eng, broker, repo = _make(tmp_path)
    # MockBroker.fetch_current_prices는 모든 티커 100 반환 → QLD/QQQ 가격 존재
    res = eng.run_one_cycle(_Loader(_series()), sim_date="2023-10-27")
    assert res.signal is not None
    # 첫 투자 → QLD/QQQ 매수 발생(둘 중 하나 이상)
    assert any(o.ticker in ("QLD", "QQQ") for o in res.signal.orders)
```

> 주의: `MockBroker.fetch_current_prices`가 모든 티커 100.0을 반환하는지 `tests/test_infra_broker.py`로 확인. 가격이 0이면 Rebalancer가 주문을 건너뛴다.

**Step 2~4:** 실행/통과 확인.

**Step 5: 커밋**
```bash
git add tests/test_core_engine_voltarget.py
git commit -m "test: VolTargetLeverageEngine 통합 사이클"
```

---

### Task 4: 전체 검증 + 백테스트 + 푸시/PR

**Step 1: 전체 스위트 + 커버리지**
Run: `pytest --cov=src --cov-fail-under=80 tests/ --ignore=tests/test_infra_broker_kis_domestic_live.py --ignore=tests/test_infra_data_live.py -q`
Expected: PASS, ≥80%

**Step 2: 백테스트 검증(가능 시)** — 캐시에 QLD/QQQ가 있으므로 `run-compare-backtest` 또는 로컬 하니스로 VolTargetLeverageEngine vs QqqEngine/SpyEngine/DipBuyGatedEngine 비교. 기대: σ=0.30 기준 CAGR ~23%, MDD ~-55%, Sharpe ~0.83(2008 포함). (실데이터 다운로드는 CI 워크플로우.)

**Step 3: arch-check** — core→infra 의존 방향, 순환 의존성 점검.

**Step 4: 커밋 & 푸시**
```bash
git push -u origin claude/investment-algorithm-setup-a8a0bu
```

**Step 5: PR 생성** (ready for review)

---

## 검증 체크리스트
- [ ] `VolatilityTargeter.crash_exposure` 기본 0.0 → 기존 엔진 동작 불변
- [ ] 레버리지 모드 출력 1.0~2.0, CRASH→1.0
- [ ] 저vol→QLD↑(2x), 고vol→QQQ↑(1x), 중간→블렌드
- [ ] `VolTargetLeverageEngine` 레지스트리 등록 → 대시보드 비교 자동 포함
- [ ] run_one_cycle 정상 투자, NaN 시 매매 중단(FullExposure 안전장치)
- [ ] 전체 테스트 통과, 커버리지 ≥80%
