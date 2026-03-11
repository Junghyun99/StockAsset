// docs/js/main.js
// 대시보드 진입점: 모드 감지, 데이터 로딩, 탭 라우팅, 렌더링 오케스트레이션

import {
    renderStrategyChart,
    renderUnifiedChart,
    renderGroupBarChart,
    updatePerformanceChartRange,
    resizeAllCharts
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

document.addEventListener('DOMContentLoaded', async function() {
    // 1. URL 파라미터에서 모드 확인 (?mode=backtest)
    const urlParams = new URLSearchParams(window.location.search);
    const isBacktest = urlParams.get('mode') === 'backtest';

    // 데이터 경로 설정
    const dataPath = isBacktest ? 'data/backtest/' : 'data/';

    // UI 초기화 (버튼 활성화 상태 및 배지 설정)
    updateModeUI(isBacktest);

    // 2. 탭 해시 라우팅 설정
    setupTabRouting();

    try {
        // 4개 JSON 파일 병렬 로드 (asset_groups.json은 현재 모드 데이터 경로 기준)
        // cache-bust: 브라우저 캐시로 인한 구 버전 데이터 방지
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

        // === Performance 탭 렌더링 (lazy - 탭 전환 시) ===
        let perfRendered = false;
        let tradesRendered = false;

        function renderPerformanceTab() {
            if (perfRendered) return;
            renderPerformanceSummaryCards(summaryData);
            renderUnifiedChart(summaryData);
            renderStrategyChart(summaryData);
            perfRendered = true;
        }

        function renderTradesTab() {
            if (tradesRendered) return;
            renderTradeSummaryStats(historyData);
            renderTradeHistory(historyData);
            tradesRendered = true;
        }

        // 탭 전환 이벤트: Chart.js hidden tab 이슈 해결
        document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                const target = e.target.getAttribute('data-bs-target');

                if (target === '#performance') {
                    renderPerformanceTab();
                    // Chart.js는 hidden 상태에서 렌더링하면 크기가 0이 됨 → resize
                    setTimeout(() => resizeAllCharts(), 50);
                } else if (target === '#trades') {
                    renderTradesTab();
                }

                // URL 해시 업데이트
                const tabName = target.replace('#', '');
                history.replaceState(null, '', '#' + tabName);
            });
        });

        // 현재 해시에 따라 해당 탭 활성화 및 렌더링
        const currentHash = window.location.hash.replace('#', '') || 'overview';
        if (currentHash === 'performance') {
            activateTab('performance-tab');
            renderPerformanceTab();
        } else if (currentHash === 'trades') {
            activateTab('trades-tab');
            renderTradesTab();
        }

        // 기간 선택 버튼 이벤트 연결
        setupTimeRangeSelector();

        // 마지막 업데이트 시간 표시
        document.getElementById('last-updated').innerText = `Last Update: ${statusData.last_updated || 'Unknown'}`;

    } catch (error) {
        console.error("Data loading failed:", error);
        document.body.insertAdjacentHTML('beforeend',
            `<div class="alert alert-warning position-fixed bottom-0 end-0 m-3 shadow" style="z-index: 9999;">
                <i class="fas fa-exclamation-triangle me-2"></i> 데이터(${dataPath}) 로드 실패. 파일 생성을 기다려주세요.
            </div>`);
    }
});

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
 * Performance 탭 - 기간 선택 버튼 이벤트 설정
 */
function setupTimeRangeSelector() {
    const selector = document.getElementById('time-range-selector');
    if (!selector) return;

    selector.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
            // 활성 버튼 토글
            selector.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // 차트 업데이트
            const range = btn.dataset.range;
            updatePerformanceChartRange(range);
        });
    });
}
