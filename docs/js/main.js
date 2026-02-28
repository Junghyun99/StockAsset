// docs/js/main.js
// 대시보드 진입점: 모드 감지, 데이터 로딩, 렌더링 오케스트레이션

import { renderPerformanceChart, renderStrategyChart, renderAllocationChart } from './charts.js';
import { updateModeUI, updateSummaryCards, updateDecisionLogic, renderTradeHistory } from './ui.js';

document.addEventListener('DOMContentLoaded', async function() {
    // 1. URL 파라미터에서 모드 확인 (?mode=backtest)
    const urlParams = new URLSearchParams(window.location.search);
    const isBacktest = urlParams.get('mode') === 'backtest';

    // 데이터 경로 설정
    const dataPath = isBacktest ? 'data/backtest/' : 'data/';

    // UI 초기화 (버튼 활성화 상태 및 배지 설정)
    updateModeUI(isBacktest);

    try {
        // 3개 JSON 파일 병렬 로드
        const [summaryRes, statusRes, historyRes] = await Promise.all([
            fetch(`${dataPath}summary.json`),
            fetch(`${dataPath}status.json`),
            fetch(`${dataPath}history.json`)
        ]);

        const summaryData = await summaryRes.json();
        const statusData = await statusRes.json();
        const historyData = await historyRes.json();

        // 각 섹션 렌더링
        updateSummaryCards(statusData, summaryData);
        renderAllocationChart(statusData);
        renderPerformanceChart(summaryData);
        renderStrategyChart(summaryData);
        updateDecisionLogic(summaryData[summaryData.length - 1]);
        renderTradeHistory(historyData);

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
