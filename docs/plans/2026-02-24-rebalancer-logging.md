# Rebalancer 상세 로깅 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `Rebalancer.generate_signal()` 실행 시 포트폴리오 평가액, 비중 판정, 목표 금액, 종목별 주문 계산 과정을 단계별로 로깅하여 주문 발생 근거를 추적 가능하게 한다.

**Architecture:** `generate_signal` 내 6개 섹션에 인라인 `logger.info()` 추가 + `_create_group_orders`에 `group_name` 파라미터 추가 후 종목별 계산 로깅. `ILogger`/`TradeLogger` 변경 없음.

**Tech Stack:** Python 3.10, unittest.mock.MagicMock, pytest

---

## Task 1: `_create_group_orders`에 종목별 로깅 추가

**Files:**
- Modify: `src/core/logic.py` — `_create_group_orders` 시그니처 및 내부
- Test: `tests/test_core_logic.py` — 종목별 로그 검증 테스트 추가

---

### Step 1: 실패하는 테스트 작성

`tests/test_core_logic.py` 파일 끝에 추가:

```python
def test_create_group_orders_logs_ticker_detail(create_portfolio):
    """_create_group_orders는 group_name과 종목별 현재/목표/주문 정보를 logger.info로 출력해야 한다."""
    from unittest.mock import MagicMock
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY', 'QLD']}, logger=mock_logger)

    pf = create_portfolio(
        holdings={'SPY': 3, 'QLD': 0},
        prices={'SPY': 100.0, 'QLD': 50.0}
    )
    # 목표: 각 $400 (SPY: 현재 $300 → +$100 매수, QLD: 현재 $0 → +$400 매수)
    rebalancer._create_group_orders(pf, ['SPY', 'QLD'], group_target_amt=800.0, group_name='A그룹')

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]

    # 그룹 헤더 출력 확인
    assert any('A그룹' in msg for msg in info_calls)
    # 각 종목 로그 포함 확인
    assert any('SPY' in msg for msg in info_calls)
    assert any('QLD' in msg for msg in info_calls)
    # 현재가치/목표/diff/주문방향 포함 확인
    assert any('BUY' in msg for msg in info_calls)


def test_create_group_orders_logs_no_order_reason(create_portfolio):
    """주문 수량이 0일 때 '주문 없음' 사유가 로깅되어야 한다."""
    from unittest.mock import MagicMock
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY']}, logger=mock_logger)

    pf = create_portfolio(
        holdings={'SPY': 10},
        prices={'SPY': 500000.0}   # 주당 50만원 → 매수 수량 0
    )
    # 목표 510만원 → 차이 10만원 → floor(10만/50만)=0주 → 주문 없음
    rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=5100000.0, group_name='A그룹')

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    assert any('주문 없음' in msg or '수량 미달' in msg for msg in info_calls)


def test_create_group_orders_no_log_without_logger(create_portfolio):
    """logger가 None이면 _create_group_orders는 아무 로그도 출력하지 않아야 한다."""
    rebalancer = Rebalancer({'A': ['SPY']}, logger=None)
    pf = create_portfolio(holdings={'SPY': 5}, prices={'SPY': 100.0})
    # 예외 없이 실행되어야 함
    orders = rebalancer._create_group_orders(pf, ['SPY'], group_target_amt=1000.0, group_name='A그룹')
    assert isinstance(orders, list)
```

### Step 2: 테스트 실패 확인

```bash
pytest tests/test_core_logic.py::test_create_group_orders_logs_ticker_detail \
       tests/test_core_logic.py::test_create_group_orders_logs_no_order_reason \
       tests/test_core_logic.py::test_create_group_orders_no_log_without_logger -v
```

Expected: **FAILED** — `_create_group_orders()` got unexpected keyword argument 'group_name'

### Step 3: 구현 — `_create_group_orders` 수정

`src/core/logic.py`의 `_create_group_orders` 메서드를 아래로 교체:

```python
def _create_group_orders(self, pf: Portfolio, tickers: List[str], group_target_amt: float, group_name: str = "") -> List[Order]:
    orders = []
    count = len(tickers)
    if count == 0: return orders

    per_stock_target = group_target_amt / count

    if self._logger and group_name:
        self._logger.info(f"[{group_name} 종목별]")

    for ticker in tickers:
        price = pf.current_prices.get(ticker, 0)
        if price <= 0:
            if self._logger:
                self._logger.warning(f"종목 {ticker}의 가격이 유효하지 않습니다 (price={price}). 주문 생성을 건너뜁니다.")
            continue

        current_qty = pf.holdings.get(ticker, 0)
        current_val = current_qty * price

        diff_val = per_stock_target - current_val

        order_desc = "→ 주문 없음 (수량 미달)"
        if diff_val > 0:
            qty = math.floor(diff_val / price)
            if qty > 0:
                orders.append(Order(ticker, OrderAction.BUY, qty, price))
                order_desc = f"→ BUY {qty}주 @${price:.2f}"
        elif diff_val < 0:
            qty = math.ceil(abs(diff_val) / price)
            qty = min(qty, current_qty)
            if qty > 0:
                orders.append(Order(ticker, OrderAction.SELL, qty, price))
                order_desc = f"→ SELL {qty}주 @${price:.2f}"

        if self._logger:
            sign = "+" if diff_val >= 0 else ""
            self._logger.info(
                f"  {ticker}: 보유 {current_qty}주 ${current_val:,.2f} → 목표 ${per_stock_target:,.2f} "
                f"| diff={sign}{diff_val:+,.2f} {order_desc}"
            )

    return orders
```

`generate_signal` 내에서 `_create_group_orders` 호출 3곳에 `group_name` 인자 추가:

```python
orders.extend(self._create_group_orders(portfolio, self.groups.get('A', []), target_val_a, group_name='A그룹(성장)'))
orders.extend(self._create_group_orders(portfolio, self.groups.get('B', []), target_val_b, group_name='B그룹(안전)'))
orders.extend(self._create_group_orders(portfolio, self.groups.get('C', []), target_val_c, group_name='C그룹(현금)'))
```

### Step 4: 테스트 통과 확인

```bash
pytest tests/test_core_logic.py::test_create_group_orders_logs_ticker_detail \
       tests/test_core_logic.py::test_create_group_orders_logs_no_order_reason \
       tests/test_core_logic.py::test_create_group_orders_no_log_without_logger -v
```

Expected: **PASSED** (3개)

### Step 5: 기존 테스트 전체 통과 확인

```bash
pytest tests/test_core_logic.py -v
```

Expected: **전체 PASSED** — `_create_group_orders` 기존 호출 코드(`test_rebalancer_small_balance_rounding` 등)는 `group_name` 기본값 `""` 덕분에 그대로 동작

### Step 6: 커밋

```bash
git add src/core/logic.py tests/test_core_logic.py
git commit -m "feat: _create_group_orders에 group_name 파라미터 및 종목별 로깅 추가"
```

---

## Task 2: `generate_signal` 6개 섹션 로깅 추가

**Files:**
- Modify: `src/core/logic.py` — `generate_signal` 내 로그 추가
- Test: `tests/test_core_logic.py` — 섹션별 로그 검증 테스트 추가

---

### Step 1: 실패하는 테스트 작성

`tests/test_core_logic.py` 파일 끝에 추가:

```python
def test_generate_signal_logs_entry_context(create_portfolio):
    """generate_signal은 시작 시 구분선, regime, exposure, total_value를 로깅해야 한다."""
    from unittest.mock import MagicMock
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=0.8, regime=MarketRegime.BULL)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 구분선 출력 확인
    assert any('═' in msg or '====' in msg for msg in info_calls)
    # regime 로깅
    assert any('Bull' in msg or 'Regime' in msg for msg in info_calls)
    # exposure 로깅
    assert any('0.80' in msg or '0.8' in msg or 'Exposure' in msg for msg in info_calls)


def test_generate_signal_logs_portfolio_section(create_portfolio):
    """generate_signal은 A/B/C 그룹별 평가액과 비중을 로깅해야 한다."""
    from unittest.mock import MagicMock
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF'], 'C': ['SHV']}, logger=mock_logger)
    pf = create_portfolio(
        cash=2000.0,
        holdings={'SPY': 10, 'IEF': 8, 'SHV': 5},
        prices={'SPY': 100.0, 'IEF': 100.0, 'SHV': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=0.8, regime=MarketRegime.BULL)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 포트폴리오 섹션 헤더
    assert any('포트폴리오' in msg for msg in info_calls)
    # A, B, C 그룹 각각 언급
    assert any('A그룹' in msg for msg in info_calls)
    assert any('B그룹' in msg for msg in info_calls)
    assert any('C그룹' in msg for msg in info_calls)


def test_generate_signal_logs_ratio_judgment(create_portfolio):
    """generate_signal은 ratio_A, ratio_B, diff, threshold, 판정 결과를 로깅해야 한다."""
    from unittest.mock import MagicMock
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    # ratio_A=0.55, ratio_B=0.45, diff=10% → BULL threshold 15% → 비율 유지
    pf = create_portfolio(
        holdings={'SPY': 550, 'IEF': 450},
        prices={'SPY': 1000.0, 'IEF': 1000.0}
    )

    rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.BULL)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 비중 판정 섹션
    assert any('비중 판정' in msg for msg in info_calls)
    # diff와 threshold 수치 포함
    assert any('10.0%' in msg or '10%' in msg or '0.100' in msg or 'diff' in msg.lower() for msg in info_calls)
    assert any('15.0%' in msg or '15%' in msg or '0.150' in msg or 'threshold' in msg.lower() for msg in info_calls)


def test_generate_signal_logs_target_amounts(create_portfolio):
    """generate_signal은 A/B/C 그룹별 현재 금액과 목표 금액을 로깅해야 한다."""
    from unittest.mock import MagicMock
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )

    rebalancer.generate_signal(pf, target_exposure=0.8, regime=MarketRegime.BULL)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 목표 금액 섹션
    assert any('목표 금액' in msg for msg in info_calls)
    # exposure와 ratio 계산 근거 포함
    assert any('0.80' in msg or '0.8' in msg or 'exposure' in msg.lower() for msg in info_calls)


def test_generate_signal_logs_final_summary(create_portfolio):
    """generate_signal은 최종 주문 건수, 총 주문금액, reason을 로깅해야 한다."""
    from unittest.mock import MagicMock
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    pf = create_portfolio(
        cash=2000000.0,
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100000.0, 'IEF': 100000.0}
    )

    signal = rebalancer.generate_signal(pf, target_exposure=1.0, regime=MarketRegime.SIDEWAYS)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    # 최종 주문 섹션 (BUY/SELL 건수 또는 주문 없음)
    assert any('최종 주문' in msg or '주문' in msg for msg in info_calls)
    # reason이 로그에 포함됨
    assert any(signal.reason in msg or '결정 사유' in msg for msg in info_calls)


def test_generate_signal_no_log_without_logger(create_portfolio):
    """logger=None이면 generate_signal은 어떤 로그도 시도하지 않고 정상 동작해야 한다."""
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=None)
    pf = create_portfolio(
        holdings={'SPY': 10, 'IEF': 10},
        prices={'SPY': 100.0, 'IEF': 100.0}
    )
    signal = rebalancer.generate_signal(pf, target_exposure=0.8, regime=MarketRegime.BULL)
    assert isinstance(signal.reason, str)


def test_generate_signal_logs_crash_early_return(create_portfolio):
    """CRASH 시 조기 리턴되지만 구분선과 입력 정보는 로깅되어야 한다."""
    from unittest.mock import MagicMock
    mock_logger = MagicMock()
    rebalancer = Rebalancer({'A': ['SPY'], 'B': ['IEF']}, logger=mock_logger)
    pf = create_portfolio(holdings={'SPY': 10}, prices={'SPY': 100.0, 'IEF': 100.0})

    rebalancer.generate_signal(pf, target_exposure=0.0, regime=MarketRegime.CRASH)

    info_calls = [call.args[0] for call in mock_logger.info.call_args_list]
    assert any('CRASH' in msg or 'Crash' in msg or 'Emergency' in msg for msg in info_calls)
```

### Step 2: 테스트 실패 확인

```bash
pytest tests/test_core_logic.py::test_generate_signal_logs_entry_context \
       tests/test_core_logic.py::test_generate_signal_logs_portfolio_section \
       tests/test_core_logic.py::test_generate_signal_logs_ratio_judgment \
       tests/test_core_logic.py::test_generate_signal_logs_target_amounts \
       tests/test_core_logic.py::test_generate_signal_logs_final_summary \
       tests/test_core_logic.py::test_generate_signal_no_log_without_logger \
       tests/test_core_logic.py::test_generate_signal_logs_crash_early_return -v
```

Expected: **FAILED** (대부분 — logger.info 호출이 아직 없음)

### Step 3: 구현 — `generate_signal` 로깅 추가

`src/core/logic.py`의 `generate_signal` 메서드를 아래로 교체:

```python
def generate_signal(self,
                    portfolio: Portfolio,
                    target_exposure: float,
                    regime: MarketRegime) -> TradeSignal:

    # ── 섹션 1: 시작 구분선 + 입력 컨텍스트 ──────────────────────────────
    if self._logger:
        self._logger.info("═" * 48)
        self._logger.info(" Rebalancer.generate_signal 시작")
        self._logger.info("═" * 48)
        self._logger.info(
            f"[입력] Regime={regime.value} | TargetExposure={target_exposure:.2f} "
            f"| TotalValue=${portfolio.total_value:,.2f} | Cash=${portfolio.total_cash:,.2f}"
        )

    # [핵심 수정] CRASH 발생 시 즉시 리턴 (가드 절)
    if regime == MarketRegime.CRASH:
        if self._logger:
            self._logger.info("[CRASH] Emergency Stop. 주문 생성을 건너뜁니다.")
            self._logger.info("═" * 48)
        return TradeSignal(
            target_exposure=target_exposure,
            orders=[],
            reason="CRASH Detected: Emergency Stop. No Action."
        )

    # 1. 국면별 리밸런싱 임계치 설정
    threshold = self._threshold_map.get(regime, 0.10)

    # 2. 가격 누락 종목 경고
    if self._logger:
        for t, q in portfolio.holdings.items():
            if q > 0 and t not in portfolio.current_prices:
                self._logger.warning(f"보유 종목 {t}의 가격 정보가 누락되어 평가액이 0으로 계산됩니다.")

    # 3. 현재 자산군(A, B) 평가액 및 비중 계산
    val_a = portfolio.get_group_value(self.groups.get('A', []))
    val_b = portfolio.get_group_value(self.groups.get('B', []))
    val_c = portfolio.get_group_value(self.groups.get('C', []))
    val_risky = val_a + val_b

    # ── 섹션 2: 포트폴리오 현황 ───────────────────────────────────────────
    if self._logger:
        total = portfolio.total_value
        pct = lambda v: (v / total * 100) if total > 0 else 0.0
        self._logger.info("[포트폴리오 현황]")
        self._logger.info(f"  A그룹(성장): ${val_a:>12,.2f} ({pct(val_a):5.1f}%)")
        self._logger.info(f"  B그룹(안전): ${val_b:>12,.2f} ({pct(val_b):5.1f}%)")
        self._logger.info(f"  C그룹(현금): ${val_c:>12,.2f} ({pct(val_c):5.1f}%)")
        self._logger.info(f"  현금(예수금): ${portfolio.total_cash:>11,.2f} ({pct(portfolio.total_cash):5.1f}%)")

    # 첫 투자 여부 판별 (위험자산 보유액이 0이면 첫 투자)
    is_first_investment = (val_risky == 0)

    # A, B 상대 비중
    if is_first_investment:
        ratio_a = 0.5
        ratio_b = 0.5
        needs_rebalance = True
        current_diff = 0.0
    else:
        ratio_a = val_a / val_risky
        ratio_b = val_b / val_risky
        current_diff = round(abs(ratio_a - ratio_b), 6)
        needs_rebalance = current_diff > threshold

    # ── 섹션 3: 비중 판정 ────────────────────────────────────────────────
    if self._logger:
        if is_first_investment:
            self._logger.info("[비중 판정] 첫 투자 → 50:50 초기 비율 적용")
        else:
            verdict = "임계치 초과 → 50:50 재조정" if needs_rebalance else "비율 유지 (리밸런싱 불필요)"
            self._logger.info(
                f"[비중 판정] ratio_A={ratio_a:.3f}  ratio_B={ratio_b:.3f}"
            )
            self._logger.info(
                f"  현재 차이: {current_diff:.1%} | 임계치: {threshold:.1%} → {verdict}"
            )

    # 3. 목표 금액 계산
    if needs_rebalance:
        target_ratio_a = 0.5
        target_ratio_b = 0.5
    else:
        target_ratio_a = ratio_a
        target_ratio_b = ratio_b

    target_val_a = portfolio.total_value * target_exposure * target_ratio_a
    target_val_b = portfolio.total_value * target_exposure * target_ratio_b
    target_val_c = max(portfolio.total_value - (target_val_a + target_val_b), 0)

    # ── 섹션 4: 목표 금액 ────────────────────────────────────────────────
    if self._logger:
        self._logger.info("[목표 금액]")
        self._logger.info(
            f"  A그룹: 현재 ${val_a:>10,.2f} → 목표 ${target_val_a:>10,.2f}"
            f"  (exposure {target_exposure:.2f} × ratio {target_ratio_a:.2f})"
        )
        self._logger.info(
            f"  B그룹: 현재 ${val_b:>10,.2f} → 목표 ${target_val_b:>10,.2f}"
            f"  (exposure {target_exposure:.2f} × ratio {target_ratio_b:.2f})"
        )
        self._logger.info(
            f"  C그룹: 현재 ${val_c:>10,.2f} → 목표 ${target_val_c:>10,.2f}  (잔여)"
        )

    # 4. 주문 생성 (섹션 5 로그는 _create_group_orders 내부에서 출력)
    orders = []
    orders.extend(self._create_group_orders(portfolio, self.groups.get('A', []), target_val_a, group_name='A그룹(성장)'))
    orders.extend(self._create_group_orders(portfolio, self.groups.get('B', []), target_val_b, group_name='B그룹(안전)'))
    orders.extend(self._create_group_orders(portfolio, self.groups.get('C', []), target_val_c, group_name='C그룹(현금)'))

    sell_orders = [o for o in orders if o.action == OrderAction.SELL]
    buy_orders  = [o for o in orders if o.action == OrderAction.BUY]
    sorted_orders = sell_orders + buy_orders

    # 4-1. 비율 유지 시 미세 주문 필터링
    if not needs_rebalance and not is_first_investment and sorted_orders:
        total_order_value = sum(o.quantity * o.price for o in sorted_orders)
        min_order_value = portfolio.total_value * self.min_order_pct
        if total_order_value < min_order_value:
            sorted_orders = []

    # 5. reason 결정
    if is_first_investment and sorted_orders:
        reason = "첫 투자: 50:50 비율로 진입"
    elif is_first_investment and not sorted_orders:
        reason = "첫 투자: 주문 단위 미달로 진입 불가"
    elif needs_rebalance and sorted_orders:
        reason = f"비율 재조정: Threshold {threshold:.0%} 초과 (Diff: {current_diff:.1%})"
    elif needs_rebalance and not sorted_orders:
        reason = f"비율 재조정 필요하나 주문 단위 미달 (Diff: {current_diff:.1%})"
    elif not needs_rebalance and sorted_orders:
        reason = "비율 유지, exposure 조정으로 주문 발생"
    else:
        reason = "비율 유지, 추가 주문 없음"

    # ── 섹션 6: 최종 요약 + 종료 구분선 ────────────────────────────────
    if self._logger:
        sell_cnt = len(sell_orders)
        buy_cnt  = len(buy_orders)
        total_order_val = sum(o.quantity * o.price for o in sorted_orders)
        order_pct = (total_order_val / portfolio.total_value * 100) if portfolio.total_value > 0 else 0.0
        if sorted_orders:
            self._logger.info(
                f"[최종 주문] SELL {sell_cnt}건 + BUY {buy_cnt}건 "
                f"(총 주문금액: ${total_order_val:,.2f} / 자산대비 {order_pct:.1f}%)"
            )
        else:
            self._logger.info("[최종 주문] 주문 없음")
        self._logger.info(f"[결정 사유] {reason}")
        self._logger.info("═" * 48)

    return TradeSignal(
        target_exposure=target_exposure,
        orders=sorted_orders,
        reason=reason
    )
```

### Step 4: 테스트 통과 확인

```bash
pytest tests/test_core_logic.py::test_generate_signal_logs_entry_context \
       tests/test_core_logic.py::test_generate_signal_logs_portfolio_section \
       tests/test_core_logic.py::test_generate_signal_logs_ratio_judgment \
       tests/test_core_logic.py::test_generate_signal_logs_target_amounts \
       tests/test_core_logic.py::test_generate_signal_logs_final_summary \
       tests/test_core_logic.py::test_generate_signal_no_log_without_logger \
       tests/test_core_logic.py::test_generate_signal_logs_crash_early_return -v
```

Expected: **PASSED** (7개)

### Step 5: 전체 테스트 스위트 통과 확인

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/
```

Expected: **PASSED**, coverage ≥ 80%

### Step 6: 커밋

```bash
git add src/core/logic.py tests/test_core_logic.py
git commit -m "feat: generate_signal 6개 섹션 단계별 로깅 추가"
```

---

## Task 3: 브랜치 푸시 및 마무리

### Step 1: 최종 전체 테스트

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/
```

Expected: **PASSED**, coverage ≥ 80%

### Step 2: 브랜치 푸시

```bash
git push -u origin claude/add-rebalancer-logging-heKZv
```

---

## 예상 로그 출력 예시

실제 운영 시 `logs/YYYY-MM-DD.log`에 아래와 같이 출력됩니다:

```
2026-02-24 09:00:01 [INFO] ════════════════════════════════════════════════
2026-02-24 09:00:01 [INFO]  Rebalancer.generate_signal 시작
2026-02-24 09:00:01 [INFO] ════════════════════════════════════════════════
2026-02-24 09:00:01 [INFO] [입력] Regime=Bull | TargetExposure=0.80 | TotalValue=$12,000.00 | Cash=$2,000.00
2026-02-24 09:00:01 [INFO] [포트폴리오 현황]
2026-02-24 09:00:01 [INFO]   A그룹(성장): $    5,000.00 ( 41.7%)
2026-02-24 09:00:01 [INFO]   B그룹(안전): $    5,000.00 ( 41.7%)
2026-02-24 09:00:01 [INFO]   C그룹(현금): $        0.00 (  0.0%)
2026-02-24 09:00:01 [INFO]   현금(예수금): $    2,000.00 ( 16.7%)
2026-02-24 09:00:01 [INFO] [비중 판정] ratio_A=0.500  ratio_B=0.500
2026-02-24 09:00:01 [INFO]   현재 차이: 0.0% | 임계치: 15.0% → 비율 유지 (리밸런싱 불필요)
2026-02-24 09:00:01 [INFO] [목표 금액]
2026-02-24 09:00:01 [INFO]   A그룹: 현재 $  5,000.00 → 목표 $  4,800.00  (exposure 0.80 × ratio 0.50)
2026-02-24 09:00:01 [INFO]   B그룹: 현재 $  5,000.00 → 목표 $  4,800.00  (exposure 0.80 × ratio 0.50)
2026-02-24 09:00:01 [INFO]   C그룹: 현재 $      0.00 → 목표 $  2,400.00  (잔여)
2026-02-24 09:00:01 [INFO] [A그룹(성장) 종목별]
2026-02-24 09:00:01 [INFO]   SSO: 보유 25주 $2,500.00 → 목표 $2,400.00 | diff=-$100.00 → SELL 1주 @$100.00
2026-02-24 09:00:01 [INFO]   QLD: 보유 25주 $2,500.00 → 목표 $2,400.00 | diff=-$100.00 → SELL 1주 @$100.00
2026-02-24 09:00:01 [INFO] [B그룹(안전) 종목별]
2026-02-24 09:00:01 [INFO]   IEF: 보유 25주 $2,750.00 → 목표 $2,400.00 | diff=-$350.00 → SELL 3주 @$110.00
2026-02-24 09:00:01 [INFO]   ...
2026-02-24 09:00:01 [INFO] [C그룹(현금) 종목별]
2026-02-24 09:00:01 [INFO]   SHV:  보유  0주 $    0.00 → 목표 $2,400.00 | diff=+$2,400.00 → BUY 24주 @$100.00
2026-02-24 09:00:01 [INFO] [최종 주문] SELL 3건 + BUY 1건 (총 주문금액: $2,730.00 / 자산대비 22.8%)
2026-02-24 09:00:01 [INFO] [결정 사유] 비율 유지, exposure 조정으로 주문 발생
2026-02-24 09:00:01 [INFO] ════════════════════════════════════════════════
```
