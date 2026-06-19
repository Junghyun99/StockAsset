# Ticker Alias Mapping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 단일 계좌 대시보드의 모든 티커 표시를 `asset_groups.json`의 `aliases`에 정의된 한글명으로 대체한다.

**Architecture:** `utils.js`에 `getTickerAlias(ticker, groupConfig)` 헬퍼를 추가하고, `ui.js`와 `charts.js`의 티커 표시 함수들에 `groupConfig` 파라미터를 추가하여 alias를 적용한다. 기존 함수 시그니처는 선택적 파라미터로 하위 호환성을 유지한다.

**Tech Stack:** Vanilla JavaScript (ES Modules), Browser-side rendering only (no Python changes)

---

## 배경 및 현황

`asset_groups.json`의 `aliases` 필드 예시:
```json
{
  "aliases": {
    "226490.KS": "KODEX 코스피",
    "133690.KS": "TIGER 미국나스닥100",
    ...
  }
}
```

티커가 raw code로 표시되는 위치 목록:
| 파일 | 함수 | 위치 | 표시 예 |
|------|------|------|---------|
| `ui.js` | `renderHoldingsTable` | 보유 종목 테이블 Ticker 컬럼 | `226490.KS` |
| `ui.js` | `renderTodayActivity` | Today's Activity 배지 | `BUY 226490.KS (3)` |
| `ui.js` | `renderTradeHistory` | Trade History 테이블 Actions 배지 | `BUY 226490.KS (3)` |
| `ui.js` | `renderFailedOrderAlert` | 상단 미체결 알림 텍스트 | `226490.KS BUY` |
| `ui.js` | `renderOperationsPanel` | Operations 탭 미체결 테이블 Ticker 컬럼 | `226490.KS` |
| `charts.js` | `renderTickerContributionChart` | 종목별 거래 기여 차트 라벨 | `226490.KS` |

---

## Task 1: `getTickerAlias` 헬퍼 추가

**Files:**
- Modify: `docs/js/utils.js` (끝에 추가)

**Step 1: 함수 추가**

`docs/js/utils.js` 파일 끝에 아래 함수를 추가한다:

```javascript
/**
 * groupConfig.aliases에서 티커의 한글명(alias)을 반환.
 * alias가 없으면 raw ticker를 그대로 반환.
 * @param {string} ticker
 * @param {Object|null} groupConfig - asset_groups.json 내용
 * @returns {string}
 */
export function getTickerAlias(ticker, groupConfig) {
    if (groupConfig && groupConfig.aliases && groupConfig.aliases[ticker]) {
        return groupConfig.aliases[ticker];
    }
    return ticker;
}
```

**Step 2: 수동 검증**

브라우저 콘솔에서:
```javascript
// groupConfig 예시
const gc = { aliases: { "226490.KS": "KODEX 코스피" } };
// 예상: "KODEX 코스피"
// alias 없는 경우: "SSO" → "SSO"
```

**Step 3: Commit**

```bash
git add docs/js/utils.js
git commit -m "feat(dashboard): add getTickerAlias helper to utils.js"
```

---

## Task 2: `ui.js` - `renderHoldingsTable` 보유 종목 테이블

**Files:**
- Modify: `docs/js/ui.js`

현재 코드 (line ~5):
```javascript
import {
    ...
} from './utils.js?v=3';
```

현재 코드 (line ~144):
```javascript
<td class="fw-bold">${h.ticker}</td>
```

**Step 1: import에 `getTickerAlias` 추가**

`docs/js/ui.js` 상단 import에 `getTickerAlias` 추가:
```javascript
import {
    getRegimeColorClass,
    getRegimeBannerClass,
    getAssetGroup,
    getTickerAlias,          // ← 추가
    formatCurrency,
    ...
} from './utils.js?v=3';
```

**Step 2: Ticker 컬럼을 alias로 교체**

`renderHoldingsTable` 함수 내 (line ~144):
```javascript
// before:
<td class="fw-bold">${h.ticker}</td>

// after:
<td class="fw-bold">${getTickerAlias(h.ticker, groupConfig)}</td>
```

**Step 3: 수동 검증 (브라우저 확인)**
- Overview 탭 → Asset Allocation 테이블 → Ticker 컬럼에 `KODEX 코스피` 등 한글명 표시 확인
- 해외 계좌(SSO, QLD 등)는 alias 없으므로 raw ticker 그대로 표시

**Step 4: Commit**

```bash
git add docs/js/ui.js
git commit -m "feat(dashboard): show ticker alias in holdings table"
```

---

## Task 3: `ui.js` - `renderTodayActivity` Today's Activity 배지

**Files:**
- Modify: `docs/js/ui.js`
- Modify: `docs/js/main.js` (call site 업데이트)

**Step 1: 함수 시그니처에 groupConfig 추가**

`renderTodayActivity` 함수 선언 변경:
```javascript
// before:
export function renderTodayActivity(historyData, statusData, marketType = 'overseas') {

// after:
export function renderTodayActivity(historyData, statusData, marketType = 'overseas', groupConfig = null) {
```

**Step 2: 배지 내 ticker를 alias로 교체**

같은 함수 내 (line ~191):
```javascript
// before:
let actionsHtml = lastTrade.executions.map(ex => `
    <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge me-1 mb-1">
        ${ex.action} ${ex.ticker} (${ex.quantity})
    </span>
`).join('');

// after:
let actionsHtml = lastTrade.executions.map(ex => `
    <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge me-1 mb-1">
        ${ex.action} ${getTickerAlias(ex.ticker, groupConfig)} (${ex.quantity})
    </span>
`).join('');
```

**Step 3: `main.js` call site 업데이트**

`docs/js/main.js`의 `_renderSingleAccount` 함수 내:
```javascript
// before:
renderTodayActivity(historyData, statusData, marketType);

// after:
renderTodayActivity(historyData, statusData, marketType, groupConfig);
```

**Step 4: 수동 검증**
- Overview 탭 → Today's Activity 배지에 `BUY KODEX 코스피 (3)` 형태로 표시

**Step 5: Commit**

```bash
git add docs/js/ui.js docs/js/main.js
git commit -m "feat(dashboard): show ticker alias in today's activity badges"
```

---

## Task 4: `ui.js` - `renderTradeHistory` Trade History 배지

**Files:**
- Modify: `docs/js/ui.js`
- Modify: `docs/js/main.js`

**Step 1: 모듈 레벨 캐시 변수 추가**

`renderTradeHistory` 위에 있는 모듈 레벨 변수들:
```javascript
// before:
let cachedHistoryData = [];
let cachedMarketType = 'overseas';

// after:
let cachedHistoryData = [];
let cachedMarketType = 'overseas';
let cachedGroupConfig = null;
```

**Step 2: 함수 시그니처에 groupConfig 추가 + 캐시 저장**

페이지네이션 시 `groupConfig` 없이 호출되면 `null`로 덮어써 alias가 사라지는 버그를 방지하기 위해,
`groupConfig`가 명시적으로 전달된 경우에만 캐시를 업데이트한다.

```javascript
// before:
export function renderTradeHistory(historyData, page = undefined, marketType = 'overseas') {
    cachedHistoryData = historyData;
    cachedMarketType = marketType;

// after:
export function renderTradeHistory(historyData, page = undefined, marketType = 'overseas', groupConfig = null) {
    cachedHistoryData = historyData;
    cachedMarketType = marketType;
    if (groupConfig !== null) {
        cachedGroupConfig = groupConfig;
    }
```

**Step 3: 배지 내 ticker를 alias로 교체 (line ~359)**

```javascript
// before:
let actionsHtml = tx.executions.map(ex => `
    <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge me-1 mb-1">
        ${ex.action} ${ex.ticker} (${ex.quantity})
    </span>
`).join('');

// after:
let actionsHtml = tx.executions.map(ex => `
    <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge me-1 mb-1">
        ${ex.action} ${getTickerAlias(ex.ticker, cachedGroupConfig)} (${ex.quantity})
    </span>
`).join('');
```

**Step 4: `main.js` call site 업데이트**

`docs/js/main.js`의 `renderTradesTab` 내:
```javascript
// before:
renderTradeHistory(historyData, undefined, marketType);

// after:
renderTradeHistory(historyData, undefined, marketType, groupConfig);
```

**Step 5: 수동 검증**
- Trades 탭 → Trade History 테이블의 Actions 컬럼에 한글명 표시 확인
- 페이지 이동 후에도 alias가 유지되는지 확인 (cachedGroupConfig 동작 검증)

**Step 6: Commit**

```bash
git add docs/js/ui.js docs/js/main.js
git commit -m "feat(dashboard): show ticker alias in trade history table"
```

---

## Task 5: `ui.js` - `renderFailedOrderAlert` 미체결 알림

**Files:**
- Modify: `docs/js/ui.js`
- Modify: `docs/js/main.js`

**Step 1: 함수 시그니처에 groupConfig 추가**

```javascript
// before:
export function renderFailedOrderAlert(historyData) {

// after:
export function renderFailedOrderAlert(historyData, groupConfig = null) {
```

**Step 2: 알림 텍스트 내 ticker를 alias로 교체 (line ~531)**

```javascript
// before:
const summary = recent.map(f => `${f.date} ${f.ticker} ${f.action} [${f.status}]`).join(', ');

// after:
const summary = recent.map(f => `${f.date} ${getTickerAlias(f.ticker, groupConfig)} ${f.action} [${f.status}]`).join(', ');
```

**Step 3: `main.js` call site 업데이트**

```javascript
// before:
renderFailedOrderAlert(historyData);

// after:
renderFailedOrderAlert(historyData, groupConfig);
```

**Step 4: Commit**

```bash
git add docs/js/ui.js docs/js/main.js
git commit -m "feat(dashboard): show ticker alias in failed order alert"
```

---

## Task 6: `ui.js` - `renderOperationsPanel` 미체결 주문 테이블

**Files:**
- Modify: `docs/js/ui.js`
- Modify: `docs/js/main.js`

**Step 1: 함수 시그니처에 groupConfig 추가**

```javascript
// before:
export function renderOperationsPanel(statusData, historyData, summaryData) {

// after:
export function renderOperationsPanel(statusData, historyData, summaryData, groupConfig = null) {
```

**Step 2: 미체결 테이블 Ticker 컬럼을 alias로 교체 (line ~594)**

```javascript
// before:
<td class="fw-bold">${f.ticker}</td>

// after:
<td class="fw-bold">${getTickerAlias(f.ticker, groupConfig)}</td>
```

**Step 3: `main.js` call site 업데이트**

`renderOperationsTab` 내:
```javascript
// before:
renderOperationsPanel(statusData, historyData, summaryData);

// after:
renderOperationsPanel(statusData, historyData, summaryData, groupConfig);
```

**Step 4: 수동 검증**
- Operations 탭 → 미체결/실패 주문 상세 테이블 → Ticker 컬럼에 한글명 표시

**Step 5: Commit**

```bash
git add docs/js/ui.js docs/js/main.js
git commit -m "feat(dashboard): show ticker alias in operations panel"
```

---

## Task 7: `charts.js` - `renderTickerContributionChart` 차트 라벨

**Files:**
- Modify: `docs/js/charts.js`

**Step 1: import에 `getTickerAlias` 추가**

`docs/js/charts.js` 상단 import:
```javascript
import {
    getAssetGroup,
    getTickerAlias,          // ← 추가
    computeTickerContribution,
    ...
} from './utils.js?v=3';
```

**Step 2: 함수 시그니처에 groupConfig 추가 (line ~942)**

```javascript
// before:
export function renderTickerContributionChart(historyData, marketType = 'overseas') {

// after:
export function renderTickerContributionChart(historyData, marketType = 'overseas', groupConfig = null) {
```

**Step 3: 차트 라벨을 alias로 교체 (line ~951)**

```javascript
// before:
const labels = data.map(d => d.ticker);

// after:
const labels = data.map(d => getTickerAlias(d.ticker, groupConfig));
```

**Step 4: `main.js` call site 업데이트**

`renderTradesTab` 내:
```javascript
// before:
renderTickerContributionChart(historyData, marketType);

// after:
renderTickerContributionChart(historyData, marketType, groupConfig);
```

**Step 5: 수동 검증**
- Trades 탭 → 종목별 거래 기여 차트 → Y축 라벨에 `KODEX 코스피` 등 한글명 표시

**Step 6: Commit**

```bash
git add docs/js/charts.js docs/js/main.js
git commit -m "feat(dashboard): show ticker alias in contribution chart labels"
```

---

## Task 8: 최종 통합 검증 및 PR 생성

**Step 1: `utils.js` 버전 캐시 확인**

`ui.js`와 `charts.js`의 import에서 `utils.js?v=3` 버전 태그가 일치하는지 확인.
`main.js`의 import에서도 `ui.js?v=3`, `charts.js?v=3` 등 버전이 일치하는지 확인.

**Step 2: 전체 시나리오 수동 테스트 체크리스트**

국내 계좌(domestic) 시나리오:
- [ ] Overview 탭 → Asset Allocation 테이블 Ticker 컬럼: `226490.KS` → `KODEX 코스피`
- [ ] Overview 탭 → Today's Activity 배지: `BUY 226490.KS` → `BUY KODEX 코스피`
- [ ] Trades 탭 → Trade History Actions 배지: alias 적용 확인
- [ ] Trades 탭 → 종목별 거래 기여 차트 라벨: alias 적용 확인
- [ ] Trades 탭 → 페이지 이동 후에도 alias 유지 확인
- [ ] Operations 탭 → 미체결 테이블 Ticker 컬럼: alias 적용 확인

해외 계좌(overseas) 시나리오 (alias 없는 경우):
- [ ] `SSO`, `QLD`, `IEF` 등 overseas 티커는 raw ticker 그대로 표시 확인

**Step 3: PR 생성**

```bash
git push -u origin claude/ticker-alias-mapping-avco4p
```

그런 다음 GitHub MCP로 PR 생성.
