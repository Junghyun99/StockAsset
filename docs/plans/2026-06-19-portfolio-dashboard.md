# Portfolio Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 멀티계좌를 한눈에 조망하는 `portfolio.html` 신규 페이지를 만든다 — 통화별(KRW/USD) 합산 배너, 계좌 카드 그리드, 누적 수익률 비교 차트.

**Architecture:** 기존 `index.html`·`ui.js`·`charts.js`는 손대지 않는다. 신규 파일(`portfolio.html`, `portfolio-main.js`, `portfolio-cards.js`, `portfolio-charts.js`)로만 구성하고, `utils.js`에 `formatAmount` 한 줄만 추가한다. 상세 보기 클릭 시 기존 `index.html`로 이동한다(별도 URL).

**Tech Stack:** Vanilla JS ES Modules, Bootstrap 5, Chart.js (기존 CDN 그대로)

---

## Task 1: `utils.js` — `formatAmount` 헬퍼 추가

**Files:**
- Modify: `docs/js/utils.js` (맨 아래 `formatCurrency` 아래에 추가)

### Step 1: 함수 추가

`formatCurrency` 함수(줄 ~299) 바로 아래에 삽입:

```js
/**
 * market_type에 따라 KRW 또는 USD 포맷 선택
 * @param {number} value
 * @param {'domestic'|'overseas'} marketType
 */
export function formatAmount(value, marketType) {
    return marketType === 'domestic' ? formatKRW(value) : formatCurrency(value);
}
```

### Step 2: 브라우저 콘솔에서 동작 확인

나중에 portfolio 페이지 열었을 때 import가 잘 되는지 확인하면 충분. 별도 테스트 없음(JS 테스트 프레임워크 없음).

### Step 3: Commit

```bash
git add docs/js/utils.js
git commit -m "feat(dashboard): add formatAmount helper for market_type-aware currency formatting"
```

---

## Task 2: `portfolio.html` — HTML 뼈대

**Files:**
- Create: `docs/portfolio.html`

### Step 1: 파일 작성

```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SolidQuant Portfolio</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link href="css/style.css" rel="stylesheet">
</head>
<body class="bg-light">

    <!-- Navbar -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <div class="d-flex align-items-center">
                <a class="navbar-brand" href="portfolio.html">
                    <i class="fas fa-robot me-2"></i>SolidQuant Bot
                </a>
                <div class="btn-group btn-group-sm ms-3" role="group">
                    <a href="portfolio.html" class="btn btn-outline-light active">Portfolio</a>
                    <a href="index.html" class="btn btn-outline-light">Live</a>
                    <a href="index.html?mode=backtest" class="btn btn-outline-light">Backtest</a>
                </div>
            </div>
            <span class="navbar-text text-white" id="last-updated">Loading...</span>
        </div>
    </nav>

    <div class="container mt-4">

        <!-- 통화별 합산 배너 -->
        <div class="row g-3 mb-4" id="currency-summary">
            <!-- portfolio-main.js가 채움 -->
        </div>

        <!-- 계좌 카드 섹션 (KRW / USD 순서) -->
        <div id="account-sections">
            <div class="text-center text-muted py-5">
                <i class="fas fa-spinner fa-spin me-2"></i>계좌 데이터 로딩 중...
            </div>
        </div>

        <!-- 누적 수익률 비교 차트 -->
        <div class="card border-0 shadow-sm mb-4" id="comparison-chart-card">
            <div class="card-header bg-white py-3 d-flex justify-content-between align-items-center flex-wrap">
                <h5 class="mb-0"><i class="fas fa-chart-line me-2"></i>누적 수익률 비교 (%)</h5>
                <div class="btn-group btn-group-sm mt-2 mt-md-0" id="chart-range-selector">
                    <button class="btn btn-outline-secondary" data-range="1M">1M</button>
                    <button class="btn btn-outline-secondary" data-range="3M">3M</button>
                    <button class="btn btn-outline-secondary" data-range="6M">6M</button>
                    <button class="btn btn-outline-secondary" data-range="1Y">1Y</button>
                    <button class="btn btn-outline-secondary active" data-range="ALL">ALL</button>
                </div>
            </div>
            <div class="card-body">
                <div style="height: 400px;">
                    <canvas id="portfolioComparisonChart"></canvas>
                </div>
            </div>
        </div>

    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script type="module" src="js/portfolio-main.js?v=1"></script>
</body>
</html>
```

### Step 2: 브라우저에서 열어 로딩 스피너가 보이는지 확인

```bash
# GitHub Pages 배포 전이면 로컬에서 확인
python3 -m http.server 8080 --directory docs/
# http://localhost:8080/portfolio.html 접속
```

### Step 3: Commit

```bash
git add docs/portfolio.html
git commit -m "feat(portfolio): add portfolio.html skeleton"
```

---

## Task 3: `portfolio-main.js` — 데이터 로딩 및 오케스트레이션

**Files:**
- Create: `docs/js/portfolio-main.js`

데이터 흐름:
- `data/accounts.json` → `["my_test", ...]`
- `data/accounts_meta.json` → `{"my_test": {"market_type": "domestic", "color": "#bdbd42"}}`
- `data/{id}/status.json` → total_value, regime, target_exposure, holdings
- `data/{id}/summary.json` → 수익률 시계열

### Step 1: 파일 작성

```js
// docs/js/portfolio-main.js
import { loadAccountsMeta, ACCOUNT_COLORS, ACCOUNT_MARKET_TYPES } from './utils.js?v=3';
import { renderCurrencySummary, renderAccountSections } from './portfolio-cards.js?v=1';
import { renderComparisonChart, updateChartRange } from './portfolio-charts.js?v=1';

document.addEventListener('DOMContentLoaded', async () => {
    const base = 'data/';
    const bust = `v=${Date.now()}`;

    try {
        await loadAccountsMeta(base);

        const accountsRes = await fetch(`${base}accounts.json?${bust}`);
        if (!accountsRes.ok) throw new Error('accounts.json not found');
        const accountIds = await accountsRes.json();

        // 각 계좌 병렬 로드
        const accountsData = new Map();
        await Promise.all(accountIds.map(async (id) => {
            const path = `${base}${id}/`;
            const [statusRes, summaryRes, groupRes] = await Promise.all([
                fetch(`${path}status.json?${bust}`),
                fetch(`${path}summary.json?${bust}`),
                fetch(`${path}asset_groups.json?${bust}`),
            ]);
            accountsData.set(id, {
                status:      statusRes.ok  ? await statusRes.json()  : {},
                summary:     summaryRes.ok ? await summaryRes.json() : [],
                groupConfig: groupRes.ok   ? await groupRes.json()   : null,
            });
        }));

        // 렌더링
        renderCurrencySummary(accountsData);
        renderAccountSections(accountsData);
        renderComparisonChart(accountsData);
        setupRangeSelector(accountsData);

        // 마지막 업데이트 시간 (첫 번째 계좌 기준)
        const first = accountsData.values().next().value;
        document.getElementById('last-updated').textContent =
            `Last Update: ${first?.status?.last_updated || 'Unknown'}`;

    } catch (err) {
        console.error('Portfolio load error:', err);
        document.getElementById('account-sections').innerHTML =
            `<div class="alert alert-warning">데이터 로드 실패: ${err.message}</div>`;
    }
});

function setupRangeSelector(accountsData) {
    const selector = document.getElementById('chart-range-selector');
    if (!selector) return;
    selector.querySelectorAll('button[data-range]').forEach(btn => {
        btn.addEventListener('click', () => {
            selector.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateChartRange(accountsData, btn.dataset.range);
        });
    });
}
```

### Step 2: Commit

```bash
git add docs/js/portfolio-main.js
git commit -m "feat(portfolio): add portfolio-main.js data loading"
```

---

## Task 4: `portfolio-cards.js` — 계좌 카드 & 통화별 섹션 렌더링

**Files:**
- Create: `docs/js/portfolio-cards.js`

각 카드에 표시할 내용:
- 계좌 ID + 색상 인디케이터
- 총 자산 (통화에 맞게)
- 일간 수익률 (summary 마지막 2개 비교)
- 시장 국면 badge (Bull/Bear/Crash 등)
- Exposure % 바
- 그룹 A/B/C 비율 바 (summary 최신값 group_a / group_b / group_c 사용)
- [상세 보기 →] → `index.html` (기존 페이지)

### Step 1: 파일 작성

```js
// docs/js/portfolio-cards.js
import {
    formatAmount, formatPercent,
    ACCOUNT_COLORS, ACCOUNT_MARKET_TYPES,
    getRegimeColorClass, filterByDateRange
} from './utils.js?v=3';

/**
 * 통화별 합산 배너 렌더링
 */
export function renderCurrencySummary(accountsData) {
    let krwTotal = 0, usdTotal = 0;
    let krwCount = 0, usdCount = 0;

    for (const [id, data] of accountsData) {
        const mt = ACCOUNT_MARKET_TYPES[id] || 'overseas';
        const val = data.status?.portfolio?.total_value ?? 0;
        if (mt === 'domestic') { krwTotal += val; krwCount++; }
        else                   { usdTotal += val; usdCount++; }
    }

    const el = document.getElementById('currency-summary');
    if (!el) return;

    const cards = [];
    if (krwCount > 0) {
        cards.push(`
            <div class="col-md-6">
                <div class="card border-0 shadow-sm h-100" style="border-left: 4px solid #0d6efd !important;">
                    <div class="card-body">
                        <div class="text-muted small mb-1">
                            <i class="fas fa-flag me-1"></i>KRW 계좌 합산 <span class="badge bg-primary ms-1">${krwCount}개</span>
                        </div>
                        <div class="fw-bold fs-4">₩${Math.round(krwTotal).toLocaleString('ko-KR')}</div>
                    </div>
                </div>
            </div>
        `);
    }
    if (usdCount > 0) {
        cards.push(`
            <div class="col-md-6">
                <div class="card border-0 shadow-sm h-100" style="border-left: 4px solid #198754 !important;">
                    <div class="card-body">
                        <div class="text-muted small mb-1">
                            <i class="fas fa-globe me-1"></i>USD 계좌 합산 <span class="badge bg-success ms-1">${usdCount}개</span>
                        </div>
                        <div class="fw-bold fs-4">$${usdTotal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
                    </div>
                </div>
            </div>
        `);
    }
    el.innerHTML = cards.join('');
}

/**
 * KRW / USD 섹션별 카드 그리드 렌더링
 */
export function renderAccountSections(accountsData) {
    const el = document.getElementById('account-sections');
    if (!el) return;

    const domesticIds  = [...accountsData.keys()].filter(id => ACCOUNT_MARKET_TYPES[id] === 'domestic');
    const overseasIds  = [...accountsData.keys()].filter(id => ACCOUNT_MARKET_TYPES[id] !== 'domestic');

    let html = '';
    if (domesticIds.length > 0) {
        html += buildSection('🇰🇷 KRW 계좌', domesticIds, accountsData, 'domestic');
    }
    if (overseasIds.length > 0) {
        html += buildSection('🇺🇸 USD 계좌', overseasIds, accountsData, 'overseas');
    }
    el.innerHTML = html;
}

function buildSection(title, ids, accountsData, marketType) {
    const cards = ids.map(id => buildCard(id, accountsData.get(id), marketType)).join('');
    return `
        <h6 class="text-muted fw-bold mb-3 mt-2">${title}</h6>
        <div class="row g-3 mb-4">${cards}</div>
    `;
}

function buildCard(id, data, marketType) {
    const status      = data.status || {};
    const summary     = data.summary || [];
    const portfolio   = status.portfolio || {};
    const strategy    = status.strategy  || {};
    const color       = ACCOUNT_COLORS[id] || '#6c757d';

    const totalValue  = portfolio.total_value ?? 0;
    const regime      = strategy.regime || '-';
    const exposure    = ((strategy.target_exposure ?? 0) * 100).toFixed(0);

    // 일간 수익률
    let dailyReturn = null;
    if (summary.length >= 2) {
        const prev = summary[summary.length - 2].total_value;
        const curr = summary[summary.length - 1].total_value;
        dailyReturn = prev > 0 ? (curr / prev - 1) * 100 : 0;
    }
    const dailyBadge = dailyReturn == null ? '' :
        `<span class="badge rounded-pill ms-2 ${dailyReturn >= 0 ? 'bg-success' : 'bg-danger'}">
            ${dailyReturn >= 0 ? '+' : ''}${dailyReturn.toFixed(2)}%
         </span>`;

    // 그룹 비율 (summary 최신값 사용)
    const latest = summary.length > 0 ? summary[summary.length - 1] : null;
    const groupBar = latest ? buildGroupBar(latest, totalValue) : '';

    // 국면 색상
    const regimeClass = getRegimeColorClass(regime);

    return `
        <div class="col-sm-6 col-lg-4 col-xl-3">
            <div class="card h-100 border-0 shadow-sm" style="border-top: 3px solid ${color} !important;">
                <div class="card-body d-flex flex-column">
                    <div class="d-flex align-items-center mb-2">
                        <span class="fw-bold">${id}</span>
                        ${dailyBadge}
                    </div>
                    <div class="fs-5 fw-bold mb-1">${formatAmount(totalValue, marketType)}</div>
                    <div class="mb-2">
                        <span class="fw-semibold ${regimeClass}">${regime.replace('_', ' ')}</span>
                        <span class="text-muted small ms-2">Exp ${exposure}%</span>
                    </div>
                    <!-- Exposure 바 -->
                    <div class="progress mb-3" style="height: 6px;">
                        <div class="progress-bar" style="width: ${exposure}%; background-color: ${color};"></div>
                    </div>
                    <!-- 그룹 비율 바 -->
                    ${groupBar}
                    <div class="mt-auto pt-2">
                        <a href="index.html" class="btn btn-outline-secondary btn-sm w-100">
                            상세 보기 <i class="fas fa-arrow-right ms-1"></i>
                        </a>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function buildGroupBar(latest, totalValue) {
    if (!totalValue) return '';
    const a = latest.group_a ?? 0;
    const b = latest.group_b ?? 0;
    const c = latest.group_c ?? 0;
    const cash = latest.cash_balance ?? 0;
    const pctA = (a / totalValue * 100).toFixed(1);
    const pctB = (b / totalValue * 100).toFixed(1);
    const pctC = (c / totalValue * 100).toFixed(1);
    const pctCash = (cash / totalValue * 100).toFixed(1);

    return `
        <div class="mb-1">
            <div class="d-flex" style="height: 8px; border-radius: 4px; overflow: hidden;">
                <div style="width: ${pctA}%; background: #0d6efd;" title="A(성장) ${pctA}%"></div>
                <div style="width: ${pctB}%; background: #198754;" title="B(안전) ${pctB}%"></div>
                <div style="width: ${pctC}%; background: #ffc107;" title="C(현금) ${pctC}%"></div>
                <div style="width: ${pctCash}%; background: #dee2e6;" title="현금 ${pctCash}%"></div>
            </div>
            <div class="d-flex gap-2 mt-1" style="font-size: 0.7rem; color: #6c757d;">
                <span><span style="color:#0d6efd;">■</span> A ${pctA}%</span>
                <span><span style="color:#198754;">■</span> B ${pctB}%</span>
                <span><span style="color:#ffc107;">■</span> C ${pctC}%</span>
            </div>
        </div>
    `;
}
```

### Step 2: 브라우저에서 카드 렌더링 확인

`http://localhost:8080/portfolio.html` 접속 후:
- KRW 합산 배너 표시 여부
- my_test 카드에 ₩ 단위 총 자산 표시 여부
- Exposure 바, 그룹 비율 바 표시 여부

### Step 3: Commit

```bash
git add docs/js/portfolio-cards.js
git commit -m "feat(portfolio): add account card and currency summary rendering"
```

---

## Task 5: `portfolio-charts.js` — 누적 수익률 비교 차트

**Files:**
- Create: `docs/js/portfolio-charts.js`

각 계좌의 `summary.json`에서 `total_value`를 가져와 첫 날 대비 누적 수익률(%) 시계열을 계산하고 Chart.js 라인 차트로 그린다. 통화가 달라도 % 기준이므로 같은 Y축에 비교 가능.

### Step 1: 파일 작성

```js
// docs/js/portfolio-charts.js
import { ACCOUNT_COLORS, filterByDateRange } from './utils.js?v=3';

let comparisonChart = null;

/**
 * 누적 수익률(%) 비교 라인 차트 렌더링
 */
export function renderComparisonChart(accountsData, range = 'ALL') {
    const canvas = document.getElementById('portfolioComparisonChart');
    if (!canvas) return;

    if (comparisonChart) {
        comparisonChart.destroy();
        comparisonChart = null;
    }

    const datasets = [];
    let allDates = new Set();

    for (const [id, data] of accountsData) {
        const filtered = filterByDateRange(data.summary || [], range);
        if (filtered.length < 2) continue;

        filtered.forEach(d => allDates.add(d.date));

        const base = filtered[0].total_value;
        const returns = filtered.map(d => ({
            x: d.date,
            y: base > 0 ? ((d.total_value / base) - 1) * 100 : 0,
        }));

        datasets.push({
            label: id,
            data: returns,
            borderColor: ACCOUNT_COLORS[id] || '#6c757d',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.1,
        });
    }

    const sortedDates = [...allDates].sort();

    comparisonChart = new Chart(canvas, {
        type: 'line',
        data: { labels: sortedDates, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top' },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y >= 0 ? '+' : ''}${ctx.parsed.y.toFixed(2)}%`,
                    },
                },
            },
            scales: {
                x: {
                    ticks: {
                        maxTicksLimit: 8,
                        callback: (_, i, arr) => {
                            // 레이블 간격 자동 조절
                            const step = Math.max(1, Math.floor(arr.length / 8));
                            return i % step === 0 ? sortedDates[i] : '';
                        },
                    },
                },
                y: {
                    ticks: {
                        callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%',
                    },
                },
            },
        },
    });
}

/**
 * 기간 선택 시 차트 재렌더링
 */
export function updateChartRange(accountsData, range) {
    renderComparisonChart(accountsData, range);
}
```

### Step 2: 브라우저에서 차트 확인

- `portfolio.html`에서 차트 라인이 표시되는지
- 1M/3M/6M/1Y/ALL 버튼 클릭 시 차트가 갱신되는지

### Step 3: Commit

```bash
git add docs/js/portfolio-charts.js
git commit -m "feat(portfolio): add cumulative return comparison chart"
```

---

## Task 6: `index.html` Navbar에 Portfolio 링크 추가

**Files:**
- Modify: `docs/index.html:24-27`

### Step 1: 기존 navbar 버튼 그룹에 Portfolio 추가

현재 코드 (`docs/index.html` 줄 24):
```html
<div class="btn-group btn-group-sm ms-3" role="group" aria-label="Mode Switcher">
    <a href="index.html" id="link-live" class="btn btn-outline-light">Live</a>
    <a href="index.html?mode=backtest" id="link-backtest" class="btn btn-outline-light">Backtest</a>
</div>
```

교체:
```html
<div class="btn-group btn-group-sm ms-3" role="group" aria-label="Mode Switcher">
    <a href="portfolio.html" class="btn btn-outline-light">Portfolio</a>
    <a href="index.html" id="link-live" class="btn btn-outline-light">Live</a>
    <a href="index.html?mode=backtest" id="link-backtest" class="btn btn-outline-light">Backtest</a>
</div>
```

### Step 2: 확인

`index.html`에서 "Portfolio" 버튼이 navbar에 표시되고, 클릭 시 `portfolio.html`로 이동하는지 확인.

### Step 3: Commit

```bash
git add docs/index.html
git commit -m "feat(portfolio): add Portfolio nav link to index.html"
```

---

## Task 7: 최종 통합 검증 및 Push

### Step 1: 전체 흐름 수동 테스트 체크리스트

- [ ] `portfolio.html` 접속 시 로딩 스피너 → 카드 렌더링 완료
- [ ] KRW 합산 배너에 `₩` 단위 표시
- [ ] 계좌 카드에 `₩` 단위 총 자산 표시 (my_test는 domestic)
- [ ] Exposure 바 정상 표시
- [ ] A/B/C 그룹 비율 바 색상 정상 (파랑/초록/노랑)
- [ ] 누적 수익률 비교 차트 표시
- [ ] 기간 선택 버튼(1M ~ ALL) 클릭 시 차트 갱신
- [ ] "상세 보기" 클릭 시 `index.html`로 이동
- [ ] `index.html`에서 Portfolio 버튼 클릭 시 `portfolio.html`로 이동

### Step 2: Python 테스트가 깨지지 않는지 확인

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=80 tests/
```
예상: PASS (JS 전용 변경, Python 코드 무관)

### Step 3: Push

```bash
git push -u origin claude/currency-display-market-type-pmrw83
```

---

## 파일 변경 요약

| 파일 | 작업 |
|------|------|
| `docs/js/utils.js` | `formatAmount` 함수 추가 (3줄) |
| `docs/portfolio.html` | 신규 생성 |
| `docs/js/portfolio-main.js` | 신규 생성 |
| `docs/js/portfolio-cards.js` | 신규 생성 |
| `docs/js/portfolio-charts.js` | 신규 생성 |
| `docs/index.html` | navbar Portfolio 링크 추가 (1줄) |

Python 코드 변경 없음 → 기존 테스트 영향 없음.
