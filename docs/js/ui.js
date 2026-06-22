// docs/js/ui.js
// DOM 업데이트: 상태 배너, 요약 카드, 결정 로직, 거래 내역, 페이지네이션

import {
    getRegimeColorClass,
    getRegimeBannerClass,
    getAssetGroup,
    getTickerAlias,
    formatCurrency,
    formatAmount,
    formatPercent,
    computeReturns,
    computeDrawdown,
    computeTradeStats,
    computeAdvancedMetrics,
    computeRollingReturn,
    computeCurrentDrawdownDays,
    computeCurrentRegimeStreak,
    computeFailedExecutions,
    inferNextRebalanceDate,
    computeExecutionGaps,
    computeRebalanceProximity,
    getStatusFreshness,
    computeRegimePerformance,
    computeYTDReturn,
    computeDividendYield,
    computeWinLossStats
} from './utils.js?v=8';

import { METRIC_TOOLTIPS } from './metric-tooltips.js?v=20260621-1';

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
export function updateSummaryCards(statusData, summaryData, marketType = 'overseas') {
    const strategy = statusData.strategy;
    const portfolio = statusData.portfolio;

    // [1] 총 자산 (Total Assets)
    document.getElementById('total-value').innerText = formatAmount(portfolio.total_value, marketType);

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
export function renderHoldingsTable(statusData, groupConfig, marketType = 'overseas') {
    const tbody = document.getElementById('holdings-table-body');
    const holdings = statusData.portfolio.holdings;
    const cash = statusData.portfolio.cash_balance;
    const totalValue = statusData.portfolio.total_value || (holdings.reduce((sum, h) => sum + (h.value || 0), 0) + (cash || 0));

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
        const ratio = totalValue > 0 ? Math.round((h.value || 0) / totalValue * 100) : 0;
        rows += `
            <tr>
                <td><span class="badge" style="background-color: ${g.color}">${g.group}: ${g.label}</span></td>
                <td class="fw-bold">${getTickerAlias(h.ticker, groupConfig)}</td>
                <td class="text-end">${h.qty}</td>
                <td class="text-end">${formatAmount(h.price, marketType)}</td>
                <td class="text-end">${formatAmount(h.value, marketType)}</td>
                <td class="text-end">${ratio}%</td>
            </tr>
        `;
    });

    // Cash 행 추가
    if (cash > 0) {
        const cashLabel = marketType === 'domestic' ? 'KRW' : 'USD';
        const cashRatio = totalValue > 0 ? Math.round(cash / totalValue * 100) : 0;
        rows += `
            <tr class="table-light">
                <td><span class="badge bg-secondary">Cash</span></td>
                <td class="fw-bold">${cashLabel}</td>
                <td class="text-end">-</td>
                <td class="text-end">-</td>
                <td class="text-end">${formatAmount(cash, marketType)}</td>
                <td class="text-end">${cashRatio}%</td>
            </tr>
        `;
    }

    tbody.innerHTML = rows || '<tr><td colspan="6" class="text-center text-muted">No holdings</td></tr>';
}

/**
 * 오늘의 활동 영역 렌더링
 */
export function renderTodayActivity(historyData, statusData, marketType = 'overseas', groupConfig = null) {
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
            ${ex.action} ${getTickerAlias(ex.ticker, groupConfig)} (${ex.quantity})
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
                Amount: ${formatAmount(lastTrade.total_trade_amount, marketType)}
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
        ['Total Return', p.totalReturn, s.totalReturn, 'percent',     true,  'totalReturn'],
        ['CAGR',         p.cagr,        s.cagr,        'percent',     true,  'cagr'],
        ['Max Drawdown', p.mdd,         s.mdd,         'percent',     false, 'mdd'],
        ['Volatility',   p.volatility,  s.volatility,  'percent_abs', false, 'volatility'],
        ['Sharpe Ratio', p.sharpe,      s.sharpe,      'ratio',       true,  'sharpe'],
        ['Sortino Ratio',p.sortino,     s.sortino,     'ratio',       true,  'sortino'],
        ['Calmar Ratio', p.calmar,      s.calmar,      'ratio',       true,  'calmar'],
        ['Beta',         p.beta,        s.beta,        'ratio',       null,  'beta'],
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
    rows.forEach(([label, portVal, spyVal, format, higherIsBetter, tooltipKey]) => {
        const portClass = compareClass(portVal, spyVal, higherIsBetter);
        const ttAttr = tooltipKey ? ` data-metric-tooltip="${tooltipKey}"` : '';
        html += `
            <tr>
                <td class="ps-3"${ttAttr}>${label} <span class="text-muted small">ⓘ</span></td>
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
            <td class="ps-3 fw-bold" data-metric-tooltip="alpha">Alpha <span class="text-muted small">ⓘ</span></td>
            <td class="text-end ${alphaClass}" colspan="2">${alpha >= 0 ? '+' : ''}${alpha.toFixed(2)}%</td>
        </tr>
    `;

    // Information Ratio 행 (포트폴리오 전용, SPY는 정의상 0)
    const ir = p.ir ?? 0;
    const irClass = ir >= 0.5 ? 'text-success fw-bold' : ir < 0 ? 'text-danger fw-bold' : 'text-dark fw-bold';
    html += `
        <tr class="table-light">
            <td class="ps-3 fw-bold" data-metric-tooltip="ir">Information Ratio <span class="text-muted small">ⓘ</span></td>
            <td class="text-end ${irClass}" colspan="2">${ir.toFixed(2)}</td>
        </tr>
    `;

    tbody.innerHTML = html;
}

/**
 * Trades 탭 - 거래 통계 카드 렌더링
 */
export function renderTradeSummaryStats(historyData, marketType = 'overseas') {
    const stats = computeTradeStats(historyData);

    document.getElementById('trade-count').innerText = stats.count.toLocaleString();
    document.getElementById('trade-volume').innerText = formatAmount(stats.totalVolume, marketType);
    document.getElementById('trade-fees').innerText = formatAmount(stats.totalFees, marketType);
}

// 거래 내역 페이지네이션 상태
let currentPage = 1;
const TRADES_PER_PAGE = 10;
let cachedHistoryData = [];
let cachedMarketType = 'overseas';
let cachedGroupConfig = null;

/**
 * 매매 기록 테이블 렌더링 (페이지네이션 지원)
 */
export function renderTradeHistory(historyData, page = undefined, marketType = 'overseas', groupConfig = null) {
    cachedHistoryData = historyData;
    cachedMarketType = marketType;
    if (groupConfig !== null) {
        cachedGroupConfig = groupConfig;
    }
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
                ${ex.action} ${getTickerAlias(ex.ticker, cachedGroupConfig)} (${ex.quantity})${Number.isFinite(ex.price) ? ' @' + formatAmount(ex.price, cachedMarketType) : ''}
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
            <td class="text-end small">${tx.portfolio_value ? formatAmount(tx.portfolio_value, cachedMarketType) : '-'}</td>
            <td class="text-end fw-bold text-dark">${formatAmount(tx.total_trade_amount, cachedMarketType)}</td>
            <td class="text-end small">${fee !== undefined ? formatAmount(fee, cachedMarketType) : '-'}</td>
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
                renderTradeHistory(cachedHistoryData, page, cachedMarketType);
            }
        });
    });
}

// ============================================================
// 대시보드 확장: 신규 UI 렌더 함수들
// ============================================================

/**
 * Performance 탭 - YTD Return 카드 (포트폴리오 + SPY 벤치마크)
 */
export function renderYTDCard(summaryData) {
    const portfolioEl = document.getElementById('ytd-portfolio');
    const spyEl = document.getElementById('ytd-spy');
    if (!portfolioEl || !spyEl) return;

    const ytd = computeYTDReturn(summaryData);
    if (ytd.portfolio == null) {
        portfolioEl.innerText = 'N/A';
        portfolioEl.className = 'fw-bold mb-1 text-muted';
        spyEl.innerText = 'SPY N/A';
        spyEl.className = 'small text-muted';
    } else {
        portfolioEl.innerText = formatPercent(ytd.portfolio);
        portfolioEl.className = 'fw-bold mb-1 ' + (ytd.portfolio >= 0 ? 'text-success' : 'text-danger');
        spyEl.innerText = 'SPY ' + formatPercent(ytd.spy);
        spyEl.className = 'small ' + (ytd.spy >= 0 ? 'text-success' : 'text-danger');
    }
}

/**
 * Performance 탭 - 롤링 수익률 카드 4개
 */
export function renderRollingReturnCards(summaryData) {
    const configs = [
        { id: 'rolling-1m', days: 21 },
        { id: 'rolling-3m', days: 63 },
        { id: 'rolling-6m', days: 126 },
        { id: 'rolling-1y', days: 252 },
    ];
    configs.forEach(cfg => {
        const el = document.getElementById(cfg.id);
        if (!el) return;
        const val = computeRollingReturn(summaryData, cfg.days);
        if (val == null) {
            el.innerText = 'N/A';
            el.className = 'fw-bold mb-0 text-muted';
        } else {
            el.innerText = formatPercent(val);
            el.className = 'fw-bold mb-0 ' + (val >= 0 ? 'text-success' : 'text-danger');
        }
    });
}

/**
 * Performance 탭 - 현재 드로다운 카드 (깊이 + 진행일수)
 */
export function renderCurrentDrawdownCard(summaryData) {
    const dd = computeCurrentDrawdownDays(summaryData);
    const valueEl = document.getElementById('current-dd-value');
    const daysEl = document.getElementById('current-dd-days');
    if (valueEl) {
        valueEl.innerText = dd.depthPct.toFixed(2) + '%';
        valueEl.className = 'fw-bold mb-0 ' + (dd.depthPct < -0.5 ? 'text-danger' : 'text-success');
    }
    if (daysEl) {
        daysEl.innerText = dd.days === 0 ? '신고점' : `${dd.days}일 진행`;
    }
}

/**
 * Performance 탭 - Calmar 비율 카드
 */
export function renderCalmarCard(summaryData) {
    const el = document.getElementById('calmar-value');
    if (!el) return;
    const metrics = computeAdvancedMetrics(summaryData);
    const calmar = metrics.portfolio.calmar;
    el.innerText = isFinite(calmar) ? calmar.toFixed(2) : 'N/A';
    el.className = 'fw-bold mb-0 ' + (calmar >= 1 ? 'text-success' : (calmar < 0 ? 'text-danger' : 'text-dark'));
}

/**
 * Trades 탭 - 수수료 영향도 카드 (누적 수수료 / 현재 자산)
 */
export function renderFeeImpactCard(historyData, summaryData) {
    const el = document.getElementById('fee-impact-pct');
    if (!el) return;
    const stats = computeTradeStats(historyData);
    const currentValue = summaryData && summaryData.length > 0
        ? summaryData[summaryData.length - 1].total_value
        : 0;
    if (currentValue <= 0) {
        el.innerText = '-';
        return;
    }
    const impact = (stats.totalFees / currentValue) * 100;
    el.innerText = impact.toFixed(3) + '%';
    el.className = 'fw-bold mb-0 ' + (impact < 0.5 ? 'text-success' : (impact < 2 ? 'text-warning' : 'text-danger'));
}

/**
 * 네브바 데이터 신선도 배지 렌더링
 */
export function renderStatusFreshnessBadge(statusData) {
    const badge = document.getElementById('freshness-badge');
    if (!badge || !statusData) return;
    const freshness = getStatusFreshness(statusData.last_updated);
    badge.className = 'badge me-3 ' + freshness.colorClass;
    badge.innerHTML = `<i class="fas fa-sync-alt me-1"></i>${freshness.label}`;
    badge.classList.remove('d-none');
}

/**
 * Overview 탭 - 미체결/실패 주문 상단 알림
 */
export function renderFailedOrderAlert(historyData, groupConfig = null) {
    const alert = document.getElementById('failed-order-alert');
    const text = document.getElementById('failed-order-alert-text');
    if (!alert || !text) return;
    const failed = computeFailedExecutions(historyData);
    if (failed.length === 0) {
        alert.classList.add('d-none');
        return;
    }
    alert.classList.remove('d-none');
    const recent = failed.slice(-3).reverse();
    const summary = recent.map(f => `${f.date} ${getTickerAlias(f.ticker, groupConfig)} ${f.action} [${f.status}]`).join(', ');
    text.innerHTML = ` ${failed.length}건 감지 — 최근: ${summary}`;
}

/**
 * Operations 탭 - 모든 카드/테이블 통합 렌더링
 */
export function renderOperationsPanel(statusData, historyData, summaryData, groupConfig = null) {
    // [1] 마지막 실행 시각 카드
    const lastRunLabel = document.getElementById('ops-last-run-label');
    const lastRunTime = document.getElementById('ops-last-run-time');
    if (lastRunLabel && lastRunTime) {
        const freshness = getStatusFreshness(statusData.last_updated);
        lastRunLabel.innerText = freshness.label;
        lastRunLabel.className = 'fw-bold mb-0 ' + (
            freshness.colorClass.includes('success') ? 'text-success' :
            freshness.colorClass.includes('danger') ? 'text-danger' :
            freshness.colorClass.includes('warning') ? 'text-warning' : 'text-dark'
        );
        lastRunTime.innerText = statusData.last_updated || '-';
    }

    // [2] 다음 리밸런싱 추정 카드
    const nextDateEl = document.getElementById('ops-next-rebal-date');
    const nextHintEl = document.getElementById('ops-next-rebal-hint');
    if (nextDateEl && nextHintEl) {
        const inferred = inferNextRebalanceDate(historyData, statusData.last_rebalancing_date);
        if (inferred.confidence === 'insufficient') {
            nextDateEl.innerText = '데이터 부족';
            nextDateEl.className = 'fw-bold mb-0 text-muted';
            nextHintEl.innerText = '거래 기록 3건 이상 필요';
        } else {
            nextDateEl.innerText = inferred.estimatedDate;
            nextDateEl.className = 'fw-bold mb-0 text-primary';
            const anchorTxt = inferred.anchorSource === 'status'
                ? `${inferred.anchorDate} 리밸런싱 기준`
                : `최근 거래 ${inferred.anchorDate} 기준`;
            nextHintEl.innerText = `${anchorTxt} · 평균 ${inferred.intervalDays}일 주기 (${inferred.confidence})`;
        }
    }

    // [3] 현재 국면 유지 기간 카드
    const regimeDays = document.getElementById('ops-regime-days');
    const regimeName = document.getElementById('ops-regime-name');
    const regimeStart = document.getElementById('ops-regime-start');
    if (regimeDays && regimeName && regimeStart) {
        const streak = computeCurrentRegimeStreak(summaryData);
        regimeDays.innerText = streak.days;
        regimeName.innerText = streak.regime.replace('_', ' ');
        regimeStart.innerText = streak.startDate;
    }

    // [4] 미체결/실패 주문 카운트 카드
    const failedCountEl = document.getElementById('ops-failed-count');
    const failedTableBody = document.getElementById('ops-failed-table-body');
    if (failedCountEl && failedTableBody) {
        const failed = computeFailedExecutions(historyData);
        failedCountEl.innerText = failed.length;
        failedCountEl.className = 'fw-bold mb-0 ' + (failed.length === 0 ? 'text-success' : 'text-danger');

        if (failed.length === 0) {
            failedTableBody.innerHTML = '<tr><td colspan="6" class="text-center text-success py-4"><i class="fas fa-check-circle me-1"></i>모든 주문이 정상 체결되었습니다</td></tr>';
        } else {
            failedTableBody.innerHTML = failed.slice().reverse().map(f => `
                <tr>
                    <td class="ps-3 small text-muted">${f.date}</td>
                    <td class="fw-bold">${getTickerAlias(f.ticker, groupConfig)}</td>
                    <td><span class="badge ${f.action === 'BUY' ? 'bg-success' : 'bg-danger'}">${f.action}</span></td>
                    <td class="text-end">${f.quantity}</td>
                    <td><span class="badge bg-warning text-dark">${f.status}</span></td>
                    <td class="pe-3 small">${f.reason || '-'}</td>
                </tr>
            `).join('');
        }
    }

    // [5] 봇 상태 요약 (우측 카드)
    const freshness = getStatusFreshness(statusData.last_updated);
    const freshnessLabelEl = document.getElementById('ops-freshness-label');
    if (freshnessLabelEl) {
        freshnessLabelEl.className = 'badge ' + freshness.colorClass;
        freshnessLabelEl.innerText = freshness.label;
    }
    const setText = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.innerText = text;
    };
    setText('ops-last-updated-raw', statusData.last_updated || '-');
    setText('ops-last-rebal-actual', statusData.last_rebalancing_date || '-');
    setText('ops-current-regime', (statusData.strategy && statusData.strategy.regime || '-').replace('_', ' '));
    setText('ops-target-exposure', statusData.strategy ? (statusData.strategy.target_exposure * 100).toFixed(0) + '%' : '-');
    setText('ops-trigger-reason', (statusData.strategy && statusData.strategy.trigger_reason) || '-');
    setText('ops-total-trades', (historyData || []).length + '건');

    // [6] 실행 연속성 카드 (스케줄 갭 감지)
    const scheduleStreakEl = document.getElementById('ops-schedule-streak');
    const scheduleDetailEl = document.getElementById('ops-schedule-detail');
    if (scheduleStreakEl && scheduleDetailEl) {
        const gaps = computeExecutionGaps(summaryData);
        scheduleStreakEl.innerText = gaps.consecutiveOkDays;
        if (gaps.totalRuns === 0) {
            scheduleStreakEl.className = 'text-muted';
            scheduleDetailEl.innerText = '실행 기록 없음';
        } else if (gaps.missedTotal === 0) {
            scheduleStreakEl.className = 'text-success';
            scheduleDetailEl.innerText = `총 ${gaps.totalRuns}회 실행 · 누락 없음`;
        } else {
            scheduleStreakEl.className = 'text-warning';
            const g = gaps.recentGap;
            const recentTxt = g ? ` (최근 ${g.from}~${g.to})` : '';
            scheduleDetailEl.innerText = `누락 의심 ${gaps.missedTotal}영업일 · 공휴일 가능${recentTxt}`;
        }
    }

    // [7] 리밸런싱 트리거 근접도 카드
    const proximityEl = document.getElementById('ops-rebal-proximity');
    const proximityBarEl = document.getElementById('ops-rebal-proximity-bar');
    const proximityDetailEl = document.getElementById('ops-rebal-proximity-detail');
    if (proximityEl && proximityBarEl && proximityDetailEl) {
        const prox = computeRebalanceProximity(summaryData);
        if (!prox.available) {
            proximityEl.innerText = 'N/A';
            proximityEl.className = 'fw-bold mb-1 text-muted';
            proximityBarEl.style.width = '0%';
            proximityBarEl.className = 'progress-bar bg-secondary';
            proximityDetailEl.innerText = '비율 데이터 부족';
        } else {
            const pct = prox.proximityPct;
            const colorWord = prox.willTrigger ? 'danger' : (pct >= 70 ? 'warning' : 'success');
            proximityEl.innerText = pct.toFixed(0) + '%';
            proximityEl.className = 'fw-bold mb-1 text-' + colorWord;
            proximityBarEl.style.width = Math.max(pct, 2) + '%';
            proximityBarEl.className = 'progress-bar bg-' + colorWord;
            const trigTxt = prox.willTrigger ? ' · 트리거 도달' : '';
            proximityDetailEl.innerText =
                `현재 A ${(prox.ratioA * 100).toFixed(1)}% / 목표 ${(prox.targetA * 100).toFixed(0)}% · ` +
                `이탈 ${(prox.maxDev * 100).toFixed(1)}% / 임계 ${(prox.threshold * 100).toFixed(1)}%${trigTxt}`;
        }
    }
}

/**
 * Performance 탭 - 국면별 성과 분석 테이블 렌더링
 */
export function renderRegimePerformanceTable(summaryData) {
    const tbody = document.getElementById('regime-performance-table-body');
    if (!tbody) return;

    const rows = computeRegimePerformance(summaryData);
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">데이터 없음</td></tr>';
        return;
    }

    // 국면 표시 순서 정의
    const ORDER = ['Bull', 'Sideways', 'Bear_Weak', 'Bear_Strong', 'Crash', 'Unknown'];
    rows.sort((a, b) => {
        const ai = ORDER.indexOf(a.regime);
        const bi = ORDER.indexOf(b.regime);
        return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    });

    tbody.innerHTML = rows.map(row => {
        const colorClass = getRegimeColorClass(row.regime);
        const cumClass = row.cumulativeReturn >= 0 ? 'text-success' : 'text-danger';
        const annClass = row.annualized >= 0 ? 'text-success' : 'text-danger';
        const mddClass = row.mdd < -5 ? 'text-danger' : 'text-muted';
        const regimeLabel = row.regime.replace('_', ' ');

        return `
            <tr>
                <td class="ps-3 fw-bold"><span class="${colorClass}">${regimeLabel}</span></td>
                <td class="text-end">${row.days.toLocaleString()}</td>
                <td class="text-end fw-bold ${cumClass}">${row.cumulativeReturn >= 0 ? '+' : ''}${row.cumulativeReturn.toFixed(2)}%</td>
                <td class="text-end ${annClass}">${row.annualized >= 0 ? '+' : ''}${row.annualized.toFixed(1)}%</td>
                <td class="text-end ${mddClass}">${row.mdd.toFixed(2)}%</td>
                <td class="text-end pe-3 text-muted">${row.periodPct.toFixed(1)}%</td>
            </tr>
        `;
    }).join('');
}

/**
 * 배당 요약 카드 3개 렌더링 (누적 배당금, 연환산 수익률, 올해 배당금)
 */
export function renderDividendSummaryCards(summaryData, marketType = 'overseas') {
    const container = document.getElementById('dividend-summary-cards');
    if (!container) return;

    const { totalDividend, annualizedYield, ytdDividend } = computeDividendYield(summaryData);
    const fmt = v => formatAmount(v, marketType);

    container.innerHTML = `
        <div class="col-md-4">
            <div class="card h-100 border-0 shadow-sm">
                <div class="card-body text-center p-3">
                    <h6 class="text-muted small mb-1">누적 배당금</h6>
                    <h5 class="fw-bold mb-1 text-success">${fmt(totalDividend)}</h5>
                    <div class="small text-muted">전체 기간 합계</div>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card h-100 border-0 shadow-sm">
                <div class="card-body text-center p-3">
                    <h6 class="text-muted small mb-1">연환산 수익률</h6>
                    <h5 class="fw-bold mb-1 ${annualizedYield > 0 ? 'text-success' : 'text-muted'}">${annualizedYield.toFixed(2)}%</h5>
                    <div class="small text-muted">배당금 / 평균 자산</div>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card h-100 border-0 shadow-sm">
                <div class="card-body text-center p-3">
                    <h6 class="text-muted small mb-1">올해 배당금</h6>
                    <h5 class="fw-bold mb-1 text-success">${fmt(ytdDividend)}</h5>
                    <div class="small text-muted">YTD 합계</div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Performance 탭 - 승률/손익비 통계 카드 4개 렌더링
 */
export function renderWinLossCards(summaryData) {
    const stats = computeWinLossStats(summaryData);

    const setCard = (id, value, colorClass) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerText = value;
        el.className = 'fw-bold mb-0 ' + colorClass;
    };

    if (stats.totalMonths === 0) {
        setCard('win-rate-value', 'N/A', 'text-muted');
        setCard('avg-win-value', 'N/A', 'text-muted');
        setCard('avg-loss-value', 'N/A', 'text-muted');
        setCard('profit-factor-value', 'N/A', 'text-muted');
    } else {
        setCard('win-rate-value',
            stats.winRate.toFixed(1) + '%',
            stats.winRate >= 50 ? 'text-success' : 'text-danger');

        setCard('avg-win-value',
            stats.avgWin > 0 ? '+' + stats.avgWin.toFixed(2) + '%' : 'N/A',
            stats.avgWin > 0 ? 'text-success' : 'text-muted');

        setCard('avg-loss-value',
            stats.avgLoss < 0 ? stats.avgLoss.toFixed(2) + '%' : 'N/A',
            stats.avgLoss < 0 ? 'text-danger' : 'text-muted');

        const pfText = !isFinite(stats.profitFactor) ? '∞' : stats.profitFactor.toFixed(2) + '×';
        const pfClass = !isFinite(stats.profitFactor) || stats.profitFactor >= 2.0
            ? 'text-success' : (stats.profitFactor >= 1.0 ? 'text-dark' : 'text-danger');
        setCard('profit-factor-value', pfText, pfClass);
    }

    const hintEl = document.getElementById('win-loss-total-months');
    if (hintEl) hintEl.innerText = `${stats.totalMonths}개월 기준`;
}

/**
 * data-metric-tooltip 속성을 가진 요소에 Bootstrap Tooltip 초기화.
 * 동적 렌더링 완료 후 호출해야 신규 DOM 요소도 적용됨.
 */
export function initTooltips() {
    if (!window.bootstrap || !window.bootstrap.Tooltip) return;
    document.querySelectorAll('[data-metric-tooltip]').forEach(el => {
        const key = el.getAttribute('data-metric-tooltip');
        const content = METRIC_TOOLTIPS[key];
        if (!content) return;
        const existing = window.bootstrap.Tooltip.getInstance(el);
        if (existing) return;
        new window.bootstrap.Tooltip(el, {
            html: true,
            title: content,
            trigger: 'hover focus',
            placement: 'right',
        });
        el.style.cursor = 'help';
    });
}
