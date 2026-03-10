// docs/js/ui.js
// DOM 업데이트: 상태 배너, 요약 카드, 결정 로직, 거래 내역, 페이지네이션

import {
    getRegimeColorClass,
    getRegimeBannerClass,
    getAssetGroup,
    formatCurrency,
    formatPercent,
    computeReturns,
    computeDrawdown,
    computeTradeStats,
    computeAdvancedMetrics
} from './utils.js?v=2';

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
 * 상태 배너 렌더링 (국면별 색상 + 주요 정보 한 줄)
 */
export function renderStatusBanner(statusData) {
    const banner = document.getElementById('status-banner');
    const bannerText = document.getElementById('banner-text');
    const bannerUpdated = document.getElementById('banner-updated');

    const strategy = statusData.strategy;
    const regime = strategy.regime.replace('_', ' ');
    const exposure = (strategy.target_exposure * 100).toFixed(0);
    const reason = strategy.trigger_reason || '';

    // 배너 색상 클래스 적용
    banner.className = 'status-banner mb-4 ' + getRegimeBannerClass(strategy.regime);
    bannerText.innerHTML = `<strong>${regime}</strong> &nbsp;|&nbsp; Exposure ${exposure}% &nbsp;|&nbsp; ${reason}`;
    bannerUpdated.textContent = statusData.last_updated || '';
}

/**
 * 상단 4개 요약 카드 정보 업데이트
 */
export function updateSummaryCards(statusData, summaryData) {
    const strategy = statusData.strategy;
    const portfolio = statusData.portfolio;

    // [1] 총 자산 (Total Assets)
    document.getElementById('total-value').innerText = formatCurrency(portfolio.total_value);

    // [1-2] 일간 수익률 계산 및 배지 업데이트 (vs Yesterday)
    const dailyReturnEl = document.getElementById('daily-return');
    if (summaryData && summaryData.length >= 2) {
        const todayVal = summaryData[summaryData.length - 1].total_value;
        const yesterdayVal = summaryData[summaryData.length - 2].total_value;
        const returnPct = ((todayVal / yesterdayVal) - 1) * 100;

        dailyReturnEl.innerText = formatPercent(returnPct);

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

    // [2-3] 트리거 사유
    const triggerEl = document.getElementById('trigger-reason');
    if (strategy.trigger_reason) {
        triggerEl.innerText = strategy.trigger_reason;
    }

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

    // [4-2] Volatility
    const volEl = document.getElementById('volatility-value');
    if (strategy.market_score.spy_volatility !== undefined) {
        volEl.innerText = (strategy.market_score.spy_volatility * 100).toFixed(1) + '%';
    }
}

/**
 * 보유 자산 테이블 렌더링 (그룹별 분류)
 */
export function renderHoldingsTable(statusData, groupConfig) {
    const tbody = document.getElementById('holdings-table-body');
    const holdings = statusData.portfolio.holdings;
    const cash = statusData.portfolio.cash_balance;

    // 그룹별 정렬
    const sorted = [...holdings].sort((a, b) => {
        const ga = getAssetGroup(a.ticker, groupConfig);
        const gb = getAssetGroup(b.ticker, groupConfig);
        return ga.group.localeCompare(gb.group);
    });

    let rows = '';
    sorted.forEach(h => {
        if (h.value <= 0 && h.qty <= 0) return; // 보유량 0인 항목 제외
        const g = getAssetGroup(h.ticker, groupConfig);
        rows += `
            <tr>
                <td><span class="badge" style="background-color: ${g.color}">${g.group}: ${g.label}</span></td>
                <td class="fw-bold">${h.ticker}</td>
                <td class="text-end">${h.qty}</td>
                <td class="text-end">${formatCurrency(h.price)}</td>
                <td class="text-end">${formatCurrency(h.value)}</td>
            </tr>
        `;
    });

    // Cash 행 추가
    if (cash > 0) {
        rows += `
            <tr class="table-light">
                <td><span class="badge bg-secondary">Cash</span></td>
                <td class="fw-bold">USD</td>
                <td class="text-end">-</td>
                <td class="text-end">-</td>
                <td class="text-end">${formatCurrency(cash)}</td>
            </tr>
        `;
    }

    tbody.innerHTML = rows || '<tr><td colspan="5" class="text-center text-muted">No holdings</td></tr>';
}

/**
 * 오늘의 활동 영역 렌더링
 */
export function renderTodayActivity(historyData, statusData) {
    const container = document.getElementById('today-activity');
    if (!historyData || historyData.length === 0) {
        container.innerHTML = `
            <div class="alert alert-light border mb-0">
                <i class="fas fa-info-circle me-1 text-muted"></i>
                <span class="small">No trade history available</span>
            </div>
        `;
        return;
    }

    // 가장 최근 거래
    const lastTrade = historyData[historyData.length - 1];
    const tradeDate = lastTrade.date.split(' ')[0];

    // 체결 종목 배지 생성
    let actionsHtml = lastTrade.executions.map(ex => `
        <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge me-1 mb-1">
            ${ex.action} ${ex.ticker} (${ex.quantity})
        </span>
    `).join('');

    container.innerHTML = `
        <div class="border rounded p-3">
            <div class="d-flex justify-content-between align-items-start mb-2">
                <span class="badge bg-primary">Latest Trade</span>
                <span class="small text-muted">${tradeDate}</span>
            </div>
            <p class="small text-muted mb-2">${lastTrade.reason}</p>
            <div>${actionsHtml}</div>
            <div class="small text-muted mt-2">
                Amount: ${formatCurrency(lastTrade.total_trade_amount)}
            </div>
        </div>
    `;
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
        <li class="list-group-item d-flex justify-content-between align-items-center px-0">
            Price > MA180
            <i class="fas ${isAboveMA ? 'fa-check-circle text-success' : 'fa-times-circle text-danger'}"></i>
        </li>
        <li class="list-group-item d-flex justify-content-between align-items-center px-0">
            Momentum (+)
            <i class="fas ${isMomPositive ? 'fa-check-circle text-success' : 'fa-times-circle text-danger'}"></i>
        </li>
        <li class="list-group-item d-flex justify-content-between align-items-center px-0">
            VIX Safe (<30)
            <i class="fas ${isVixSafe ? 'fa-check-circle text-success' : 'fa-times-circle text-danger'}"></i>
        </li>
        <li class="list-group-item mt-2 bg-light p-2 rounded px-0">
            <small class="text-muted d-block">Current Logic:</small>
            <strong class="small">${lastData.regime}</strong>
        </li>
    `;
}

/**
 * Performance 탭 - 포트폴리오 vs SPY 비교 테이블 렌더링
 */
export function renderPerformanceSummaryCards(summaryData) {
    const metrics = computeAdvancedMetrics(summaryData);
    const p = metrics.portfolio;
    const s = metrics.spy;

    // 지표 정의: [label, portValue, spyValue, format, higherIsBetter]
    const rows = [
        ['Total Return', p.totalReturn, s.totalReturn, 'percent', true],
        ['CAGR', p.cagr, s.cagr, 'percent', true],
        ['Max Drawdown', p.mdd, s.mdd, 'percent', false],
        ['Volatility', p.volatility, s.volatility, 'percent_abs', false],
        ['Sharpe Ratio', p.sharpe, s.sharpe, 'ratio', true],
        ['Sortino Ratio', p.sortino, s.sortino, 'ratio', true],
        ['Calmar Ratio', p.calmar, s.calmar, 'ratio', true],
        ['Beta', p.beta, s.beta, 'ratio', null],
    ];

    function fmt(value, format) {
        if (format === 'percent') {
            const sign = value >= 0 ? '+' : '';
            return sign + value.toFixed(2) + '%';
        }
        if (format === 'percent_abs') {
            return value.toFixed(2) + '%';
        }
        return value.toFixed(2);
    }

    // 우열 판단: 포트폴리오가 우수하면 text-success, 열위하면 text-danger
    function compareClass(portVal, spyVal, higherIsBetter) {
        if (higherIsBetter === null) return ''; // Beta는 비교 안 함
        if (Math.abs(portVal - spyVal) < 0.005) return ''; // 거의 동일
        if (higherIsBetter) {
            return portVal > spyVal ? 'text-success fw-bold' : 'text-danger';
        } else {
            // MDD, Volatility: 낮을수록 좋음 (MDD는 음수이므로 더 큰 값이 좋음)
            return portVal > spyVal ? 'text-success fw-bold' : 'text-danger';
        }
    }

    const tbody = document.querySelector('#metrics-comparison-table tbody');
    let html = '';
    rows.forEach(([label, portVal, spyVal, format, higherIsBetter]) => {
        const portClass = compareClass(portVal, spyVal, higherIsBetter);
        html += `
            <tr>
                <td class="ps-3">${label}</td>
                <td class="text-end ${portClass}">${fmt(portVal, format)}</td>
                <td class="text-end pe-3">${fmt(spyVal, format)}</td>
            </tr>
        `;
    });

    // Alpha 행 (포트폴리오 전용)
    const alpha = p.totalReturn - s.totalReturn;
    const alphaClass = alpha >= 0 ? 'text-success fw-bold' : 'text-danger fw-bold';
    html += `
        <tr class="table-light">
            <td class="ps-3 fw-bold">Alpha</td>
            <td class="text-end ${alphaClass}" colspan="2">${alpha >= 0 ? '+' : ''}${alpha.toFixed(2)}%</td>
        </tr>
    `;

    tbody.innerHTML = html;
}

/**
 * Trades 탭 - 거래 통계 카드 렌더링
 */
export function renderTradeSummaryStats(historyData) {
    const stats = computeTradeStats(historyData);

    document.getElementById('trade-count').innerText = stats.count.toLocaleString();
    document.getElementById('trade-volume').innerText = formatCurrency(stats.totalVolume);
    document.getElementById('trade-fees').innerText = formatCurrency(stats.totalFees);
}

// 거래 내역 페이지네이션 상태
let currentPage = 1;
const TRADES_PER_PAGE = 10;
let cachedHistoryData = [];

/**
 * 매매 기록 테이블 렌더링 (페이지네이션 지원)
 */
export function renderTradeHistory(historyData, page) {
    cachedHistoryData = historyData;
    if (page !== undefined) currentPage = page;

    const tbody = document.getElementById('history-table-body');
    tbody.innerHTML = '';

    // 최신 순 정렬
    const sorted = historyData.slice().reverse();
    const totalPages = Math.max(1, Math.ceil(sorted.length / TRADES_PER_PAGE));

    // 현재 페이지 범위
    if (currentPage > totalPages) currentPage = totalPages;
    const start = (currentPage - 1) * TRADES_PER_PAGE;
    const pageTrades = sorted.slice(start, start + TRADES_PER_PAGE);

    if (pageTrades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No trade history found.</td></tr>';
        renderPagination(0);
        return;
    }

    pageTrades.forEach(tx => {
        const row = document.createElement('tr');

        // 체결 종목 배지 생성
        let actionsHtml = tx.executions.map(ex => `
            <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge me-1 mb-1">
                ${ex.action} ${ex.ticker} (${ex.quantity})
            </span>
        `).join('');

        // 수수료 계산
        let fee = tx.total_fee;
        if (fee === undefined && tx.executions) {
            fee = tx.executions.reduce((sum, ex) => sum + (ex.fee || 0), 0);
        }

        row.innerHTML = `
            <td class="small fw-bold text-muted">${tx.date.split(' ')[0]}</td>
            <td class="small">${tx.reason}</td>
            <td class="text-end small">${tx.portfolio_value ? formatCurrency(tx.portfolio_value) : '-'}</td>
            <td class="text-end fw-bold text-dark">${formatCurrency(tx.total_trade_amount)}</td>
            <td class="text-end small">${fee !== undefined ? formatCurrency(fee) : '-'}</td>
            <td>${actionsHtml}</td>
        `;
        tbody.appendChild(row);
    });

    // 페이지 정보 배지
    const pageInfo = document.getElementById('trade-page-info');
    pageInfo.textContent = `${sorted.length} trades total`;

    renderPagination(totalPages);
}

/**
 * 페이지네이션 컨트롤 렌더링
 */
function renderPagination(totalPages) {
    const pagination = document.getElementById('trade-pagination');
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = '';

    // Previous
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${currentPage - 1}">&laquo;</a>
    </li>`;

    // Page numbers
    for (let i = 1; i <= totalPages; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" data-page="${i}">${i}</a>
        </li>`;
    }

    // Next
    html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${currentPage + 1}">&raquo;</a>
    </li>`;

    pagination.innerHTML = html;

    // 페이지 클릭 이벤트
    pagination.querySelectorAll('a[data-page]').forEach(a => {
        a.addEventListener('click', (e) => {
            e.preventDefault();
            const page = parseInt(a.dataset.page);
            if (page >= 1 && page <= totalPages) {
                renderTradeHistory(cachedHistoryData, page);
            }
        });
    });
}
