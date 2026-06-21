# Performance Metrics Tooltips Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 대시보드 전체의 지표 레이블에 hover 시 설명+평가기준이 담긴 Bootstrap Tooltip을 표시한다.

**Architecture:** `metric-tooltips.js`에 지표별 HTML 콘텐츠를 사전으로 정의하고, 각 요소에 `data-metric-tooltip="<key>"` 속성을 부여한 뒤 `initTooltips()`가 Bootstrap Tooltip 인스턴스를 생성한다. 동적으로 렌더링되는 요소(메트릭 비교 테이블)는 렌더 함수 내부에서 속성을 주입하고, 정적 HTML 요소(카드 h6, 국면 테이블 th, Overview Risk Indicators)는 index.html에 직접 속성을 추가한다.

**Tech Stack:** Bootstrap 5.3 Tooltip (전역 `window.bootstrap`), Vanilla JS ES Module, HTML5 data 속성

---

## 파일 변경 목록

| 작업 | 파일 |
|------|------|
| 신규 생성 | `docs/js/metric-tooltips.js` |
| 수정 | `docs/js/ui.js` |
| 수정 | `docs/index.html` |
| 수정 | `docs/js/main.js` |

---

## Task 1: `docs/js/metric-tooltips.js` 생성

**Files:**
- Create: `docs/js/metric-tooltips.js`

**Step 1: 파일 생성**

아래 내용으로 신규 파일을 만든다. `METRIC_TOOLTIPS`는 `data-metric-tooltip` 속성값(key)을 Bootstrap Tooltip에 넣을 HTML 문자열에 매핑한다.

```javascript
// docs/js/metric-tooltips.js
// 지표별 툴팁 콘텐츠 (설명 + 평가 기준)
// Bootstrap Tooltip의 html: true 옵션으로 렌더링됨

export const METRIC_TOOLTIPS = {

    // ── Performance 비교 테이블 ─────────────────────────────
    totalReturn: `<strong>Total Return (누적 수익률)</strong><br>
투자 시작부터 현재까지의 전체 수익률.<br>
기간 길이를 보정하지 않으므로 장기 비교엔 CAGR 사용 권장.<br><br>
✅ <strong>좋음</strong>: +50% 이상<br>
⚠️ <strong>보통</strong>: +10 ~ +50%<br>
❌ <strong>나쁨</strong>: 음수`,

    cagr: `<strong>CAGR (연평균 성장률)</strong><br>
복리로 환산한 연평균 수익률. 투자 기간 차이를<br>보정해 다른 전략과 공정하게 비교 가능.<br><br>
✅ <strong>좋음</strong>: 15% 이상<br>
⚠️ <strong>보통</strong>: 7 ~ 15%<br>
❌ <strong>나쁨</strong>: 7% 미만`,

    mdd: `<strong>Max Drawdown (최대 낙폭)</strong><br>
고점 대비 가장 크게 떨어진 손실폭. 최악의<br>시나리오에서 버텨야 할 고통의 크기.<br><br>
✅ <strong>좋음</strong>: -10% 이내<br>
⚠️ <strong>보통</strong>: -10 ~ -25%<br>
❌ <strong>나쁨</strong>: -25% 초과`,

    volatility: `<strong>Volatility (연환산 변동성)</strong><br>
일간 수익률의 표준편차를 연율화한 값.<br>높을수록 수익이 들쭉날쭉하여 심리적 부담이 큼.<br><br>
✅ <strong>좋음</strong>: 15% 미만<br>
⚠️ <strong>보통</strong>: 15 ~ 25%<br>
❌ <strong>나쁨</strong>: 25% 초과`,

    sharpe: `<strong>Sharpe Ratio (샤프 비율)</strong><br>
무위험 수익률을 초과한 수익을 변동성으로 나눈 값.<br>단위 리스크당 얼마나 벌었는지를 측정.<br><br>
✅ <strong>좋음</strong>: 1.5 이상<br>
⚠️ <strong>보통</strong>: 0.5 ~ 1.5<br>
❌ <strong>나쁨</strong>: 0.5 미만`,

    sortino: `<strong>Sortino Ratio (소르티노 비율)</strong><br>
Sharpe와 유사하나 하방 변동성(손실)만 패널티 적용.<br>상승 변동성을 좋은 것으로 간주해 더 정교한 평가.<br><br>
✅ <strong>좋음</strong>: 2.0 이상<br>
⚠️ <strong>보통</strong>: 1.0 ~ 2.0<br>
❌ <strong>나쁨</strong>: 1.0 미만`,

    calmar: `<strong>Calmar Ratio (칼마 비율)</strong><br>
CAGR ÷ |Max Drawdown|. 낙폭 대비 얼마나<br>성장했는지를 나타내는 리스크 조정 수익 지표.<br><br>
✅ <strong>좋음</strong>: 1.0 이상<br>
⚠️ <strong>보통</strong>: 0.5 ~ 1.0<br>
❌ <strong>나쁨</strong>: 0.5 미만`,

    beta: `<strong>Beta (베타)</strong><br>
시장(SPY) 대비 수익률 민감도.<br>
1 = 시장과 동일 움직임 / &lt;1 = 방어적 / &gt;1 = 공격적.<br><br>
이 전략 목표: Bear/Crash 시 Beta &lt; 1 유지`,

    alpha: `<strong>Alpha (초과 수익)</strong><br>
포트폴리오 수익률 − SPY 수익률의 차이.<br>벤치마크를 얼마나 이겼는지 보여주는 핵심 지표.<br><br>
✅ <strong>좋음</strong>: 양수 (벤치마크 초과)<br>
❌ <strong>나쁨</strong>: 음수 (벤치마크 미달)`,

    ir: `<strong>Information Ratio (정보 비율)</strong><br>
Alpha를 추적 오차(Tracking Error)로 나눈 값.<br>초과 수익의 크기뿐 아니라 일관성까지 측정.<br><br>
✅ <strong>좋음</strong>: 0.5 이상<br>
⚠️ <strong>보통</strong>: 0 ~ 0.5<br>
❌ <strong>나쁨</strong>: 음수`,

    // ── Win/Loss 카드 ────────────────────────────────────────
    winRate: `<strong>Win Rate (승률)</strong><br>
전체 월 중 수익이 발생한 월의 비율.<br>높을수록 꾸준히 수익이 나는 전략임을 의미.<br><br>
✅ <strong>좋음</strong>: 60% 이상<br>
⚠️ <strong>보통</strong>: 45 ~ 60%<br>
❌ <strong>나쁨</strong>: 45% 미만`,

    avgWin: `<strong>Avg Win (평균 이익 월)</strong><br>
수익이 발생한 달의 평균 수익률.<br>Avg Loss와 함께 기대값 계산의 핵심 요소.<br><br>
Avg Win이 클수록 리스크 대비 잠재 보상이 큼.`,

    avgLoss: `<strong>Avg Loss (평균 손실 월)</strong><br>
손실이 발생한 달의 평균 손실률.<br>Avg Win ÷ |Avg Loss| = 손익비 (Reward/Risk Ratio).<br><br>
✅ <strong>좋음</strong>: 손익비 2 이상 (Avg Win이 2배 이상)`,

    profitFactor: `<strong>Profit Factor (수익 팩터)</strong><br>
총 이익 합계 ÷ 총 손실 합계.<br>1 이하면 장기적으로 손실, 1 이상이면 이익 구조.<br><br>
✅ <strong>좋음</strong>: 2.0 이상<br>
⚠️ <strong>보통</strong>: 1.0 ~ 2.0<br>
❌ <strong>나쁨</strong>: 1.0 미만`,

    // ── 롤링 수익률 카드 ─────────────────────────────────────
    rolling1m: `<strong>1M Return (최근 1개월 수익률)</strong><br>
직전 약 21 거래일(1개월) 기준 수익률.<br>단기 모멘텀과 최근 시장 반응을 빠르게 확인.`,

    rolling3m: `<strong>3M Return (최근 3개월 수익률)</strong><br>
직전 약 63 거래일(3개월) 기준 수익률.<br>분기 단위 성과 점검에 활용.`,

    rolling6m: `<strong>6M Return (최근 6개월 수익률)</strong><br>
직전 약 126 거래일(6개월) 기준 수익률.<br>중기 추세 및 반기 성과 확인에 활용.`,

    rolling1y: `<strong>1Y Return (최근 1년 수익률)</strong><br>
직전 약 252 거래일(1년) 기준 수익률.<br>연환산 성과와 비교하여 최근 1년이 장기 평균 대비<br>좋은지/나쁜지 판단 가능.`,

    // ── Current DD / Calmar / YTD 카드 ──────────────────────
    currentDD: `<strong>Current DD (현재 드로다운)</strong><br>
직전 고점 대비 현재까지 하락한 비율과 경과 일수.<br>0%면 신고점 경신 중, 클수록 회복까지 갈 길이 멈.<br><br>
⚠️ <strong>주의</strong>: -15% 이상 지속되면 전략 점검 필요`,

    ytd: `<strong>YTD Return (연초 대비 수익률)</strong><br>
올해 1월 1일 이후 현재까지의 수익률.<br>같은 연도 내 SPY와 비교하여 상대 성과를 판단.<br><br>
✅ <strong>좋음</strong>: SPY YTD 초과<br>
❌ <strong>나쁨</strong>: SPY YTD 미달`,

    // ── Overview 탭 Risk Indicators ──────────────────────────
    vix: `<strong>VIX (변동성 지수 / 공포 지수)</strong><br>
S&amp;P500 옵션 시장에서 추출한 향후 30일<br>예상 변동성. 시장 불안 심리의 바로미터.<br><br>
✅ <strong>안정</strong>: 15 미만<br>
⚠️ <strong>경계</strong>: 15 ~ 25<br>
❌ <strong>공포</strong>: 25 이상 (이 전략은 Bear/Crash 국면 전환)`,

    spyMdd: `<strong>SPY MDD (현재 SPY 드로다운)</strong><br>
SPY(S&amp;P500 ETF)의 직전 고점 대비 현재 낙폭.<br>Bear/Crash 국면 판단의 주요 입력값.<br><br>
⚠️ <strong>경고</strong>: -10% 이하 → Bear 국면 진입 가능<br>
❌ <strong>위험</strong>: -20% 이하 → Crash 국면 가능`,

    spyVolatility: `<strong>SPY Volatility (SPY 변동성)</strong><br>
SPY 일간 수익률의 표준편차를 연율화한 값.<br>포트폴리오의 목표 익스포저(변동성 타겟팅) 계산에 사용.<br><br>
✅ <strong>낮음</strong>: 15% 미만 → 높은 익스포저 허용<br>
❌ <strong>높음</strong>: 25% 이상 → 익스포저 축소`,

    // ── 국면별 성과 분석 테이블 헤더 ────────────────────────
    regimeCumReturn: `<strong>누적 수익률</strong><br>
해당 국면 기간 동안의 포트폴리오 누적 수익률.<br>국면이 여러 번 발생했으면 모든 구간을 합산.`,

    regimeAnnReturn: `<strong>연환산 수익률</strong><br>
해당 국면의 누적 수익률을 CAGR로 환산한 값.<br>국면 지속 기간 차이를 보정해 Bull/Bear 간 비교 가능.`,

    regimeMDD: `<strong>국면 내 MDD</strong><br>
해당 국면 기간 중 발생한 최대 낙폭.<br>핵심 가설 검증: Bear/Crash 시 포트폴리오 MDD가<br>SPY MDD보다 작으면 전략 유효성 확인.`,

    regimePct: `<strong>전체 비율</strong><br>
전체 운용 기간 중 해당 국면이 차지하는 일수 비율.<br>Bull이 60% 이상이면 전반적 상승장이었음을 의미.`,
};
```

**Step 2: 확인**

파일이 생성되었는지 확인한다:
```bash
ls -la docs/js/metric-tooltips.js
```
Expected: 파일 존재, 크기 > 0

---

## Task 2: `docs/js/ui.js` 수정

**Files:**
- Modify: `docs/js/ui.js`

### Step 1: import 추가 (파일 상단)

`docs/js/ui.js` 1번째 줄 import 블록 끝(26번째 줄 `} from './utils.js?v=6';` 바로 아래)에 추가:

```javascript
import { METRIC_TOOLTIPS } from './metric-tooltips.js?v=20260621-1';
```

### Step 2: `renderPerformanceSummaryCards()` rows 배열 수정

현재 `docs/js/ui.js:260`의 rows 배열:
```javascript
const rows = [
    ['Total Return', p.totalReturn, s.totalReturn, 'percent', true],
    ['CAGR', p.cagr, s.cagr, 'percent', true],
    ['Max Drawdown', p.mdd, s.mdd, 'percent', false],
    ['Volatility', p.volatility, s.volatility, 'percent_abs', false],
    ['Sharpe Ratio', p.sharpe, s.sharpe, 'ratio', true],
    ['Sortino Ratio', p.sortino, s.sortino, 'ratio', true],
    ['Calmar Ratio', p.calmar, s.calmar, 'ratio', true],
    ['Beta', p.beta, s.beta, 'ratio', null],
];
```

6번째 요소(tooltip key)를 추가하여 교체:
```javascript
const rows = [
    ['Total Return', p.totalReturn, s.totalReturn, 'percent', true,  'totalReturn'],
    ['CAGR',         p.cagr,        s.cagr,        'percent', true,  'cagr'],
    ['Max Drawdown', p.mdd,         s.mdd,         'percent', false, 'mdd'],
    ['Volatility',   p.volatility,  s.volatility,  'percent_abs', false, 'volatility'],
    ['Sharpe Ratio', p.sharpe,      s.sharpe,      'ratio', true,   'sharpe'],
    ['Sortino Ratio',p.sortino,     s.sortino,     'ratio', true,   'sortino'],
    ['Calmar Ratio', p.calmar,      s.calmar,      'ratio', true,   'calmar'],
    ['Beta',         p.beta,        s.beta,        'ratio', null,   'beta'],
];
```

### Step 3: `rows.forEach` 렌더링 부분 수정

현재 `docs/js/ui.js:296` 의 forEach:
```javascript
rows.forEach(([label, portVal, spyVal, format, higherIsBetter]) => {
    const portClass = compareClass(portVal, spyVal, higherIsBetter);
    html += `
        <tr>
            <td class="ps-3">${label}</td>
            <td class="text-end ${portClass}">${fmt(portVal, format)}</td>
            <td class="text-end pe-3">${fmt(spyVal, format)}</td>
        </tr>
    `;
});
```

6번째 요소(tooltipKey)를 포함하도록 교체:
```javascript
rows.forEach(([label, portVal, spyVal, format, higherIsBetter, tooltipKey]) => {
    const portClass = compareClass(portVal, spyVal, higherIsBetter);
    const ttAttr = tooltipKey ? ` data-metric-tooltip="${tooltipKey}"` : '';
    html += `
        <tr>
            <td class="ps-3"${ttAttr}>${label} <span class="text-muted small">ⓘ</span></td>
            <td class="text-end ${portClass}">${fmt(portVal, format)}</td>
            <td class="text-end pe-3">${fmt(spyVal, format)}</td>
        </tr>
    `;
});
```

### Step 4: Alpha / Information Ratio 행 수정

현재 `docs/js/ui.js:310` Alpha 행:
```javascript
html += `
    <tr class="table-light">
        <td class="ps-3 fw-bold">Alpha</td>
        ...
    </tr>
`;
```

`data-metric-tooltip` 속성 추가:
```javascript
html += `
    <tr class="table-light">
        <td class="ps-3 fw-bold" data-metric-tooltip="alpha">Alpha <span class="text-muted small">ⓘ</span></td>
        <td class="text-end ${alphaClass}" colspan="2">${alpha >= 0 ? '+' : ''}${alpha.toFixed(2)}%</td>
    </tr>
`;
```

현재 `docs/js/ui.js:321` Information Ratio 행:
```javascript
html += `
    <tr class="table-light">
        <td class="ps-3 fw-bold">Information Ratio</td>
        ...
    </tr>
`;
```

속성 추가:
```javascript
html += `
    <tr class="table-light">
        <td class="ps-3 fw-bold" data-metric-tooltip="ir">Information Ratio <span class="text-muted small">ⓘ</span></td>
        <td class="text-end ${irClass}" colspan="2">${ir.toFixed(2)}</td>
    </tr>
`;
```

### Step 5: `initTooltips()` 함수 추가

`docs/js/ui.js` 파일 끝(마지막 export 함수 다음)에 추가:

```javascript
/**
 * data-metric-tooltip 속성을 가진 요소에 Bootstrap Tooltip 초기화.
 * 동적 렌더링 완료 후 호출해야 신규 DOM 요소도 적용됨.
 */
export function initTooltips() {
    document.querySelectorAll('[data-metric-tooltip]').forEach(el => {
        const key = el.getAttribute('data-metric-tooltip');
        const content = METRIC_TOOLTIPS[key];
        if (!content) return;
        const existing = window.bootstrap.Tooltip.getInstance(el);
        if (existing) existing.dispose();
        new window.bootstrap.Tooltip(el, {
            html: true,
            title: content,
            trigger: 'hover focus',
            placement: 'right',
        });
        el.style.cursor = 'help';
    });
}
```

### Step 6: 확인

저장 후 브라우저에서 Performance 탭을 열고 CAGR 행의 레이블 위에 마우스를 올려 툴팁이 보이는지 확인.

---

## Task 3: `docs/index.html` 정적 요소에 속성 추가

**Files:**
- Modify: `docs/index.html`

### Step 1: Overview 탭 Risk Indicators (약 147~157줄)

현재:
```html
<span class="small">VIX</span>
<span class="small">SPY MDD</span>
<span class="small">Volatility</span>
```

`data-metric-tooltip` 추가:
```html
<span class="small" data-metric-tooltip="vix">VIX ⓘ</span>
<span class="small" data-metric-tooltip="spyMdd">SPY MDD ⓘ</span>
<span class="small" data-metric-tooltip="spyVolatility">Volatility ⓘ</span>
```

### Step 2: Performance 탭 Win/Loss 카드 h6 (약 286~316줄)

현재:
```html
<h6 class="text-muted small mb-1">Win Rate</h6>
<h6 class="text-muted small mb-1">Avg Win</h6>
<h6 class="text-muted small mb-1">Avg Loss</h6>
<h6 class="text-muted small mb-1">Profit Factor</h6>
```

속성 추가 (각 h6에 `data-metric-tooltip` 부여):
```html
<h6 class="text-muted small mb-1" data-metric-tooltip="winRate">Win Rate ⓘ</h6>
<h6 class="text-muted small mb-1" data-metric-tooltip="avgWin">Avg Win ⓘ</h6>
<h6 class="text-muted small mb-1" data-metric-tooltip="avgLoss">Avg Loss ⓘ</h6>
<h6 class="text-muted small mb-1" data-metric-tooltip="profitFactor">Profit Factor ⓘ</h6>
```

### Step 3: Performance 탭 롤링 수익률 카드 (약 326~371줄)

현재:
```html
<h6 class="text-muted small mb-1">1M Return</h6>
<h6 class="text-muted small mb-1">3M Return</h6>
<h6 class="text-muted small mb-1">6M Return</h6>
<h6 class="text-muted small mb-1">1Y Return</h6>
<h6 class="text-muted small mb-1">Calmar</h6>
<h6 class="text-muted small mb-1">Current DD</h6>
```

속성 추가:
```html
<h6 class="text-muted small mb-1" data-metric-tooltip="rolling1m">1M Return ⓘ</h6>
<h6 class="text-muted small mb-1" data-metric-tooltip="rolling3m">3M Return ⓘ</h6>
<h6 class="text-muted small mb-1" data-metric-tooltip="rolling6m">6M Return ⓘ</h6>
<h6 class="text-muted small mb-1" data-metric-tooltip="rolling1y">1Y Return ⓘ</h6>
<h6 class="text-muted small mb-1" data-metric-tooltip="calmar">Calmar ⓘ</h6>
<h6 class="text-muted small mb-1" data-metric-tooltip="currentDD">Current DD ⓘ</h6>
```

### Step 4: YTD Return 카드 (약 273줄)

현재:
```html
<h6 class="text-muted small mb-1">YTD Return</h6>
```

속성 추가:
```html
<h6 class="text-muted small mb-1" data-metric-tooltip="ytd">YTD Return ⓘ</h6>
```

### Step 5: 국면별 성과 분석 테이블 헤더 (약 252~257줄)

현재:
```html
<th class="ps-3">국면</th>
<th class="text-end">일수</th>
<th class="text-end">누적 수익률</th>
<th class="text-end">연환산 수익률</th>
<th class="text-end">국면 내 MDD</th>
<th class="text-end pe-3">전체 비율</th>
```

데이터 있는 4개 컬럼에만 추가:
```html
<th class="ps-3">국면</th>
<th class="text-end">일수</th>
<th class="text-end" data-metric-tooltip="regimeCumReturn">누적 수익률 ⓘ</th>
<th class="text-end" data-metric-tooltip="regimeAnnReturn">연환산 수익률 ⓘ</th>
<th class="text-end" data-metric-tooltip="regimeMDD">국면 내 MDD ⓘ</th>
<th class="text-end pe-3" data-metric-tooltip="regimePct">전체 비율 ⓘ</th>
```

---

## Task 4: `docs/js/main.js` 수정 및 버전 업데이트

**Files:**
- Modify: `docs/js/main.js`
- Modify: `docs/index.html` (버전 문자열)

### Step 1: `initTooltips` import 추가

`docs/js/main.js` 25번째 줄의 ui.js import 블록:
```javascript
import {
    ...
    renderWinLossCards
} from './ui.js?v=6';
```

`initTooltips` 추가 및 버전 업데이트:
```javascript
import {
    updateModeUI,
    updateSummaryCards,
    renderStatusBanner,
    renderHoldingsTable,
    renderTodayActivity,
    updateDecisionLogic,
    renderPerformanceSummaryCards,
    renderTradeSummaryStats,
    renderTradeHistory,
    renderRollingReturnCards,
    renderCurrentDrawdownCard,
    renderCalmarCard,
    renderFeeImpactCard,
    renderStatusFreshnessBadge,
    renderFailedOrderAlert,
    renderOperationsPanel,
    renderRegimePerformanceTable,
    renderYTDCard,
    renderDividendSummaryCards,
    renderWinLossCards,
    initTooltips
} from './ui.js?v=20260621-1';
```

### Step 2: `renderPerformanceTab()` 끝에 호출 추가

`docs/js/main.js` 약 207~228줄의 `renderPerformanceTab()` 함수:
```javascript
function renderPerformanceTab() {
    if (perfRendered) return;
    renderPerformanceSummaryCards(summaryData);
    // ... (기존 렌더 함수들)
    setupTimeRangeSelector(summaryData, marketType);
    perfRendered = true;
}
```

`perfRendered = true;` 바로 위에 추가:
```javascript
    initTooltips();   // 동적 DOM 생성 완료 후 툴팁 초기화
    perfRendered = true;
}
```

### Step 3: Overview 탭 초기 렌더 완료 후 호출 추가

`docs/js/main.js` `_renderSingleAccount()` 함수에서 overview 즉시 렌더 블록 바로 다음(약 200번째 줄, `let perfRendered = false;` 바로 위)에 추가:

```javascript
    // Overview 탭 정적 요소 툴팁 초기화 (VIX, SPY MDD, Volatility)
    initTooltips();
```

### Step 4: `index.html` 에서 main.js 버전 업데이트

`docs/index.html` 마지막 `<script>` 태그(약 812줄):
```html
<script type="module" src="js/main.js?v=5"></script>
```

버전 업데이트:
```html
<script type="module" src="js/main.js?v=20260621-1"></script>
```

### Step 5: 동작 확인

브라우저를 열어 다음을 순서대로 확인:
1. Overview 탭 → Risk Indicators 카드 → "VIX ⓘ" 위에 호버 → 툴팁 표시 여부
2. Performance 탭 클릭 → "CAGR ⓘ" 위에 호버 → 툴팁 표시 여부
3. Performance 탭 → "Win Rate ⓘ" h6 위에 호버 → 툴팁 표시 여부
4. Performance 탭 → 국면별 분석 테이블 헤더 "누적 수익률 ⓘ" 호버 → 툴팁 표시 여부
5. 툴팁 내용: 설명 텍스트와 평가기준(✅⚠️❌) 표시 여부

---

## Task 5: 커밋

```bash
git add docs/js/metric-tooltips.js docs/js/ui.js docs/index.html docs/js/main.js
git commit -m "feat: add hover tooltips for performance metrics

대시보드 전체 지표(CAGR, Sharpe, MDD 등 20개+)에 Bootstrap Tooltip 추가.
hover 시 한국어 설명과 평가 기준(좋음/보통/나쁨)을 표시.

- metric-tooltips.js: 지표별 툴팁 콘텐츠 사전 (신규)
- ui.js: initTooltips() 추가, 메트릭 비교 테이블에 data-metric-tooltip 주입
- index.html: 정적 카드 h6, 국면 테이블 th, Overview Risk Indicators에 속성 추가
- main.js: Overview/Performance 탭 렌더 완료 시점에 initTooltips() 호출"
```

---

## 트러블슈팅 체크리스트

| 증상 | 원인 | 해결 |
|------|------|------|
| 툴팁 아예 안 뜸 | `window.bootstrap` 미초기화 (Bootstrap JS 로딩 순서) | `<script src="bootstrap.bundle.min.js">` 가 `main.js` 보다 먼저 로드되는지 확인 |
| 성능 탭 테이블만 안 뜸 | `initTooltips()`가 렌더 전에 실행됨 | `perfRendered = true` 직전으로 호출 위치 이동 |
| 툴팁 HTML 태그가 텍스트로 출력됨 | `html: true` 옵션 누락 | `initTooltips()`의 Tooltip 생성자 옵션 확인 |
| 같은 요소에 툴팁 중복 초기화 경고 | 탭 전환 시 `initTooltips()` 재호출 | `Tooltip.getInstance(el)` dispose 로직 확인 |
