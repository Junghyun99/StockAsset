// docs/js/ui.js
// DOM 업데이트: 요약 카드, 결정 로직, 거래 내역

import { getRegimeColorClass } from './utils.js';

/**
 * 상단 내비게이션 바의 모드 버튼 및 상태 배지 업데이트
 */
export function updateModeUI(isBacktest) {
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
 * 상단 4개 요약 카드 정보 업데이트
 */
export function updateSummaryCards(statusData, summaryData) {
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
 * 전략 판단 근거 리스트 업데이트
 */
export function updateDecisionLogic(lastData) {
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
 * 매매 기록 테이블 렌더링
 */
export function renderTradeHistory(historyData) {
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
