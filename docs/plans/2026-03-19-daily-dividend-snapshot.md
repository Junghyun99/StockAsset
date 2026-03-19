# Daily Dividend Snapshot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `save_daily_summary`가 저장하는 일별 스냅샷에 그날의 총 배당금(`daily_dividend`)을 기록한다.

**Architecture:** 배당 계산은 호출자(runner.py, main.py)가 담당하고, `run_one_cycle(daily_dividend=0.0)` 파라미터로 엔진에 전달한다. 엔진은 받은 값을 `persist()` → `save_daily_summary()`로 내려보내 JSON에 저장만 한다. 실거래는 `YFinanceLoader.fetch_daily_dividends()`를 새로 추가해 yfinance에서 조회한다.

**Tech Stack:** Python 3.10, yfinance, pytest, unittest.mock

---

### Task 1: `DayResult` 모델에 `daily_dividend` 필드 추가

**Files:**
- Modify: `src/core/models.py` (DayResult dataclass, 약 96~106줄)
- Test: `tests/test_core_engine.py`

**Step 1: 실패 테스트 작성**

`tests/test_core_engine.py` 파일 맨 아래에 아래 테스트를 추가한다.

```python
def test_day_result_daily_dividend_default_zero():
    """DayResult 생성 시 daily_dividend 기본값이 0.0인지 확인"""
    from src.core.models import DayResult, MarketData, MarketRegime, TradeSignal
    import math

    result = DayResult(
        market_data=MarketData("2024-01-01", 100.0, 90.0, 0.12, 0.05, -0.05, 18.0),
        regime=MarketRegime.BULL,
        exposure=1.0,
        signal=TradeSignal(1.0, [], "test"),
        executions=[],
        final_pf=Portfolio(1000.0, {}, {}),
        is_rebalancing=False,
        nan_fields=[],
    )
    assert result.daily_dividend == 0.0


def test_day_result_daily_dividend_set():
    """DayResult에 daily_dividend 값을 설정할 수 있는지 확인"""
    from src.core.models import DayResult, MarketData, MarketRegime, TradeSignal

    result = DayResult(
        market_data=MarketData("2024-01-01", 100.0, 90.0, 0.12, 0.05, -0.05, 18.0),
        regime=MarketRegime.BULL,
        exposure=1.0,
        signal=TradeSignal(1.0, [], "test"),
        executions=[],
        final_pf=Portfolio(1000.0, {}, {}),
        is_rebalancing=False,
        nan_fields=[],
        daily_dividend=42.5,
    )
    assert result.daily_dividend == 42.5
```

**Step 2: 테스트 실패 확인**

```bash
pytest tests/test_core_engine.py::test_day_result_daily_dividend_default_zero -v
```
Expected: `FAILED` — `DayResult.__init__() got an unexpected keyword argument 'daily_dividend'`

**Step 3: 최소 구현**

`src/core/models.py`의 `DayResult` 클래스 끝에 필드 추가:

```python
@dataclass
class DayResult:
    """하루치 트레이딩 사이클 실행 결과"""
    market_data: MarketData
    regime: MarketRegime
    exposure: float
    signal: TradeSignal
    executions: List[TradeExecution]
    final_pf: Portfolio
    is_rebalancing: bool
    nan_fields: List[str]
    daily_dividend: float = 0.0   # ← 추가
```

**Step 4: 테스트 통과 확인**

```bash
pytest tests/test_core_engine.py::test_day_result_daily_dividend_default_zero tests/test_core_engine.py::test_day_result_daily_dividend_set -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add src/core/models.py tests/test_core_engine.py
git commit -m "feat: DayResult에 daily_dividend 필드 추가"
```

---

### Task 2: `IRepository` 인터페이스 + `JsonRepository` 저장 구현

**Files:**
- Modify: `src/core/interfaces.py` (IRepository.save_daily_summary 시그니처)
- Modify: `src/infra/repo.py` (JsonRepository.save_daily_summary 구현)
- Test: `tests/test_infra_repo.py`

**Step 1: 실패 테스트 작성**

`tests/test_infra_repo.py` 파일 맨 아래에 추가:

```python
def test_save_daily_summary_records_dividend(repo, dummy_market_data, dummy_portfolio):
    """daily_dividend가 summary.json 레코드에 저장되는지 확인"""
    import json
    signal = TradeSignal(1.0, [], "test")

    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL,
                            daily_dividend=55.25)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)

    assert data[0]['daily_dividend'] == 55.25


def test_save_daily_summary_default_dividend_zero(repo, dummy_market_data, dummy_portfolio):
    """daily_dividend 미전달 시 기본값 0.0으로 저장되는지 확인"""
    import json
    signal = TradeSignal(1.0, [], "test")

    repo.save_daily_summary(dummy_market_data, signal, dummy_portfolio, MarketRegime.BULL)

    with open(repo.summary_file, 'r') as f:
        data = json.load(f)

    assert data[0]['daily_dividend'] == 0.0
```

**Step 2: 테스트 실패 확인**

```bash
pytest tests/test_infra_repo.py::test_save_daily_summary_records_dividend -v
```
Expected: `FAILED` — `TypeError: save_daily_summary() got an unexpected keyword argument 'daily_dividend'`

**Step 3: 인터페이스 시그니처 업데이트**

`src/core/interfaces.py`의 `IRepository.save_daily_summary` 추상 메서드:

```python
@abstractmethod
def save_daily_summary(self, market_data: MarketData, signal: TradeSignal,
                       portfolio: Portfolio, regime: MarketRegime,
                       daily_dividend: float = 0.0) -> None: ...
```

**Step 4: `JsonRepository.save_daily_summary` 구현 업데이트**

`src/infra/repo.py`의 `save_daily_summary` 메서드 시그니처와 record dict 수정:

```python
def save_daily_summary(self, market: MarketData, signal: TradeSignal, pf: Portfolio,
                       regime: MarketRegime, daily_dividend: float = 0.0):
    """일별 요약 저장 (Append 방식)"""
    # ... (기존 val_a, val_b, val_c 계산 코드 유지) ...

    record = {
        "date": market.date,

        # [자산 정보]
        "total_value": pf.total_value,
        "cash_balance": pf.total_cash,
        "group_a": val_a,
        "group_b": val_b,
        "group_c": val_c_total,
        "daily_dividend": daily_dividend,   # ← 추가
        # [시장 지표]
        "spy_price": market.spy_price,
        # ... (나머지 기존 필드 유지) ...
    }
    # ... (나머지 저장 로직 유지) ...
```

**Step 5: 테스트 통과 확인**

```bash
pytest tests/test_infra_repo.py::test_save_daily_summary_records_dividend tests/test_infra_repo.py::test_save_daily_summary_default_dividend_zero -v
```
Expected: `2 passed`

**Step 6: 기존 테스트 전체 확인**

```bash
pytest tests/test_infra_repo.py -v
```
Expected: 모두 `passed`

**Step 7: Commit**

```bash
git add src/core/interfaces.py src/infra/repo.py tests/test_infra_repo.py
git commit -m "feat: save_daily_summary에 daily_dividend 파라미터 추가 및 JSON 저장"
```

---

### Task 3: `TradingEngine` — `run_one_cycle` / `persist` 파라미터 연결

**Files:**
- Modify: `src/core/engine.py` (`run_one_cycle`, `persist` 메서드)
- Test: `tests/test_core_engine.py`

**Step 1: 실패 테스트 작성**

`tests/test_core_engine.py`에 추가:

```python
def test_run_one_cycle_passes_daily_dividend_to_repo():
    """run_one_cycle(daily_dividend=X) 전달 시 repo.save_daily_summary에 X가 전달되는지 확인"""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")
    mocks["broker"].execute_orders.return_value = []

    engine.run_one_cycle(mocks["data_provider"], daily_dividend=99.9)

    call_kwargs = mocks["repo"].save_daily_summary.call_args
    assert call_kwargs.kwargs.get("daily_dividend") == 99.9 \
        or (len(call_kwargs.args) >= 5 and call_kwargs.args[4] == 99.9)


def test_run_one_cycle_day_result_contains_daily_dividend():
    """DayResult.daily_dividend에 전달된 값이 반영되는지 확인"""
    engine, mocks = _make_engine(repo_last_reb=None)
    md = _make_market_data()

    mocks["calculator"].calculate.return_value = md
    mocks["analyzer"].analyze.return_value = MarketRegime.BULL
    mocks["targeter"].calculate_exposure.return_value = 1.0
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [], "Hold")
    mocks["broker"].execute_orders.return_value = []

    result = engine.run_one_cycle(mocks["data_provider"], daily_dividend=77.3)

    assert result.daily_dividend == 77.3
```

**Step 2: 테스트 실패 확인**

```bash
pytest tests/test_core_engine.py::test_run_one_cycle_passes_daily_dividend_to_repo -v
```
Expected: `FAILED` — `run_one_cycle() got an unexpected keyword argument 'daily_dividend'`

**Step 3: 엔진 구현 업데이트**

`src/core/engine.py`에서 다음 두 메서드를 수정한다.

`run_one_cycle` 시그니처 및 `persist` 호출부:
```python
def run_one_cycle(
    self,
    data_provider: IDataProvider,
    sim_date: Optional[str] = None,
    daily_dividend: float = 0.0,        # ← 추가
) -> DayResult:
    # ... (기존 Step 1~5 코드 유지) ...

    # Step 6: 저장
    self.logger.info(">>> Step 6: Archiving Data")
    self.persist(market_data, signal, executions, final_pf, regime, exposure,
                 is_rebalancing, sim_date, daily_dividend)   # ← daily_dividend 추가

    return DayResult(
        market_data=market_data,
        regime=regime,
        exposure=exposure,
        signal=signal,
        executions=executions,
        final_pf=final_pf,
        is_rebalancing=is_rebalancing,
        nan_fields=nan_fields,
        daily_dividend=daily_dividend,   # ← 추가
    )
```

`persist` 시그니처 및 `save_daily_summary` 호출부:
```python
def persist(
    self,
    market_data: MarketData,
    signal: TradeSignal,
    executions: List[TradeExecution],
    final_pf: Portfolio,
    regime: MarketRegime,
    exposure: float,
    is_rebalancing: bool,
    sim_date: Optional[str],
    daily_dividend: float = 0.0,        # ← 추가
) -> None:
    """Step 6: 저장 3종 호출."""
    rebalancing_date = (sim_date or market_data.date) if is_rebalancing else None
    self.repo.save_daily_summary(market_data, signal, final_pf, regime,
                                 daily_dividend=daily_dividend)   # ← 추가
    self.repo.save_trade_history(executions, final_pf, signal.reason, sim_date=sim_date)
    self.repo.update_status(
        regime, exposure, final_pf, market_data, signal.reason,
        sim_date=sim_date,
        rebalancing_date=rebalancing_date,
    )
```

**Step 4: 테스트 통과 확인**

```bash
pytest tests/test_core_engine.py::test_run_one_cycle_passes_daily_dividend_to_repo tests/test_core_engine.py::test_run_one_cycle_day_result_contains_daily_dividend -v
```
Expected: `2 passed`

**Step 5: 기존 엔진 테스트 전체 확인**

```bash
pytest tests/test_core_engine.py -v
```
Expected: 모두 `passed`

**Step 6: Commit**

```bash
git add src/core/engine.py tests/test_core_engine.py
git commit -m "feat: run_one_cycle/persist에 daily_dividend 파라미터 연결"
```

---

### Task 4: `YFinanceLoader.fetch_daily_dividends()` 추가

**Files:**
- Modify: `src/infra/data.py`
- Test: `tests/test_infra_data.py`

**Step 1: 실패 테스트 작성**

`tests/test_infra_data.py` 파일 맨 아래에 추가:

```python
def test_fetch_daily_dividends_returns_dividend_on_ex_date(mock_yf_download, mock_logger):
    """오늘 배당락일인 종목의 주당 배당금을 반환하는지 확인"""
    from datetime import date
    import pandas as pd

    today = pd.Timestamp(date.today())
    # Dividends 컬럼이 있는 MultiIndex DataFrame 생성
    columns = pd.MultiIndex.from_product([['Close', 'Dividends'], ['IEF', 'GLD']])
    data = {
        ('Close', 'IEF'): [100.0],
        ('Close', 'GLD'): [200.0],
        ('Dividends', 'IEF'): [0.35],
        ('Dividends', 'GLD'): [0.0],
    }
    mock_df = pd.DataFrame(data, index=[today])
    mock_yf_download.return_value = mock_df

    loader = YFinanceLoader(mock_logger)
    result = loader.fetch_daily_dividends(['IEF', 'GLD'])

    assert result == {'IEF': 0.35}   # GLD는 0이므로 제외


def test_fetch_daily_dividends_returns_empty_when_no_dividend(mock_yf_download, mock_logger):
    """오늘 배당이 없으면 빈 dict 반환"""
    from datetime import date, timedelta
    import pandas as pd

    yesterday = pd.Timestamp(date.today() - timedelta(days=1))
    columns = pd.MultiIndex.from_product([['Close', 'Dividends'], ['IEF']])
    data = {('Close', 'IEF'): [100.0], ('Dividends', 'IEF'): [0.35]}
    mock_df = pd.DataFrame(data, index=[yesterday])   # 오늘 날짜 없음
    mock_yf_download.return_value = mock_df

    loader = YFinanceLoader(mock_logger)
    result = loader.fetch_daily_dividends(['IEF'])

    assert result == {}


def test_fetch_daily_dividends_returns_empty_on_error(mock_yf_download, mock_logger):
    """yfinance 오류 시 빈 dict 반환 (봇 중단 없음)"""
    mock_yf_download.side_effect = Exception("Network Error")

    loader = YFinanceLoader(mock_logger)
    result = loader.fetch_daily_dividends(['IEF'])

    assert result == {}
    mock_logger.error.assert_called_once()
```

**Step 2: 테스트 실패 확인**

```bash
pytest tests/test_infra_data.py::test_fetch_daily_dividends_returns_dividend_on_ex_date -v
```
Expected: `FAILED` — `AttributeError: 'YFinanceLoader' object has no attribute 'fetch_daily_dividends'`

**Step 3: 구현**

`src/infra/data.py`의 `YFinanceLoader` 클래스 끝에 메서드 추가:

```python
def fetch_daily_dividends(self, tickers: List[str]) -> Dict[str, float]:
    """오늘 날짜의 티커별 주당 배당금 조회. {ticker: div_per_share}.
    배당락일이 아니거나 오류 시 {} 반환.
    """
    from datetime import date as _date
    try:
        df = yf.download(tickers, period="5d", auto_adjust=False, actions=True, progress=False)
        if df is None or df.empty:
            return {}
        if not isinstance(df.columns, pd.MultiIndex) and len(tickers) == 1:
            df.columns = pd.MultiIndex.from_product([df.columns, tickers])
        level0 = df.columns.get_level_values(0)
        if "Dividends" not in level0:
            return {}
        divs = df["Dividends"]
        if isinstance(divs, pd.Series):
            divs = divs.to_frame(name=tickers[0])
        today_ts = pd.Timestamp(_date.today())
        if today_ts not in divs.index:
            return {}
        row = divs.loc[today_ts]
        return {t: float(v) for t, v in row.items() if float(v) > 0}
    except Exception as e:
        self.logger.error(f"[Data] ❌ Error fetching dividends: {e}. Returning empty.")
        return {}
```

`src/infra/data.py` 상단에 `Dict` 임포트 추가 (기존 `from typing import List` → `from typing import List, Dict`):

```python
from typing import List, Dict
```

**Step 4: 테스트 통과 확인**

```bash
pytest tests/test_infra_data.py::test_fetch_daily_dividends_returns_dividend_on_ex_date tests/test_infra_data.py::test_fetch_daily_dividends_returns_empty_when_no_dividend tests/test_infra_data.py::test_fetch_daily_dividends_returns_empty_on_error -v
```
Expected: `3 passed`

**Step 5: 기존 data 테스트 전체 확인**

```bash
pytest tests/test_infra_data.py -v
```
Expected: 모두 `passed`

**Step 6: Commit**

```bash
git add src/infra/data.py tests/test_infra_data.py
git commit -m "feat: YFinanceLoader에 fetch_daily_dividends() 추가"
```

---

### Task 5: `main.py` 실거래 배당 계산 연결

**Files:**
- Modify: `src/main.py` (`TradingBot.run()` 메서드)

> 이 Task는 실거래 환경 의존도가 높아 unit test 대신 코드 수정만 진행한다.

**Step 1: `run()` 메서드 수정**

`src/main.py`의 `run()` 메서드를 다음과 같이 수정한다:

```python
def run(self):
    try:
        # 배당 계산: 당일 보유 수량 × 주당 배당금
        daily_dividend = 0.0
        try:
            portfolio = self.broker.get_portfolio()
            divs = self.data_loader.fetch_daily_dividends(self.engine.all_tickers)
            daily_dividend = sum(
                portfolio.holdings.get(t, 0) * div
                for t, div in divs.items()
            )
        except Exception as e:
            self.logger.warning(f"배당 조회 실패, 0.0으로 처리: {e}")

        self.engine.run_one_cycle(self.data_loader, daily_dividend=daily_dividend)
    except Exception as e:
        error_msg = f"Critical Error:\n{traceback.format_exc()}"
        self.logger.error(error_msg)
        self.notifier.send_alert(f"🔥 Bot Crashed!\n{str(e)}")
        raise e
```

**Step 2: 전체 테스트 통과 확인**

```bash
pytest tests/ -v --ignore=tests/test_infra_data_live.py
```
Expected: 모두 `passed`

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: main.py 실거래에서 daily_dividend 계산 후 엔진에 전달"
```

---

### Task 6: `runner.py` 백테스트 배당 전달

**Files:**
- Modify: `src/backtest/runner.py` (시뮬레이션 루프)

**Step 1: 수정 위치 확인**

`src/backtest/runner.py`의 시뮬레이션 루프에서 `engine.run_one_cycle` 호출부를 찾는다 (현재 약 249줄).

현재:
```python
result = ctx["engine"].run_one_cycle(ctx["loader"], sim_date=sim_date)
```

**Step 2: `div_income`을 `run_one_cycle`에 전달**

```python
result = ctx["engine"].run_one_cycle(
    ctx["loader"],
    sim_date=sim_date,
    daily_dividend=div_income,   # ← 추가
)
```

> `div_income`은 이미 같은 루프 블록 안에서 계산되어 있다 (`reinvest_dividends` 블록). `div_income`이 정의되지 않는 경우(`reinvest_dividends=False`)를 위해 루프 변수 초기화가 필요하다.

루프 블록 상단(엔진별 루프 안쪽 시작)에 `div_income = 0.0` 초기화를 추가한다:

```python
for name, ctx in engines.items():
    ctx["loader"].set_date(today)
    ctx["broker"].set_date(today)
    ctx["broker"].set_prices(current_prices)

    div_income = 0.0                # ← 추가 (reinvest_dividends=False 경우 대비)
    if reinvest_dividends:
        div_income = _calculate_dividend_income(today, full_dividends, ctx["broker"])
        if div_income > 0:
            ctx["broker"].receive_dividends(div_income)
            ctx["dividend_income"] += div_income

    try:
        result = ctx["engine"].run_one_cycle(
            ctx["loader"],
            sim_date=sim_date,
            daily_dividend=div_income,   # ← 추가
        )
```

**Step 3: 전체 테스트 통과 확인**

```bash
pytest tests/ -v --ignore=tests/test_infra_data_live.py
```
Expected: 모두 `passed`

**Step 4: 커버리지 포함 최종 확인**

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/ --ignore=tests/test_infra_data_live.py
```
Expected: 커버리지 80% 이상, 모두 `passed`

**Step 5: Commit & Push**

```bash
git add src/backtest/runner.py
git commit -m "feat: 백테스트 runner에서 daily_dividend를 run_one_cycle에 전달"
git push -u origin claude/review-daily-summary-save-iCH7n
```
