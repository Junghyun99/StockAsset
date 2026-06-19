// docs/js/portfolio-cards.js
import {
    formatAmount,
    ACCOUNT_COLORS, ACCOUNT_MARKET_TYPES,
    getRegimeColorClass
} from './utils.js?v=3';

/**
 * 통화별 합산 배너 렌더링
 */
export function renderCurrencySummary(accountsData) {
    let krwTotal = 0, usdTotal = 0;
    let krwCount = 0, usdCount = 0;

    for (const [id, data] of accountsData) {
        const mt = ACCOUNT_MARKET_TYPES[id] || 'overseas';
        const val = data.status?.portfolio?.total_value ?? 0;
        if (mt === 'domestic') { krwTotal += val; krwCount++; }
        else                   { usdTotal += val; usdCount++; }
    }

    const el = document.getElementById('currency-summary');
    if (!el) return;

    const cards = [];
    if (krwCount > 0) {
        cards.push(`
            <div class="col-md-6">
                <div class="card border-0 shadow-sm h-100" style="border-left: 4px solid #0d6efd !important;">
                    <div class="card-body">
                        <div class="text-muted small mb-1">
                            <i class="fas fa-flag me-1"></i>KRW 계좌 합산 <span class="badge bg-primary ms-1">${krwCount}개</span>
                        </div>
                        <div class="fw-bold fs-4">₩${Math.round(krwTotal).toLocaleString('ko-KR')}</div>
                    </div>
                </div>
            </div>
        `);
    }
    if (usdCount > 0) {
        cards.push(`
            <div class="col-md-6">
                <div class="card border-0 shadow-sm h-100" style="border-left: 4px solid #198754 !important;">
                    <div class="card-body">
                        <div class="text-muted small mb-1">
                            <i class="fas fa-globe me-1"></i>USD 계좌 합산 <span class="badge bg-success ms-1">${usdCount}개</span>
                        </div>
                        <div class="fw-bold fs-4">$${usdTotal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
                    </div>
                </div>
            </div>
        `);
    }
    el.innerHTML = cards.join('');
}

/**
 * KRW / USD 섹션별 카드 그리드 렌더링
 */
export function renderAccountSections(accountsData) {
    const el = document.getElementById('account-sections');
    if (!el) return;

    const domesticIds = [...accountsData.keys()].filter(id => ACCOUNT_MARKET_TYPES[id] === 'domestic');
    const overseasIds = [...accountsData.keys()].filter(id => ACCOUNT_MARKET_TYPES[id] !== 'domestic');

    let html = '';
    if (domesticIds.length > 0) {
        html += buildSection('🇰🇷 KRW 계좌', domesticIds, accountsData, 'domestic');
    }
    if (overseasIds.length > 0) {
        html += buildSection('🇺🇸 USD 계좌', overseasIds, accountsData, 'overseas');
    }
    el.innerHTML = html;
}

function buildSection(title, ids, accountsData, marketType) {
    const cards = ids.map(id => buildCard(id, accountsData.get(id), marketType)).join('');
    return `
        <h6 class="text-muted fw-bold mb-3 mt-2">${title}</h6>
        <div class="row g-3 mb-4">${cards}</div>
    `;
}

function buildCard(id, data, marketType) {
    const status    = data.status || {};
    const summary   = data.summary || [];
    const portfolio = status.portfolio || {};
    const strategy  = status.strategy  || {};
    const color     = ACCOUNT_COLORS[id] || '#6c757d';

    const totalValue = portfolio.total_value ?? 0;
    const regime     = strategy.regime || '-';
    const exposure   = ((strategy.target_exposure ?? 0) * 100).toFixed(0);

    // 일간 수익률
    let dailyReturn = null;
    if (summary.length >= 2) {
        const prev = summary[summary.length - 2].total_value;
        const curr = summary[summary.length - 1].total_value;
        dailyReturn = prev > 0 ? (curr / prev - 1) * 100 : 0;
    }
    const dailyBadge = dailyReturn == null ? '' :
        `<span class="badge rounded-pill ms-2 ${dailyReturn >= 0 ? 'bg-success' : 'bg-danger'}">
            ${dailyReturn >= 0 ? '+' : ''}${dailyReturn.toFixed(2)}%
         </span>`;

    // 그룹 비율 (summary 최신값 사용)
    const latest  = summary.length > 0 ? summary[summary.length - 1] : null;
    const groupBar = latest ? buildGroupBar(latest, totalValue) : '';

    const regimeClass = getRegimeColorClass(regime);

    return `
        <div class="col-sm-6 col-lg-4 col-xl-3">
            <div class="card h-100 border-0 shadow-sm" style="border-top: 3px solid ${color} !important;">
                <div class="card-body d-flex flex-column">
                    <div class="d-flex align-items-center mb-2">
                        <span class="fw-bold">${id}</span>
                        ${dailyBadge}
                    </div>
                    <div class="fs-5 fw-bold mb-1">${formatAmount(totalValue, marketType)}</div>
                    <div class="mb-2">
                        <span class="fw-semibold ${regimeClass}">${regime.replace('_', ' ')}</span>
                        <span class="text-muted small ms-2">Exp ${exposure}%</span>
                    </div>
                    <div class="progress mb-3" style="height: 6px;">
                        <div class="progress-bar" style="width: ${exposure}%; background-color: ${color};"></div>
                    </div>
                    ${groupBar}
                    <div class="mt-auto pt-2">
                        <a href="index.html" class="btn btn-outline-secondary btn-sm w-100">
                            상세 보기 <i class="fas fa-arrow-right ms-1"></i>
                        </a>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function buildGroupBar(latest, totalValue) {
    if (!totalValue) return '';
    const a    = latest.group_a ?? 0;
    const b    = latest.group_b ?? 0;
    const c    = latest.group_c ?? 0;
    const cash = latest.cash_balance ?? 0;
    const pctA    = (a    / totalValue * 100).toFixed(1);
    const pctB    = (b    / totalValue * 100).toFixed(1);
    const pctC    = (c    / totalValue * 100).toFixed(1);
    const pctCash = (cash / totalValue * 100).toFixed(1);

    return `
        <div class="mb-1">
            <div class="d-flex" style="height: 8px; border-radius: 4px; overflow: hidden;">
                <div style="width: ${pctA}%;    background: #0d6efd;" title="A(성장) ${pctA}%"></div>
                <div style="width: ${pctB}%;    background: #198754;" title="B(안전) ${pctB}%"></div>
                <div style="width: ${pctC}%;    background: #ffc107;" title="C(현금) ${pctC}%"></div>
                <div style="width: ${pctCash}%; background: #dee2e6;" title="현금 ${pctCash}%"></div>
            </div>
            <div class="d-flex gap-2 mt-1" style="font-size: 0.7rem; color: #6c757d;">
                <span><span style="color:#0d6efd;">■</span> A ${pctA}%</span>
                <span><span style="color:#198754;">■</span> B ${pctB}%</span>
                <span><span style="color:#ffc107;">■</span> C ${pctC}%</span>
            </div>
        </div>
    `;
}
