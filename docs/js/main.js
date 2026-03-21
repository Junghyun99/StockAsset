// docs/js/main.js
// 대시보드 진입점: 모드 감지, 데이터 로딩, 탭 라우팅, 렌더링 오케스트레이션

import {
    renderStrategyChart,
    renderUnifiedChart,
    renderGroupBarChart,
    resizeAllCharts,
    updatePerformanceChartRange,
    renderCumulativeDividendChart,
    renderYearlyDividendChart
} from './charts.js?v=2';

import {
    updateModeUI,
    updateSummaryCards,
    renderStatusBanner,
    renderHoldingsTable,
    renderTodayActivity,
    updateDecisionLogic,
    renderPerformanceSummaryCards,
    renderTradeSummaryStats,
    renderTradeHistory
} from './ui.js?v=2';

import { loadEngineMeta } from './utils.js?v=2';

import {
    renderCompareOverview,
    renderCompareTradesTab,
} from './compare-ui.js?v=2';

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
 * Live 모드 데이터 로딩 및 렌더링 (기존 로직)
 */
async function loadLiveMode() {
    const dataPath = 'data/';
    const cacheBust = `v=${Date.now()}`;
    const [summaryRes, statusRes, historyRes, groupConfigRes] = await Promise.all([
        fetch(`${dataPath}summary.json?${cacheBust}`),
        fetch(`${dataPath}status.json?${cacheBust}`),
        fetch(`${dataPath}history.json?${cacheBust}`),
        fetch(`${dataPath}asset_groups.json?${cacheBust}`)
    ]);

    const summaryData = await summaryRes.json();
    const statusData = await statusRes.json();
    const historyData = await historyRes.json();
    const groupConfig = groupConfigRes.ok ? await groupConfigRes.json() : null;

    // === Overview 탭 렌더링 ===
    renderStatusBanner(statusData);
    updateSummaryCards(statusData, summaryData);
    renderGroupBarChart(statusData, groupConfig);
    renderHoldingsTable(statusData, groupConfig);
    renderTodayActivity(historyData, statusData);
    updateDecisionLogic(summaryData[summaryData.length - 1]);

    // === Performance / Trades 탭 (lazy) ===
    let perfRendered = false;
    let tradesRendered = false;

    function renderPerformanceTab() {
        if (perfRendered) return;
        renderPerformanceSummaryCards(summaryData);
        renderUnifiedChart(summaryData);
        renderStrategyChart(summaryData);
        renderCumulativeDividendChart(summaryData);
        renderYearlyDividendChart(summaryData);
        setupTimeRangeSelector(summaryData);
        perfRendered = true;
    }

    function renderTradesTab() {
        if (tradesRendered) return;
        renderTradeSummaryStats(historyData);
        renderTradeHistory(historyData);
        tradesRendered = true;
    }

    setupTabEvents(renderPerformanceTab, renderTradesTab, resizeAllCharts);

    // 마지막 업데이트 시간 표시
    document.getElementById('last-updated').innerText = `Last Update: ${statusData.last_updated || 'Unknown'}`;
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

    setupTabEvents(renderPerformanceTab, renderTradesTab, resizeCompareCharts);

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
                <h5 class="mb-0"><i class="fas fa-calendar-alt me-2"></i>Monthly Dividend Comparison (Last 12M)</h5>
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
 */
function setupTabEvents(onPerformance, onTrades, onResize) {
    document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tab => {
        tab.addEventListener('shown.bs.tab', (e) => {
            const target = e.target.getAttribute('data-bs-target');

            if (target === '#performance') {
                onPerformance();
                setTimeout(() => onResize(), 50);
            } else if (target === '#trades') {
                onTrades();
            }

            const tabName = target.replace('#', '');
            history.replaceState(null, '', '#' + tabName);
        });
    });

    // 현재 해시에 따라 해당 탭 활성화
    const currentHash = window.location.hash.replace('#', '') || 'overview';
    if (currentHash === 'performance') {
        activateTab('performance-tab');
        onPerformance();
    } else if (currentHash === 'trades') {
        activateTab('trades-tab');
        onTrades();
    }
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
            'trades': 'trades-tab'
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
function setupTimeRangeSelector(summaryData) {
    const selector = document.getElementById('time-range-selector');
    if (!selector) return;

    selector.querySelectorAll('button[data-range]').forEach(btn => {
        btn.addEventListener('click', () => {
            selector.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updatePerformanceChartRange(summaryData, btn.getAttribute('data-range'));
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
