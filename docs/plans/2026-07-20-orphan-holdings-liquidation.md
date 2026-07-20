# 고아 종목 자동 청산 (Orphan Holdings Liquidation) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 엔진 변경 시 이전 엔진의 보유 종목(현재 엔진의 A/B/C 그룹에 속하지 않는 종목)을 자동 감지·매도하여, MTS 수동 매도 없이 데이터(net_deposit)가 자연스럽게 이어지도록 한다.

**Architecture:** `TradingEngine.execute_cycle()`에 고아 감지→매도→포트폴리오 갱신 단계를 기존 3-way 분기(NaN/모니터링/리밸런싱) 앞에 삽입한다. 고아 매도는 리밸런싱 인터벌과 무관하게 즉시 실행하며, 매도 체결 내역이 `executions`에 포함되어 `net_deposit` 역산에 자동 반영된다. 순수 도메인 로직이므로 core 계층만 수정한다.

**Tech Stack:** Python 3.10, pytest, unittest.mock

---

## 설계 요점

### 왜 execute_cycle에 넣는가
- 고아 매도는 "매매 행위"이므로 Step 5 (execute_cycle) 범위에 속한다.
- Step 4 (get_portfolio)는 조회 전용이므로 매매를 넣지 않는다 (CQS 원칙).
- `deactivated_cycle`에는 넣지 않는다 — 비활성 계좌는 매매 금지.

### 리밸런싱 인터벌과의 관계
- 고아 매도는 인터벌 체크(`_is_due`) 전에 실행한다.
- 모니터링 날이어도 고아 매도는 진행하고, 이후 정상 흐름(모니터링/리밸런싱)을 탄다.
- 고아 매도만 발생한 모니터링 날: `is_rebalancing=False`, 고아 체결만 executions에 포함.

### net_deposit 정합성
- 고아 매도 체결이 executions에 포함 → `derive_net_deposit`의 `당일체결현금영향`에 반영.
- 결과: 고아 매도로 증가한 현금이 "외부 입금"으로 잡히지 않는다.

### 고아 판정 조건
- `portfolio.holdings`에서 `qty > 0`인 종목 중 `self.all_tickers`에 없는 종목.
- NaN 데이터 이상 시에는 고아 매도도 스킵한다 (데이터 이상 시 모든 매매 중단 원칙 유지).

### get_portfolio에서의 가격 조회
- 현재 `get_portfolio()`는 `self.all_tickers`의 가격만 조회한다.
- 고아 종목의 가격도 조회해야 한다 (total_value 정확성 + 매도 주문가 결정).
- `get_portfolio()`에서 보유 종목 중 `self.all_tickers`에 없는 것의 가격도 함께 조회한다.

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `src/core/engine/base.py` | `get_portfolio()` 고아 가격 조회, `_detect_orphan_holdings()`, `_liquidate_orphans()`, `execute_cycle()` 고아 처리 삽입 |
| `tests/test_core_engine.py` | 고아 감지/매도/net_deposit 검증 테스트 |

---

### Task 1: get_portfolio에서 고아 종목 가격도 조회

현재 `get_portfolio()`는 `self.all_tickers`의 가격만 fetch한다. 고아 종목의 가격이 누락되면 `total_value`가 왜곡되고, 매도 주문가를 결정할 수 없다. 보유 종목 중 엔진 티커에 없는 것의 가격도 함께 조회한다.

**Files:**
- Modify: `src/core/engine/base.py:249-259` (`get_portfolio` 메서드)
- Test: `tests/test_core_engine.py`

**Step 1: Write the failing test**

```python
def test_get_portfolio_fetches_orphan_prices():
    """get_portfolio는 엔진 그룹 외 보유 종목의 가격도 조회한다"""
    engine, mocks = _make_engine()
    # 포트폴리오에 엔진 그룹 외 종목(AAPL)이 있음
    pf_with_orphan = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    mocks["broker"].get_portfolio.return_value = pf_with_orphan
    # fetch_current_prices는 요청된 티커만 반환
    def fake_fetch(tickers):
        prices = {"SSO": 101.0, "QLD": 50.0, "IEF": 90.0, "GLD": 180.0, "SHV": 110.0, "AAPL": 155.0}
        return {t: prices[t] for t in tickers if t in prices}
    mocks["broker"].fetch_current_prices.side_effect = fake_fetch

    result = engine.get_portfolio()

    # AAPL 가격이 실시간 가격(155.0)으로 갱신되어야 한다
    assert result.current_prices["AAPL"] == 155.0
    # 엔진 티커도 정상 갱신
    assert result.current_prices["SSO"] == 101.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_engine.py::test_get_portfolio_fetches_orphan_prices -v`
Expected: FAIL — 현재 코드는 AAPL 가격을 별도 조회하지 않음

**Step 3: Write minimal implementation**

`src/core/engine/base.py`의 `get_portfolio` 메서드를 수정:

```python
def get_portfolio(self) -> Portfolio:
    """Step 4: 포트폴리오 조회 후 실시간 가격 업데이트 + 벤치마크 현재가 수집."""
    portfolio = self.broker.get_portfolio()
    self.logger.info("Fetching Real-time prices from Broker...")
    # 엔진 관리 티커 + 고아 종목(보유 중이나 엔진 그룹에 없는 종목) 가격 조회
    orphan_tickers = [
        t for t in portfolio.holdings
        if portfolio.holdings[t] > 0 and t not in self.all_tickers
    ]
    fetch_tickers = self.all_tickers + orphan_tickers
    real_time_prices = self.broker.fetch_current_prices(fetch_tickers)
    for ticker, price in real_time_prices.items():
        if price > 0:
            portfolio.current_prices[ticker] = price
    self._benchmark_prices = self._fetch_benchmark_prices()
    return portfolio
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_core_engine.py::test_get_portfolio_fetches_orphan_prices -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/engine/base.py tests/test_core_engine.py
git commit -m "feat: get_portfolio에서 고아 종목 가격도 조회"
```

---

### Task 2: _detect_orphan_holdings 헬퍼 추가

포트폴리오에서 현재 엔진의 어떤 그룹(A/B/C)에도 속하지 않는 보유 종목을 감지하는 순수 헬퍼 메서드.

**Files:**
- Modify: `src/core/engine/base.py` (private 헬퍼 섹션, `_is_due` 근처)
- Test: `tests/test_core_engine.py`

**Step 1: Write the failing test**

```python
def test_detect_orphan_holdings_finds_unknown_tickers():
    """엔진 그룹에 없는 보유 종목을 고아로 감지한다"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5, "TSLA": 3, "IEF": 2},
        current_prices={"SSO": 100.0, "AAPL": 150.0, "TSLA": 200.0, "IEF": 90.0},
    )
    orphans = engine._detect_orphan_holdings(pf)
    # SSO, IEF는 엔진 그룹에 속함. AAPL, TSLA만 고아.
    assert sorted(orphans) == ["AAPL", "TSLA"]


def test_detect_orphan_holdings_ignores_zero_qty():
    """보유 수량이 0인 종목은 고아로 감지하지 않는다"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 0},
        current_prices={"SSO": 100.0},
    )
    orphans = engine._detect_orphan_holdings(pf)
    assert orphans == []


def test_detect_orphan_holdings_empty_when_all_managed():
    """모든 보유 종목이 엔진 그룹에 속하면 빈 리스트"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "IEF": 5},
        current_prices={"SSO": 100.0, "IEF": 90.0},
    )
    orphans = engine._detect_orphan_holdings(pf)
    assert orphans == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_engine.py::test_detect_orphan_holdings_finds_unknown_tickers -v`
Expected: FAIL — `AttributeError: 'TradingEngine' has no attribute '_detect_orphan_holdings'`

**Step 3: Write minimal implementation**

`src/core/engine/base.py`의 private helpers 섹션에 추가:

```python
def _detect_orphan_holdings(self, portfolio: Portfolio) -> List[str]:
    """현재 엔진의 어떤 그룹에도 속하지 않는 보유 종목 티커 목록."""
    managed = set(self.all_tickers)
    return [t for t, q in portfolio.holdings.items() if q > 0 and t not in managed]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_core_engine.py -k "detect_orphan" -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/core/engine/base.py tests/test_core_engine.py
git commit -m "feat: _detect_orphan_holdings 헬퍼 추가"
```

---

### Task 3: _liquidate_orphans 메서드 추가

고아 종목의 전량 매도 주문을 생성·실행하고, 포트폴리오를 갱신한다.

**Files:**
- Modify: `src/core/engine/base.py` (private 헬퍼 섹션)
- Test: `tests/test_core_engine.py`

**Step 1: Write the failing test**

```python
def test_liquidate_orphans_sells_all_and_refreshes_portfolio():
    """고아 종목을 전량 매도하고 포트폴리오를 갱신한다"""
    engine, mocks = _make_engine(is_live_trading=False)
    orphan_pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    updated_pf = Portfolio(
        total_cash=5750.0,  # 5000 + 5*150
        holdings={"SSO": 10},
        current_prices={"SSO": 100.0},
    )

    fake_exec = TradeExecution("AAPL", OrderAction.SELL, 5, 150.0, 0.5, "2024-01-10", ExecutionStatus.FILLED)
    mocks["broker"].execute_orders.return_value = [fake_exec]
    mocks["broker"].get_portfolio.return_value = updated_pf
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 101.0}

    execs, result_pf = engine._liquidate_orphans(orphan_pf, ["AAPL"])

    # SELL 주문이 나갔는지 확인
    sell_orders = mocks["broker"].execute_orders.call_args[0][0]
    assert len(sell_orders) == 1
    assert sell_orders[0].ticker == "AAPL"
    assert sell_orders[0].action == OrderAction.SELL
    assert sell_orders[0].quantity == 5
    assert sell_orders[0].price == 150.0
    # 체결 결과 반환
    assert execs == [fake_exec]
    # 포트폴리오 갱신됨
    assert result_pf.total_cash == 5750.0


def test_liquidate_orphans_skips_zero_price():
    """가격 조회 실패(0원) 종목은 매도하지 않는다"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"AAPL": 5},
        current_prices={"AAPL": 0.0},  # 가격 없음
    )

    execs, result_pf = engine._liquidate_orphans(pf, ["AAPL"])

    mocks["broker"].execute_orders.assert_not_called()
    assert execs == []
    assert result_pf is pf  # 원본 그대로 반환
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_engine.py::test_liquidate_orphans_sells_all_and_refreshes_portfolio -v`
Expected: FAIL — `AttributeError: 'TradingEngine' has no attribute '_liquidate_orphans'`

**Step 3: Write minimal implementation**

`src/core/engine/base.py`의 private helpers 섹션에 추가:

```python
def _liquidate_orphans(
    self, portfolio: Portfolio, orphan_tickers: List[str]
) -> Tuple[List[TradeExecution], Portfolio]:
    """고아 종목 전량 매도 → 체결 결과 + 갱신된 포트폴리오 반환."""
    orders = []
    for ticker in orphan_tickers:
        qty = portfolio.holdings.get(ticker, 0)
        price = portfolio.current_prices.get(ticker, 0)
        if qty > 0 and price > 0:
            orders.append(Order(ticker, OrderAction.SELL, qty, price))
            self.logger.info(
                f"[고아 종목] {ticker_display(ticker)}: {qty}주 @${price:,.0f} → 전량 매도"
            )
        elif qty > 0:
            self.logger.warning(
                f"[고아 종목] {ticker_display(ticker)}: {qty}주 보유 중이나 가격 조회 실패 → 매도 스킵"
            )

    if not orders:
        return [], portfolio

    self.logger.info(f">>> 고아 종목 청산: {len(orders)}건 매도 실행")
    executions = self.broker.execute_orders(orders)

    if executions and self.is_live_trading:
        time.sleep(3)
    try:
        updated_pf = self.broker.get_portfolio()
        all_fetch = self.all_tickers + orphan_tickers
        real_time_prices = self.broker.fetch_current_prices(all_fetch)
        for t, p in real_time_prices.items():
            if p > 0:
                updated_pf.current_prices[t] = p
        self._benchmark_prices = self._fetch_benchmark_prices()
        return executions, updated_pf
    except RuntimeError as e:
        self.logger.error(f"⚠️ 고아 청산 후 포트폴리오 조회 실패: {e}")
        return executions, portfolio
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_core_engine.py -k "liquidate_orphans" -v`
Expected: 2 PASS

**Step 5: Commit**

```bash
git add src/core/engine/base.py tests/test_core_engine.py
git commit -m "feat: _liquidate_orphans 고아 종목 전량 매도 메서드"
```

---

### Task 4: execute_cycle에 고아 처리 삽입

`execute_cycle` 3-way 분기(NaN/모니터링/리밸런싱) 앞에 고아 감지→매도를 삽입한다. NaN 데이터 이상 시에는 고아 매도도 스킵한다.

**Files:**
- Modify: `src/core/engine/base.py:280-400` (`execute_cycle` 메서드)
- Test: `tests/test_core_engine.py`

**Step 1: Write the failing test**

```python
def test_execute_cycle_liquidates_orphans_before_rebalancing():
    """execute_cycle은 고아 종목을 먼저 매도한 뒤 리밸런싱을 진행한다"""
    engine, mocks = _make_engine(repo_last_reb=None)  # 인터벌 충족
    # 포트폴리오: 엔진 종목(SSO) + 고아(AAPL)
    pf_before = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    pf_after_orphan_sell = Portfolio(
        total_cash=5750.0,
        holdings={"SSO": 10},
        current_prices={"SSO": 100.0},
    )
    orphan_exec = TradeExecution("AAPL", OrderAction.SELL, 5, 150.0, 0.5, "2024-01-10", ExecutionStatus.FILLED)
    rebal_order = Order("SSO", OrderAction.BUY, 3, 100.0)
    rebal_exec = TradeExecution("SSO", OrderAction.BUY, 3, 100.0, 0.1, "2024-01-10", ExecutionStatus.FILLED)

    mocks["broker"].execute_orders.side_effect = [[orphan_exec], [rebal_exec]]
    mocks["broker"].get_portfolio.return_value = pf_after_orphan_sell
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 100.0}
    mocks["rebalancer"].generate_signal.return_value = TradeSignal(1.0, [rebal_order], "첫 투자: 50:50 비율로 진입")
    mocks["rebalancer"].get_target_params.return_value = (0.5, 0.075)

    md = _make_market_data()
    signal, execs, final_pf, is_rebal = engine.execute_cycle(
        md, pf_before, MarketRegime.BULL, 1.0, [], None, "2024-01-10"
    )

    # 고아 매도 + 리밸런싱 매수, 합계 2건
    assert len(execs) == 2
    assert execs[0].ticker == "AAPL"  # 고아 먼저
    assert execs[1].ticker == "SSO"   # 리밸런싱 다음
    assert is_rebal is True


def test_execute_cycle_orphan_only_on_monitoring_day():
    """모니터링 날에도 고아 매도는 실행하되, is_rebalancing은 False"""
    engine, mocks = _make_engine(repo_last_reb="2024-01-10", trading_interval_days=5)
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    pf_after = Portfolio(total_cash=5750.0, holdings={"SSO": 10}, current_prices={"SSO": 100.0})
    orphan_exec = TradeExecution("AAPL", OrderAction.SELL, 5, 150.0, 0.5, "2024-01-10", ExecutionStatus.FILLED)
    mocks["broker"].execute_orders.return_value = [orphan_exec]
    mocks["broker"].get_portfolio.return_value = pf_after
    mocks["broker"].fetch_current_prices.return_value = {"SSO": 100.0}
    mocks["rebalancer"].get_target_params.return_value = (0.5, 0.075)

    md = _make_market_data()
    signal, execs, final_pf, is_rebal = engine.execute_cycle(
        md, pf, MarketRegime.BULL, 1.0, [], None, "2024-01-11"  # 인터벌 미충족
    )

    # 고아 매도는 실행됨
    assert len(execs) == 1
    assert execs[0].ticker == "AAPL"
    # 하지만 리밸런싱은 아님 (모니터링)
    assert is_rebal is False
    assert "모니터링" in signal.reason


def test_execute_cycle_skips_orphan_on_nan():
    """NaN 데이터 이상 시 고아 매도도 스킵한다"""
    engine, mocks = _make_engine()
    pf = Portfolio(
        total_cash=5000.0,
        holdings={"SSO": 10, "AAPL": 5},
        current_prices={"SSO": 100.0, "AAPL": 150.0},
    )
    mocks["rebalancer"].get_target_params.return_value = (0.5, 0.075)

    md = _make_market_data()
    signal, execs, final_pf, is_rebal = engine.execute_cycle(
        md, pf, MarketRegime.BULL, 1.0, ["spy_volatility"], None, "2024-01-10"
    )

    # 고아 매도 안 함
    mocks["broker"].execute_orders.assert_not_called()
    assert execs == []
    assert "NaN" in signal.reason
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_engine.py::test_execute_cycle_liquidates_orphans_before_rebalancing -v`
Expected: FAIL — 고아 매도 미실행, execs에 AAPL 체결 없음

**Step 3: Write minimal implementation**

`src/core/engine/base.py`의 `execute_cycle` 메서드를 수정:

```python
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
    """Step 5: 3-way 조건 분기: NaN이상 / 모니터링 / 리밸런싱."""
    orphan_executions: List[TradeExecution] = []
    executions: List[TradeExecution] = []
    final_pf = portfolio
    is_rebalancing = False

    # ── 고아 종목 청산 (NaN 이상이 아닌 경우에만) ──
    if not nan_fields:
        orphan_tickers = self._detect_orphan_holdings(portfolio)
        if orphan_tickers:
            self.logger.info(">>> Step 4.5: Orphan Holdings Liquidation")
            self._notify_alert(
                f"⚠️ 엔진 변경 감지: 이전 엔진 종목 {len(orphan_tickers)}건 자동 청산",
                detail=self._cycle_detail(),
            )
            orphan_executions, portfolio = self._liquidate_orphans(portfolio, orphan_tickers)
            final_pf = portfolio

    # 보유 종목 중 가격 조회 실패(0.0 또는 누락) 종목 감지
    zero_price_tickers = [
        t for t, q in portfolio.holdings.items()
        if q > 0 and portfolio.current_prices.get(t, 0) <= 0
    ]

    # 모든 분기에서 공통으로 사용할 목표 파라미터 (regime 기반)
    target_ratio_a, rebalance_threshold = self.rebalancer.get_target_params(regime)

    if nan_fields:
        signal = TradeSignal(0.0, [], f"데이터 이상 - NaN: {', '.join(nan_fields)}",
                             target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold)
        msg = (
            f"⚠️ Data Quality Alert — 매매 중단\n"
            f"날짜: {record_date}\n"
            f"NaN 필드: {', '.join(nan_fields)}\n"
            f"데이터 품질 이상으로 매매를 중단합니다."
        )
        self.logger.error(msg)
        self._notify_alert(msg, detail=self._cycle_detail())

    elif zero_price_tickers:
        display_names = [ticker_display(t) for t in zero_price_tickers]
        signal = TradeSignal(0.0, [], f"가격 조회 실패 — 매매 중단: {', '.join(display_names)}",
                             target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold)
        msg = (
            f"⚠️ Price Data Alert — 매매 중단\n"
            f"날짜: {record_date}\n"
            f"가격 조회 실패 종목: {', '.join(display_names)}\n"
            f"보유 종목 가격 이상으로 리밸런싱을 중단합니다.\n"
            f"total_value 왜곡으로 인한 비정상 주문 방지."
        )
        self.logger.error(msg)
        self._notify_alert(msg, detail=self._cycle_detail())

    elif not self._is_due(sim_date) and regime != MarketRegime.CRASH:
        signal = TradeSignal(exposure, [], f"{regime.value} (모니터링)",
                             target_ratio_a=target_ratio_a, rebalance_threshold=rebalance_threshold)
        self.logger.info(
            f">>> Step 5: Monitoring "
            f"(리밸런싱 인터벌 미충족, {self.trading_interval_days}일 기준)"
        )
        self._notify_message(
            f"모니터링 완료. {regime.value} | ${portfolio.total_value:,.0f}",
            detail=self._cycle_detail(),
        )

    else:
        is_rebalancing = True
        self.logger.info(">>> Step 5: Rebalancing")
        signal = self.rebalancer.generate_signal(portfolio, exposure, regime)

        # CRASH 알림 발송
        if regime == MarketRegime.CRASH:
            crash_msg = self._build_crash_alert(market_data, portfolio)
            self.logger.error(crash_msg)
            self._notify_alert(crash_msg, detail=self._cycle_detail())

        if signal.has_orders:
            self.logger.info(f"Executing {len(signal.orders)} orders ({signal.reason})")
            executions = self.broker.execute_orders(signal.orders)

            total = len(signal.orders)
            filled = sum(1 for e in executions if e.status == ExecutionStatus.FILLED)
            partial = sum(1 for e in executions if e.status == ExecutionStatus.PARTIAL)
            ordered = sum(1 for e in executions if e.status == ExecutionStatus.ORDERED)
            rejected = sum(1 for e in executions if e.status == ExecutionStatus.REJECTED)
            failed = total - len(executions)
            self.logger.info(
                f"Order Summary: total={total} filled={filled} partial={partial} "
                f"ordered={ordered} rejected={rejected} failed={failed}"
            )

            if executions:
                self._notify_message(
                    f"✅ Orders Executed. Count: {len(executions)}",
                    detail=self._cycle_detail(),
                )
                if self.is_live_trading:
                    time.sleep(3)
                try:
                    final_pf = self.broker.get_portfolio()
                    self.logger.info(
                        f"Updated Portfolio: Cash=${final_pf.total_cash:,.0f}, "
                        f"Value=${final_pf.total_value:,.0f}"
                    )
                except RuntimeError as e:
                    warn_msg = (
                        f"⚠️ 거래 후 포트폴리오 조회 실패 — 거래 전 포트폴리오로 대체\n{e}\n"
                        f"거래 기록은 정상 저장됩니다."
                    )
                    self.logger.error(warn_msg)
                    self._notify_alert(warn_msg, detail=self._cycle_detail())
            else:
                self._notify_alert(
                    "⚠️ Orders sent but NO execution result returned.",
                    detail=self._cycle_detail(),
                )
        else:
            self.logger.info("No Rebalance Needed.")
            self._notify_message(
                f"Bot Finished. Hold. ({regime.value})",
                detail=self._cycle_detail(),
            )

    return signal, orphan_executions + executions, final_pf, is_rebalancing
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_core_engine.py -k "execute_cycle" -v`
Expected: 신규 3건 + 기존 테스트 PASS

**Step 5: Commit**

```bash
git add src/core/engine/base.py tests/test_core_engine.py
git commit -m "feat: execute_cycle에 고아 종목 자동 청산 삽입"
```

---

### Task 5: 전체 테스트 + 커버리지 확인

**Step 1: 전체 테스트 실행**

Run: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/`
Expected: 80% 이상 커버리지, 모든 테스트 PASS

**Step 2: 기존 테스트 regression 확인**

기존 `test_core_engine.py` 테스트 중 `execute_cycle`을 호출하는 테스트가 깨지지 않는지 확인.
특히 `execute_cycle` 반환값이 `(signal, orphan_execs + execs, final_pf, is_rebal)`로 변경되었으므로, 기존 테스트에서 `execs` 길이나 내용을 검증하는 부분을 확인한다.

고아 종목이 없는 기존 테스트에서는 `orphan_executions = []`이므로 반환값 변경이 없다.

**Step 3: Commit (if fixes needed)**

```bash
git add -A
git commit -m "fix: 기존 테스트 호환성 수정"
```

---

## 예상 실행 흐름 (엔진 변경 시)

```
=== [my_test] 계좌 실행 시작 ===
>>> Step 1: Data Collection
>>> Step 2: Indicator Calculation
>>> Step 3: Strategy Analysis
>>> Step 4: Portfolio Status
Current Portfolio: Cash=$38,261, Value=$4,192,141
>>> Step 4.5: Orphan Holdings Liquidation
  [고아 종목] TIGER 미국S&P500레버리지(합성 H): 10주 @$162,291 → 전량 매도
  [고아 종목] TIGER 미국나스닥100: 15주 @$168,731 → 전량 매도
  ...
  >>> 고아 종목 청산: 5건 매도 실행
  Order Summary: total=5 filled=5 ...
>>> Step 5: Rebalancing
  [비중 판정] 첫 투자 → 0:100 초기 비율 적용
  ...
>>> Step 6: Archiving Data
  net_deposit ≈ 0  ← 고아 매도 체결이 당일체결현금영향에 반영
```
