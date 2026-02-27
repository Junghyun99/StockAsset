// docs/js/dashboard.js

// 차트 객체를 저장할 변수 (모드 전환 시 기존 차트 삭제 및 메모리 관리용)
let perfChart, allocChart, stratChart;

document.addEventListener('DOMContentLoaded', function() {
    // 1. URL 파라미터에서 모드 확인 (?mode=backtest)
    const urlParams = new URLSearchParams(window.location.search);
    const isBacktest = urlParams.get('mode') === 'backtest';
    
    // 데이터 경로 설정
    const dataPath = isBacktest ? 'data/backtest/' : 'data/';
    
    // UI 초기화 (버튼 활성화 상태 및 배지 설정)
    updateModeUI(isBacktest);
    
    // 대시보드 데이터 로드 실행
    initDashboard(dataPath);
});

/**
 * 상단 내비게이션 바의 모드 버튼 및 상태 배지 업데이트
 */
function updateModeUI(isBacktest) {
    const liveBtn = document.getElementById('link-live');
    const backtestBtn = document.getElementById('link-backtest');
    const modeBadge = document.getElementById('mode-badge');

    if (isBacktest) {
        backtestBtn.classList.add('active-backtest');
        modeBadge.classList.add('bg-info', 'text-dark');
        modeBadge.innerHTML = '<i class="fas fa-history me-1"></i> BACKTEST MODE';
    } else {
        liveBtn.classList.add('active-live');
        modeBadge.classList.add('bg-success');
        modeBadge.innerHTML = '<i class="fas fa-broadcast-tower me-1"></i> LIVE MODE';
    }
}

/**
 * 메인 데이터 로드 및 각 섹션 렌더링 컨트롤러
 */
async function initDashboard(dataPath) {
    try {
        // 1. 요약 데이터 로드 (시계열 차트 및 수익률 계산용)
        const summaryRes = await fetch(`${dataPath}summary.json`);
        const summaryData = await summaryRes.json();

        // 2. 상태 데이터 로드 (현재 포지션 및 지표 요약용)
        const statusRes = await fetch(`${dataPath}status.json`);
        const statusData = await statusRes.json();

        // 3. UI 업데이트 함수 호출
        updateSummaryCards(statusData, summaryData); 
        renderAllocationChart(statusData);
        renderCharts(summaryData);

        // 4. 매매 기록 데이터 로드
        const historyRes = await fetch(`${dataPath}history.json`);
        const historyData = await historyRes.json();
        renderTradeHistory(historyData);

        // 마지막 업데이트 시간 표시
        document.getElementById('last-updated').innerText = `Last Update: ${statusData.last_updated || 'Unknown'}`;

    } catch (error) {
        console.error("Data loading failed:", error);
        // 사용자에게 에러 알림
        const errorHtml = `<div class="alert alert-warning position-fixed bottom-0 end-0 m-3 shadow" style="z-index: 9999;">
            <i class="fas fa-exclamation-triangle me-2"></i> 데이터(${dataPath}) 로드 실패. 파일 생성을 기다려주세요.
        </div>`;
        document.body.insertAdjacentHTML('beforeend', errorHtml);
    }
}

/**
 * 상단 4개 요약 카드 정보 업데이트
 */
function updateSummaryCards(statusData, summaryData) {
    const strategy = statusData.strategy;
    const portfolio = statusData.portfolio;

    // [1] 총 자산 (Total Assets)
    document.getElementById('total-value').innerText = `$${portfolio.total_value.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
    
    // [1-2] 일간 수익률 계산 및 배지 업데이트 (vs Yesterday)
    const dailyReturnEl = document.getElementById('daily-return');
    if (summaryData && summaryData.length >= 2) {
        const todayVal = summaryData[summaryData.length - 1].total_value;
        const yesterdayVal = summaryData[summaryData.length - 2].total_value;
        const returnPct = ((todayVal / yesterdayVal) - 1) * 100;

        dailyReturnEl.innerText = (returnPct >= 0 ? '+' : '') + returnPct.toFixed(2) + '%';
        
        // 수익률 상태에 따른 색상 변경
        if (returnPct > 0) {
            dailyReturnEl.className = 'badge rounded-pill bg-success';
        } else if (returnPct < 0) {
            dailyReturnEl.className = 'badge rounded-pill bg-danger';
        } else {
            dailyReturnEl.className = 'badge rounded-pill bg-secondary';
        }
    }

    // [2] 시장 국면 (Market Regime)
    const regimeEl = document.getElementById('regime-text');
    regimeEl.innerText = strategy.regime.replace('_', ' ');
    regimeEl.className = 'fw-bold mb-0 ' + getRegimeColorClass(strategy.regime);

    // [2-2] 모멘텀 점수
    document.getElementById('momentum-score').innerText = (strategy.market_score.spy_momentum * 100).toFixed(2) + '%';

    // [3] 목표 비중 (Target Exposure)
    const exposure = (strategy.target_exposure * 100).toFixed(0);
    document.getElementById('target-exposure').innerText = exposure + '%';
    document.getElementById('exposure-bar').style.width = exposure + '%';

    // [4] 리스크 지표 (Risk Indicators)
    document.getElementById('vix-value').innerText = strategy.market_score.vix.toFixed(2);
    const mddVal = (strategy.market_score.spy_mdd * 100).toFixed(2);
    const mddEl = document.getElementById('mdd-value');
    mddEl.innerText = mddVal + '%';
    mddEl.className = 'fw-bold ' + (mddVal <= -10 ? 'text-danger' : 'text-dark');
    
    // 현금 잔고 (Holdings 카드 하단)
    document.getElementById('cash-value').innerText = `$${portfolio.cash_balance.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
}

/**
 * Performance 차트 및 전략 노출 비중 차트 렌더링
 */

function renderCharts(summaryData) {
    const labels = summaryData.map(d => d.date);
    
    // Performance 데이터 준비 (상단 그래프용)
    const portfolioValues = summaryData.map(d => d.total_value);
    const spyPrices = summaryData.map(d => d.spy_price);
    const initialPort = portfolioValues[0];
    const initialSpy = spyPrices[0];
    const portReturns = portfolioValues.map(v => (v / initialPort - 1) * 100);
    const spyReturns = spyPrices.map(v => (v / initialSpy - 1) * 100);

    // Strategy 데이터 준비 (하단 그래프용)
    const exposures = summaryData.map(d => d.target_exposure * 100);
    // [정보 추가] VIX와 모멘텀 지표를 함께 시각화
    // VIX는 스케일이 다르므로 보조축을 사용하거나 비율로 표시
    const spyMomentums = summaryData.map(d => d.spy_momentum * 100); 

    // (1) Performance History 차트 (기존과 유사하지만 툴팁 강화)
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

    // (2) Strategy Analysis 차트 (대폭 업그레이드)
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
                y: { // 왼쪽 축: 비중
                    beginAtZero: true, max: 110,
                    title: { display: true, text: 'Exposure (%)' }
                },
                y1: { // 오른쪽 축: 지표
                    position: 'right',
                    title: { display: true, text: 'Momentum (%)' },
                    grid: { drawOnChartArea: false }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        // 툴팁에서 모든 전략적 근거 데이터 표시
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

    // 인사이트 리스트 업데이트 (가장 최신일 기준)
    updateDecisionLogic(summaryData[summaryData.length - 1]);
}

/**
 * 전략 판단 근거 리스트 업데이트
 */
function updateDecisionLogic(lastData) {
    const list = document.getElementById('decision-logic-list');
    if (!lastData) return;

    const isAboveMA = lastData.spy_price > lastData.spy_ma180;
    const isMomPositive = lastData.spy_momentum > 0;
    const isVixSafe = lastData.vix < 30;

    list.innerHTML = `
        <li class="list-group-item d-flex justify-content-between align-items-center">
            Price > MA180
            <i class="fas ${isAboveMA ? 'fa-check-circle text-success' : 'fa-times-circle text-danger'}"></i>
        </li>
        <li class="list-group-item d-flex justify-content-between align-items-center">
            Momentum (+)
            <i class="fas ${isMomPositive ? 'fa-check-circle text-success' : 'fa-times-circle text-danger'}"></i>
        </li>
        <li class="list-group-item d-flex justify-content-between align-items-center">
            VIX Safe (<30)
            <i class="fas ${isVixSafe ? 'fa-check-circle text-success' : 'fa-times-circle text-danger'}"></i>
        </li>
        <li class="list-group-item mt-2 bg-light p-2 rounded">
            <small class="text-muted d-block">Current Logic:</small>
            <strong class="small">${lastData.regime}</strong>
        </li>
    `;
}   
            
    
      
            
            
/**
 * 현재 보유 자산 구성 차트 (Doughnut)
 */
function renderAllocationChart(statusData) {
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
            cutout: '60%' // 도넛 두께
        }
    });
}

/**
 * 매매 기록 테이블 렌더링
 */
function renderTradeHistory(historyData) {
    const tbody = document.getElementById('history-table-body');
    tbody.innerHTML = '';

    // 최신 순 정렬 후 상위 10개만 추출
    const recentTrades = historyData.slice().reverse().slice(0, 10);

    if (recentTrades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No trade history found.</td></tr>';
        return;
    }

    recentTrades.forEach(tx => {
        const row = document.createElement('tr');
        
        // 체결 종목 배지 생성
        let actionsHtml = tx.executions.map(ex => `
            <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge">
                ${ex.action} ${ex.ticker} (${ex.quantity})
            </span>
        `).join('');

        row.innerHTML = `
            <td class="small fw-bold text-muted">${tx.date.split(' ')[0]}</td>
            <td class="small">${tx.reason}</td>
            <td class="fw-bold text-dark">$${tx.total_trade_amount.toLocaleString(undefined, {maximumFractionDigits: 0})}</td>
            <td>${actionsHtml}</td>
        `;
        tbody.appendChild(row);
    });
}

/**
 * 시장 국면에 따른 텍스트 색상 클래스 반환 유틸
 */
function getRegimeColorClass(regime) {
    regime = regime.toLowerCase();
    if (regime.includes('bull')) return 'text-success';
    if (regime.includes('bear')) return 'text-danger';
    if (regime.includes('sideways')) return 'text-warning';
    if (regime.includes('crash')) return 'text-white bg-danger px-2 rounded';
    return 'text-muted';
}