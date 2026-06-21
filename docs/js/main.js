// docs/js/main.js
// 대시보드 진입점: 모드 감지, 데이터 로딩, 탭 라우팅, 렌더링 오케스트레이션

import {
    renderStrategyChart,
    renderUnifiedChart,
    renderGroupBarChart,
    resizeAllCharts,
    updatePerformanceChartRange,
    renderCumulativeDividendChart,
    renderYearlyDividendChart,
    renderCumulativePnlChart,
    renderDrawdownChart,
    renderAlphaLineChart,
    renderMonthlyHeatmap,
    renderAnnualReturnsChart,
    renderTradeReasonPie,
    renderMonthlyTradeFrequencyChart,
    renderTickerContributionChart,
    renderCurrentAllocationDoughnut,
    renderRegimeDistributionDoughnut,
    renderHistoricalAllocationChart
} from './charts.js?v=3';

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
    renderWinLossCards
} from './ui.js?v=6';

import { loadEngineMeta, loadAccountsMeta, ACCOUNT_MARKET_TYPES } from './utils.js?v=6';

import {
    renderCompareOverview,
    renderCompareTradesTab,
} from './compare-ui.js?v=3';

import {
    renderAccountOverview,
    renderAccountTradesTab,
} from './account-compare-ui.js?v=2';

import {
    renderAccountPerformanceChart,
    renderAccountStrategyChart,
    updateAccountChartRange,
    resizeAccountCharts,
} from './account-compare-charts.js?v=1';

import {
    renderComparePerformanceChart,
    renderCompareStrategyChart,
    renderCompareCumulativeDividendChart,
    renderCompareYearlyDividendChart,
    updateCompareChartRange,
    resizeCompareCharts,
} from './compare-charts.js?v=2';

document.addEventListener('DOMContentLoaded', async function() {
    // 1. URL 파라미터에서 모드 확인 (?mode=backtest)
    const urlParams = new URLSearchParams(window.location.search);
    const isBacktest = urlParams.get('mode') === 'backtest';

    // UI 초기화 (버튼 활성화 상태 및 배지 설정)
    updateModeUI(isBacktest);

    // 2. 탭 해시 라우팅 설정
    setupTabRouting();

    try {
        if (isBacktest) {
            await loadCompareMode();
        } else {
            await loadLiveMode();
        }
    } catch (error) {
        console.error("Data loading failed:", error);
        const dataPath = isBacktest ? 'data/backtest/compare/' : 'data/';
        document.body.insertAdjacentHTML('beforeend',
            `<div class="alert alert-warning position-fixed bottom-0 end-0 m-3 shadow" style="z-index: 9999;">
                <i class="fas fa-exclamation-triangle me-2"></i> 데이터(${dataPath}) 로드 실패. 파일 생성을 기다려주세요.
            </div>`);
    }
});

/**
 * Live 모드 데이터 로딩 및 렌더링.
 * accounts.json 유무에 따라 단일 계좌(기존 UI) / 다중 계좌(비교 UI)로 분기.
 */
async function loadLiveMode() {
    const basePath = 'data/';
    const cacheBust = `v=${Date.now()}`;

    // 계좌 메타(색상·시장유형) 로드
    await loadAccountsMeta(basePath);

    // accounts.json 로드 시도
    const accountsRes = await fetch(`${basePath}accounts.json?${cacheBust}`);

    if (!accountsRes.ok) {
        // Fallback: accounts.json 없으면 레거시 단일 계좌 모드 (data/ 직하위)
        return _loadLegacySingleAccount(basePath, cacheBust);
    }

    const accountIds = await accountsRes.json();
    if (!accountIds || accountIds.length === 0) {
        return _loadLegacySingleAccount(basePath, cacheBust);
    }

    // 각 계좌별 데이터 병렬 로드
    const accountsData = new Map();
    await Promise.all(accountIds.map(async (id) => {
        const path = `${basePath}${id}/`;
        const [summaryRes, statusRes, historyRes, groupRes] = await Promise.all([
            fetch(`${path}summary.json?${cacheBust}`),
            fetch(`${path}status.json?${cacheBust}`),
            fetch(`${path}history.json?${cacheBust}`),
            fetch(`${path}asset_groups.json?${cacheBust}`),
        ]);
        accountsData.set(id, {
            summary:    summaryRes.ok ? await summaryRes.json().catch(() => [])    : [],
            status:     statusRes.ok  ? await statusRes.json().catch(() => ({}))   : {},
            history:    historyRes.ok ? await historyRes.json().catch(() => [])    : [],
            groupConfig: groupRes.ok  ? await groupRes.json().catch(() => null)    : null,
        });
    }));

    if (accountIds.length === 1) {
        // 단일 계좌: 기존 UI (경로만 계좌 서브디렉토리로 수정)
        const data = accountsData.get(accountIds[0]);
        const marketType = (ACCOUNT_MARKET_TYPES[accountIds[0]] || 'overseas');
        _renderSingleAccount(data, marketType);
    } else {
        // 다중 계좌: 비교 UI
        renderAccountOverview(accountsData);
        disableLiveOnlyTabs();

        let perfRendered = false;
        let tradesRendered = false;

        function renderPerformanceTab() {
            if (perfRendered) return;
            setupAccountPerformanceHTML();
            renderAccountPerformanceChart(accountsData);
            renderAccountStrategyChart(accountsData);
            setupAccountTimeRangeSelector(accountsData);
            perfRendered = true;
        }

        function renderTradesTab() {
            if (tradesRendered) return;
            renderAccountTradesTab(accountsData);
            tradesRendered = true;
        }

        setupTabEvents({
            performance: renderPerformanceTab,
            trades: renderTradesTab,
            onResize: resizeAccountCharts,
        });

        const firstData = accountsData.values().next().value;
        document.getElementById('last-updated').innerText =
            `Last Update: ${firstData.status?.last_updated || 'Unknown'}`;
    }
}

/**
 * 단일 계좌 UI 렌더링 (기존 loadLiveMode 로직)
 */
function _renderSingleAccount({ summary: summaryData, status: statusData, history: historyData, groupConfig }, marketType = 'overseas') {
    window.__summary = summaryData;
    window.__status = statusData;
    window.__history = historyData;

    renderStatusBanner(statusData);
    updateSummaryCards(statusData, summaryData, marketType);
    renderGroupBarChart(statusData, groupConfig, marketType);
    renderHoldingsTable(statusData, groupConfig, marketType);
    renderTodayActivity(historyData, statusData, marketType, groupConfig);
    updateDecisionLogic(summaryData[summaryData.length - 1]);
    renderFailedOrderAlert(historyData, groupConfig);
    renderStatusFreshnessBadge(statusData);

    let perfRendered = false;
    let allocationRendered = false;
    let tradesRendered = false;
    let opsRendered = false;

    function renderPerformanceTab() {
        if (perfRendered) return;
        renderPerformanceSummaryCards(summaryData);
        renderRegimePerformanceTable(summaryData);
        renderYTDCard(summaryData);
        renderWinLossCards(summaryData);
        renderRollingReturnCards(summaryData);
        renderCurrentDrawdownCard(summaryData);
        renderCalmarCard(summaryData);
        renderUnifiedChart(summaryData, marketType);
        renderCumulativePnlChart(summaryData, marketType);
        renderDrawdownChart(summaryData);
        renderAlphaLineChart(summaryData);
        renderAnnualReturnsChart(summaryData);
        renderMonthlyHeatmap(summaryData);
        renderStrategyChart(summaryData);
        renderDividendSummaryCards(summaryData, marketType);
        renderCumulativeDividendChart(summaryData, marketType);
        renderYearlyDividendChart(summaryData, marketType);
        setupTimeRangeSelector(summaryData, marketType);
        perfRendered = true;
    }

    function renderAllocationTab() {
        if (allocationRendered) return;
        renderCurrentAllocationDoughnut(statusData, groupConfig, marketType);
        renderRegimeDistributionDoughnut(summaryData);
        renderHistoricalAllocationChart(summaryData, marketType);
        allocationRendered = true;
    }

    function renderTradesTab() {
        if (tradesRendered) return;
        renderTradeSummaryStats(historyData, marketType);
        renderFeeImpactCard(historyData, summaryData);
        renderTradeReasonPie(historyData);
        renderMonthlyTradeFrequencyChart(historyData);
        renderTickerContributionChart(historyData, marketType, groupConfig);
        renderTradeHistory(historyData, undefined, marketType, groupConfig);
        tradesRendered = true;
    }

    function renderOperationsTab() {
        if (opsRendered) return;
        renderOperationsPanel(statusData, historyData, summaryData, groupConfig);
        opsRendered = true;
    }

    setupTabEvents({
        performance: renderPerformanceTab,
        allocation: renderAllocationTab,
        trades: renderTradesTab,
        operations: renderOperationsTab,
        onResize: resizeAllCharts,
    });

    document.getElementById('last-updated').innerText = `Last Update: ${statusData.last_updated || 'Unknown'}`;
}

/**
 * Fallback: accounts.json 없을 때 레거시 data/ 직하위 경로에서 로드
 */
async function _loadLegacySingleAccount(basePath, cacheBust) {
    const [summaryRes, statusRes, historyRes, groupConfigRes] = await Promise.all([
        fetch(`${basePath}summary.json?${cacheBust}`),
        fetch(`${basePath}status.json?${cacheBust}`),
        fetch(`${basePath}history.json?${cacheBust}`),
        fetch(`${basePath}asset_groups.json?${cacheBust}`),
    ]);
    _renderSingleAccount({
        summary: await summaryRes.json(),
        status:  await statusRes.json(),
        history: await historyRes.json(),
        groupConfig: groupConfigRes.ok ? await groupConfigRes.json() : null,
    }, 'overseas');
}

/**
 * Backtest Compare 모드 데이터 로딩 및 렌더링
 */
async function loadCompareMode() {
    const basePath = 'data/backtest/compare/';
    const cacheBust = `v=${Date.now()}`;

    // 0. 엔진 색상 메타 로드 (ENGINE_COLORS 런타임 주입)
    await loadEngineMeta(basePath);

    // 1. 엔진 목록 로드
    const enginesRes = await fetch(`${basePath}engines.json?${cacheBust}`);
    if (!enginesRes.ok) throw new Error('engines.json not found');
    const engineNames = await enginesRes.json();

    // 2. 각 엔진별 데이터 병렬 로드
    const enginesData = new Map();
    const loadPromises = engineNames.map(async (name) => {
        const enginePath = `${basePath}${name}/`;
        const [summaryRes, statusRes, historyRes, groupRes] = await Promise.all([
            fetch(`${enginePath}summary.json?${cacheBust}`),
            fetch(`${enginePath}status.json?${cacheBust}`),
            fetch(`${enginePath}history.json?${cacheBust}`),
            fetch(`${enginePath}asset_groups.json?${cacheBust}`),
        ]);
        enginesData.set(name, {
            summary: await summaryRes.json(),
            status: await statusRes.json(),
            history: await historyRes.json(),
            groupConfig: groupRes.ok ? await groupRes.json() : null,
        });
    });
    await Promise.all(loadPromises);

    // 3. Overview 탭 렌더링
    renderCompareOverview(enginesData);

    // 컴페어 모드에서는 Allocation/Operations 탭 비활성화 (Live 전용)
    disableLiveOnlyTabs();

    // 4. Performance / Trades 탭 (lazy)
    let perfRendered = false;
    let tradesRendered = false;

    function renderPerformanceTab() {
        if (perfRendered) return;
        setupComparePerformanceHTML();
        renderComparePerformanceChart(enginesData);
        renderCompareStrategyChart(enginesData);
        renderCompareCumulativeDividendChart(enginesData);
        renderCompareYearlyDividendChart(enginesData);
        setupCompareTimeRangeSelector(enginesData);
        perfRendered = true;
    }

    function renderTradesTab() {
        if (tradesRendered) return;
        renderCompareTradesTab(enginesData);
        tradesRendered = true;
    }

    setupTabEvents({
        performance: renderPerformanceTab,
        trades: renderTradesTab,
        onResize: resizeCompareCharts
    });

    // 마지막 업데이트 시간
    const firstEngine = enginesData.values().next().value;
    document.getElementById('last-updated').innerText =
        `Last Update: ${firstEngine.status.last_updated || 'Unknown'}`;
}

/**
 * Performance 탭의 Compare 모드 HTML 구조 삽입
 */
function setupComparePerformanceHTML() {
    const perfTab = document.getElementById('performance');
    if (!perfTab) return;

    perfTab.innerHTML = `
        <!-- Performance Chart + Time Range Selector -->
        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3 d-flex justify-content-between align-items-start flex-wrap">
                <div>
                    <h5 class="mb-0"><i class="fas fa-chart-area me-2"></i>Engine Performance Comparison</h5>
                    <div class="mt-2 small d-flex gap-2 flex-wrap">
                        <span class="badge border text-dark" style="background-color: rgba(25, 135, 84, 0.15);">Bull</span>
                        <span class="badge border text-dark" style="background-color: rgba(255, 193, 7, 0.15);">Sideways</span>
                        <span class="badge border text-dark" style="background-color: rgba(220, 53, 69, 0.1);">Bear Weak</span>
                        <span class="badge border text-dark" style="background-color: rgba(220, 53, 69, 0.2);">Bear Strong</span>
                        <span class="badge border text-white" style="background-color: rgba(33, 37, 41, 0.4);">Crash</span>
                    </div>
                </div>
                <div class="btn-group btn-group-sm mt-2 mt-md-0" id="time-range-selector" role="group">
                    <button type="button" class="btn btn-outline-secondary" data-range="1M">1M</button>
                    <button type="button" class="btn btn-outline-secondary" data-range="3M">3M</button>
                    <button type="button" class="btn btn-outline-secondary" data-range="6M">6M</button>
                    <button type="button" class="btn btn-outline-secondary" data-range="1Y">1Y</button>
                    <button type="button" class="btn btn-outline-secondary active" data-range="ALL">ALL</button>
                </div>
            </div>
            <div class="card-body">
                <div style="height: 500px;">
                    <canvas id="comparePerformanceChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Strategy Comparison Chart -->
        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3">
                <h5 class="mb-0"><i class="fas fa-microchip me-2"></i>Exposure Strategy Comparison</h5>
            </div>
            <div class="card-body">
                <div style="height: 300px;">
                    <canvas id="compareStrategyChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Dividend Charts -->
        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3">
                <h5 class="mb-0"><i class="fas fa-hand-holding-usd me-2"></i>Cumulative Dividend Comparison</h5>
            </div>
            <div class="card-body">
                <div style="height: 280px;">
                    <canvas id="compareCumulativeDividendChart"></canvas>
                </div>
            </div>
        </div>

        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3">
                <h5 class="mb-0"><i class="fas fa-calendar-alt me-2"></i>Annual Dividend Comparison (Full Period)</h5>
            </div>
            <div class="card-body">
                <div style="height: 280px;">
                    <canvas id="compareYearlyDividendChart"></canvas>
                </div>
            </div>
        </div>
    `;
}

/**
 * 탭 전환 이벤트 설정 (공통)
 * @param {Object} handlers - { performance, allocation, trades, operations, onResize }
 *   각 탭 핸들러는 선택적 (미지정 시 해당 탭에 no-op).
 */
function setupTabEvents(handlers) {
    const { performance: onPerformance, allocation: onAllocation,
            trades: onTrades, operations: onOperations, onResize } = handlers;

    const dispatch = (target) => {
        if (target === '#performance' && onPerformance) {
            onPerformance();
            if (onResize) setTimeout(() => onResize(), 50);
        } else if (target === '#allocation' && onAllocation) {
            onAllocation();
            if (onResize) setTimeout(() => onResize(), 50);
        } else if (target === '#trades' && onTrades) {
            onTrades();
        } else if (target === '#operations' && onOperations) {
            onOperations();
        }
    };

    document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tab => {
        tab.addEventListener('shown.bs.tab', (e) => {
            const target = e.target.getAttribute('data-bs-target');
            dispatch(target);
            const tabName = target.replace('#', '');
            history.replaceState(null, '', '#' + tabName);
        });
    });

    // 현재 해시에 따라 해당 탭 활성화
    const currentHash = window.location.hash.replace('#', '') || 'overview';
    const hashToTabId = {
        'performance': 'performance-tab',
        'allocation': 'allocation-tab',
        'trades': 'trades-tab',
        'operations': 'operations-tab',
    };
    if (hashToTabId[currentHash]) {
        activateTab(hashToTabId[currentHash]);
        dispatch('#' + currentHash);
    }
}

/**
 * Compare 모드: Live 전용 탭 비활성화
 */
function disableLiveOnlyTabs() {
    ['allocation-tab', 'operations-tab'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.classList.add('disabled');
            btn.setAttribute('aria-disabled', 'true');
            btn.setAttribute('tabindex', '-1');
            btn.title = 'Live 모드 전용';
            btn.style.pointerEvents = 'none';
            btn.style.opacity = '0.45';
        }
    });
}

/**
 * URL 해시 기반 탭 라우팅 설정
 */
function setupTabRouting() {
    window.addEventListener('hashchange', () => {
        const hash = window.location.hash.replace('#', '');
        const tabMap = {
            'overview': 'overview-tab',
            'performance': 'performance-tab',
            'allocation': 'allocation-tab',
            'trades': 'trades-tab',
            'operations': 'operations-tab'
        };
        if (tabMap[hash]) {
            activateTab(tabMap[hash]);
        }
    });
}

/**
 * 프로그래밍 방식으로 탭 활성화
 */
function activateTab(tabId) {
    const tabEl = document.getElementById(tabId);
    if (tabEl) {
        const tab = new bootstrap.Tab(tabEl);
        tab.show();
    }
}

/**
 * Live 모드용 기간 선택 버튼 이벤트
 */
function setupTimeRangeSelector(summaryData, marketType = 'overseas') {
    const selector = document.getElementById('time-range-selector');
    if (!selector) return;

    selector.querySelectorAll('button[data-range]').forEach(btn => {
        btn.addEventListener('click', () => {
            selector.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updatePerformanceChartRange(summaryData, btn.getAttribute('data-range'), marketType);
        });
    });
}

/**
 * 계좌 비교 모드 Performance 탭 HTML 구조 삽입
 */
function setupAccountPerformanceHTML() {
    const perfTab = document.getElementById('performance');
    if (!perfTab) return;

    perfTab.innerHTML = `
        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3 d-flex justify-content-between align-items-start flex-wrap">
                <div>
                    <h5 class="mb-0"><i class="fas fa-chart-area me-2"></i>Account Performance Comparison</h5>
                    <div class="mt-2 small d-flex gap-2 flex-wrap">
                        <span class="badge border text-dark" style="background-color: rgba(25,135,84,0.15);">Bull</span>
                        <span class="badge border text-dark" style="background-color: rgba(255,193,7,0.15);">Sideways</span>
                        <span class="badge border text-dark" style="background-color: rgba(220,53,69,0.1);">Bear Weak</span>
                        <span class="badge border text-dark" style="background-color: rgba(220,53,69,0.2);">Bear Strong</span>
                        <span class="badge border text-white" style="background-color: rgba(33,37,41,0.4);">Crash</span>
                    </div>
                </div>
                <div class="btn-group btn-group-sm mt-2 mt-md-0" id="time-range-selector" role="group">
                    <button type="button" class="btn btn-outline-secondary" data-range="1M">1M</button>
                    <button type="button" class="btn btn-outline-secondary" data-range="3M">3M</button>
                    <button type="button" class="btn btn-outline-secondary" data-range="6M">6M</button>
                    <button type="button" class="btn btn-outline-secondary" data-range="1Y">1Y</button>
                    <button type="button" class="btn btn-outline-secondary active" data-range="ALL">ALL</button>
                </div>
            </div>
            <div class="card-body">
                <div style="height: 500px;"><canvas id="accountPerformanceChart"></canvas></div>
            </div>
        </div>

        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3">
                <h5 class="mb-0"><i class="fas fa-microchip me-2"></i>Exposure Strategy Comparison</h5>
            </div>
            <div class="card-body">
                <div style="height: 300px;"><canvas id="accountStrategyChart"></canvas></div>
            </div>
        </div>
    `;
}

/**
 * 계좌 비교 모드용 기간 선택 버튼 이벤트
 */
function setupAccountTimeRangeSelector(accountsData) {
    const selector = document.getElementById('time-range-selector');
    if (!selector) return;

    selector.querySelectorAll('button[data-range]').forEach(btn => {
        btn.addEventListener('click', () => {
            selector.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateAccountChartRange(accountsData, btn.getAttribute('data-range'));
        });
    });
}

/**
 * Compare 모드용 기간 선택 버튼 이벤트
 */
function setupCompareTimeRangeSelector(enginesData) {
    const selector = document.getElementById('time-range-selector');
    if (!selector) return;

    selector.querySelectorAll('button[data-range]').forEach(btn => {
        btn.addEventListener('click', () => {
            selector.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateCompareChartRange(enginesData, btn.getAttribute('data-range'));
        });
    });
}
