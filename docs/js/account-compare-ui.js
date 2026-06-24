// docs/js/account-compare-ui.js
// 라이브 다중 계좌 비교 전용 UI 렌더링

import {
    computeAdvancedMetrics,
    computeTradeStats,
    formatCurrency,
    formatKRW,
    formatPercent,
    ACCOUNT_COLORS,
    ACCOUNT_MARKET_TYPES,
} from './utils.js?v=20260624-1';

/**
 * Overview 탭 - 계좌별 비교 요약 테이블 렌더링 (해외/국내 섹션 분리)
 * @param {Map<string, Object>} accountsData - {accId: {summary, status, history, groupConfig}}
 */
export function renderAccountOverview(accountsData) {
    const container = document.getElementById('overview');
    if (!container) return;

    const accountIds = [...accountsData.keys()];
    const overseasIds = accountIds.filter(id => ACCOUNT_MARKET_TYPES[id] !== 'domestic');
    const domesticIds  = accountIds.filter(id => ACCOUNT_MARKET_TYPES[id] === 'domestic');

    const accountMetrics = {};
    for (const [id, data] of accountsData) {
        accountMetrics[id] = computeAdvancedMetrics(data.summary, null);
    }

    const today = new Date().toISOString().slice(0, 10);

    function colorDot(id) {
        const color = ACCOUNT_COLORS[id] || '#6c757d';
        return `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;"></span>`;
    }

    function hadTradeToday(history) {
        if (!history || history.length === 0) return false;
        const last = history[history.length - 1];
        return (last.date || '').slice(0, 10) === today;
    }

    // 지표 정의: [label, key, format, higherIsBetter]
    const metricDefs = [
        ['Final Value',   'finalValue',   'currency',    true],
        ['Total Return',  'totalReturn',  'percent',     true],
        ['CAGR',          'cagr',         'percent',     true],
        ['Max Drawdown',  'mdd',          'percent',     false],
        ['Volatility',    'volatility',   'percent_abs', false],
        ['Sharpe',        'sharpe',       'ratio',       true],
        ['Calmar',        'calmar',       'ratio',       true],
        ['Information Ratio', 'ir',       'ratio',       true],
    ];

    function buildSection(ids, marketType) {
        if (ids.length === 0) return '';

        const isOverseas = marketType === 'overseas';
        const fmtVal  = isOverseas ? formatCurrency : formatKRW;
        const sectionTitle = isOverseas
            ? '<i class="fas fa-globe me-2"></i>해외 계좌 비교 <span class="badge bg-secondary ms-1 fw-normal">USD</span>'
            : '<i class="fas fa-flag me-2"></i>국내 계좌 비교 <span class="badge bg-primary ms-1 fw-normal">KRW</span>';

        function fmt(value, format) {
            if (format === 'currency')    return fmtVal(value);
            if (format === 'percent')     return formatPercent(value);
            if (format === 'percent_abs') return (value ?? 0).toFixed(2) + '%';
            return (value ?? 0).toFixed(2);
        }

        function findBestWorst(metricKey, higherIsBetter) {
            if (higherIsBetter === null) return { best: -1, worst: -1 };
            const values = ids.map(id => {
                if (metricKey === 'finalValue') {
                    const s = accountsData.get(id).summary;
                    return s[s.length - 1]?.total_value || 0;
                }
                return accountMetrics[id].portfolio[metricKey];
            });
            let bestIdx = 0, worstIdx = 0;
            for (let i = 1; i < values.length; i++) {
                if (values[i] > values[bestIdx]) bestIdx = i;
                if (values[i] < values[worstIdx]) worstIdx = i;
            }
            if (values[bestIdx] === values[worstIdx]) return { best: -1, worst: -1 };
            return { best: bestIdx, worst: worstIdx };
        }

        const headerCols = ids.map(id =>
            `<th class="text-end pe-3">${colorDot(id)}${id}</th>`
        ).join('');

        let rows = '';
        for (const [label, key, format, higherIsBetter] of metricDefs) {
            const { best, worst } = findBestWorst(key, higherIsBetter);
            let cells = '';
            ids.forEach((id, idx) => {
                let value;
                if (key === 'finalValue') {
                    const s = accountsData.get(id).summary;
                    value = s[s.length - 1]?.total_value || 0;
                } else {
                    value = accountMetrics[id].portfolio[key];
                }
                let cls = '';
                if (idx === best)  cls = 'text-success fw-bold';
                else if (idx === worst) cls = 'text-danger';
                cells += `<td class="text-end pe-3 ${cls}">${fmt(value, format)}</td>`;
            });
            rows += `<tr><td class="ps-3">${label}</td>${cells}</tr>`;
        }

        // 계좌 상태 카드 (국면, 비중, 오늘 매매 여부)
        const portfolioCards = ids.map(id => {
            const data   = accountsData.get(id);
            const status = data.status;
            const pf     = status.portfolio || {};
            const regime   = status.strategy?.regime || '-';
            const exposure = ((status.strategy?.target_exposure || 0) * 100).toFixed(0);
            const color    = ACCOUNT_COLORS[id] || '#6c757d';
            const tradedBadge = hadTradeToday(data.history)
                ? '<span class="badge bg-success ms-2">매매 발생</span>'
                : '<span class="badge bg-light text-muted border ms-2">매매 없음</span>';
            return `
                <div class="col-md-6 col-lg-3">
                    <div class="card h-100 border-0 shadow-sm" style="border-top: 3px solid ${color} !important;">
                        <div class="card-body">
                            <h6 class="text-muted small">${colorDot(id)}${id}${tradedBadge}</h6>
                            <h4 class="fw-bold mb-1">${fmtVal(pf.total_value ?? 0)}</h4>
                            <div class="d-flex justify-content-between small text-muted">
                                <span>Regime: <strong>${regime}</strong></span>
                                <span>Exposure: <strong>${exposure}%</strong></span>
                            </div>
                            <div class="small text-muted mt-1">
                                Holdings: ${pf.holdings?.length || 0} | Cash: ${fmtVal(pf.cash_balance ?? 0)}
                            </div>
                            <div class="small text-muted mt-1">
                                Updated: ${status.last_updated?.slice(0, 16) || '-'}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="card border-0 shadow-sm mb-4">
                <div class="card-header bg-white py-3">
                    <h5 class="mb-0">${sectionTitle}</h5>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-hover mb-0 align-middle">
                            <thead class="table-light">
                                <tr>
                                    <th class="ps-3">Metric</th>
                                    ${headerCols}
                                </tr>
                            </thead>
                            <tbody>${rows}</tbody>
                        </table>
                    </div>
                </div>
            </div>
            <div class="row g-3 mb-4">
                ${portfolioCards}
            </div>
        `;
    }

    const lastUpdated = [...accountsData.values()]
        .map(d => d.status?.last_updated || '')
        .filter(Boolean)
        .sort().pop() || '-';

    container.innerHTML = `
        <div class="status-banner mb-4 status-banner-default">
            <div class="d-flex align-items-center justify-content-between flex-wrap">
                <div class="d-flex align-items-center">
                    <i class="fas fa-users me-2"></i>
                    <span><strong>Live Account Comparison</strong> &nbsp;|&nbsp;
                    계좌 ${accountIds.length}개 &nbsp;|&nbsp; 기준일: ${today}</span>
                </div>
                <div class="small text-muted">Last Update: ${lastUpdated}</div>
            </div>
        </div>

        ${buildSection(overseasIds, 'overseas')}
        ${buildSection(domesticIds, 'domestic')}
    `;
}

/**
 * Trades 탭 - 계좌별 거래 통계 비교 + 선택 계좌 거래 내역
 * @param {Map<string, Object>} accountsData
 */
export function renderAccountTradesTab(accountsData) {
    const container = document.getElementById('trades');
    if (!container) return;

    const accountIds = [...accountsData.keys()];

    let statRows = '';
    for (const id of accountIds) {
        const stats = computeTradeStats(accountsData.get(id).history);
        const color = ACCOUNT_COLORS[id] || '#6c757d';
        const isDomestic = ACCOUNT_MARKET_TYPES[id] === 'domestic';
        const fmtVol = isDomestic ? formatKRW : formatCurrency;
        const marketBadge = isDomestic
            ? '<span class="badge bg-primary ms-1 fw-normal">국내</span>'
            : '<span class="badge bg-secondary ms-1 fw-normal">해외</span>';
        statRows += `
            <tr>
                <td class="ps-3">
                    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;"></span>
                    ${id}${marketBadge}
                </td>
                <td class="text-end">${stats.count.toLocaleString()}</td>
                <td class="text-end">${fmtVol(stats.totalVolume)}</td>
                <td class="text-end pe-3">${fmtVol(stats.totalFees)}</td>
            </tr>
        `;
    }

    const accountOptions = accountIds.map(id => {
        const isDomestic = ACCOUNT_MARKET_TYPES[id] === 'domestic';
        return `<option value="${id}">${isDomestic ? '[국내]' : '[해외]'} ${id}</option>`;
    }).join('');

    container.innerHTML = `
        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3">
                <h5 class="mb-0"><i class="fas fa-exchange-alt me-2"></i>Trade Statistics Comparison</h5>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="table-light">
                            <tr>
                                <th class="ps-3">Account</th>
                                <th class="text-end">Total Trades</th>
                                <th class="text-end">Total Volume</th>
                                <th class="text-end pe-3">Total Fees</th>
                            </tr>
                        </thead>
                        <tbody>${statRows}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3 d-flex justify-content-between align-items-center">
                <h5 class="mb-0"><i class="fas fa-history me-2"></i>Trade History</h5>
                <div class="d-flex align-items-center gap-2">
                    <select id="account-trade-selector" class="form-select form-select-sm" style="width: auto;">
                        ${accountOptions}
                    </select>
                    <span class="badge bg-light text-dark border" id="trade-page-info"></span>
                </div>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="table-light">
                            <tr>
                                <th>Date</th>
                                <th>Reason</th>
                                <th class="text-end">Portfolio</th>
                                <th class="text-end">Amount</th>
                                <th class="text-end">Fees</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="history-table-body"></tbody>
                    </table>
                </div>
            </div>
            <div class="card-footer bg-white d-flex justify-content-center">
                <nav><ul class="pagination pagination-sm mb-0" id="trade-pagination"></ul></nav>
            </div>
        </div>
    `;

    const selector = document.getElementById('account-trade-selector');
    selector.addEventListener('change', () => {
        const id = selector.value;
        const isDomestic = ACCOUNT_MARKET_TYPES[id] === 'domestic';
        renderAccountTradeHistory(accountsData.get(id).history, 1, isDomestic);
    });

    const firstId = accountIds[0];
    const firstIsDomestic = ACCOUNT_MARKET_TYPES[firstId] === 'domestic';
    renderAccountTradeHistory(accountsData.get(firstId).history, 1, firstIsDomestic);
}

// 페이지네이션 상태
let _currentPage = 1;
const _TRADES_PER_PAGE = 10;
let _cachedHistory = [];
let _cachedIsDomestic = false;

function renderAccountTradeHistory(historyData, page, isDomestic) {
    _cachedHistory    = historyData;
    _cachedIsDomestic = isDomestic;
    if (page !== undefined) _currentPage = page;

    const tbody = document.getElementById('history-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    const fmtVal = isDomestic ? formatKRW : formatCurrency;
    const sorted = historyData.slice().reverse();
    const totalPages = Math.max(1, Math.ceil(sorted.length / _TRADES_PER_PAGE));
    if (_currentPage > totalPages) _currentPage = totalPages;

    const pageTrades = sorted.slice(
        (_currentPage - 1) * _TRADES_PER_PAGE,
        _currentPage * _TRADES_PER_PAGE
    );

    if (pageTrades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No trade history found.</td></tr>';
        _renderTradePagination(0);
        return;
    }

    pageTrades.forEach(tx => {
        const row = document.createElement('tr');
        const actionsHtml = (tx.executions || []).map(ex => `
            <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} me-1 mb-1">
                ${ex.action} ${ex.ticker} (${ex.quantity})
            </span>
        `).join('');

        let fee = tx.total_fee;
        if (fee == null) {
            fee = (tx.executions || []).reduce((s, ex) => s + (ex.fee || 0), 0);
        }

        row.innerHTML = `
            <td class="small fw-bold text-muted">${(tx.date || '').slice(0, 10)}</td>
            <td class="small">${tx.reason || '-'}</td>
            <td class="text-end small">${tx.portfolio_value != null ? fmtVal(tx.portfolio_value) : '-'}</td>
            <td class="text-end fw-bold">${fmtVal(tx.total_trade_amount || 0)}</td>
            <td class="text-end small">${fee != null ? fmtVal(fee) : '-'}</td>
            <td>${actionsHtml}</td>
        `;
        tbody.appendChild(row);
    });

    const info = document.getElementById('trade-page-info');
    if (info) info.textContent = `${sorted.length} trades total`;
    _renderTradePagination(totalPages);
}

function _renderTradePagination(totalPages) {
    const pagination = document.getElementById('trade-pagination');
    if (!pagination) return;
    if (totalPages <= 1) { pagination.innerHTML = ''; return; }

    let html = `<li class="page-item ${_currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${_currentPage - 1}">&laquo;</a></li>`;

    for (let i = 1; i <= totalPages; i++) {
        html += `<li class="page-item ${i === _currentPage ? 'active' : ''}">
            <a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
    }

    html += `<li class="page-item ${_currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${_currentPage + 1}">&raquo;</a></li>`;

    pagination.innerHTML = html;
    pagination.querySelectorAll('a[data-page]').forEach(a => {
        a.addEventListener('click', e => {
            e.preventDefault();
            const p = parseInt(a.dataset.page);
            if (p >= 1 && p <= totalPages) {
                renderAccountTradeHistory(_cachedHistory, p, _cachedIsDomestic);
            }
        });
    });
}
