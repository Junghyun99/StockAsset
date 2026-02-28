// docs/js/charts.js
// Chart.js 차트 생성 및 관리

import { filterByDateRange, getAssetGroup, formatCurrency } from './utils.js';

// 차트 인스턴스 (모듈 스코프, 모드 전환 시 기존 차트 삭제용)
let perfChart = null;
let stratChart = null;
let groupBarChartInstance = null;
let groupAllocChart = null;

// 원본 데이터 캐시 (기간 필터용)
let cachedSummaryData = null;

/**
 * Performance History 차트 렌더링 (Portfolio vs SPY 벤치마크)
 * @param {Array} summaryData - summary 배열
 * @param {string} range - 기간 필터 ('1M', '3M', '6M', '1Y', 'ALL')
 */
export function renderPerformanceChart(summaryData, range) {
    // 원본 데이터 캐시 (최초 호출 시)
    if (range === undefined) {
        cachedSummaryData = summaryData;
        range = 'ALL';
    }

    const filtered = filterByDateRange(summaryData, range);
    if (filtered.length === 0) return;

    const labels = filtered.map(d => d.date);

    // 수익률(%) 계산 - 필터된 범위의 첫 날 기준
    const portfolioValues = filtered.map(d => d.total_value);
    const spyPrices = filtered.map(d => d.spy_price);
    const initialPort = portfolioValues[0];
    const initialSpy = spyPrices[0];
    const portReturns = portfolioValues.map(v => (v / initialPort - 1) * 100);
    const spyReturns = spyPrices.map(v => (v / initialSpy - 1) * 100);

    if (perfChart) perfChart.destroy();

    const canvas = document.getElementById('performanceChart');
    if (!canvas) return;

    perfChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Portfolio (%)',
                    data: portReturns,
                    borderColor: '#0d6efd',
                    fill: true,
                    backgroundColor: 'rgba(13, 110, 253, 0.05)',
                    tension: 0.1,
                    pointRadius: portReturns.length > 50 ? 0 : 3
                },
                {
                    label: 'SPY Benchmark (%)',
                    data: spyReturns,
                    borderColor: '#adb5bd',
                    borderDash: [5, 5],
                    tension: 0.1,
                    pointRadius: 0,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: { mode: 'index', intersect: false }
            },
            scales: {
                y: {
                    title: { display: true, text: 'Return (%)' }
                }
            }
        }
    });
}

/**
 * 기간 필터 변경 핸들러
 */
export function updatePerformanceChartRange(range) {
    if (cachedSummaryData) {
        renderPerformanceChart(cachedSummaryData, range);
    }
}

/**
 * Strategy Analysis 차트 렌더링 (투자 비중 + 모멘텀 듀얼 축)
 */
export function renderStrategyChart(summaryData) {
    const labels = summaryData.map(d => d.date);
    const exposures = summaryData.map(d => d.target_exposure * 100);
    const spyMomentums = summaryData.map(d => d.spy_momentum * 100);

    if (stratChart) stratChart.destroy();

    const canvas = document.getElementById('strategyChart');
    if (!canvas) return;

    stratChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Investment Exposure (%)',
                    data: exposures,
                    borderColor: '#17a2b8',
                    backgroundColor: 'rgba(23, 162, 184, 0.1)',
                    fill: true,
                    stepped: true,
                    yAxisID: 'y'
                },
                {
                    label: 'Momentum Score (%)',
                    data: spyMomentums,
                    borderColor: '#ffc107',
                    borderWidth: 1,
                    fill: false,
                    pointRadius: 0,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                y: {
                    beginAtZero: true, max: 110,
                    title: { display: true, text: 'Exposure (%)' }
                },
                y1: {
                    position: 'right',
                    title: { display: true, text: 'Momentum (%)' },
                    grid: { drawOnChartArea: false }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        afterBody: function(context) {
                            const dataIndex = context[0].dataIndex;
                            const d = summaryData[dataIndex];
                            return [
                                `--------------------`,
                                `VIX: ${d.vix ? d.vix.toFixed(2) : 'N/A'}`,
                                `SPY Price: $${d.spy_price.toFixed(2)}`,
                                `MA180: $${d.spy_ma180 ? d.spy_ma180.toFixed(2) : 'N/A'}`,
                                `MDD: ${(d.mdd * 100).toFixed(2)}%`,
                                `Regime: ${d.regime}`
                            ];
                        }
                    }
                }
            }
        }
    });
}

/**
 * Overview 탭 - 자산 그룹별 수평 Stacked Bar 차트
 */
export function renderGroupBarChart(statusData) {
    const holdings = statusData.portfolio.holdings;
    const cash = statusData.portfolio.cash_balance;
    const totalValue = statusData.portfolio.total_value;

    // 그룹별 합산
    let groupA = 0, groupB = 0, groupC = 0;
    holdings.forEach(h => {
        const g = getAssetGroup(h.ticker);
        if (g.group === 'A') groupA += h.value;
        else if (g.group === 'B') groupB += h.value;
        else if (g.group === 'C') groupC += h.value;
    });
    groupC += cash; // Cash를 C 그룹에 포함

    if (groupBarChartInstance) groupBarChartInstance.destroy();

    const canvas = document.getElementById('groupBarChart');
    if (!canvas) return;

    groupBarChartInstance = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: [''],
            datasets: [
                {
                    label: `A: Growth (${formatCurrency(groupA)})`,
                    data: [totalValue > 0 ? (groupA / totalValue * 100) : 0],
                    backgroundColor: '#0d6efd',
                    barPercentage: 0.8
                },
                {
                    label: `B: Safety (${formatCurrency(groupB)})`,
                    data: [totalValue > 0 ? (groupB / totalValue * 100) : 0],
                    backgroundColor: '#198754',
                    barPercentage: 0.8
                },
                {
                    label: `C: Cash (${formatCurrency(groupC)})`,
                    data: [totalValue > 0 ? (groupC / totalValue * 100) : 0],
                    backgroundColor: '#ffc107',
                    barPercentage: 0.8
                }
            ]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    stacked: true,
                    max: 100,
                    display: false
                },
                y: {
                    stacked: true,
                    display: false
                }
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { boxWidth: 12, font: { size: 11 } }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ' + context.raw.toFixed(1) + '%';
                        }
                    }
                }
            }
        }
    });
}

/**
 * Performance 탭 - 자산 그룹별 Stacked Area 차트 (시계열)
 */
export function renderGroupAllocationChart(summaryData) {
    // group_a/b/c 필드가 있는지 확인
    const hasGroupData = summaryData.some(d => d.group_a !== undefined);

    const canvas = document.getElementById('groupAllocationChart');
    const placeholder = document.getElementById('group-allocation-placeholder');

    if (!hasGroupData) {
        if (canvas) canvas.style.display = 'none';
        if (placeholder) placeholder.classList.remove('d-none');
        return;
    }

    if (canvas) canvas.style.display = 'block';
    if (placeholder) placeholder.classList.add('d-none');

    const labels = summaryData.map(d => d.date);
    const groupAData = summaryData.map(d => d.group_a || 0);
    const groupBData = summaryData.map(d => d.group_b || 0);
    const groupCData = summaryData.map(d => d.group_c || 0);

    if (groupAllocChart) groupAllocChart.destroy();

    groupAllocChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'A: Growth',
                    data: groupAData,
                    borderColor: '#0d6efd',
                    backgroundColor: 'rgba(13, 110, 253, 0.3)',
                    fill: true,
                    tension: 0.1,
                    pointRadius: groupAData.length > 50 ? 0 : 2
                },
                {
                    label: 'B: Safety',
                    data: groupBData,
                    borderColor: '#198754',
                    backgroundColor: 'rgba(25, 135, 84, 0.3)',
                    fill: true,
                    tension: 0.1,
                    pointRadius: groupBData.length > 50 ? 0 : 2
                },
                {
                    label: 'C: Cash',
                    data: groupCData,
                    borderColor: '#ffc107',
                    backgroundColor: 'rgba(255, 193, 7, 0.3)',
                    fill: true,
                    tension: 0.1,
                    pointRadius: groupCData.length > 50 ? 0 : 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { display: true },
                y: {
                    stacked: true,
                    title: { display: true, text: 'Value ($)' }
                }
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { boxWidth: 12 }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ' + formatCurrency(context.raw);
                        }
                    }
                }
            }
        }
    });
}

/**
 * 모든 차트 리사이즈 (탭 전환 시 사용)
 */
export function resizeAllCharts() {
    [perfChart, stratChart, groupBarChartInstance, groupAllocChart].forEach(chart => {
        if (chart) chart.resize();
    });
}
