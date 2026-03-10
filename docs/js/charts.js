// docs/js/charts.js
// Chart.js 차트 생성 및 관리

import { filterByDateRange, getAssetGroup, formatCurrency } from './utils.js?v=2';

// 차트 인스턴스 (모듈 스코프, 모드 전환 시 기존 차트 삭제용)
let perfChart = null;
let stratChart = null;
let groupBarChartInstance = null;
let groupAllocChart = null;
let unifiedChart = null;

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
            datasets:[
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
