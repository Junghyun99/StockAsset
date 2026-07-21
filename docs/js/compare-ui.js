// docs/js/compare-ui.js
// 멀티 엔진 비교 전용 UI 렌더링

import {
    computeAdvancedMetrics,
    computeTradeStats,
    formatCurrency,
    formatKRW,
    formatPercent,
    ENGINE_COLORS,
    ENGINE_MARKET_TYPES,
} from './utils.js?v=20260721-1';

/**
 * Overview 탭 - 엔진 비교 요약 테이블 렌더링 (해외/국내 섹션 분리)
 * @param {Map<string, Object>} enginesData - {engineName: {summary, status, history, groupConfig}}
 */
export function renderCompareOverview(enginesData) {
    const container = document.getElementById('overview');
    if (!container) return;

    const engineNames = [...enginesData.keys()];

    // 해외/국내 엔진 분리
    const overseasNames = engineNames.filter(n => ENGINE_MARKET_TYPES[n] !== 'domestic');
    const domesticNames = engineNames.filter(n => ENGINE_MARKET_TYPES[n] === 'domestic');

    // 각 엔진 metrics 계산
    const engineMetrics = {};
    for (const [name, data] of enginesData) {
        const initialCash = data.status?.initial_cash ?? null;
        engineMetrics[name] = computeAdvancedMetrics(data.summary, initialCash, ENGINE_MARKET_TYPES[name]);
    }

    // 각 엔진 최종 자산
    const engineFinalValues = {};
    for (const [name, data] of enginesData) {
        const s = data.summary;
        engineFinalValues[name] = s[s.length - 1]?.total_value || 0;
    }

    // 기간 정보 (첫 번째 해외 엔진 기준, 없으면 국내 첫 엔진)
    const firstEngineName = overseasNames[0] || domesticNames[0];
    const firstSummary = enginesData.get(firstEngineName)?.summary || [];
    const startDate = firstSummary[0]?.date || '-';
    const endDate = firstSummary[firstSummary.length - 1]?.date || '-';

    // 엔진 컬러 도트
    function colorDot(name) {
        const color = ENGINE_COLORS[name] || '#6c757d';
        return `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;"></span>`;
    }

    // 지표 정의: [label, key, format, higherIsBetter]
    const metricDefs = [
        ['Final Value', 'finalValue', 'currency', true],
        ['Total Return', 'totalReturn', 'percent', true],
        ['CAGR', 'cagr', 'percent', true],
        ['Max Drawdown', 'mdd', 'percent', false],
        ['Volatility', 'volatility', 'percent_abs', false],
        ['Sharpe', 'sharpe', 'ratio', true],
        ['Sortino', 'sortino', 'ratio', true],
        ['Calmar', 'calmar', 'ratio', true],
        ['Beta', 'beta', 'ratio', null],
        ['Information Ratio', 'ir', 'ratio', true],
    ];

    /**
     * 섹션별 비교 테이블 + 포트폴리오 카드 HTML 생성
     * @param {string[]} names - 엔진 이름 배열
     * @param {'overseas'|'domestic'} marketType
     */
    function buildSection(names, marketType) {
        if (names.length === 0) return '';

        const isOverseas = marketType === 'overseas';
        const fmtFinalValue = isOverseas ? formatCurrency : formatKRW;
        const fmtCash = isOverseas ? formatCurrency : formatKRW;
        const sectionTitle = isOverseas
            ? '<i class="fas fa-globe me-2"></i>해외 엔진 비교 <span class="badge bg-secondary ms-1 fw-normal">USD</span>'
            : '<i class="fas fa-flag me-2"></i>국내 엔진 비교 <span class="badge bg-primary ms-1 fw-normal">KRW</span>';

        function fmt(value, format) {
            if (format === 'currency') return fmtFinalValue(value);
            if (format === 'percent') return formatPercent(value);
            if (format === 'percent_abs') return value.toFixed(2) + '%';
            return value.toFixed(2);
        }

        function findBestWorst(metricKey, higherIsBetter) {
            if (higherIsBetter === null) return { best: -1, worst: -1 };
            const values = names.map(name => {
                if (metricKey === 'finalValue') return engineFinalValues[name];
                return engineMetrics[name].portfolio[metricKey];
            });
            let bestIdx = 0, worstIdx = 0;
            for (let i = 1; i < values.length; i++) {
                if (values[i] > values[bestIdx]) bestIdx = i;
                if (values[i] < values[worstIdx]) worstIdx = i;
            }
            if (values[bestIdx] === values[worstIdx]) return { best: -1, worst: -1 };
            return { best: bestIdx, worst: worstIdx };
        }

        const headerCols = names.map(name =>
            `<th class="text-end pe-3">${colorDot(name)}${name}</th>`
        ).join('');

        let rows = '';
        for (const [label, key, format, higherIsBetter] of metricDefs) {
            const { best, worst } = findBestWorst(key, higherIsBetter);
            let cells = '';
            names.forEach((name, idx) => {
                const value = key === 'finalValue'
                    ? engineFinalValues[name]
                    : engineMetrics[name].portfolio[key];
                let cls = '';
                if (idx === best) cls = 'text-success fw-bold';
                else if (idx === worst) cls = 'text-danger';
                cells += `<td class="text-end pe-3 ${cls}">${fmt(value, format)}</td>`;
            });
            rows += `<tr><td class="ps-3">${label}</td>${cells}</tr>`;
        }

        // Alpha 행 (해외 섹션의 SpyEngine 기준)
        if (isOverseas) {
            const spyEngineName = names.find(n => n === 'SpyEngine');
            if (spyEngineName) {
                const spyTotalReturn = engineMetrics[spyEngineName].portfolio.totalReturn;
                let alphaCells = '';
                names.forEach(name => {
                    const alpha = engineMetrics[name].portfolio.totalReturn - spyTotalReturn;
                    const cls = name === spyEngineName ? 'text-muted' :
                                alpha >= 0 ? 'text-success fw-bold' : 'text-danger fw-bold';
                    const label = name === spyEngineName ? '-' : formatPercent(alpha);
                    alphaCells += `<td class="text-end pe-3 ${cls}">${label}</td>`;
                });
                rows += `<tr class="table-light"><td class="ps-3 fw-bold">Alpha (vs SPY)</td>${alphaCells}</tr>`;
            }
        }

        const portfolioCards = names.map(name => {
            const data = enginesData.get(name);
            const status = data.status;
            const portfolio = status.portfolio;
            const regime = status.strategy?.regime || '-';
            const exposure = ((status.strategy?.target_exposure || 0) * 100).toFixed(0);
            const color = ENGINE_COLORS[name] || '#6c757d';
            return `
                <div class="col-md-6 col-lg-3">
                    <div class="card h-100 border-0 shadow-sm" style="border-top: 3px solid ${color} !important;">
                        <div class="card-body">
                            <h6 class="text-muted small">${colorDot(name)}${name}</h6>
                            <h4 class="fw-bold mb-1">${fmtFinalValue(portfolio.total_value)}</h4>
                            <div class="d-flex justify-content-between small text-muted">
                                <span>Regime: <strong>${regime}</strong></span>
                                <span>Exposure: <strong>${exposure}%</strong></span>
                            </div>
                            <div class="small text-muted mt-1">
                                Holdings: ${portfolio.holdings?.length || 0} | Cash: ${fmtCash(portfolio.cash_balance)}
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

    const overseasCount = overseasNames.length;
    const domesticCount = domesticNames.length;
    const bannerDetail = [
        overseasCount > 0 ? `해외 ${overseasCount}개` : '',
        domesticCount > 0 ? `국내 ${domesticCount}개` : '',
    ].filter(Boolean).join(' &nbsp;|&nbsp; ');

    container.innerHTML = `
        <!-- 백테스트 기간 배너 -->
        <div class="status-banner mb-4 status-banner-default">
            <div class="d-flex align-items-center justify-content-between flex-wrap">
                <div class="d-flex align-items-center">
                    <i class="fas fa-balance-scale me-2"></i>
                    <span><strong>Engine Comparison</strong> &nbsp;|&nbsp; ${startDate} ~ ${endDate} &nbsp;|&nbsp; ${bannerDetail}</span>
                </div>
            </div>
        </div>

        ${buildSection(overseasNames, 'overseas')}
        ${buildSection(domesticNames, 'domestic')}
    `;
}

/**
 * Trades 탭 - 엔진별 거래 통계 비교 + 선택 엔진 거래 내역
 * @param {Map<string, Object>} enginesData
 */
export function renderCompareTradesTab(enginesData) {
    const container = document.getElementById('trades');
    if (!container) return;

    const engineNames = [...enginesData.keys()];

    // 거래 통계 비교
    let statRows = '';
    for (const name of engineNames) {
        const stats = computeTradeStats(enginesData.get(name).history);
        const color = ENGINE_COLORS[name] || '#6c757d';
        const isDomestic = ENGINE_MARKET_TYPES[name] === 'domestic';
        const fmtVol = isDomestic ? formatKRW : formatCurrency;
        const marketBadge = isDomestic
            ? '<span class="badge bg-primary ms-1 fw-normal">국내</span>'
            : '<span class="badge bg-secondary ms-1 fw-normal">해외</span>';
        statRows += `
            <tr>
                <td class="ps-3">
                    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;"></span>
                    ${name}${marketBadge}
                </td>
                <td class="text-end">${stats.count.toLocaleString()}</td>
                <td class="text-end">${fmtVol(stats.totalVolume)}</td>
                <td class="text-end pe-3">${fmtVol(stats.totalFees)}</td>
            </tr>
        `;
    }

    const engineOptions = engineNames.map(name => {
        const isDomestic = ENGINE_MARKET_TYPES[name] === 'domestic';
        const label = isDomestic ? `[국내] ${name}` : `[해외] ${name}`;
        return `<option value="${name}">${label}</option>`;
    }).join('');

    container.innerHTML = `
        <!-- 거래 통계 비교 테이블 -->
        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3">
                <h5 class="mb-0"><i class="fas fa-exchange-alt me-2"></i>Trade Statistics Comparison</h5>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="table-light">
                            <tr>
                                <th class="ps-3">Engine</th>
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

        <!-- 엔진 선택 + 상세 거래 내역 -->
        <div class="card border-0 shadow-sm mb-4">
            <div class="card-header bg-white py-3 d-flex justify-content-between align-items-center">
                <h5 class="mb-0"><i class="fas fa-history me-2"></i>Trade History</h5>
                <div class="d-flex align-items-center gap-2">
                    <select id="engine-trade-selector" class="form-select form-select-sm" style="width: auto;">
                        ${engineOptions}
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
                        <tbody id="history-table-body">
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="card-footer bg-white d-flex justify-content-center">
                <nav aria-label="Trade history pagination">
                    <ul class="pagination pagination-sm mb-0" id="trade-pagination">
                    </ul>
                </nav>
            </div>
        </div>
    `;

    // 엔진 선택 이벤트
    const selector = document.getElementById('engine-trade-selector');
    selector.addEventListener('change', () => {
        renderEngineTradeHistory(enginesData.get(selector.value).history, 1);
    });

    // 초기 렌더링 (첫 번째 엔진)
    renderEngineTradeHistory(enginesData.get(engineNames[0]).history, 1);
}

// 페이지네이션 상태
let currentPage = 1;
const TRADES_PER_PAGE = 10;
let cachedHistoryData = [];

/**
 * 선택된 엔진의 거래 내역 렌더링 (페이지네이션)
 */
function renderEngineTradeHistory(historyData, page) {
    cachedHistoryData = historyData;
    if (page !== undefined) currentPage = page;

    const tbody = document.getElementById('history-table-body');
    tbody.innerHTML = '';

    const sorted = historyData.slice().reverse();
    const totalPages = Math.max(1, Math.ceil(sorted.length / TRADES_PER_PAGE));
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
        let actionsHtml = tx.executions.map(ex => `
            <span class="badge ${ex.action === 'BUY' ? 'bg-success' : 'bg-danger'} order-badge me-1 mb-1">
                ${ex.action} ${ex.ticker} (${ex.quantity})
            </span>
        `).join('');

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

    document.getElementById('trade-page-info').textContent = `${sorted.length} trades total`;
    renderPagination(totalPages);
}

function renderPagination(totalPages) {
    const pagination = document.getElementById('trade-pagination');
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = '';
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${currentPage - 1}">&laquo;</a>
    </li>`;

    for (let i = 1; i <= totalPages; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" data-page="${i}">${i}</a>
        </li>`;
    }

    html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${currentPage + 1}">&raquo;</a>
    </li>`;

    pagination.innerHTML = html;

    pagination.querySelectorAll('a[data-page]').forEach(a => {
        a.addEventListener('click', (e) => {
            e.preventDefault();
            const page = parseInt(a.dataset.page);
            if (page >= 1 && page <= totalPages) {
                renderEngineTradeHistory(cachedHistoryData, page);
            }
        });
    });
}
