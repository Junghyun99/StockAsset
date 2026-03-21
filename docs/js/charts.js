// docs/js/charts.js
// Chart.js 차트 생성 및 관리

import { filterByDateRange, getAssetGroup, formatCurrency } from './utils.js?v=2';

// 차트 인스턴스 (모듈 스코프, 모드 전환 시 기존 차트 삭제용)
let stratChart = null;
let groupBarChartInstance = null;
let unifiedChart = null;
let cumulativeDividendChart = null;
let yearlyDividendChart = null;

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
export function renderGroupBarChart(statusData, groupConfig) {
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
                label: `${group}: ${info.label} (${formatCurrency(value)})`,
                data: [totalValue > 0 ? (value / totalValue * 100) : 0],
                backgroundColor: info.color,
                barPercentage: 0.8
            };
        });
        // 매칭 안 된 티커('?')가 있으면 마지막에 추가
        if (groupValues['?']) {
            const otherValue = groupValues['?'];
            datasets.push({
                label: `Other (${formatCurrency(otherValue)})`,
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
            { label: `A: Growth (${formatCurrency(groupA)})`, data: [totalValue > 0 ? (groupA / totalValue * 100) : 0], backgroundColor: '#0d6efd', barPercentage: 0.8 },
            { label: `B: Safety (${formatCurrency(groupB)})`, data: [totalValue > 0 ? (groupB / totalValue * 100) : 0], backgroundColor: '#198754', barPercentage: 0.8 },
            { label: `C: Cash (${formatCurrency(groupC)})`, data: [totalValue > 0 ? (groupC / totalValue * 100) : 0], backgroundColor: '#ffc107', barPercentage: 0.8 }
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
    [stratChart, groupBarChartInstance, unifiedChart, cumulativeDividendChart, yearlyDividendChart].forEach(chart => {
        if (chart) chart.resize();
    });
}

/**
 * 누적 배당금 차트 (전체 기간 누적 합계 라인 차트)
 */
export function renderCumulativeDividendChart(summaryData) {
    const canvas = document.getElementById('cumulativeDividendChart');
    if (!canvas) return;

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
                label: '누적 배당금 ($)',
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
                    title: { display: true, text: 'Cumulative Dividend ($)' },
                    ticks: {
                        callback: v => '$' + v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => `누적 배당금: $${ctx.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    }
                }
            }
        }
    });
}

/**
 * 전체 기간 연간 배당금 바 차트
 */
export function renderYearlyDividendChart(summaryData) {
    const canvas = document.getElementById('yearlyDividendChart');
    if (!canvas) return;

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
                label: '연간 배당금 ($)',
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
                    title: { display: true, text: 'Annual Dividend ($)' },
                    ticks: {
                        callback: v => '$' + v.toFixed(0)
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => `연간 배당금: $${ctx.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
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

export function renderUnifiedChart(summaryData) {
    if (!summaryData || summaryData.length === 0) return;

    const canvas = document.getElementById('unifiedPerformanceChart');
    if (!canvas) return; // HTML에 캔버스가 없으면 에러 방지
    const ctx = canvas.getContext('2d');

    // 데이터 가공
    const labels = summaryData.map(d => d.date);
    const initialPortfolioValue = summaryData[0].total_value;
    const initialSpyPrice = summaryData[0].spy_price;

    // SPY 가격을 내 포트폴리오 초기 투자금 기준으로 환산 (스케일링)
    const spyScaledData = summaryData.map(d => (d.spy_price / initialSpyPrice) * initialPortfolioValue);
    
    const portfolioData = summaryData.map(d => d.total_value);
    const groupAData = summaryData.map(d => d.group_a || 0);
    const groupBData = summaryData.map(d => d.group_b || 0);
    const groupCData = summaryData.map(d => d.group_c || 0);

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
                    label: 'Total Portfolio ($)',
                    data: portfolioData,
                    borderColor: '#0d6efd',
                    borderWidth: 2,
                    pointRadius: 0, 
                    fill: false,
                    tension: 0.1,
                    order: 1, // 가장 위에 그림
                    stack: 'total'
                },
                {
                    label: 'SPY Benchmark ($)',
                    data: spyScaledData,
                    borderColor: 'rgba(253, 126, 20, 0.8)',
                    borderWidth: 2,
                    borderDash:[5, 5], 
                    pointRadius: 0,
                    fill: false,
                    tension: 0.1,
                    order: 2,
                    stack: 'spy'
                },
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
                    title: { display: true, text: 'Asset Value ($)' },
                    ticks: {
                        callback: function(value) { return '$' + value.toLocaleString(); }
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
                            // 2. 그 외의 경우 (Total Portfolio, SPY) -> 총액($)으로 표시
                            else {
                                return `${datasetLabel}: $${value.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}`;
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
export function updatePerformanceChartRange(summaryData, range) {
    const filtered = filterByDateRange(summaryData, range);
    renderUnifiedChart(filtered);
}
