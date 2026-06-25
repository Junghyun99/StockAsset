// docs/js/charts.js
// Chart.js 차트 생성 및 관리

import {
    filterByDateRange,
    getAssetGroup,
    getTickerAlias,
    formatCurrency,
    formatAmount,
    computeMonthlyReturns,
    computeCumulativePnl,
    computeAlphaSeries,
    computeDrawdownSeries,
    computeRegimeDistribution,
    computeTradeReasonDistribution,
    computeMonthlyTradeFrequency,
    computeTickerContribution,
    computeAnnualReturns
} from './utils.js?v=20260624-4';

// 차트 인스턴스 (모듈 스코프, 모드 전환 시 기존 차트 삭제용)
let stratChart = null;
let groupBarChartInstance = null;
let unifiedChart = null;
let cumulativeDividendChart = null;
let yearlyDividendChart = null;

// 신규 차트 인스턴스
let cumulativePnlChart = null;
let drawdownChart = null;
let alphaLineChart = null;
let monthlyHeatmapChart = null;
let tradeReasonPieChart = null;
let monthlyFrequencyChart = null;
let tickerContributionChart = null;
let currentAllocationDoughnut = null;
let historicalAllocationChart = null;
let regimeDistributionDoughnut = null;
let annualReturnsChart = null;
let targetVsActualChart = null;
let deviationTrendChart = null;

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
export function renderGroupBarChart(statusData, groupConfig, marketType = 'overseas') {
    const holdings = statusData.portfolio.holdings;
    const cash = statusData.portfolio.cash_balance;
    const totalValue = statusData.portfolio.total_value;

    // 그룹별 합산 (groupConfig 기반으로 동적 집계)
    const groupValues = {};
    holdings.forEach(h => {
        const g = getAssetGroup(h.ticker, groupConfig);
        groupValues[g.group] = (groupValues[g.group] || 0) + h.value;
    });

    // 마지막 그룹에 현금 포함
    const cashGroup = groupConfig ? Object.keys(groupConfig).slice(-1)[0] : 'C';
    groupValues[cashGroup] = (groupValues[cashGroup] || 0) + cash;

    if (groupBarChartInstance) groupBarChartInstance.destroy();

    const canvas = document.getElementById('groupBarChart');
    if (!canvas) return;

    // groupConfig 기반으로 동적 datasets 생성
    let datasets;
    if (groupConfig && Object.keys(groupConfig).length > 0) {
        datasets = Object.entries(groupConfig).map(([group, info]) => {
            const value = groupValues[group] || 0;
            return {
                label: `${group}: ${info.label} (${formatAmount(value, marketType)})`,
                data: [totalValue > 0 ? (value / totalValue * 100) : 0],
                backgroundColor: info.color,
                barPercentage: 0.8
            };
        });
        // 매칭 안 된 티커('?')가 있으면 마지막에 추가
        if (groupValues['?']) {
            const otherValue = groupValues['?'];
            datasets.push({
                label: `Other (${formatAmount(otherValue, marketType)})`,
                data: [totalValue > 0 ? (otherValue / totalValue * 100) : 0],
                backgroundColor: '#adb5bd',
                barPercentage: 0.8
            });
        }
    } else {
        // groupConfig 없을 때 폴백 (A/B/C 고정)
        const groupA = groupValues['A'] || 0;
        const groupB = groupValues['B'] || 0;
        const groupC = groupValues['C'] || 0;
        datasets = [
            { label: `A: Growth (${formatAmount(groupA, marketType)})`, data: [totalValue > 0 ? (groupA / totalValue * 100) : 0], backgroundColor: '#0d6efd', barPercentage: 0.8 },
            { label: `B: Safety (${formatAmount(groupB, marketType)})`, data: [totalValue > 0 ? (groupB / totalValue * 100) : 0], backgroundColor: '#198754', barPercentage: 0.8 },
            { label: `C: Cash (${formatAmount(groupC, marketType)})`, data: [totalValue > 0 ? (groupC / totalValue * 100) : 0], backgroundColor: '#ffc107', barPercentage: 0.8 }
        ];
    }

    groupBarChartInstance = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: [''],
            datasets: datasets
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
 * 모든 차트 리사이즈 (탭 전환 시 사용)
 */
export function resizeAllCharts() {
    [
        stratChart, groupBarChartInstance, unifiedChart, cumulativeDividendChart, yearlyDividendChart,
        cumulativePnlChart, drawdownChart, alphaLineChart, monthlyHeatmapChart, tradeReasonPieChart,
        monthlyFrequencyChart, tickerContributionChart, currentAllocationDoughnut,
        historicalAllocationChart, regimeDistributionDoughnut, annualReturnsChart,
        targetVsActualChart, deviationTrendChart
    ].forEach(chart => {
        if (chart) chart.resize();
    });
}

/**
 * 누적 배당금 차트 (전체 기간 누적 합계 라인 차트)
 */
export function renderCumulativeDividendChart(summaryData, marketType = 'overseas') {
    const canvas = document.getElementById('cumulativeDividendChart');
    if (!canvas) return;
    const currSymbol = marketType === 'domestic' ? '₩' : '$';

    // 배당금이 있는 날짜만 추출해 누적 합산
    let cumulative = 0;
    const labels = [];
    const cumulativeData = [];

    summaryData.forEach(d => {
        const div = d.daily_dividend || 0;
        if (div > 0) {
            cumulative += div;
            labels.push(d.date);
            cumulativeData.push(parseFloat(cumulative.toFixed(2)));
        }
    });

    // 배당이 없으면 빈 상태 표시
    if (labels.length === 0) {
        labels.push(summaryData[0]?.date || '-');
        cumulativeData.push(0);
    }

    if (cumulativeDividendChart) cumulativeDividendChart.destroy();

    cumulativeDividendChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: `누적 배당금 (${currSymbol})`,
                data: cumulativeData,
                borderColor: '#198754',
                backgroundColor: 'rgba(25, 135, 84, 0.15)',
                fill: true,
                tension: 0.3,
                pointRadius: 4,
                pointBackgroundColor: '#198754',
                stepped: false
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false } },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: `Cumulative Dividend (${currSymbol})` },
                    ticks: {
                        callback: v => currSymbol + v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => `누적 배당금: ${currSymbol}${ctx.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    }
                }
            }
        }
    });
}

/**
 * 전체 기간 연간 배당금 바 차트
 */
export function renderYearlyDividendChart(summaryData, marketType = 'overseas') {
    const canvas = document.getElementById('yearlyDividendChart');
    if (!canvas) return;
    const currSymbol = marketType === 'domestic' ? '₩' : '$';

    // 전체 기간 연도별 집계
    const yearlyMap = {};
    summaryData.forEach(d => {
        const div = d.daily_dividend || 0;
        if (div > 0) {
            const year = d.date.slice(0, 4); // "YYYY"
            yearlyMap[year] = (yearlyMap[year] || 0) + div;
        }
    });

    // 데이터 범위 내 연도 레이블 생성
    const years = Object.keys(yearlyMap).sort();
    if (years.length === 0 && summaryData.length > 0) {
        const firstYear = summaryData[0].date.slice(0, 4);
        const lastYear = summaryData[summaryData.length - 1].date.slice(0, 4);
        for (let y = parseInt(firstYear); y <= parseInt(lastYear); y++) years.push(String(y));
    }

    const barData = years.map(y => parseFloat((yearlyMap[y] || 0).toFixed(2)));

    if (yearlyDividendChart) yearlyDividendChart.destroy();

    yearlyDividendChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: years,
            datasets: [{
                label: `연간 배당금 (${currSymbol})`,
                data: barData,
                backgroundColor: barData.map(v =>
                    v > 0 ? 'rgba(25, 135, 84, 0.75)' : 'rgba(200, 200, 200, 0.3)'
                ),
                borderColor: barData.map(v =>
                    v > 0 ? '#198754' : 'rgba(200,200,200,0.5)'
                ),
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { display: false } },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: `Annual Dividend (${currSymbol})` },
                    ticks: {
                        callback: v => currSymbol + v.toFixed(0)
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => `연간 배당금: ${currSymbol}${ctx.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    }
                }
            }
        }
    });
}

function getRegimeColor(regimeStr) {
    if (!regimeStr) return 'transparent';
    const str = regimeStr.toLowerCase();
    
    if (str.includes('bull')) return 'rgba(25, 135, 84, 0.15)';        // 초록 (상승)
    if (str.includes('bear_strong')) return 'rgba(220, 53, 69, 0.2)'; // 짙은 빨강 (강하락)
    if (str.includes('bear')) return 'rgba(220, 53, 69, 0.1)';        // 옅은 빨강 (약하락/기본하락)
    if (str.includes('sideways')) return 'rgba(255, 193, 7, 0.15)';   // 노랑 (횡보)
    if (str.includes('crash')) return 'rgba(33, 37, 41, 0.4)';        // 어두운 회색 (폭락)
    
    return 'transparent'; // 매칭 안되면 투명하게
}

export function renderUnifiedChart(summaryData, marketType = 'overseas') {
    if (!summaryData || summaryData.length === 0) return;

    const canvas = document.getElementById('unifiedPerformanceChart');
    if (!canvas) return; // HTML에 캔버스가 없으면 에러 방지
    const ctx = canvas.getContext('2d');
    const currSymbol = marketType === 'domestic' ? '₩' : '$';

    // 데이터 가공
    const labels = summaryData.map(d => d.date);
    const initialPortfolioValue = summaryData[0].total_value;

    const portfolioData = summaryData.map(d => d.total_value);
    const groupAData = summaryData.map(d => d.group_a || 0);
    const groupBData = summaryData.map(d => d.group_b || 0);
    const groupCData = summaryData.map(d => d.group_c || 0);

    // 벤치마크 선: summary.json의 benchmarks 맵(논리명→가격)을 순회해
    // 논리명별 정규화 선을 생성한다. 계좌 통화에 맞춘 지수라 환율 오염이 없다.
    // 구버전 레코드엔 benchmarks가 없으므로(forward-only) 결측은 null로 처리해
    // 데이터가 존재하는 구간부터 선이 그려진다.
    const BENCHMARK_STYLE = {
        'S&P500':    'rgba(253, 126, 20, 0.8)',  // 주황
        'NASDAQ100': 'rgba(23, 190, 207, 0.8)',  // 청록
        'KOSPI200':  'rgba(111, 66, 193, 0.8)',  // 보라
    };
    const benchmarkNames = Object.keys(BENCHMARK_STYLE).filter(name =>
        summaryData.some(d => d.benchmarks && typeof d.benchmarks[name] === 'number')
    );
    const benchmarkDatasets = benchmarkNames.map(name => {
        // 벤치마크가 처음 등장하는 날의 포트폴리오 평가액에 기준선을 맞춰
        // "그 시점 이후 누가 앞서는가"를 공정하게 비교한다.
        const baseIdx = summaryData.findIndex(d => d.benchmarks && typeof d.benchmarks[name] === 'number');
        const basePrice = summaryData[baseIdx].benchmarks[name];
        const anchor = summaryData[baseIdx].total_value;
        const data = summaryData.map(d => {
            const p = d.benchmarks ? d.benchmarks[name] : undefined;
            return (typeof p === 'number') ? (p / basePrice) * anchor : null;
        });
        return {
            label: `${name} (${currSymbol})`,
            data: data,
            borderColor: BENCHMARK_STYLE[name],
            borderWidth: 2,
            borderDash: [5, 5],
            pointRadius: 0,
            fill: false,
            tension: 0.1,
            spanGaps: false,
            order: 2,
            stack: `bm_${name}`,
        };
    });

    // 국면(Regime) 배경 박스 계산 (Annotation 플러그인용)
    const annotations = {};
    let currentRegime = summaryData[0].regime;
    let startIdx = 0;
    let boxIndex = 0;

    for (let i = 0; i < summaryData.length; i++) {
        // 국면이 바뀌거나 데이터의 끝에 도달했을 때 박스를 생성
        if (summaryData[i].regime !== currentRegime || i === summaryData.length - 1) {
            annotations[`regimeBox${boxIndex++}`] = {
                type: 'box',
                xMin: labels[startIdx],
                xMax: labels[i],
                // yMin: 'min',
                // yMax: 'max',
                backgroundColor: getRegimeColor(currentRegime),
                borderWidth: 0,
                drawTime: 'beforeDraw' // 데이터 선 뒤(배경)에 그리도록 설정
            };
            currentRegime = summaryData[i].regime;
            startIdx = i;
        }
    }

    // 기존 차트가 있으면 삭제 (날짜 변경, 데이터 리로드 시 중첩 방지)
    if (unifiedChart) {
        unifiedChart.destroy();
    }

    // 차트 생성
    unifiedChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: `Total Portfolio (${currSymbol})`,
                    data: portfolioData,
                    borderColor: '#0d6efd',
                    borderWidth: 2,
                    pointRadius: 0, 
                    fill: false,
                    tension: 0.1,
                    order: 1, // 가장 위에 그림
                    stack: 'total'
                },
                ...benchmarkDatasets,
                {
                    label: 'Group C (Cash/SHV)',
                    data: groupCData,
                    backgroundColor: 'rgba(25, 135, 84, 0.5)',
                    borderColor: 'transparent',
                    fill: true,
                    pointRadius: 0,
                    stack: 'AssetStack', // 이 이름이 같아야 영역이 쌓임
                    order: 5
                },
                {
                    label: 'Group B (Safety)',
                    data: groupBData,
                    backgroundColor: 'rgba(108, 117, 125, 0.5)',
                    borderColor: 'transparent',
                    fill: true,
                    pointRadius: 0,
                    stack: 'AssetStack',
                    order: 4
                },
                {
                    label: 'Group A (Growth)',
                    data: groupAData,
                    backgroundColor: 'rgba(13, 110, 253, 0.3)',
                    borderColor: 'transparent',
                    fill: true,
                    pointRadius: 0,
                    stack: 'AssetStack',
                    order: 3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            scales: {
                x: { grid: { display: false } },
                y: {
                    stacked: true,
                    title: { display: true, text: `Asset Value (${currSymbol})` },
                    ticks: {
                        callback: function(value) { return currSymbol + value.toLocaleString(); }
                    }
                }
            },
            plugins: {
                annotation: { annotations: annotations }, // 여기서 배경색 칠해짐
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let datasetLabel = context.dataset.label || '';
                            let value = context.parsed.y;
                            
                            if (value === null) return datasetLabel;

                            // 1. 라벨 이름에 'Group'이 포함된 경우 (자산군 A, B, C) -> 비율(%)로 표시
                            if (datasetLabel.includes('Group')) {
                                // 현재 마우스가 위치한 데이터의 인덱스로 총 자산액을 가져옴
                                const totalValue = summaryData[context.dataIndex].total_value;
                                // 총액 대비 해당 자산군의 비율 계산 (총액이 0일 경우 방어코드 포함)
                                const percentage = totalValue > 0 ? (value / totalValue) * 100 : 0;
                                
                                return `${datasetLabel}: ${percentage.toFixed(1)}%`;
                            } 
                            // 2. 그 외의 경우 (Total Portfolio, SPY) -> 총액으로 표시
                            else {
                                return `${datasetLabel}: ${currSymbol}${value.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}`;
                            }
                        }                        
                    }
                },
                legend: {
                    display: true,
                    position: 'bottom',
                    labels: { usePointStyle: true, padding: 20 }
                }
            }
        }
    });
}

/**
 * 기간 선택 버튼(1M/3M/6M/1Y/ALL)에 따라 통합 차트를 재렌더링
 * @param {Array} summaryData - 전체 summary 배열
 * @param {string} range - '1M' | '3M' | '6M' | '1Y' | 'ALL'
 */
export function updatePerformanceChartRange(summaryData, range, marketType = 'overseas') {
    const filtered = filterByDateRange(summaryData, range);
    renderUnifiedChart(filtered, marketType);
    // 신규: 누적 P&L / 드로다운 / Alpha / 월별 히트맵도 기간에 맞춰 함께 갱신
    renderCumulativePnlChart(filtered, marketType);
    renderDrawdownChart(filtered);
    renderAlphaLineChart(filtered);
    renderMonthlyHeatmap(filtered);
}

// ============================================================
// 신규 차트 함수들 (대시보드 확장)
// ============================================================

/**
 * 누적 손익 ($) 라인 차트 — 0 기준선 포함
 */
export function renderCumulativePnlChart(summaryData, marketType = 'overseas') {
    const canvas = document.getElementById('cumulativePnlChart');
    if (!canvas) return;
    if (cumulativePnlChart) cumulativePnlChart.destroy();
    if (!summaryData || summaryData.length === 0) return;

    const currSymbol = marketType === 'domestic' ? '₩' : '$';
    const pnlSeries = computeCumulativePnl(summaryData);
    const labels = pnlSeries.map(p => p.date);
    const values = pnlSeries.map(p => p.pnl);

    cumulativePnlChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: `누적 손익 (${currSymbol})`,
                data: values,
                borderColor: '#0d6efd',
                backgroundColor: 'rgba(13, 110, 253, 0.12)',
                fill: true,
                tension: 0.15,
                pointRadius: 0,
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
                y: {
                    title: { display: true, text: `누적 손익 (${currSymbol})` },
                    ticks: {
                        callback: v => (v >= 0 ? `+${currSymbol}` : `-${currSymbol}`) + Math.abs(Math.round(v)).toLocaleString()
                    }
                }
            },
            plugins: {
                legend: { display: false },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            yMin: 0, yMax: 0,
                            borderColor: 'rgba(108, 117, 125, 0.6)',
                            borderWidth: 1,
                            borderDash: [4, 4]
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const v = ctx.parsed.y;
                            const sign = v >= 0 ? '+' : '-';
                            return `누적 손익: ${sign}${currSymbol}${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * 드로다운 히스토리 차트 (Underwater Chart)
 * 역대 신고점 대비 낙폭(%) 시계열 — 0% 기준선 아래 빨간 영역
 */
export function renderDrawdownChart(summaryData) {
    const canvas = document.getElementById('drawdownChart');
    if (!canvas) return;
    if (drawdownChart) { drawdownChart.destroy(); drawdownChart = null; }
    if (!summaryData || summaryData.length === 0) return;

    const series = computeDrawdownSeries(summaryData);
    const labels = series.map(p => p.date);
    const values = series.map(p => p.drawdown);

    drawdownChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: '드로다운 (%)',
                data: values,
                borderColor: 'rgba(220, 53, 69, 0.85)',
                backgroundColor: 'rgba(220, 53, 69, 0.15)',
                fill: true,
                tension: 0.1,
                pointRadius: 0,
                borderWidth: 1.5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
                y: {
                    max: 0,
                    title: { display: true, text: '드로다운 (%)' },
                    ticks: {
                        callback: v => v.toFixed(1) + '%'
                    }
                }
            },
            plugins: {
                legend: { display: false },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            yMin: 0, yMax: 0,
                            borderColor: 'rgba(108, 117, 125, 0.6)',
                            borderWidth: 1,
                            borderDash: [4, 4]
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const v = ctx.parsed.y;
                            return `드로다운: ${v.toFixed(2)}%`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * SPY 대비 누적 초과수익률(Alpha) 라인 — 양수=초록, 음수=빨강 영역
 */
export function renderAlphaLineChart(summaryData) {
    const canvas = document.getElementById('alphaLineChart');
    if (!canvas) return;
    if (alphaLineChart) alphaLineChart.destroy();
    if (!summaryData || summaryData.length === 0) return;

    const series = computeAlphaSeries(summaryData);
    const labels = series.map(p => p.date);
    const values = series.map(p => p.alpha);

    alphaLineChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Alpha vs S&P500 (%)',
                data: values,
                borderColor: ctx => {
                    const val = ctx.raw;
                    return val >= 0 ? '#198754' : '#dc3545';
                },
                segment: {
                    borderColor: ctx => (ctx.p1.parsed.y >= 0 ? '#198754' : '#dc3545'),
                    backgroundColor: ctx => (ctx.p1.parsed.y >= 0 ? 'rgba(25, 135, 84, 0.15)' : 'rgba(220, 53, 69, 0.15)'),
                },
                fill: { target: 'origin', above: 'rgba(25, 135, 84, 0.12)', below: 'rgba(220, 53, 69, 0.12)' },
                pointRadius: 0,
                borderWidth: 2,
                tension: 0.15
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
                y: {
                    title: { display: true, text: 'Alpha (%)' },
                    ticks: { callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%' }
                }
            },
            plugins: {
                legend: { display: false },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            yMin: 0, yMax: 0,
                            borderColor: 'rgba(108, 117, 125, 0.6)',
                            borderWidth: 1,
                            borderDash: [4, 4]
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const v = ctx.parsed.y;
                            return `Alpha: ${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * 월별 수익률 히트맵 (chartjs-chart-matrix 플러그인)
 * matrix 플러그인이 없으면 HTML 테이블 폴백으로 대체
 */
export function renderMonthlyHeatmap(summaryData) {
    const canvas = document.getElementById('monthlyHeatmap');
    const container = document.getElementById('monthly-heatmap-container');
    if (!canvas || !container) return;
    if (monthlyHeatmapChart) { monthlyHeatmapChart.destroy(); monthlyHeatmapChart = null; }
    if (!summaryData || summaryData.length < 2) return;

    const monthly = computeMonthlyReturns(summaryData);
    if (monthly.length === 0) return;

    // matrix 컨트롤러 사용 가능 여부 체크
    const hasMatrix = typeof Chart !== 'undefined' &&
        Chart.registry && Chart.registry.controllers &&
        Chart.registry.controllers.get && Chart.registry.controllers.get('matrix');

    if (!hasMatrix) {
        // 폴백: HTML 테이블 렌더링
        renderMonthlyHeatmapTable(container, monthly);
        return;
    }

    // 캔버스 복원 (이전 폴백 테이블을 지우고 canvas 재사용)
    if (!document.getElementById('monthlyHeatmap')) {
        container.innerHTML = '<canvas id="monthlyHeatmap"></canvas>';
    }
    const ctx = document.getElementById('monthlyHeatmap');

    const years = Array.from(new Set(monthly.map(m => m.year))).sort();
    const data = monthly.map(m => ({ x: m.month, y: m.year, v: m.return * 100 }));
    const maxAbs = Math.max(...data.map(d => Math.abs(d.v)), 0.01);

    monthlyHeatmapChart = new Chart(ctx, {
        type: 'matrix',
        data: {
            datasets: [{
                label: '월별 수익률 (%)',
                data: data,
                backgroundColor: c => {
                    const v = c.raw && c.raw.v;
                    if (v == null) return 'rgba(200,200,200,0.2)';
                    const ratio = Math.min(Math.abs(v) / maxAbs, 1);
                    if (v >= 0) return `rgba(25, 135, 84, ${0.15 + 0.7 * ratio})`;
                    return `rgba(220, 53, 69, ${0.15 + 0.7 * ratio})`;
                },
                borderColor: 'rgba(255,255,255,0.5)',
                borderWidth: 1,
                width: ctxArg => {
                    const area = ctxArg.chart.chartArea;
                    return area ? (area.right - area.left) / 12 - 2 : 20;
                },
                height: ctxArg => {
                    const area = ctxArg.chart.chartArea;
                    return area ? (area.bottom - area.top) / years.length - 2 : 20;
                }
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'linear',
                    min: 0.5, max: 12.5,
                    ticks: {
                        stepSize: 1,
                        callback: v => ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][v - 1] || ''
                    },
                    grid: { display: false }
                },
                y: {
                    type: 'linear',
                    reverse: true,
                    min: Math.min(...years) - 0.5,
                    max: Math.max(...years) + 0.5,
                    ticks: { stepSize: 1, callback: v => Number.isInteger(v) ? v : '' },
                    grid: { display: false }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: items => {
                            const r = items[0].raw;
                            const monthName = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][r.x - 1];
                            return `${r.y} ${monthName}`;
                        },
                        label: item => {
                            const v = item.raw.v;
                            return `수익률: ${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * matrix 플러그인 폴백: HTML 테이블로 월별 수익률 렌더링
 */
function renderMonthlyHeatmapTable(container, monthly) {
    const years = Array.from(new Set(monthly.map(m => m.year))).sort();
    const maxAbs = Math.max(...monthly.map(m => Math.abs(m.return * 100)), 0.01);
    const lookup = {};
    monthly.forEach(m => { lookup[`${m.year}-${m.month}`] = m.return * 100; });

    const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    let html = '<table class="table table-bordered table-sm mb-0 text-center small"><thead class="table-light"><tr><th></th>';
    monthNames.forEach(m => html += `<th>${m}</th>`);
    html += '</tr></thead><tbody>';

    years.forEach(y => {
        html += `<tr><th class="table-light">${y}</th>`;
        for (let m = 1; m <= 12; m++) {
            const v = lookup[`${y}-${m}`];
            if (v == null) {
                html += '<td class="text-muted">-</td>';
            } else {
                const ratio = Math.min(Math.abs(v) / maxAbs, 1);
                const bg = v >= 0
                    ? `rgba(25, 135, 84, ${0.15 + 0.7 * ratio})`
                    : `rgba(220, 53, 69, ${0.15 + 0.7 * ratio})`;
                const sign = v >= 0 ? '+' : '';
                html += `<td style="background-color:${bg}">${sign}${v.toFixed(1)}%</td>`;
            }
        }
        html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

/**
 * 거래 사유 분포 파이 차트
 */
export function renderTradeReasonPie(historyData) {
    const canvas = document.getElementById('tradeReasonPie');
    if (!canvas) return;
    if (tradeReasonPieChart) tradeReasonPieChart.destroy();

    const dist = computeTradeReasonDistribution(historyData);
    const labels = Object.keys(dist);
    const values = Object.values(dist);

    if (labels.length === 0) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.textAlign = 'center';
        ctx.fillStyle = '#6c757d';
        ctx.font = '14px sans-serif';
        ctx.fillText('거래 내역이 없습니다', canvas.width / 2, canvas.height / 2);
        return;
    }

    const palette = ['#0d6efd', '#198754', '#ffc107', '#dc3545', '#6f42c1', '#20c997', '#fd7e14', '#6c757d'];

    tradeReasonPieChart = new Chart(canvas, {
        type: 'pie',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: labels.map((_, i) => palette[i % palette.length]),
                borderColor: '#fff',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const total = values.reduce((s, v) => s + v, 0);
                            const pct = total > 0 ? (ctx.parsed / total * 100).toFixed(1) : '0';
                            return `${ctx.label}: ${ctx.parsed}건 (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * 월별 거래 빈도 바 차트
 */
export function renderMonthlyTradeFrequencyChart(historyData) {
    const canvas = document.getElementById('monthlyFrequencyChart');
    if (!canvas) return;
    if (monthlyFrequencyChart) monthlyFrequencyChart.destroy();

    const data = computeMonthlyTradeFrequency(historyData);
    const labels = data.map(d => d.month);
    const values = data.map(d => d.count);

    monthlyFrequencyChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: '거래 건수',
                data: values,
                backgroundColor: 'rgba(13, 110, 253, 0.65)',
                borderColor: '#0d6efd',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { display: false } },
                y: {
                    beginAtZero: true,
                    ticks: { precision: 0 },
                    title: { display: true, text: '거래 건수' }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.parsed.y}건`
                    }
                }
            }
        }
    });
}

/**
 * 티커별 거래 기여 가로 바 차트
 */
export function renderTickerContributionChart(historyData, marketType = 'overseas', groupConfig = null) {
    const canvas = document.getElementById('tickerContributionChart');
    if (!canvas) return;
    if (tickerContributionChart) tickerContributionChart.destroy();

    const data = computeTickerContribution(historyData);
    if (data.length === 0) return;

    const currSymbol = marketType === 'domestic' ? '₩' : '$';
    const labels = data.map(d => getTickerAlias(d.ticker, groupConfig));
    const volumes = data.map(d => d.totalVolume);

    tickerContributionChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: `거래 금액 (${currSymbol})`,
                data: volumes,
                backgroundColor: 'rgba(25, 135, 84, 0.65)',
                borderColor: '#198754',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    beginAtZero: true,
                    title: { display: true, text: `거래 금액 (${currSymbol})` },
                    ticks: { callback: v => currSymbol + Math.round(v).toLocaleString() }
                },
                y: { grid: { display: false } }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const d = data[ctx.dataIndex];
                            return [
                                `금액: ${formatAmount(d.totalVolume, marketType)}`,
                                `거래 건수: ${d.trades}건`,
                                `수수료: ${formatAmount(d.totalFees, marketType)}`
                            ];
                        }
                    }
                }
            }
        }
    });
}

/**
 * 현재 자산 배분 도넛 (그룹 합산 + Cash)
 */
export function renderCurrentAllocationDoughnut(statusData, groupConfig, marketType = 'overseas') {
    const canvas = document.getElementById('currentAllocationDoughnut');
    if (!canvas) return;
    if (currentAllocationDoughnut) currentAllocationDoughnut.destroy();
    if (!statusData || !statusData.portfolio) return;

    const holdings = statusData.portfolio.holdings || [];
    const cash = statusData.portfolio.cash_balance || 0;

    // 그룹별 합산
    const groupValues = {};
    const groupColors = {};
    holdings.forEach(h => {
        if (h.value <= 0) return;
        const g = getAssetGroup(h.ticker, groupConfig);
        groupValues[g.label] = (groupValues[g.label] || 0) + h.value;
        groupColors[g.label] = g.color;
    });

    if (cash > 0) {
        groupValues['Cash'] = (groupValues['Cash'] || 0) + cash;
        groupColors['Cash'] = '#6c757d';
    }

    const labels = Object.keys(groupValues);
    const values = Object.values(groupValues);
    const colors = labels.map(l => groupColors[l] || '#adb5bd');

    currentAllocationDoughnut = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderColor: '#fff',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const total = values.reduce((s, v) => s + v, 0);
                            const pct = total > 0 ? (ctx.parsed / total * 100).toFixed(1) : '0';
                            return `${ctx.label}: ${formatAmount(ctx.parsed, marketType)} (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * 국면 분포 도넛
 */
export function renderRegimeDistributionDoughnut(summaryData) {
    const canvas = document.getElementById('regimeDistributionDoughnut');
    if (!canvas) return;
    if (regimeDistributionDoughnut) regimeDistributionDoughnut.destroy();
    if (!summaryData || summaryData.length === 0) return;

    const dist = computeRegimeDistribution(summaryData);
    const labels = Object.keys(dist);
    const values = Object.values(dist);
    const total = values.reduce((s, v) => s + v, 0);

    const regimeColors = {
        'Bull': '#198754',
        'Sideways': '#ffc107',
        'Bear_Weak': '#dc3545',
        'Bear_Strong': 'rgba(220, 53, 69, 0.85)',
        'Crash': '#212529',
        'Unknown': '#6c757d'
    };
    const colors = labels.map(l => regimeColors[l] || '#adb5bd');

    regimeDistributionDoughnut = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: labels.map(l => l.replace('_', ' ')),
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderColor: '#fff',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const pct = total > 0 ? (ctx.parsed / total * 100).toFixed(1) : '0';
                            return `${ctx.label}: ${ctx.parsed}일 (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * 연간 수익률 vs SPY Grouped Bar Chart
 */
export function renderAnnualReturnsChart(summaryData) {
    const canvas = document.getElementById('annualReturnsChart');
    if (!canvas) return;
    if (annualReturnsChart) annualReturnsChart.destroy();
    if (!summaryData || summaryData.length < 2) return;

    const data = computeAnnualReturns(summaryData);
    if (data.length === 0) return;

    const labels = data.map(d => d.isYTD ? `${d.year} (YTD)` : d.year);

    annualReturnsChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Portfolio',
                    data: data.map(d => d.portfolioReturn),
                    backgroundColor: data.map(d => d.portfolioReturn >= 0 ? 'rgba(25, 135, 84, 0.75)' : 'rgba(220, 53, 69, 0.75)'),
                    borderColor: data.map(d => d.portfolioReturn >= 0 ? '#198754' : '#dc3545'),
                    borderWidth: 1,
                    borderRadius: 4
                },
                {
                    label: 'S&P500',
                    data: data.map(d => d.spyReturn),
                    backgroundColor: data.map(d => d.spyReturn >= 0 ? 'rgba(253, 126, 20, 0.65)' : 'rgba(220, 53, 69, 0.45)'),
                    borderColor: data.map(d => d.spyReturn >= 0 ? '#fd7e14' : '#dc3545'),
                    borderWidth: 1,
                    borderRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false } },
                y: {
                    title: { display: true, text: 'Return (%)' },
                    ticks: {
                        callback: v => (v >= 0 ? '+' : '') + v.toFixed(0) + '%'
                    }
                }
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { boxWidth: 12, font: { size: 11 } }
                },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            yMin: 0, yMax: 0,
                            borderColor: 'rgba(108, 117, 125, 0.6)',
                            borderWidth: 1,
                            borderDash: [4, 4]
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const v = ctx.parsed.y;
                            const sign = v >= 0 ? '+' : '';
                            return `${ctx.dataset.label}: ${sign}${v.toFixed(2)}%`;
                        },
                        afterBody: ctx => {
                            const idx = ctx[0].dataIndex;
                            const d = data[idx];
                            const alpha = d.portfolioReturn - d.spyReturn;
                            const sign = alpha >= 0 ? '+' : '';
                            return [`Alpha: ${sign}${alpha.toFixed(2)}%`];
                        }
                    }
                }
            }
        }
    });
}

/**
 * 자산군 비중 변화 추이 (Stacked Area)
 * group_a/b/c의 절대 금액을 시간축으로 쌓음
 */
export function renderHistoricalAllocationChart(summaryData, marketType = 'overseas') {
    const canvas = document.getElementById('historicalAllocationChart');
    if (!canvas) return;
    if (historicalAllocationChart) historicalAllocationChart.destroy();
    if (!summaryData || summaryData.length === 0) return;
    const currSymbol = marketType === 'domestic' ? '₩' : '$';

    const labels = summaryData.map(d => d.date);
    const groupA = summaryData.map(d => d.group_a || 0);
    const groupB = summaryData.map(d => d.group_b || 0);
    const groupC = summaryData.map(d => d.group_c || 0);

    historicalAllocationChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Group C (Cash/SHV)',
                    data: groupC,
                    backgroundColor: 'rgba(25, 135, 84, 0.5)',
                    borderColor: 'transparent',
                    fill: true,
                    pointRadius: 0,
                    stack: 'alloc',
                    order: 3
                },
                {
                    label: 'Group B (Safety)',
                    data: groupB,
                    backgroundColor: 'rgba(108, 117, 125, 0.5)',
                    borderColor: 'transparent',
                    fill: true,
                    pointRadius: 0,
                    stack: 'alloc',
                    order: 2
                },
                {
                    label: 'Group A (Growth)',
                    data: groupA,
                    backgroundColor: 'rgba(13, 110, 253, 0.5)',
                    borderColor: 'transparent',
                    fill: true,
                    pointRadius: 0,
                    stack: 'alloc',
                    order: 1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 10 } },
                y: {
                    stacked: true,
                    title: { display: true, text: `Asset Value (${currSymbol})` },
                    ticks: { callback: v => currSymbol + v.toLocaleString() }
                }
            },
            plugins: {
                legend: { position: 'bottom', labels: { usePointStyle: true, padding: 15 } },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const total = summaryData[ctx.dataIndex].total_value || 0;
                            const pct = total > 0 ? (ctx.parsed.y / total * 100).toFixed(1) : '0';
                            return `${ctx.dataset.label}: ${formatAmount(ctx.parsed.y, marketType)} (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * 목표 vs 실제 자산 배분 막대 차트 + 리밸런싱 이격도 배지.
 *
 * 목표 비중(% 총자산): A = exposure×eff_a, B = exposure×eff_b, C = 1−exposure
 * 실제 비중: 보유 종목 평가액 / 총자산 (C는 SHV 등 + 예수금)
 * 이격도: 봇과 동일하게 위험자산(A+B) 내부 비율 기준
 *   rel_dev = |실제비율 − 목표비율| / 목표비율,  rel_dev > threshold 시 리밸런싱 발동
 *
 * eff_a·threshold는 같은 사이클에 기록된 최신 summary 레코드에서 가져온다.
 */
export function renderTargetVsActualChart(statusData, groupConfig, marketType = 'overseas', summaryData = null) {
    const canvas = document.getElementById('targetVsActualChart');
    const badge = document.getElementById('rebalanceDeviationBadge');
    if (!canvas) return;
    if (targetVsActualChart) targetVsActualChart.destroy();

    const strategy = statusData && statusData.strategy;
    const portfolio = statusData && statusData.portfolio;
    const lastRec = summaryData && summaryData.length ? summaryData[summaryData.length - 1] : null;
    if (!groupConfig || !strategy || !portfolio || !lastRec || lastRec.target_ratio_a == null) {
        if (badge) badge.innerHTML = '';
        return;
    }

    const exposure = strategy.target_exposure != null ? strategy.target_exposure : 1.0;
    const effA = lastRec.target_ratio_a;
    const threshold = lastRec.rebalance_threshold;
    const effB = Math.max(1 - effA, 0);

    // 목표 비중(% 총자산)
    const targetA = exposure * effA * 100;
    const targetB = exposure * effB * 100;
    const targetC = Math.max(1 - exposure, 0) * 100;

    // 실제 비중 (보유 종목 그룹별 합산)
    const holdings = portfolio.holdings || [];
    const cash = portfolio.cash_balance || 0;
    const total = portfolio.total_value || 0;
    const tickersA = (groupConfig.A && groupConfig.A.tickers) || [];
    const tickersB = (groupConfig.B && groupConfig.B.tickers) || [];
    let valA = 0, valB = 0, valCStock = 0;
    holdings.forEach(h => {
        if (!h.value || h.value <= 0) return;
        if (tickersA.includes(h.ticker)) valA += h.value;
        else if (tickersB.includes(h.ticker)) valB += h.value;
        else valCStock += h.value;  // C그룹(SHV 등) 또는 미분류
    });
    const valC = valCStock + cash;
    const actualA = total > 0 ? valA / total * 100 : 0;
    const actualB = total > 0 ? valB / total * 100 : 0;
    const actualC = total > 0 ? valC / total * 100 : 0;

    const labelA = (groupConfig.A && groupConfig.A.label) || 'A';
    const labelB = (groupConfig.B && groupConfig.B.label) || 'B';
    const labels = [`A · ${labelA}`, `B · ${labelB}`, 'C · Cash'];

    targetVsActualChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: '목표',
                    data: [targetA, targetB, targetC],
                    backgroundColor: 'rgba(13, 110, 253, 0.35)',
                    borderColor: '#0d6efd',
                    borderWidth: 1.5,
                    borderRadius: 4
                },
                {
                    label: '실제',
                    data: [actualA, actualB, actualC],
                    backgroundColor: 'rgba(25, 135, 84, 0.65)',
                    borderColor: '#198754',
                    borderWidth: 1.5,
                    borderRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { display: false } },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: '총자산 대비 비중 (%)' },
                    ticks: { callback: v => v + '%' }
                }
            },
            plugins: {
                legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 10 } },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%`,
                        afterBody: items => {
                            const i = items[0].dataIndex;
                            const tgt = [targetA, targetB, targetC][i];
                            const act = [actualA, actualB, actualC][i];
                            return `편차: ${(act - tgt >= 0 ? '+' : '') + (act - tgt).toFixed(1)}%p`;
                        }
                    }
                }
            }
        }
    });

    // 이격도 배지 (봇과 동일한 위험자산 내부 비율 기준)
    if (badge) badge.innerHTML = _buildDeviationBadge(valA, valB, effA, effB, threshold);
}

/**
 * 리밸런싱 이격도 배지 HTML 생성.
 */
function _buildDeviationBadge(valA, valB, effA, effB, threshold) {
    const valRisky = valA + valB;
    if (valRisky <= 0) {
        return '<span class="badge bg-secondary">위험자산 미보유</span>';
    }
    const ratioA = valA / valRisky;
    const ratioB = valB / valRisky;
    const relDevA = effA > 0 ? Math.abs(ratioA - effA) / effA : 0;
    const relDevB = effB > 0 ? Math.abs(ratioB - effB) / effB : 0;
    const maxDev = Math.max(relDevA, relDevB);
    const devPct = (maxDev * 100).toFixed(1);
    const thrPct = (threshold * 100).toFixed(1);
    if (maxDev > threshold) {
        return `<span class="badge bg-danger">리밸런싱 발동 · 이격도 ${devPct}% &gt; 임계 ${thrPct}%</span>`;
    }
    const marginPct = ((threshold - maxDev) * 100).toFixed(1);
    return `<span class="badge bg-success">비율 유지 · 이격도 ${devPct}% (임계 ${thrPct}%, 여유 ${marginPct}%p)</span>`;
}

/**
 * 이격도(이탈도) 추이 라인 차트.
 *
 * summary.json 레코드에 그 시점 저장된 target_ratio_a·rebalance_threshold와
 * group_a/b로부터 위험자산 내부 비율 이격도를 계산해 시계열로 표시한다.
 * 저장값을 그대로 쓰므로 이후 설정이 바뀌어도 과거 이격도는 불변이다.
 * 임계치는 국면별로 달라 stepped 라인으로 함께 표시.
 */
export function renderDeviationTrendChart(summaryData) {
    const canvas = document.getElementById('deviationTrendChart');
    if (!canvas) return;
    if (deviationTrendChart) deviationTrendChart.destroy();
    if (!summaryData || summaryData.length === 0) return;

    const labels = [];
    const devA = [];
    const devB = [];
    const thr = [];
    summaryData.forEach(d => {
        labels.push(d.date);
        // 그 시점에 저장된 목표비율·임계치 사용 (설정 변경에도 불변).
        const effA = d.target_ratio_a;
        const effB = effA != null ? Math.max(1 - effA, 0) : null;
        const threshold = d.rebalance_threshold;
        const valRisky = (d.group_a || 0) + (d.group_b || 0);
        if (effA == null || valRisky <= 0) {
            devA.push(null);
            devB.push(null);
        } else {
            const ratioA = (d.group_a || 0) / valRisky;
            const ratioB = (d.group_b || 0) / valRisky;
            // 목표 비중 0이면 이격도 0 (백엔드 Rebalancer·이격도 배지와 동일 규약)
            devA.push(effA > 0 ? Math.abs(ratioA - effA) / effA * 100 : 0);
            devB.push(effB > 0 ? Math.abs(ratioB - effB) / effB * 100 : 0);
        }
        thr.push(threshold != null ? threshold * 100 : null);
    });

    deviationTrendChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'A그룹 이격도',
                    data: devA,
                    borderColor: '#0d6efd',
                    backgroundColor: 'rgba(13, 110, 253, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    spanGaps: true,
                    tension: 0.2
                },
                {
                    label: 'B그룹 이격도',
                    data: devB,
                    borderColor: '#198754',
                    backgroundColor: 'rgba(25, 135, 84, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    spanGaps: true,
                    tension: 0.2
                },
                {
                    label: '리밸런싱 임계치',
                    data: thr,
                    borderColor: '#dc3545',
                    borderWidth: 1.5,
                    borderDash: [6, 4],
                    pointRadius: 0,
                    stepped: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 10 } },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: '위험자산 내부 이격도 (%)' },
                    ticks: { callback: v => v + '%' }
                }
            },
            plugins: {
                legend: { position: 'bottom', labels: { usePointStyle: true, padding: 15 } },
                tooltip: {
                    callbacks: {
                        label: ctx => ctx.parsed.y == null ? null : `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%`
                    }
                }
            }
        }
    });
}
