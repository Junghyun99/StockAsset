// docs/js/compare-charts.js
// 멀티 엔진 비교 전용 차트

import { filterByDateRange, ENGINE_COLORS } from './utils.js?v=2';

let comparePerformanceChart = null;
let compareStrategyChart = null;
let compareCumulativeDividendChart = null;
let compareYearlyDividendChart = null;

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
 * 멀티 엔진 누적 배당금 비교 차트 (오버레이 라인)
 * @param {Map<string, Object>} enginesData
 */
export function renderCompareCumulativeDividendChart(enginesData) {
    const canvas = document.getElementById('compareCumulativeDividendChart');
    if (!canvas) return;

    if (compareCumulativeDividendChart) compareCumulativeDividendChart.destroy();

    const engineNames = [...enginesData.keys()];
    const datasets = [];

    // 전체 날짜 범위를 첫 번째 엔진 기준으로 설정
    const firstSummary = enginesData.get(engineNames[0]).summary;
    if (!firstSummary || firstSummary.length === 0) return;

    for (const name of engineNames) {
        const summary = enginesData.get(name).summary;
        if (!summary) continue;

        let cumulative = 0;
        const dateMap = new Map();
        summary.forEach(d => {
            const div = d.daily_dividend || 0;
            if (div > 0) {
                cumulative += div;
            }
            dateMap.set(d.date, parseFloat(cumulative.toFixed(2)));
        });

        // 전체 날짜 기준으로 정렬된 데이터 생성
        const data = firstSummary.map(d => dateMap.get(d.date) ?? null);
        const hasDividend = data.some(v => v !== null && v > 0);

        datasets.push({
            label: name,
            data: hasDividend ? data : firstSummary.map(() => 0),
            borderColor: ENGINE_COLORS[name] || '#6c757d',
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
        });
    }

    const labels = firstSummary.map(d => d.date);

    compareCumulativeDividendChart = new Chart(canvas, {
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
                    title: { display: true, text: 'Cumulative Dividend ($)' },
                    ticks: {
                        callback: v => '$' + v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
                    },
                },
            },
            plugins: {
                legend: { display: true, position: 'bottom', labels: { usePointStyle: true, padding: 15 } },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: $${ctx.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                    },
                },
            },
        },
    });
}

/**
 * 멀티 엔진 월별 배당금 비교 바 차트 (최근 1년)
 * @param {Map<string, Object>} enginesData
 */
export function renderCompareYearlyDividendChart(enginesData) {
    const canvas = document.getElementById('compareYearlyDividendChart');
    if (!canvas) return;

    if (compareYearlyDividendChart) compareYearlyDividendChart.destroy();

    // 최근 12개월 레이블 생성
    const months = [];
    const now = new Date();
    for (let i = 11; i >= 0; i--) {
        const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
        months.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    }
    const labels = months.map(m => {
        const [y, mo] = m.split('-');
        return `${y}.${mo}`;
    });

    const oneYearAgo = new Date();
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);

    const engineNames = [...enginesData.keys()];
    const datasets = [];

    for (const name of engineNames) {
        const summary = enginesData.get(name).summary;
        if (!summary) continue;

        const monthlyMap = {};
        summary.filter(d => new Date(d.date) >= oneYearAgo).forEach(d => {
            const div = d.daily_dividend || 0;
            if (div > 0) {
                const month = d.date.slice(0, 7);
                monthlyMap[month] = (monthlyMap[month] || 0) + div;
            }
        });

        datasets.push({
            label: name,
            data: months.map(m => parseFloat((monthlyMap[m] || 0).toFixed(2))),
            backgroundColor: ENGINE_COLORS[name] ? ENGINE_COLORS[name].replace(')', ', 0.65)').replace('rgb', 'rgba') : 'rgba(108,117,125,0.65)',
            borderColor: ENGINE_COLORS[name] || '#6c757d',
            borderWidth: 1,
            borderRadius: 3,
        });
    }

    compareYearlyDividendChart = new Chart(canvas, {
        type: 'bar',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false } },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'Dividend ($)' },
                    ticks: { callback: v => '$' + v.toFixed(0) },
                },
            },
            plugins: {
                legend: { display: true, position: 'bottom', labels: { usePointStyle: true, padding: 15 } },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: $${ctx.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
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
    [comparePerformanceChart, compareStrategyChart, compareCumulativeDividendChart, compareYearlyDividendChart].forEach(chart => {
        if (chart) chart.resize();
    });
}
