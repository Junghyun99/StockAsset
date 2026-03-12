// docs/js/compare-charts.js
// 멀티 엔진 비교 전용 차트

import { filterByDateRange, ENGINE_COLORS, SPY_COLOR } from './utils.js?v=2';

let comparePerformanceChart = null;
let compareStrategyChart = null;

function getRegimeColor(regimeStr) {
    if (!regimeStr) return 'transparent';
    const str = regimeStr.toLowerCase();
    if (str.includes('bull')) return 'rgba(25, 135, 84, 0.15)';
    if (str.includes('bear_strong')) return 'rgba(220, 53, 69, 0.2)';
    if (str.includes('bear')) return 'rgba(220, 53, 69, 0.1)';
    if (str.includes('sideways')) return 'rgba(255, 193, 7, 0.15)';
    if (str.includes('crash')) return 'rgba(33, 37, 41, 0.4)';
    return 'transparent';
}

/**
 * 멀티 엔진 성과 비교 차트 (오버레이)
 * @param {Map<string, Object>} enginesData
 * @param {Array} [filteredSummaries] - 필터링된 summary 배열 (시간 범위 변경 시)
 */
export function renderComparePerformanceChart(enginesData, filteredSummaries) {
    const canvas = document.getElementById('comparePerformanceChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (comparePerformanceChart) comparePerformanceChart.destroy();

    const engineNames = [...enginesData.keys()];
    const firstEngineName = engineNames[0];
    const firstSummary = filteredSummaries
        ? filteredSummaries.get(firstEngineName)
        : enginesData.get(firstEngineName).summary;

    if (!firstSummary || firstSummary.length === 0) return;

    const labels = firstSummary.map(d => d.date);

    // 각 엔진의 portfolio value를 초기값 기준 정규화 (동일 스케일)
    const datasets = [];

    for (const name of engineNames) {
        const summary = filteredSummaries
            ? filteredSummaries.get(name)
            : enginesData.get(name).summary;
        if (!summary || summary.length === 0) continue;

        const initialValue = summary[0].total_value;
        const normalizedData = summary.map(d => (d.total_value / initialValue) * 100);

        datasets.push({
            label: name,
            data: normalizedData,
            borderColor: ENGINE_COLORS[name] || '#6c757d',
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
        });
    }

    // SPY 벤치마크
    const spyInitial = firstSummary[0].spy_price;
    const spyData = firstSummary.map(d => (d.spy_price / spyInitial) * 100);
    datasets.push({
        label: 'SPY Benchmark',
        data: spyData,
        borderColor: SPY_COLOR,
        borderWidth: 2,
        borderDash: [5, 5],
        pointRadius: 0,
        fill: false,
        tension: 0.1,
    });

    // Regime 배경 박스
    const annotations = {};
    let currentRegime = firstSummary[0].regime;
    let startIdx = 0;
    let boxIndex = 0;

    for (let i = 0; i < firstSummary.length; i++) {
        if (firstSummary[i].regime !== currentRegime || i === firstSummary.length - 1) {
            annotations[`regimeBox${boxIndex++}`] = {
                type: 'box',
                xMin: labels[startIdx],
                xMax: labels[i],
                backgroundColor: getRegimeColor(currentRegime),
                borderWidth: 0,
                drawTime: 'beforeDraw',
            };
            currentRegime = firstSummary[i].regime;
            startIdx = i;
        }
    }

    comparePerformanceChart = new Chart(ctx, {
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
                    ticks: {
                        callback: value => value.toFixed(0),
                    },
                },
            },
            plugins: {
                annotation: { annotations },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const value = context.parsed.y;
                            const change = value - 100;
                            const sign = change >= 0 ? '+' : '';
                            return `${context.dataset.label}: ${value.toFixed(1)} (${sign}${change.toFixed(1)}%)`;
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
 * 멀티 엔진 전략(Exposure) 비교 차트
 * @param {Map<string, Object>} enginesData
 */
export function renderCompareStrategyChart(enginesData) {
    const canvas = document.getElementById('compareStrategyChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (compareStrategyChart) compareStrategyChart.destroy();

    const engineNames = [...enginesData.keys()];
    const firstSummary = enginesData.get(engineNames[0]).summary;
    if (!firstSummary || firstSummary.length === 0) return;

    const labels = firstSummary.map(d => d.date);
    const datasets = [];

    for (const name of engineNames) {
        const summary = enginesData.get(name).summary;
        if (!summary) continue;
        datasets.push({
            label: `${name} Exposure`,
            data: summary.map(d => d.target_exposure * 100),
            borderColor: ENGINE_COLORS[name] || '#6c757d',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            stepped: true,
        });
    }

    compareStrategyChart = new Chart(ctx, {
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
                        afterBody: function(context) {
                            const idx = context[0].dataIndex;
                            const d = firstSummary[idx];
                            return [
                                `--------------------`,
                                `Regime: ${d.regime}`,
                                `SPY: $${d.spy_price.toFixed(2)}`,
                                `VIX: ${d.vix ? d.vix.toFixed(2) : 'N/A'}`,
                            ];
                        },
                    },
                },
            },
        },
    });
}

/**
 * 시간 범위에 따라 비교 성과 차트 재렌더링
 */
export function updateCompareChartRange(enginesData, range) {
    const filtered = new Map();
    for (const [name, data] of enginesData) {
        filtered.set(name, filterByDateRange(data.summary, range));
    }
    renderComparePerformanceChart(enginesData, filtered);
}

/**
 * 비교 차트 리사이즈
 */
export function resizeCompareCharts() {
    [comparePerformanceChart, compareStrategyChart].forEach(chart => {
        if (chart) chart.resize();
    });
}
