# Performance 탭 배당 섹션 통합 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 이슈 #300의 Dividend Yield 카드를 기존 누적/연간 배당금 차트와 통합하여, Performance 탭 하단에 배당 전용 섹션으로 묶는다.

**Architecture:** `utils.js`에 `computeDividendYield()` 순수 함수를 추가하고, `ui.js`에 요약 카드 3개를 렌더링하는 함수를 만든다. `index.html`의 기존 배당 차트 영역 바로 위에 카드 row를 삽입하고 섹션 헤더를 추가한다. 차트 부제에 "(추정, yfinance 기준)"을 표기한다.

**Tech Stack:** Vanilla JS (ES modules), Chart.js, Bootstrap 5

**관련 파일:**
- `docs/js/utils.js` — 계산 함수
- `docs/js/ui.js` — 카드 렌더링
- `docs/js/main.js` — 호출 연결
- `docs/index.html` — HTML 구조
- `docs/js/charts.js` — 기존 배당 차트 (수정 최소화)

**데이터 필드:** `summary.json`의 `daily_dividend` (숫자, 배당락일에만 > 0)

---

### Task 1: `computeDividendYield()` 함수 추가

**Files:**
- Modify: `docs/js/utils.js` (파일 끝에 추가)

**Step 1: 함수 작성**

`utils.js` 파일 끝에 아래 함수를 추가한다.

```js
/**
 * 배당 수익률 요약 계산 (추정치, yfinance 배당락일 기준)
 * @param {Array} summaryData - summary 배열 (daily_dividend, total_value 필드)
 * @returns {{totalDividend: number, annualizedYield: number, ytdDividend: number}}
 */
export function computeDividendYield(summaryData) {
    if (!summaryData || summaryData.length < 2) {
        return { totalDividend: 0, annualizedYield: 0, ytdDividend: 0 };
    }

    const first = summaryData[0];
    const last = summaryData[summaryData.length - 1];

    // 누적 배당금
    const totalDividend = summaryData.reduce((s, d) => s + (d.daily_dividend || 0), 0);

    // 평균 포트폴리오 가치
    const avgValue = summaryData.reduce((s, d) => s + d.total_value, 0) / summaryData.length;

    // 기간 (연 단위)
    const msPerYear = 365.25 * 24 * 60 * 60 * 1000;
    const years = Math.max((new Date(last.date) - new Date(first.date)) / msPerYear, 1 / 365);

    // 연환산 배당 수익률 (%)
    const annualizedYield = avgValue > 0 ? (totalDividend / avgValue / years) * 100 : 0;

    // 올해 배당금 (데이터셋 마지막 날짜 기준 연도)
    const dataYear = last.date.slice(0, 4);
    const ytdDividend = summaryData
        .filter(d => d.date && d.date.startsWith(dataYear))
        .reduce((s, d) => s + (d.daily_dividend || 0), 0);

    return { totalDividend, annualizedYield, ytdDividend };
}
```

**Step 2: Commit**

```bash
git add docs/js/utils.js
git commit -m "feat: add computeDividendYield() to utils.js"
```

---

### Task 2: 배당 요약 카드 렌더링 함수 추가

**Files:**
- Modify: `docs/js/ui.js` (파일 끝에 추가)

**Step 1: import 추가**

`ui.js` 상단의 `utils.js` import 문에 `computeDividendYield`를 추가한다.

**Step 2: 렌더링 함수 작성**

`ui.js` 파일 끝에 아래 함수를 추가한다.

```js
/**
 * 배당 요약 카드 3개 렌더링 (누적 배당금, 연환산 수익률, 올해 배당금)
 */
export function renderDividendSummaryCards(summaryData, marketType = 'overseas') {
    const container = document.getElementById('dividend-summary-cards');
    if (!container) return;

    const { totalDividend, annualizedYield, ytdDividend } = computeDividendYield(summaryData);
    const fmt = v => formatAmount(v, marketType);

    container.innerHTML = `
        <div class="col-md-4">
            <div class="card h-100 border-0 shadow-sm">
                <div class="card-body text-center p-3">
                    <h6 class="text-muted small mb-1">누적 배당금</h6>
                    <h5 class="fw-bold mb-1 text-success">${fmt(totalDividend)}</h5>
                    <div class="small text-muted">전체 기간 합계</div>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card h-100 border-0 shadow-sm">
                <div class="card-body text-center p-3">
                    <h6 class="text-muted small mb-1">연환산 수익률</h6>
                    <h5 class="fw-bold mb-1 ${annualizedYield > 0 ? 'text-success' : 'text-muted'}">${annualizedYield.toFixed(2)}%</h5>
                    <div class="small text-muted">배당금 / 평균 자산</div>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card h-100 border-0 shadow-sm">
                <div class="card-body text-center p-3">
                    <h6 class="text-muted small mb-1">올해 배당금</h6>
                    <h5 class="fw-bold mb-1 text-success">${fmt(ytdDividend)}</h5>
                    <div class="small text-muted">YTD 합계</div>
                </div>
            </div>
        </div>
    `;
}
```

이 함수에서 사용하는 `computeDividendYield`와 `formatAmount`는 이미 Step 1에서 import한 것을 사용한다.

**Step 3: Commit**

```bash
git add docs/js/ui.js
git commit -m "feat: add renderDividendSummaryCards() to ui.js"
```

---

### Task 3: HTML 구조 수정 — 배당 섹션 헤더 + 카드 row 추가

**Files:**
- Modify: `docs/index.html`

**Step 1: 배당 섹션 통합**

기존 `<!-- Dividend Charts -->` 블록(약 437~467행) 앞에 섹션 헤더와 카드 row를 삽입하고, 차트 부제에 "(추정, yfinance 기준)"을 추가한다.

변경 전:
```html
                <!-- Dividend Charts -->
                <div class="row g-4 mb-4">
                    <!-- Cumulative Dividend -->
                    <div class="col-lg-6">
                        <div class="card border-0 shadow-sm h-100">
                            <div class="card-header bg-white py-3">
                                <h5 class="mb-0"><i class="fas fa-piggy-bank me-2 text-success"></i>누적 배당금</h5>
                                <div class="text-muted small mt-1">전체 기간 배당금 누적 합계</div>
```

변경 후:
```html
                <!-- ── Dividend Section ── -->
                <div class="d-flex align-items-center mb-3 mt-2">
                    <h5 class="mb-0"><i class="fas fa-hand-holding-usd me-2 text-success"></i>배당금 분석</h5>
                    <span class="badge bg-light text-muted border ms-2">추정치 · yfinance 기준</span>
                </div>

                <!-- Dividend Summary Cards -->
                <div class="row g-3 mb-4" id="dividend-summary-cards">
                    <!-- renderDividendSummaryCards()가 채움 -->
                </div>

                <!-- Dividend Charts -->
                <div class="row g-4 mb-4">
                    <!-- Cumulative Dividend -->
                    <div class="col-lg-6">
                        <div class="card border-0 shadow-sm h-100">
                            <div class="card-header bg-white py-3">
                                <h5 class="mb-0"><i class="fas fa-piggy-bank me-2 text-success"></i>누적 배당금</h5>
                                <div class="text-muted small mt-1">전체 기간 배당금 누적 합계</div>
```

**Step 2: Commit**

```bash
git add docs/index.html
git commit -m "feat: add dividend section header and summary cards container"
```

---

### Task 4: main.js에서 렌더 호출 연결

**Files:**
- Modify: `docs/js/main.js`

**Step 1: import 추가**

`main.js` 상단의 `ui.js` import 문에 `renderDividendSummaryCards`를 추가한다.

**Step 2: 호출 추가**

`renderPerformanceTab()` 함수 내에서, 기존 `renderCumulativeDividendChart` 호출 바로 앞에 아래 한 줄을 추가한다.

```js
        renderDividendSummaryCards(summaryData, marketType);
        renderCumulativeDividendChart(summaryData, marketType);
        renderYearlyDividendChart(summaryData, marketType);
```

**Step 3: Commit**

```bash
git add docs/js/main.js
git commit -m "feat: wire renderDividendSummaryCards into performance tab"
```

---

### Task 5: 수동 검증

**Step 1: 로컬 확인**

`docs/` 디렉토리를 로컬 서버로 열어 Performance 탭 하단을 확인한다.

```bash
cd docs && python3 -m http.server 8080
```

**확인 항목:**
- [ ] "배당금 분석" 섹션 헤더와 "추정치 · yfinance 기준" 배지 표시
- [ ] 3개 카드 (누적 배당금, 연환산 수익률, 올해 배당금) 표시
- [ ] 기존 누적 배당금 차트, 연간 배당금 차트 정상 렌더링
- [ ] 배당 데이터가 0인 경우 카드에 $0.00 / 0.00% 표시 (에러 없음)
- [ ] domestic 계정 선택 시 ₩ 포맷 적용

**Step 2: 최종 Commit & Push**

```bash
git push -u origin <branch>
```

---

## 최종 레이아웃

```
Performance 탭 (스크롤 하단)
────────────────────────────────────────
📊 Strategy Analysis 차트
────────────────────────────────────────
💰 배당금 분석         [추정치 · yfinance 기준]
┌──────────┐ ┌──────────┐ ┌──────────┐
│ 누적 배당금 │ │연환산 수익률│ │ 올해 배당금 │
│ $1,234   │ │  2.34%   │ │  $234    │
└──────────┘ └──────────┘ └──────────┘
┌─── 누적 배당금 ───┐┌── 연간 배당금 ──┐
│  (라인 차트)       ││  (바 차트)      │
└──────────────────┘└────────────────┘
────────────────────────────────────────
```

## 변경 파일 요약

| 파일 | 변경 내용 |
|------|----------|
| `docs/js/utils.js` | `computeDividendYield()` 함수 추가 |
| `docs/js/ui.js` | `renderDividendSummaryCards()` 함수 추가, import 추가 |
| `docs/index.html` | 배당 섹션 헤더 + 카드 컨테이너 row 추가 |
| `docs/js/main.js` | import 추가, 렌더 호출 1줄 추가 |

백엔드 변경 없음. `summary.json`의 기존 `daily_dividend` 필드를 그대로 사용.
