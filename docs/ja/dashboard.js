document.addEventListener("DOMContentLoaded", function() {
    initDashboard();
});

// 캐시 방지용 타임스탬프
const ts = new Date().getTime();

async function initDashboard() {
    try {
        // 병렬로 데이터 로드 (속도 향상)
        const [statusRes, summaryRes, historyRes] = await Promise.all([
            fetch(`data/status.json?t=${ts}`),
            fetch(`data/summary.json?t=${ts}`),
            fetch(`data/history.json?t=${ts}`)
        ]);

        const statusData = await statusRes.json();
        const summaryData = await summaryRes.json();
        const historyData = await historyRes.json();

        // UI 업데이트 실행
        renderStatus(statusData, summaryData);
        renderCharts(summaryData);
        renderHoldings(statusData);
        renderHistory(historyData);

    } catch (error) {
        console.error("Failed to load dashboard data:", error);
        document.querySelector('.container').innerHTML = `
            <div class="alert alert-danger mt-5">
                <h4>Error Loading Data</h4>
                <p>데이터 파일을 불러오는 데 실패했습니다. 봇이 아직 실행되지 않았거나 경로가 잘못되었습니다.</p>
                <small>${error}</small>
            </div>`;
    }
}

// 1. 상단 상태 카드 렌더링
function renderStatus(status, summary) {
    const s = status.strategy;
    const p = status.portfolio;
    const m = s.market_score;

    // 업데이트 시간
    document.getElementById('last-updated').innerText = `Last Update: ${status.last_updated}`;

    // 총 자산
    document.getElementById('total-value').innerText = formatCurrency(p.total_value);

    // 일간 수익률 계산 (Summary의 마지막 데이터와 비교)
    let dailyRet = 0;
    if (summary.length > 0) {
        const lastSummary = summary[summary.length - 1];
        // 만약 오늘 날짜가 summary에 이미 반영되어 있다면 그 전날과 비교해야 정확함.
        // 여기서는 단순화를 위해 summary 마지막 값(어제 확정분)과 현재 status(오늘 라이브)를 비교
        const prevValue = lastSummary.total_value;
        dailyRet = ((p.total_value - prevValue) / prevValue) * 100;
    }
    
    const retEl = document.getElementById('daily-return');
    retEl.innerText = `${dailyRet >= 0 ? '+' : ''}${dailyRet.toFixed(2)}%`;
    retEl.className = `badge rounded-pill ${dailyRet >= 0 ? 'bg-success' : 'bg-danger'}`;

    // 국면 (Regime)
    const regimeEl = document.getElementById('regime-text');
    regimeEl.innerText = s.regime.replace('_', ' '); // Bear_Weak -> Bear Weak
    
    // 국면별 스타일 적용
    if (s.regime.includes("Bull")) regimeEl.className = "fw-bold mb-0 regime-bull";
    else if (s.regime.includes("Bear")) regimeEl.className = "fw-bold mb-0 regime-bear";
    else if (s.regime.includes("Crash")) regimeEl.className = "fw-bold mb-0 regime-crash";
    else regimeEl.className = "fw-bold mb-0 regime-sideways";

    document.getElementById('momentum-score').innerText = m.spy_momentum.toFixed(4);

    // 타겟 비중
    document.getElementById('target-exposure').innerText = `${(s.target_exposure * 100).toFixed(0)}%`;
    document.getElementById('exposure-bar').style.width = `${s.target_exposure * 100}%`;

    // 위험 지표
    document.getElementById('vix-value').innerText = m.vix.toFixed(2);
    const mddEl = document.getElementById('mdd-value');
    mddEl.innerText = `${(m.spy_mdd * 100).toFixed(2)}%`;
    if (m.spy_mdd < -0.15) mddEl.classList.add('text-danger'); // 위험 강조
}

// 2. 보유 종목 (파이 차트 & 텍스트)
function renderHoldings(status) {
    const pf = status.portfolio;
    document.getElementById('cash-value').innerText = formatCurrency(pf.cash_balance);

    const labels = ['Cash'];
    const data = [pf.cash_balance];
    const colors = ['#e9ecef']; // Cash color

    // 보유 종목 추가
    pf.holdings.forEach(h => {
        labels.push(h.ticker);
        data.push(h.value);
        // 간단한 색상 할당 (랜덤 or 고정)
        if (h.ticker === 'SHV') colors.push('#adb5bd'); // Safe asset
        else colors.push('#0d6efd'); // Risky asset
    });

    const ctx = document.getElementById('allocationChart').getContext('2d');
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors,
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom' }
            }
        }
    });
}

// 3. 차트 렌더링 (Performance & Strategy)
function renderCharts(summary) {
    // 최근 90일 데이터만 사용 (너무 많으면 느림)
    const recentData = summary.slice(-90);
    const labels = recentData.map(d => d.date.substring(5)); // MM-DD

    // 3-1. 메인 차트: 자산 가치 vs SPY 주가 (Dual Axis)
    const ctxMain = document.getElementById('performanceChart').getContext('2d');
    new Chart(ctxMain, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'My Portfolio ($)',
                    data: recentData.map(d => d.total_value),
                    borderColor: '#0d6efd',
                    backgroundColor: 'rgba(13, 110, 253, 0.1)',
                    yAxisID: 'y',
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'SPY Price ($)',
                    data: recentData.map(d => d.spy_price),
                    borderColor: '#adb5bd',
                    borderDash: [5, 5], // 점선
                    yAxisID: 'y1',
                    tension: 0.3,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            interaction: { mode: 'index', intersect: false },
            scales: {
                y: { type: 'linear', display: true, position: 'left' },
                y1: { type: 'linear', display: true, position: 'right', grid: { drawOnChartArea: false } }
            }
        }
    });

    // 3-2. 전략 차트: SPY Price vs MA180 (마켓 타이밍 시각화)
    const ctxStrat = document.getElementById('strategyChart').getContext('2d');
    new Chart(ctxStrat, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'SPY Close',
                    data: recentData.map(d => d.spy_price),
                    borderColor: '#198754',
                    borderWidth: 1.5,
                    pointRadius: 0
                },
                {
                    label: 'MA 180',
                    data: recentData.map(d => d.spy_ma180),
                    borderColor: '#dc3545',
                    borderWidth: 1.5,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } }, // 공간 절약
            scales: {
                x: { display: false }, // X축 숨김
                y: { display: false }  // Y축 숨김 (트렌드만 확인)
            }
        }
    });
}

// 4. 매매 기록 (History Table)
function renderHistory(history) {
    // 최신순 정렬 후 10개만
    const recent = history.slice().reverse().slice(0, 10);
    const tbody = document.getElementById('history-table-body');
    
    tbody.innerHTML = recent.map(row => {
        // executions 필드가 있으면 그것을 쓰고, 없으면(구버전) orders를 씀
        const actions = row.executions || row.orders || [];
        
        let actionBadges = actions.map(a => {
            const color = a.action === 'BUY' ? 'success' : 'danger';
            return `<span class="badge bg-${color} order-badge">${a.action} ${a.ticker} (${a.quantity})</span>`;
        }).join(" ");

        if (actions.length === 0) actionBadges = '<span class="text-muted">-</span>';

        return `
            <tr>
                <td>${row.date.substring(0, 10)}</td>
                <td><small>${row.reason}</small></td>
                <td><small>${row.total_trade_amount ? '$'+formatCurrency(row.total_trade_amount) : '-'}</small></td>
                <td>${actionBadges}</td>
            </tr>
        `;
    }).join("");
}

// 유틸리티: 화폐 포맷
function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value).replace('$', '');
}