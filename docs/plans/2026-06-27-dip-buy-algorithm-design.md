# 오즐웅줍(눌림목 분할매수) 알고리즘 설계

## 배경

기존 StockAsset 엔진은 "항상 투자 상태"를 유지하며 자산군(A/B/C) 간 비율을
리밸런싱하는 철학이다. 반면 "오즐웅줍" 알고리즘은 **현금을 보유**하다가
이동평균선 눌림목·과매도 구간에서 **현금을 분할 투입**하고, 과열 구간에서
일부를 분할 매도하는 **트리거 기반 현금 투입(timing)** 전략이다.

원본 알고리즘:

1. **매수**
   - MA20 터치 → 현금의 10% 매수
   - MA60 부근 → 현금의 50% 매수, 5일 분할
   - MA120 부근 → 현금의 50% 매수, 5일 분할
   - MA120 아래 & RSI 30 아래 → 현금 100% 매수, 40일 분할
2. **매도(현금 확보)**
   - RSI 70 이상 → 5일 분할 매도로 목표 현금비중 확보
3. 트리거가 안 오면 "즐기는 구간"(대기)

## 목표 / 범위

- **백테스트 연구용 먼저.** 새 엔진으로 등록해 `run-compare-backtest`에서
  기존 전략들과 성과 비교가 가능해야 한다.
- **대상: QLD 단일 종목**(변동성 큰 레버리지 ETF). 현금은 예수금으로 보유.
- **현금 모델: 초기 일시불**(외부 적립 유입 없음). "근로소득 저축"은 후속 범위.
- **라이브 영속성을 설계 단계에서 확정**하여, 백테스트만 배선해도 라이브 전환 시
  영속성 로직을 다시 짤 필요가 없게 한다.

## 핵심 결정 사항

| 항목 | 결정 |
|---|---|
| 대상 자산 | QLD 단일 종목 |
| 트리거 판정 | **종가 ±2% 밴드** (밴드 폭은 파라미터) |
| 분할 금액 기준 | **트리거 시점에 `현금×비중`을 고정**해 N등분 (큐) |
| 중첩 트리거 | 큐에 누적, 활성 트랜치들의 당일 슬라이스 합산(병행 소진) |
| 매도 목표 현금비중 | **20%** |
| 매도 트리거 | **A+B**: price>ma120(추세 위) **그리고** RSI 70 상향 후 하향 돌파(꺾임 확인) |
| 영속성 | 국면 히스테리시스와 동일 패턴(repo 저장 → 생성 시 복원) |

## 선택한 접근법: 전용 엔진 + 전용 순수 로직 컴포넌트

`TradingEngine`(Template Method)을 상속하여 `collect_data` /
`calculate_indicators` / `execute_cycle`만 오버라이드한다. 지표·트리거 로직은
`core/logic`에 별도 컴포넌트로 분리한다(SRP).

기각한 대안:
- **B안 — `MarketData` 확장 + `Rebalancer` 재사용**: MA20/60/120/RSI를 공용
  frozen 모델에 추가하면 한 엔진만 쓰는 필드로 모델이 오염되고, 그룹비율
  리밸런싱 모델과 트리거/트랜치 로직이 맞지 않아 억지 결합이 된다.
- **C안 — 프레임워크 밖 독립 스크립트**: "백테스트는 프로덕션 로직 100% 재사용,
  코드 분기 없음" 규칙 위반, 비교 백테스트 불가.

## 영속성 설계 (백테스트 = 라이브 단일 코드 경로)

기존 시스템은 이미 "프로세스 수명을 넘는 상태"를 다음 패턴으로 유지한다
(국면 히스테리시스 `_prev_regime`):

1. 저장: `update_status()` → `status.json`
2. 복원: 엔진 `__init__`에서 `repo.load_last_regime()` (`base.py`)
3. 커밋: 라이브 워크플로우가 실행 후 `docs/data/**/*.json` 자동 커밋

트랜치 큐도 같은 종류의 상태이므로 **동일 패턴**을 따른다. 핵심은 큐를
플래너 내부 필드가 아니라 **직렬화 가능한 명시적 상태 객체**로 입출력하여
영속화를 자명하게 만드는 것이다.

### 영속 상태 스키마 (`strategy_state.json`)

```json
{
  "queue": [
    {"side": "BUY", "per_day_amount": 1234.5, "remaining_days": 4}
  ],
  "armed": {"ma20": true, "ma60": false, "ma120": true, "dip": true, "sell": false}
}
```

- `queue`: 활성 트랜치 목록. 각 트랜치는 트리거 시점에 고정된 1일 슬라이스
  금액(`per_day_amount`)과 남은 일수(`remaining_days`).
- `armed`: 트리거별 무장 플래그. "밴드 진입 순간 1회 발동, 밴드 이탈 시 재무장"의
  엣지 트리거를 위해 어제 밴드 안에 있었는지 기억한다. **반드시 영속화 대상.**

### 왜 분기 없이 둘 다 동작하는가

- **백테스트**: 엔진 1회 생성 → 첫 사이클에 빈 상태 로드(per-engine 디렉터리는
  `runner.py`에서 `shutil.rmtree`로 초기화) → 이후 매 사이클 메모리에서 갱신 +
  repo 저장. 인메모리 큐는 repo 영속 상태의 캐시일 뿐이다.
- **라이브**: 엔진 매일 재생성 → repo에서 어제 상태 로드 → 갱신 → 저장. 워크플로우가
  `strategy_state.json`을 자동 커밋.
- 진실의 원천(source of truth)은 repo이며, `_prev_regime`과 구조가 완전히 동일하다.

## 구성 요소

```
src/core/logic/dip_buy_indicators.py   # DipBuyIndicatorCalculator → DipBuySignals
src/core/logic/dip_buy_planner.py      # DipBuyPlanner (순수, 무상태) + 상태 dataclass
src/core/engine/dip_buy.py             # DipBuyEngine(TradingEngine) @register_engine
tests/test_core_logic_dip_buy.py       # 지표/플래너 단위 테스트
tests/test_core_engine_dip_buy.py      # 엔진 통합 테스트(MockBroker + 합성 가격)
```

### DipBuySignals (경량 dataclass, `dip_buy_indicators.py`)

```python
@dataclass(frozen=True)
class DipBuySignals:
    date: str
    price: float      # 종가
    ma20: float
    ma60: float
    ma120: float
    rsi: float        # RSI(14)
```

공용 `MarketData`는 건드리지 않는다(SRP, 대시보드/repo 호환 유지).

### DipBuyIndicatorCalculator

OHLCV(종가)에서 MA20/60/120, RSI(14, Wilder smoothing)를 계산해 `DipBuySignals`
반환. 데이터 부족(<120행) 또는 NaN이면 해당 필드를 NaN으로 두어 엔진이 매매를
스킵하게 한다.

### DipBuyPlanner (순수, 무상태)

```python
@dataclass
class DipBuyState:
    queue: list[Tranche]            # 활성 트랜치
    armed: dict[str, bool]          # 매수 트리거별 무장 플래그(ma20/ma60/ma120/dip)
    rsi_was_overbought: bool        # 직전 RSI>70 도달 여부(매도 꺾임 판정용)
    # to_dict() / from_dict() 로 JSON 직렬화

@dataclass
class Tranche:
    side: str            # "BUY" | "SELL"
    per_day_amount: float
    remaining_days: int

class DipBuyPlanner:
    def plan(self, signals, portfolio, state) -> (orders, reason, new_state): ...
```

**plan() 로직(매 거래일):**

1. **매수 트리거 평가** (종가 기준, 밴드폭 `band`=0.02):
   - `in_band(price, ma, band)`: `|price/ma - 1| <= band`
   - `ma20` 밴드 진입 & `armed.ma20` → 매수 트랜치(현금×0.10, 1일) 적재, `armed.ma20=False`
   - `ma60` 밴드 진입 & `armed.ma60` → 매수 트랜치(현금×0.50, 5일) 적재, `armed.ma60=False`
   - `ma120` 밴드 진입 & `armed.ma120` → 매수 트랜치(현금×0.50, 5일) 적재, `armed.ma120=False`
   - `price < ma120` & `rsi < 30` & `armed.dip` → 매수 트랜치(현금×1.00, 40일) 적재, `armed.dip=False`
2. **매도 트리거 평가 (A+B 추세 필터)**: RSI는 모멘텀 지표일 뿐 추세를 구분하지
   못하므로 단독 매도는 하락장 반등/횡보장 상단에서도 발동한다. 따라서:
   - `rsi > 70` → `rsi_was_overbought=True` (과매수 도달만 기록, 매도 안 함)
   - `rsi <= 70` & 직전 `rsi_was_overbought` & `price > ma120` → 매도 트랜치
     (목표 현금비중 20%까지 부족분, 5일) 적재 (B. 꺾임 확인 + A. 추세 위)
   - `rsi <= 70`이면 `rsi_was_overbought=False`로 재무장 (추세 아래면 매도 없이 종료
     → 데드캣 바운스에 바닥 매수분을 되파는 사고 방지)
3. **재무장(매수)**: 각 매수 트리거 조건이 더 이상 성립하지 않으면 해당 `armed=True`로
   복귀 (밴드 이탈). → 같은 신호가 매일 재발동하는 것 방지.
4. **당일 슬라이스 산출**: 모든 활성 트랜치에서 `per_day_amount`를 합산,
   `remaining_days -= 1`, 0 되면 큐에서 제거.
5. **주문 생성**:
   - 매수: 합산 매수금액을 가용현금으로 캡 → `floor(amount / price)`주 BUY
   - 매도: 합산 매도금액 → `ceil(amount / price)`주(보유 수량 한도) SELL
6. **반환**: orders, reason(사유 문자열), new_state

> 가격 가드: `price`(대상 티커)가 없음/NaN/≤0이면 상태 변경 없이 조기 반환
> (트랜치 헛소진 방지).

**엣지 처리:**
- 현금 0 → 매수 트랜치 슬라이스 스킵(트랜치는 유지, remaining_days만 감소하지
  않도록 — 자금 복귀 시 재개) ※ 단순화를 위해 "현금 부족이면 가능한 만큼만 매수,
  remaining_days는 정상 감소"로 시작하고 백테스트로 검증.
- 보유 0 & 매도 트리거 → 매도 트랜치 미적재
- RSI NaN 등 지표 계산 불가 → 해당 트리거 비활성

### IRepository 상태 저장 포트 (안전한 기본 no-op)

`ILogger`의 캡처 메서드 패턴(추상 아님 + 안전한 기본 구현)을 따른다.

```python
def load_strategy_state(self, key: str) -> dict:   # 기본 {} 반환
    return {}
def save_strategy_state(self, key: str, state: dict) -> None:  # 기본 no-op
    return None
```

`JsonRepository`는 repo 루트의 `strategy_state.json`에 `{key: state}` 형태로 저장.
status.json 스키마 불변(대시보드 무영향).

### DipBuyEngine

```python
@register_engine(color="#...", backtest=True)
class DipBuyEngine(TradingEngine):
    ASSET_GROUPS = {'A': ['QLD']}      # 현금은 예수금으로 보유
    BAND = 0.02
    SELL_TARGET_CASH_RATIO = 0.20
    STATE_KEY = "dip_buy"
```

- `__init__`: super 호출 후 `self.dip_state = DipBuyState.from_dict(
  repo.load_strategy_state(STATE_KEY))` (국면 복원과 나란히)
- `collect_data`: SPY 대신 `ASSET_GROUPS['A'][0]`(QLD) OHLCV(400일) + VIX
- `calculate_indicators`:
  ① 기존 `IndicatorCalculator`로 `MarketData` 생성(대시보드/repo 호환, QLD 기준)
  ② `DipBuyIndicatorCalculator`로 `DipBuySignals` 생성 → `self.dip_signals`
- `execute_cycle` 오버라이드: NaN/가격 가드는 기존 로직 재사용, 정상 시
  `Rebalancer` 대신 `planner.plan(self.dip_signals, portfolio, self.dip_state)` →
  주문 실행 → `self.dip_state = new_state` → `repo.save_strategy_state(STATE_KEY, ...)`
- `trading_interval_days`와 무관하게 매 거래일 평가(execute_cycle 자체 제어).

## 데이터 흐름 (매 거래일)

```
run_one_cycle
  ├─ collect_data            → QLD OHLCV(400d), VIX
  ├─ calculate_indicators    → MarketData(QLD 기준) + DipBuySignals(MA20/60/120, RSI)
  ├─ analyze_strategy        → 기존 NaN 가드 + 국면(로깅/대시보드용), exposure는 보고용
  ├─ get_portfolio
  ├─ execute_cycle(override)
  │     planner.plan(signals, pf, dip_state) → orders, reason, new_state
  │     broker.execute_orders(orders)
  │     repo.save_strategy_state("dip_buy", new_state.to_dict())
  └─ persist                 → 기존 summary/history/status 저장(스키마 무변경)
```

## 변경 / 신규 파일

| 파일 | 변경 내용 |
|---|---|
| `src/core/logic/dip_buy_indicators.py` | 신규: `DipBuySignals`, `DipBuyIndicatorCalculator` |
| `src/core/logic/dip_buy_planner.py` | 신규: `Tranche`, `DipBuyState`, `DipBuyPlanner` |
| `src/core/logic/__init__.py` | 신규 컴포넌트 export |
| `src/core/engine/dip_buy.py` | 신규: `DipBuyEngine` |
| `src/core/engine/__init__.py` | `dip_buy` 모듈 import(레지스트리 등록) |
| `src/core/interfaces.py` | `IRepository`에 `load/save_strategy_state` 기본 메서드 추가 |
| `src/infra/repo.py` | `strategy_state.json` 입출력 구현 |
| `tests/test_core_logic_dip_buy.py` | 지표·플래너 단위 테스트 |
| `tests/test_core_engine_dip_buy.py` | 엔진 통합 테스트 |

## 테스트 전략

- **순수 단위(mock 불필요)**:
  - 지표: MA20/60/120, RSI(14) 값 정확도(합성 가격으로 기대값 검증)
  - 밴드 엣지 트리거: 진입 시 1회 발동, 밴드 안 머무는 동안 재발동 없음, 이탈 후 재무장
  - 큐: 다중 트리거 누적, 5일/40일 분할 슬라이스 합산·소진, remaining_days 감소
  - 현금 캡: 합산 매수 > 가용현금 시 캡
  - 매도: RSI>70 → 목표 현금비중 20%까지 5일 분할, 보유 한도
  - 직렬화: `DipBuyState.to_dict/from_dict` 라운드트립
- **엔진 통합**: `MockBroker` + 합성 가격 시계열로 `run_one_cycle` 다일 시나리오,
  상태가 `save/load_strategy_state` 라운드트립으로 유지되는지(라이브 재시작 모사) 검증
- 커버리지 80% 충족(`.claude/rules/testing.md`)

## 후속(이번 범위 외)

- 라이브 배선: `main.py`에서 DipBuyEngine 계정 추가, 스케줄 워크플로우 연결
- 정기 적립(근로소득) 유입 모델
- 현금 부족 시 트랜치 일시정지(remaining_days 동결) 정교화
