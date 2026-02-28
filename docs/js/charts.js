// docs/js/charts.js
// Chart.js 차트 생성 및 관리

// 차트 인스턴스 (모듈 스코프, 모드 전환 시 기존 차트 삭제용)
let perfChart = null;
let allocChart = null;
let stratChart = null;

/**
 * Performance History 차트 렌더링 (Portfolio vs SPY 벤치마크)
 */
export function renderPerformanceChart(summaryData) {
    const labels = summaryData.map(d => d.date);

    // 수익률(%) 계산
    const portfolioValues = summaryData.map(d => d.total_value);
    const spyPrices = summaryData.map(d => d.spy_price);
    const initialPort = portfolioValues[0];
    const initialSpy = spyPrices[0];
    const portReturns = portfolioValues.map(v => (v / initialPort - 1) * 100);
    const spyReturns = spyPrices.map(v => (v / initialSpy - 1) * 100);

    if (perfChart) perfChart.destroy();
    perfChart = new Chart(document.getElementById('performanceChart'), {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                { label: 'Portfolio (%)', data: portReturns, borderColor: '#0d6efd', fill: true, backgroundColor: 'rgba(13, 110, 253, 0.05)', tension: 0.1 },
                { label: 'SPY Benchmark (%)', data: spyReturns, borderColor: '#adb5bd', borderDash: [5, 5], tension: 0.1, pointRadius: 0 }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { tooltip: { mode: 'index', intersect: false } }
        }
    });
}

/**
 * Strategy Analysis 차트 렌더링 (투자 비중 + 모멘텀 듀얼 축)
 */
export function renderStrategyChart(summaryData) {
    const labels = summaryData.map(d => d.date);
    const exposures = summaryData.map(d => d.target_exposure * 100);
    const spyMomentums = summaryData.map(d => d.spy_momentum * 100);

    if (stratChart) stratChart.destroy();
    stratChart = new Chart(document.getElementById('strategyChart'), {
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
                    yAxisID: 'y',
                    zIndex: 2
                },
                {
                    label: 'Momentum Score (%)',
                    data: spyMomentums,
                    borderColor: '#ffc107',
                    borderWidth: 1,
                    fill: false,
                    pointRadius: 0,
                    yAxisID: 'y1',
                    zIndex: 1
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
 * 현재 보유 자산 구성 차트 (Doughnut)
 */
export function renderAllocationChart(statusData) {
    const holdings = statusData.portfolio.holdings;
    const cash = statusData.portfolio.cash_balance;

    const labels = holdings.map(h => h.ticker);
    const values = holdings.map(h => h.value);

    // 현금 비중 추가
    if (cash > 0) {
        labels.push('Cash');
        values.push(cash);
    }

    if (allocChart) allocChart.destroy();
    const ctxAlloc = document.getElementById('allocationChart').getContext('2d');
    allocChart = new Chart(ctxAlloc, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: [
                    '#0d6efd', '#6610f2', '#6f42c1', '#d63384',
                    '#fd7e14', '#ffc107', '#20c997', '#adb5bd'
                ],
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12 } }
            },
            cutout: '60%'
        }
    });
}
