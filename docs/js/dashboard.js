// docs/js/dashboard.js

// 차트 객체를 저장할 변수 (모드 전환 시 기존 차트 삭제용)
let perfChart, allocChart, stratChart;

document.addEventListener('DOMContentLoaded', function() {
    const urlParams = new URLSearchParams(window.location.search);
    const isBacktest = urlParams.get('mode') === 'backtest';
    const dataPath = isBacktest ? 'data/backtest/' : 'data/';
    
    updateModeUI(isBacktest);
    initDashboard(dataPath);
});

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

async function initDashboard(dataPath) {
    try {
        // 1. 상태 데이터 로드
        const statusRes = await fetch(`${dataPath}status.json`);
        const statusData = await statusRes.json();
        updateSummaryCards(statusData);
        renderAllocationChart(statusData);

        // 2. 요약 데이터 로드 (시계열 차트용)
        const summaryRes = await fetch(`${dataPath}summary.json`);
        const summaryData = await summaryRes.json();
        renderCharts(summaryData);

        // 3. 히스토리 로드 (테이블용)
        const historyRes = await fetch(`${dataPath}history.json`);
        const historyData = await historyRes.json();
        renderTradeHistory(historyData);

        document.getElementById('last-updated').innerText = `Last Update: ${statusData.last_updated || 'Unknown'}`;

    } catch (error) {
        console.error("Data loading failed:", error);
        // 파일이 없을 경우 대비 (처음 세팅 시)
        document.body.innerHTML += `<div class="alert alert-danger position-fixed bottom-0 end-0 m-3">
            데이터 파일(${dataPath})을 찾을 수 없습니다.</div>`;
    }
}

// 1. 상단 카드 요약 정보 업데이트
function updateSummaryCards(data) {
    const strategy = data.strategy;
    const portfolio = data.portfolio;

    // 총 자산
    document.getElementById('total-value').innerText = `$${portfolio.total_value.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
    
    // 현금
    document.getElementById('cash-value').innerText = `$${portfolio.cash_balance.toLocaleString(undefined, {minimumFractionDigits: 2})}`;

    // 시장 국면
    const regimeEl = document.getElementById('regime-text');
    regimeEl.innerText = strategy.regime.replace('_', ' ');
    regimeEl.className = 'fw-bold mb-0 ' + getRegimeColorClass(strategy.regime);

    // 모멘텀 스코어
    document.getElementById('momentum-score').innerText = (strategy.market_score.spy_momentum * 100).toFixed(2) + '%';

    // 목표 노출 비중
    const exposure = (strategy.target_exposure * 100).toFixed(0);
    document.getElementById('target-exposure').innerText = exposure + '%';
    document.getElementById('exposure-bar').style.width = exposure + '%';

    // 리스크 지표
    document.getElementById('vix-value').innerText = strategy.market_score.vix.toFixed(2);
    const mddVal = (strategy.market_score.spy_mdd * 100).toFixed(2);
    const mddEl = document.getElementById('mdd-value');
    mddEl.innerText = mddVal + '%';
    mddEl.className = 'fw-bold ' + (mddVal < -10 ? 'text-danger' : 'text-dark');
}

// 2. 차트 렌더링 (Performance & Strategy)
function renderCharts(summaryData) {
    const labels = summaryData.map(d => d.date);
    const portfolioValues = summaryData.map(d => d.total_value);
    const spyPrices = summaryData.map(d => d.spy_price);
    const exposures = summaryData.map(d => d.target_exposure * 100);

    // 지수화를 위한 첫 번째 값 기준 계산 (수익률 비교용)
    const initialPort = portfolioValues[0];
    const initialSpy = spyPrices[0];
    const portReturns = portfolioValues.map(v => (v / initialPort - 1) * 100);
    const spyReturns = spyPrices.map(v => (v / initialSpy - 1) * 100);

    // Performance Chart
    if (perfChart) perfChart.destroy();
    const ctxPerf = document.getElementById('performanceChart').getContext('2d');
    perfChart = new Chart(ctxPerf, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Portfolio Return (%)',
                    data: portReturns,
                    borderColor: '#0d6efd',
                    backgroundColor: 'rgba(13, 110, 253, 0.1)',
                    fill: true,
                    tension: 0.1
                },
                {
                    label: 'SPY (Benchmark) (%)',
                    data: spyReturns,
                    borderColor: '#adb5bd',
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.1
                }
            ]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });

    // Strategy Chart (Exposure)
    if (stratChart) stratChart.destroy();
    const ctxStrat = document.getElementById('strategyChart').getContext('2d');
    stratChart = new Chart(ctxStrat, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Target Exposure (%)',
                data: exposures,
                borderColor: '#17a2b8',
                backgroundColor: 'rgba(23, 162, 184, 0.2)',
                fill: true,
                stepped: true
            }]
        },
        options: { 
            responsive: true, 
            maintainAspectRatio: false,
            scales: { y: { min: 0, max: 110 } }
        }
    });
}

// 3. 포트폴리오 비중 차트 (Pie)
function renderAllocationChart(statusData) {
    const holdings = statusData.portfolio.holdings;
    const cash = statusData.portfolio.cash_balance;
    
    const labels = holdings.map(h => h.ticker);
    const values = holdings.map(h => h.value);
    
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
                backgroundColor: ['#0d6efd', '#6610f2', '#6f42c1', '#d63384', '#fd7e14', '#ffc107', '#20c997', '#adb5bd']
            }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
    });
}

// 4. 매매 기록 테이블 업데이트
function renderTradeHistory(historyData) {
    const tbody = document.getElementById('history-table-body');
    tbody.innerHTML = '';

    // 최근 10개만 표시
    const recentTrades = historyData.slice().reverse().slice(0, 10);

    recentTrades.forEach(tx => {
        const row = document.createElement('tr');
        
        let actionsHtml = tx.executions.map(ex => `
            <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge">
                ${ex.action} ${ex.ticker} (${ex.quantity})
            </span>
        `).join('');

        row.innerHTML = `
            <td class="small">${tx.date.split(' ')[0]}</td>
            <td class="small">${tx.reason}</td>
            <td class="fw-bold">$${tx.total_trade_amount.toLocaleString()}</td>
            <td>${actionsHtml}</td>
        `;
        tbody.appendChild(row);
    });
}

// 헬퍼: 국면별 색상 클래스
function getRegimeColorClass(regime) {
    regime = regime.toLowerCase();
    if (regime.includes('bull')) return 'text-success';
    if (regime.includes('bear')) return 'text-danger';
    if (regime.includes('sideways')) return 'text-warning';
    if (regime.includes('crash')) return 'text-dark bg-warning p-1 rounded';
    return 'text-muted';
}
