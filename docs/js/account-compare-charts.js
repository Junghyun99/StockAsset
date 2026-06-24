// docs/js/account-compare-charts.js
// 라이브 다중 계좌 비교 전용 차트

import { filterByDateRange, ACCOUNT_COLORS } from './utils.js?v=20260624-1';

let accountPerformanceChart = null;
let accountStrategyChart = null;

function getRegimeColor(regimeStr) {
    if (!regimeStr) return 'transparent';
    const s = regimeStr.toLowerCase();
    if (s.includes('bull'))         return 'rgba(25, 135, 84, 0.15)';
    if (s.includes('bear_strong'))  return 'rgba(220, 53, 69, 0.2)';
    if (s.includes('bear'))         return 'rgba(220, 53, 69, 0.1)';
    if (s.includes('sideways'))     return 'rgba(255, 193, 7, 0.15)';
    if (s.includes('crash'))        return 'rgba(33, 37, 41, 0.4)';
    return 'transparent';
}

/**
 * 다중 계좌 성과 비교 차트 (초기값=100 정규화)
 * @param {Map<string, Object>} accountsData
 * @param {Map<string, Array>} [filteredSummaries] - 시간 범위 필터링 시 전달
 */
export function renderAccountPerformanceChart(accountsData, filteredSummaries) {
    const canvas = document.getElementById('accountPerformanceChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (accountPerformanceChart) accountPerformanceChart.destroy();

    const accountIds = [...accountsData.keys()];
    const firstId = accountIds[0];
    const firstSummary = filteredSummaries
        ? filteredSummaries.get(firstId)
        : accountsData.get(firstId).summary;

    if (!firstSummary || firstSummary.length === 0) return;

    const labels = firstSummary.map(d => d.date);
    const datasets = [];

    for (const id of accountIds) {
        const summary = filteredSummaries
            ? filteredSummaries.get(id)
            : accountsData.get(id).summary;
        if (!summary || summary.length === 0) continue;

        const initialValue = summary[0].total_value || 1;
        const summaryMap = new Map(summary.map(d => [d.date, d]));
        datasets.push({
            label: id,
            data: labels.map(l => {
                const d = summaryMap.get(l);
                return d ? (d.total_value / initialValue) * 100 : null;
            }),
            borderColor: ACCOUNT_COLORS[id] || '#6c757d',
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
        });
    }

    // Regime 배경 박스 (첫 번째 계좌 기준)
    const annotations = {};
    let currentRegime = firstSummary[0]?.regime;
    let startIdx = 0;
    let boxIdx = 0;

    for (let i = 1; i <= firstSummary.length; i++) {
        const regime = firstSummary[i]?.regime;
        if (regime !== currentRegime || i === firstSummary.length) {
            annotations[`regimeBox${boxIdx++}`] = {
                type: 'box',
                xMin: labels[startIdx],
                xMax: labels[i - 1] ?? labels[labels.length - 1],
                backgroundColor: getRegimeColor(currentRegime),
                borderWidth: 0,
                drawTime: 'beforeDraw',
            };
            currentRegime = regime;
            startIdx = i;
        }
    }

    accountPerformanceChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false } },
                y: {
                    title: { display: true, text: 'Normalized Value (Initial = 100)' },
                    ticks: { callback: v => v.toFixed(0) },
                },
            },
            plugins: {
                annotation: { annotations },
                tooltip: {
                    callbacks: {
                        label(context) {
                            const v = context.parsed.y;
                            const chg = v - 100;
                            return `${context.dataset.label}: ${v.toFixed(1)} (${chg >= 0 ? '+' : ''}${chg.toFixed(1)}%)`;
                        },
                    },
                },
                legend: {
                    display: true,
                    position: 'bottom',
                    labels: { usePointStyle: true, padding: 15 },
                },
            },
        },
    });
}

/**
 * 다중 계좌 목표비중(Exposure) 비교 차트
 * @param {Map<string, Object>} accountsData
 */
export function renderAccountStrategyChart(accountsData) {
    const canvas = document.getElementById('accountStrategyChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (accountStrategyChart) accountStrategyChart.destroy();

    const accountIds = [...accountsData.keys()];
    const firstSummary = accountsData.get(accountIds[0]).summary;
    if (!firstSummary || firstSummary.length === 0) return;

    const labels = firstSummary.map(d => d.date);
    const datasets = [];

    for (const id of accountIds) {
        const summary = accountsData.get(id).summary;
        if (!summary) continue;
        const summaryMap = new Map(summary.map(d => [d.date, d]));
        datasets.push({
            label: `${id} Exposure`,
            data: labels.map(l => (summaryMap.get(l)?.target_exposure ?? 0) * 100),
            borderColor: ACCOUNT_COLORS[id] || '#6c757d',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            stepped: true,
        });
    }

    accountStrategyChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false } },
                y: {
                    beginAtZero: true,
                    max: 110,
                    title: { display: true, text: 'Exposure (%)' },
                },
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'bottom',
                    labels: { usePointStyle: true, padding: 15 },
                },
                tooltip: {
                    callbacks: {
                        afterBody(context) {
                            const idx = context[0].dataIndex;
                            const d = firstSummary[idx];
                            return [
                                '--------------------',
                                `Regime: ${d.regime || '-'}`,
                                `VIX: ${d.vix != null ? d.vix.toFixed(2) : 'N/A'}`,
                            ];
                        },
                    },
                },
            },
        },
    });
}

/**
 * 시간 범위 변경 시 차트 재렌더
 * @param {Map<string, Object>} accountsData
 * @param {string} range - '1M'|'3M'|'6M'|'1Y'|'ALL'
 */
export function updateAccountChartRange(accountsData, range) {
    if (range === 'ALL') {
        renderAccountPerformanceChart(accountsData);
        return;
    }

    const filtered = new Map();
    for (const [id, data] of accountsData) {
        filtered.set(id, filterByDateRange(data.summary, range));
    }
    renderAccountPerformanceChart(accountsData, filtered);
}

/**
 * 창 크기 변경 시 차트 리사이즈
 */
export function resizeAccountCharts() {
    if (accountPerformanceChart) accountPerformanceChart.resize();
    if (accountStrategyChart) accountStrategyChart.resize();
}
