# Currency Mismatch Live Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `market_type: domestic` 계좌에서 라이브 페이지가 `$` 대신 `₩`로 금액을 표시하도록 수정.

**Architecture:** `utils.js`에 이미 `formatAmount(value, marketType)` 함수가 있음. `main.js`에서 `ACCOUNT_MARKET_TYPES`로부터 `marketType`을 읽어 모든 렌더 함수에 전달하고, `ui.js`·`charts.js`에서 `formatCurrency()` 대신 `formatAmount()`를 사용하도록 변경.

**Tech Stack:** Vanilla JS (ES Modules), Chart.js, Bootstrap 5

---

## 변경 범위

| 파일 | 변경 내용 |
|------|-----------|
| `docs/js/main.js` | `marketType` 결정 → `_renderSingleAccount`에 전달 |
| `docs/js/ui.js` | 관련 함수에 `marketType` 파라미터 추가, `formatAmount()` 사용 |
| `docs/js/charts.js` | 관련 함수에 `marketType` 파라미터 추가, 통화 기호 동적 처리 |
| `docs/index.html` | 하드코딩된 `$-` 초기값 수정 |

---

### Task 1: `main.js` — marketType 결정 및 전달

**Files:**
- Modify: `docs/js/main.js`

**Step 1: 현재 `_renderSingleAccount` 시그니처 확인**

`main.js:181` — 현재 시그니처:
```js
function _renderSingleAccount({ summary, status, history, groupConfig }) {
```

**Step 2: marketType을 받아 전달하도록 수정**

```js
// loadLiveMode() 단일 계좌 분기 (main.js:139-143)
// 변경 전
const data = accountsData.get(accountIds[0]);
_renderSingleAccount(data);

// 변경 후
const data = accountsData.get(accountIds[0]);
const marketType = (ACCOUNT_MARKET_TYPES[accountIds[0]] || 'overseas');
_renderSingleAccount(data, marketType);
```

```js
// _loadLegacySingleAccount() (main.js:256-268)
// 변경 전
_renderSingleAccount({ summary, status, history, groupConfig });

// 변경 후
_renderSingleAccount({ summary, status, history, groupConfig }, 'overseas');
```

```js
// _renderSingleAccount 시그니처 변경 (main.js:181)
// 변경 전
function _renderSingleAccount({ summary: summaryData, status: statusData, history: historyData, groupConfig }) {

// 변경 후
function _renderSingleAccount({ summary: summaryData, status: statusData, history: historyData, groupConfig }, marketType = 'overseas') {
```

**Step 3: `_renderSingleAccount` 내부 — 렌더 호출에 marketType 전달**

```js
// 변경 전 (main.js:187-192)
renderStatusBanner(statusData);
updateSummaryCards(statusData, summaryData);
renderGroupBarChart(statusData, groupConfig);
renderHoldingsTable(statusData, groupConfig);
renderTodayActivity(historyData, statusData);

// 변경 후
renderStatusBanner(statusData);
updateSummaryCards(statusData, summaryData, marketType);
renderGroupBarChart(statusData, groupConfig, marketType);
renderHoldingsTable(statusData, groupConfig, marketType);
renderTodayActivity(historyData, statusData, marketType);
```

```js
// 변경 전 (main.js:225-234) renderTradesTab 내부
renderTradeSummaryStats(historyData);
renderFeeImpactCard(historyData, summaryData);
renderTradeReasonPie(historyData);
renderMonthlyTradeFrequencyChart(historyData);
renderTickerContributionChart(historyData);
renderTradeHistory(historyData);

// 변경 후
renderTradeSummaryStats(historyData, marketType);
renderFeeImpactCard(historyData, summaryData);
renderTradeReasonPie(historyData);
renderMonthlyTradeFrequencyChart(historyData);
renderTickerContributionChart(historyData, marketType);
renderTradeHistory(historyData, undefined, marketType);
```

```js
// renderPerformanceTab 내부 — 차트 함수에도 marketType 전달
// 변경 전 (main.js:201-213)
renderUnifiedChart(summaryData);
renderCumulativePnlChart(summaryData);
renderCumulativeDividendChart(summaryData);
renderYearlyDividendChart(summaryData);

// 변경 후
renderUnifiedChart(summaryData, marketType);
renderCumulativePnlChart(summaryData, marketType);
renderCumulativeDividendChart(summaryData, marketType);
renderYearlyDividendChart(summaryData, marketType);
```

```js
// renderAllocationTab 내부
// 변경 전 (main.js:218-222)
renderCurrentAllocationDoughnut(statusData, groupConfig);
renderHistoricalAllocationChart(summaryData);

// 변경 후
renderCurrentAllocationDoughnut(statusData, groupConfig, marketType);
renderHistoricalAllocationChart(summaryData, marketType);
```

**Step 4: ACCOUNT_MARKET_TYPES import 추가**

```js
// main.js 상단 import (main.js:42)
// 변경 전
import { loadEngineMeta, loadAccountsMeta } from './utils.js?v=4';

// 변경 후
import { loadEngineMeta, loadAccountsMeta, ACCOUNT_MARKET_TYPES } from './utils.js?v=4';
```

**Step 5: 커밋**

```bash
git add docs/js/main.js
git commit -m "feat: pass marketType through _renderSingleAccount pipeline"
```

---

### Task 2: `ui.js` — formatAmount 사용

**Files:**
- Modify: `docs/js/ui.js`

**Step 1: `formatAmount` import 추가**

```js
// 변경 전 (ui.js:4-20)
import {
    getRegimeColorClass,
    ...
    formatCurrency,
    formatPercent,
    ...
} from './utils.js?v=3';

// 변경 후: formatAmount 추가
import {
    getRegimeColorClass,
    ...
    formatCurrency,
    formatAmount,
    formatPercent,
    ...
} from './utils.js?v=3';
```

**Step 2: `updateSummaryCards` — marketType 파라미터 추가**

```js
// 변경 전 (ui.js:63)
export function updateSummaryCards(statusData, summaryData) {

// 변경 후
export function updateSummaryCards(statusData, summaryData, marketType = 'overseas') {
```

```js
// 변경 전 (ui.js:68)
document.getElementById('total-value').innerText = formatCurrency(portfolio.total_value);

// 변경 후
document.getElementById('total-value').innerText = formatAmount(portfolio.total_value, marketType);
```

**Step 3: `renderHoldingsTable` — marketType 파라미터 추가, USD 하드코딩 제거**

```js
// 변경 전 (ui.js:124)
export function renderHoldingsTable(statusData, groupConfig) {

// 변경 후
export function renderHoldingsTable(statusData, groupConfig, marketType = 'overseas') {
```

```js
// 변경 전 (ui.js:144-147)
<td class="text-end">${h.price}</td>
<td class="text-end">${formatCurrency(h.price)}</td>
<td class="text-end">${formatCurrency(h.value)}</td>

// 변경 후 (rows += 내부)
<td class="text-end">${formatAmount(h.price, marketType)}</td>
<td class="text-end">${formatAmount(h.value, marketType)}</td>
```

```js
// Cash 행 — "USD" 하드코딩 제거, marketType 통화 기호 사용
// 변경 전 (ui.js:152-159)
rows += `
    <tr class="table-light">
        <td><span class="badge bg-secondary">Cash</span></td>
        <td class="fw-bold">USD</td>
        <td class="text-end">-</td>
        <td class="text-end">-</td>
        <td class="text-end">${formatCurrency(cash)}</td>
    </tr>
`;

// 변경 후
const cashLabel = marketType === 'domestic' ? 'KRW' : 'USD';
rows += `
    <tr class="table-light">
        <td><span class="badge bg-secondary">Cash</span></td>
        <td class="fw-bold">${cashLabel}</td>
        <td class="text-end">-</td>
        <td class="text-end">-</td>
        <td class="text-end">${formatAmount(cash, marketType)}</td>
    </tr>
`;
```

**Step 4: `renderTodayActivity` — marketType 파라미터**

```js
// 변경 전 (ui.js:170)
export function renderTodayActivity(historyData, statusData) {

// 변경 후
export function renderTodayActivity(historyData, statusData, marketType = 'overseas') {
```

```js
// 변경 전 (ui.js:202)
Amount: ${formatCurrency(lastTrade.total_trade_amount)}

// 변경 후
Amount: ${formatAmount(lastTrade.total_trade_amount, marketType)}
```

**Step 5: `renderTradeSummaryStats` — marketType 파라미터**

```js
// 변경 전 (ui.js:311)
export function renderTradeSummaryStats(historyData) {

// 변경 후
export function renderTradeSummaryStats(historyData, marketType = 'overseas') {
```

```js
// 변경 전 (ui.js:315-316)
document.getElementById('trade-volume').innerText = formatCurrency(stats.totalVolume);
document.getElementById('trade-fees').innerText = formatCurrency(stats.totalFees);

// 변경 후
document.getElementById('trade-volume').innerText = formatAmount(stats.totalVolume, marketType);
document.getElementById('trade-fees').innerText = formatAmount(stats.totalFees, marketType);
```

**Step 6: `renderTradeHistory` — marketType 파라미터**

```js
// 변경 전 (ui.js:327)
export function renderTradeHistory(historyData, page) {

// 변경 후
export function renderTradeHistory(historyData, page, marketType = 'overseas') {
```

`renderTradeHistory`는 모듈 스코프의 `cachedHistoryData`와 페이지네이션을 씁니다.  
`marketType`도 캐시해야 합니다:

```js
// 변경 전 (ui.js:320-322)
let currentPage = 1;
const TRADES_PER_PAGE = 10;
let cachedHistoryData = [];

// 변경 후
let currentPage = 1;
const TRADES_PER_PAGE = 10;
let cachedHistoryData = [];
let cachedMarketType = 'overseas';
```

```js
// 변경 전 (ui.js:328-329)
export function renderTradeHistory(historyData, page) {
    cachedHistoryData = historyData;

// 변경 후
export function renderTradeHistory(historyData, page, marketType = 'overseas') {
    cachedHistoryData = historyData;
    cachedMarketType = marketType;
```

페이지네이션 클릭 핸들러에서도 `cachedMarketType` 전달:
```js
// 변경 전 (ui.js:418-421)
if (page >= 1 && page <= totalPages) {
    renderTradeHistory(cachedHistoryData, page);
}

// 변경 후
if (page >= 1 && page <= totalPages) {
    renderTradeHistory(cachedHistoryData, page, cachedMarketType);
}
```

거래 내역 행 내 금액:
```js
// 변경 전 (ui.js:368-371)
<td class="text-end small">${tx.portfolio_value ? formatCurrency(tx.portfolio_value) : '-'}</td>
<td class="text-end fw-bold text-dark">${formatCurrency(tx.total_trade_amount)}</td>
<td class="text-end small">${fee !== undefined ? formatCurrency(fee) : '-'}</td>

// 변경 후
<td class="text-end small">${tx.portfolio_value ? formatAmount(tx.portfolio_value, cachedMarketType) : '-'}</td>
<td class="text-end fw-bold text-dark">${formatAmount(tx.total_trade_amount, cachedMarketType)}</td>
<td class="text-end small">${fee !== undefined ? formatAmount(fee, cachedMarketType) : '-'}</td>
```

**Step 7: 커밋**

```bash
git add docs/js/ui.js
git commit -m "feat: use formatAmount in ui.js for domestic/overseas currency display"
```

---

### Task 3: `charts.js` — 통화 기호 동적 처리

**Files:**
- Modify: `docs/js/charts.js`

**Step 1: `formatAmount` import 추가**

```js
// 변경 전 (charts.js:1-15)
import {
    filterByDateRange,
    getAssetGroup,
    formatCurrency,
    ...
} from './utils.js?v=3';

// 변경 후
import {
    filterByDateRange,
    getAssetGroup,
    formatCurrency,
    formatAmount,
    ...
} from './utils.js?v=3';
```

**Step 2: `renderGroupBarChart` — marketType 파라미터**

```js
// 변경 전 (charts.js:113)
export function renderGroupBarChart(statusData, groupConfig) {

// 변경 후
export function renderGroupBarChart(statusData, groupConfig, marketType = 'overseas') {
```

```js
// 변경 전 — label에 formatCurrency 사용 (charts.js:141, 150, 162-164)
label: `${group}: ${info.label} (${formatCurrency(value)})`
label: `Other (${formatCurrency(otherValue)})`
label: `A: Growth (${formatCurrency(groupA)})`  // 등

// 변경 후 — formatAmount 사용
label: `${group}: ${info.label} (${formatAmount(value, marketType)})`
label: `Other (${formatAmount(otherValue, marketType)})`
label: `A: Growth (${formatAmount(groupA, marketType)})`  // 등
```

**Step 3: `renderUnifiedChart` — marketType 파라미터 + 통화 기호**

```js
// 변경 전 (charts.js:375)
export function renderUnifiedChart(summaryData) {

// 변경 후
export function renderUnifiedChart(summaryData, marketType = 'overseas') {
```

```js
// 통화 기호 헬퍼
const currSymbol = marketType === 'domestic' ? '₩' : '$';
```

```js
// 변경 전 label/axis (charts.js:431, 496-499, 522-523)
label: 'Total Portfolio ($)'
label: 'SPY Benchmark ($)'
title: { display: true, text: 'Asset Value ($)' }
ticks: { callback: function(value) { return '$' + value.toLocaleString(); } }
return `${datasetLabel}: $${value.toLocaleString(...)}`

// 변경 후
label: `Total Portfolio (${currSymbol})`
label: `SPY Benchmark (${currSymbol})`
title: { display: true, text: `Asset Value (${currSymbol})` }
ticks: { callback: function(value) { return currSymbol + value.toLocaleString(); } }
return `${datasetLabel}: ${currSymbol}${value.toLocaleString(...)}`
```

**Step 4: `updatePerformanceChartRange` — marketType 전달**

```js
// 변경 전 (charts.js:543-549)
export function updatePerformanceChartRange(summaryData, range) {
    const filtered = filterByDateRange(summaryData, range);
    renderUnifiedChart(filtered);
    renderCumulativePnlChart(filtered);
    renderAlphaLineChart(filtered);
    renderMonthlyHeatmap(filtered);
}

// 변경 후
export function updatePerformanceChartRange(summaryData, range, marketType = 'overseas') {
    const filtered = filterByDateRange(summaryData, range);
    renderUnifiedChart(filtered, marketType);
    renderCumulativePnlChart(filtered, marketType);
    renderAlphaLineChart(filtered);
    renderMonthlyHeatmap(filtered);
}
```

`main.js`의 `setupTimeRangeSelector`도 `marketType`을 캡처해 전달:
```js
// main.js setupTimeRangeSelector 내부
// 변경 전
updatePerformanceChartRange(summaryData, btn.getAttribute('data-range'));

// 변경 후 (클로저로 marketType 캡처)
// _renderSingleAccount 내에서 호출되므로, setupTimeRangeSelector에 marketType 전달 필요
// 시그니처: function setupTimeRangeSelector(summaryData, marketType)
updatePerformanceChartRange(summaryData, btn.getAttribute('data-range'), marketType);
```

**Step 5: `renderCumulativePnlChart` — marketType 파라미터**

```js
// 변경 전 (charts.js:559)
export function renderCumulativePnlChart(summaryData) {

// 변경 후
export function renderCumulativePnlChart(summaryData, marketType = 'overseas') {
```

```js
const currSymbol = marketType === 'domestic' ? '₩' : '$';

// axis title/ticks/tooltip 모두 currSymbol 사용:
title: { display: true, text: `누적 손익 (${currSymbol})` }
ticks: { callback: v => (v >= 0 ? `+${currSymbol}` : `-${currSymbol}`) + Math.abs(Math.round(v)).toLocaleString() }
label: ctx => {
    const v = ctx.parsed.y;
    const sign = v >= 0 ? '+' : '-';
    return `누적 손익: ${sign}${currSymbol}${Math.abs(v).toLocaleString(...)}`;
}
```

**Step 6: `renderCumulativeDividendChart` — marketType 파라미터**

```js
// 변경 전 (charts.js:223)
export function renderCumulativeDividendChart(summaryData) {

// 변경 후
export function renderCumulativeDividendChart(summaryData, marketType = 'overseas') {

// 내부: currSymbol 헬퍼 + 모든 '$' 교체
const currSymbol = marketType === 'domestic' ? '₩' : '$';
```

```js
// 변경 전 (charts.js:254, 275, 283)
label: '누적 배당금 ($)'
text: 'Cumulative Dividend ($)'
ticks callback: v => '$' + v.toLocaleString(...)
tooltip: `누적 배당금: $${...}`

// 변경 후
label: `누적 배당금 (${currSymbol})`
text: `Cumulative Dividend (${currSymbol})`
ticks callback: v => currSymbol + v.toLocaleString(...)
tooltip: `누적 배당금: ${currSymbol}${...}`
```

**Step 7: `renderYearlyDividendChart` — marketType 파라미터**

```js
// 변경 전 (charts.js:294)
export function renderYearlyDividendChart(summaryData) {

// 변경 후
export function renderYearlyDividendChart(summaryData, marketType = 'overseas') {

const currSymbol = marketType === 'domestic' ? '₩' : '$';
// 모든 '$' 교체 (chart.js:325, 346, 354)
```

**Step 8: `renderTickerContributionChart` — marketType 파라미터**

```js
// 변경 전 (charts.js:937)
export function renderTickerContributionChart(historyData) {

// 변경 후
export function renderTickerContributionChart(historyData, marketType = 'overseas') {

const currSymbol = marketType === 'domestic' ? '₩' : '$';
// label: '거래 금액 ($)' → `거래 금액 (${currSymbol})`
// ticks: '$' → currSymbol
// tooltip: formatCurrency → formatAmount(..., marketType)
```

**Step 9: `renderCurrentAllocationDoughnut` — marketType 파라미터**

```js
// 변경 전 (charts.js:995)
export function renderCurrentAllocationDoughnut(statusData, groupConfig) {

// 변경 후
export function renderCurrentAllocationDoughnut(statusData, groupConfig, marketType = 'overseas') {

// tooltip: formatCurrency(ctx.parsed) → formatAmount(ctx.parsed, marketType)
```

**Step 10: `renderHistoricalAllocationChart` — marketType 파라미터**

```js
// 변경 전 (charts.js:1110)
export function renderHistoricalAllocationChart(summaryData) {

// 변경 후
export function renderHistoricalAllocationChart(summaryData, marketType = 'overseas') {

const currSymbol = marketType === 'domestic' ? '₩' : '$';
// title text: 'Asset Value ($)' → `Asset Value (${currSymbol})`
// ticks: '$' → currSymbol
// tooltip: formatCurrency → formatAmount(..., marketType)
```

**Step 11: 커밋**

```bash
git add docs/js/charts.js
git commit -m "feat: use formatAmount in charts.js for domestic/overseas currency display"
```

---

### Task 4: `index.html` — 하드코딩된 `$-` 수정

**Files:**
- Modify: `docs/index.html`

**Step 1: Total Assets 초기값 수정**

```html
<!-- 변경 전 (index.html:105) -->
<h2 class="fw-bold mb-0" id="total-value">$-</h2>

<!-- 변경 후 -->
<h2 class="fw-bold mb-0" id="total-value">-</h2>
```

**Step 2: 누적 손익 차트 헤더 — 달러 아이콘 제거 (선택적)**

```html
<!-- 변경 전 (index.html:299) -->
<h5 class="mb-0"><i class="fas fa-dollar-sign me-2"></i>누적 손익 ($)</h5>

<!-- 변경 후: dollar-sign 아이콘 → chart-line 아이콘, 통화 표기 제거 -->
<h5 class="mb-0"><i class="fas fa-chart-line me-2"></i>누적 손익</h5>
```

**Step 3: 커밋**

```bash
git add docs/index.html
git commit -m "fix: remove hardcoded dollar sign from live page HTML"
```

---

### Task 5: `main.js` — setupTimeRangeSelector에 marketType 전달

**Files:**
- Modify: `docs/js/main.js`

`setupTimeRangeSelector`는 `_renderSingleAccount` 내에서 호출되므로, `marketType`을 클로저로 캡처하면 됩니다. 별도 파라미터 불필요 — `_renderSingleAccount` 내부의 `marketType` 변수를 이미 참조합니다.

**Step 1: 확인 — `setupTimeRangeSelector` 는 `_renderSingleAccount` 내의 중첩 함수 아님**

`setupTimeRangeSelector`는 모듈 스코프 함수이고 `summaryData`만 받습니다. `marketType`도 파라미터로 추가해야 합니다.

```js
// 변경 전 (main.js:513)
function setupTimeRangeSelector(summaryData) {
    ...
    updatePerformanceChartRange(summaryData, btn.getAttribute('data-range'));

// 변경 후
function setupTimeRangeSelector(summaryData, marketType = 'overseas') {
    ...
    updatePerformanceChartRange(summaryData, btn.getAttribute('data-range'), marketType);
```

```js
// _renderSingleAccount 내 호출 (main.js:213)
// 변경 전
setupTimeRangeSelector(summaryData);

// 변경 후
setupTimeRangeSelector(summaryData, marketType);
```

**Step 2: charts.js에서 import 업데이트 (main.js:9)**

```js
// 변경 전
import {
    ...
    renderCumulativeDividendChart,
    renderYearlyDividendChart,
    ...
    updatePerformanceChartRange,
    ...
} from './charts.js?v=3';

// 변경 후: 동일 (updatePerformanceChartRange 이미 import됨, 시그니처만 변경)
```

**Step 3: 커밋**

```bash
git add docs/js/main.js
git commit -m "feat: pass marketType to setupTimeRangeSelector and performance chart range"
```

---

### Task 6: 전체 검증

**Step 1: 로컬에서 `docs/index.html` 열어 확인**

브라우저에서 `file:///` 또는 로컬 서버로 열어서:
- Overview 탭 → Total Assets: `₩4,473,236` 표시 확인
- Holdings 테이블: 가격/금액이 `₩` 단위 확인
- Cash 행: "USD" → "KRW" 확인
- Trades 탭: 거래 금액이 `₩` 단위 확인
- Performance 탭 차트: Y축이 `₩` 단위 확인

**Step 2: overseas 계좌로 regression 없음 확인**

`accounts_meta.json`에 `"market_type": "overseas"` 계좌가 있을 경우 `$` 표시 유지 확인 (기본값 `'overseas'` 덕분에 기존 동작 유지).

**Step 3: 최종 커밋 및 push**

```bash
git push -u origin claude/currency-mismatch-live-page-j0ohmi
```
