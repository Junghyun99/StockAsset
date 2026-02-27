// docs/js/dashboard.js 내의 해당 함수를 아래 내용으로 교체하세요.

function updateSummaryCards(data, summaryData) { // summaryData 인자 추가
    const strategy = data.strategy;
    const portfolio = data.portfolio;

    // 1. 총 자산 표시
    document.getElementById('total-value').innerText = `$${portfolio.total_value.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
    
    // 2. 일간 수익률 계산 (summaryData 활용)
    const dailyReturnEl = document.getElementById('daily-return');
    if (summaryData && summaryData.length >= 2) {
        const todayVal = summaryData[summaryData.length - 1].total_value;
        const yesterdayVal = summaryData[summaryData.length - 2].total_value;
        const returnPct = ((todayVal / yesterdayVal) - 1) * 100;

        dailyReturnEl.innerText = (returnPct >= 0 ? '+' : '') + returnPct.toFixed(2) + '%';
        
        // 수익률에 따른 색상 변경
        if (returnPct > 0) {
            dailyReturnEl.className = 'badge rounded-pill bg-success'; // 상승: 초록
        } else if (returnPct < 0) {
            dailyReturnEl.className = 'badge rounded-pill bg-danger';  // 하락: 빨강
        } else {
            dailyReturnEl.className = 'badge rounded-pill bg-secondary'; // 변동없음: 회색
        }
    }

    // 3. 현금 표시
    document.getElementById('cash-value').innerText = `$${portfolio.cash_balance.toLocaleString(undefined, {minimumFractionDigits: 2})}`;

    // 4. 시장 국면 표시
    const regimeEl = document.getElementById('regime-text');
    regimeEl.innerText = strategy.regime.replace('_', ' ');
    regimeEl.className = 'fw-bold mb-0 ' + getRegimeColorClass(strategy.regime);

    // 5. 모멘텀 스코어 표시
    document.getElementById('momentum-score').innerText = (strategy.market_score.spy_momentum * 100).toFixed(2) + '%';

    // 6. 목표 노출 비중 표시
    const exposure = (strategy.target_exposure * 100).toFixed(0);
    document.getElementById('target-exposure').innerText = exposure + '%';
    document.getElementById('exposure-bar').style.width = exposure + '%';

    // 7. 리스크 지표 표시
    document.getElementById('vix-value').innerText = strategy.market_score.vix.toFixed(2);
    const mddVal = (strategy.market_score.spy_mdd * 100).toFixed(2);
    const mddEl = document.getElementById('mdd-value');
    mddEl.innerText = mddVal + '%';
    mddEl.className = 'fw-bold ' + (mddVal < -10 ? 'text-danger' : 'text-dark');
}

// 그리고 initDashboard 함수 내의 호출 부분도 순서를 살짝 바꿔야 합니다.
async function initDashboard(dataPath) {
    try {
        // 1. 요약 데이터 먼저 로드 (수익률 계산을 위해 필요)
        const summaryRes = await fetch(`${dataPath}summary.json`);
        const summaryData = await summaryRes.json();

        // 2. 상태 데이터 로드
        const statusRes = await fetch(`${dataPath}status.json`);
        const statusData = await statusRes.json();
        
        // 3. 업데이트 함수 호출 시 summaryData 전달
        updateSummaryCards(statusData, summaryData); 
        renderAllocationChart(statusData);
        renderCharts(summaryData);

        const historyRes = await fetch(`${dataPath}history.json`);
        const historyData = await historyRes.json();
        renderTradeHistory(historyData);

        document.getElementById('last-updated').innerText = `Last Update: ${statusData.last_updated || 'Unknown'}`;
    } catch (error) {
        console.error("Data loading failed:", error);
    }
}