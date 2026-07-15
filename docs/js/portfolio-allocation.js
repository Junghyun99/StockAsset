// docs/js/portfolio-allocation.js
// 통화 그룹별 비중 테이블 (계좌별 / 종목별)
import {
    formatAmount,
    getTickerAlias, getAssetGroup,
    ACCOUNT_COLORS, ACCOUNT_MARKET_TYPES,
} from './utils.js?v=20260715-3';

const CASH_KEY = '__CASH__';
const CASH_COLOR = '#dee2e6';
const FALLBACK_COLOR = '#adb5bd';

/**
 * 통화 그룹(domestic/overseas)별 비중 집계 (순수 함수)
 *
 * 통화가 다르면 금액을 합산할 수 없으므로 그룹별로 따로 계산한다.
 * - 계좌 비중 = 계좌 total_value / 그룹 총자산
 * - 종목 비중 = 종목별 합산 평가금액 / 그룹 총자산 (현금은 '현금' 행으로 포함)
 * 같은 티커가 여러 계좌에 걸쳐 있으면 합산하고, 한글명(alias)/그룹색은
 * 해당 티커를 아는 계좌의 asset_groups.json에서 병합 조회한다.
 *
 * @param {Map<string, {status:Object, groupConfig:Object|null}>} accountsData
 * @returns {Array<{marketType, total, accounts, tickers}>} total>0 그룹만
 */
export function buildAllocation(accountsData) {
    const groups = new Map(); // marketType -> { total, accounts, tickerMap }

    const groupOf = (mt) => {
        if (!groups.has(mt)) groups.set(mt, { total: 0, accounts: [], tickerMap: new Map() });
        return groups.get(mt);
    };

    // 종목 티커 항목을 얻거나 만들고, 이름/색을 최대한 해석한다.
    const upsertTicker = (g, ticker, addValue, groupConfig) => {
        let entry = g.tickerMap.get(ticker);
        if (!entry) {
            entry = { ticker, name: ticker, color: FALLBACK_COLOR, value: 0 };
            g.tickerMap.set(ticker, entry);
        }
        entry.value += addValue;
        // 아직 한글명 미해석(name === ticker)이면 이 계좌 설정으로 시도
        // (헬퍼가 유효값을 반환할 때만 덮어써 방어)
        if (entry.name === ticker) {
            const alias = getTickerAlias(ticker, groupConfig);
            if (alias) entry.name = alias;
        }
        // 아직 그룹색 미해석이면 이 계좌 설정으로 시도
        if (entry.color === FALLBACK_COLOR) {
            const group = getAssetGroup(ticker, groupConfig);
            if (group && group.color) entry.color = group.color;
        }
    };

    for (const [id, data] of accountsData) {
        const mt = ACCOUNT_MARKET_TYPES[id] || 'overseas';
        const g = groupOf(mt);
        const portfolio = data.status?.portfolio || {};
        const totalValue = portfolio.total_value ?? 0;

        g.total += totalValue;
        g.accounts.push({ id, value: totalValue });

        for (const h of portfolio.holdings || []) {
            upsertTicker(g, h.ticker, h.value ?? 0, data.groupConfig);
        }
        const cash = portfolio.cash_balance ?? 0;
        if (cash) {
            let entry = g.tickerMap.get(CASH_KEY);
            if (!entry) {
                entry = { ticker: CASH_KEY, name: '현금', color: CASH_COLOR, value: 0 };
                g.tickerMap.set(CASH_KEY, entry);
            }
            entry.value += cash;
        }
    }

    const result = [];
    for (const [marketType, g] of groups) {
        if (g.total <= 0 || g.accounts.length === 0) continue;
        const pct = (v) => (g.total > 0 ? (v / g.total) * 100 : 0);

        const accounts = g.accounts
            .map(a => ({ ...a, pct: pct(a.value), color: ACCOUNT_COLORS[a.id] || '#6c757d' }))
            .sort((a, b) => b.value - a.value);

        const tickers = [...g.tickerMap.values()]
            .map(t => ({ ...t, pct: pct(t.value) }))
            .sort((a, b) => b.value - a.value);

        result.push({ marketType, total: g.total, accounts, tickers });
    }
    // KRW(domestic) 먼저, USD(overseas) 다음
    result.sort((a, b) => (a.marketType === 'domestic' ? -1 : 1) - (b.marketType === 'domestic' ? -1 : 1));
    return result;
}

/**
 * 비중 테이블 섹션 렌더링 (계좌별 / 종목별 좌우 배치)
 * @param {Map} accountsData
 */
export function renderAllocationSections(accountsData) {
    const el = document.getElementById('allocation-sections');
    if (!el) return;

    const groups = buildAllocation(accountsData);
    if (groups.length === 0) { el.innerHTML = ''; return; }

    el.innerHTML = groups.map(g => {
        const title = g.marketType === 'domestic' ? '🇰🇷 KRW 비중' : '🇺🇸 USD 비중';
        const accountRows = g.accounts
            .map(a => buildRow(a.id, a.value, a.pct, a.color, g.marketType))
            .join('');
        const tickerRows = g.tickers
            .map(t => buildRow(t.name, t.value, t.pct, t.color, g.marketType))
            .join('');

        return `
            <div class="card border-0 shadow-sm mb-4">
                <div class="card-header bg-white py-3">
                    <h5 class="mb-0"><i class="fas fa-chart-pie me-2"></i>${title}</h5>
                </div>
                <div class="card-body">
                    <div class="row g-4">
                        <div class="col-lg-6">
                            <div class="text-muted small fw-bold mb-2">
                                <i class="fas fa-wallet me-1"></i>계좌별 비중
                            </div>
                            ${buildTable(accountRows)}
                        </div>
                        <div class="col-lg-6">
                            <div class="text-muted small fw-bold mb-2">
                                <i class="fas fa-coins me-1"></i>종목별 비중
                            </div>
                            ${buildTable(tickerRows)}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function buildTable(rowsHtml) {
    return `
        <table class="table table-sm align-middle mb-0">
            <tbody>${rowsHtml}</tbody>
        </table>
    `;
}

function buildRow(name, value, pct, color, marketType) {
    const pctStr = pct.toFixed(1);
    // 음수(미수금 등)/100 초과 값이 CSS width를 깨뜨리지 않도록 바 너비만 [0,100]으로 제한.
    // 텍스트 라벨(pctStr)은 실제 값을 그대로 표시한다.
    const widthPct = Math.max(0, Math.min(100, pct));
    return `
        <tr>
            <td style="min-width: 120px;">
                <span style="color:${color};">■</span>
                <span class="ms-1">${name}</span>
            </td>
            <td class="text-end text-nowrap text-muted small">${formatAmount(value, marketType)}</td>
            <td style="width: 38%;">
                <div class="d-flex align-items-center gap-2">
                    <div class="progress flex-grow-1" style="height: 6px;">
                        <div class="progress-bar" style="width: ${widthPct}%; background-color: ${color};"></div>
                    </div>
                    <span class="small fw-semibold text-nowrap" style="min-width: 44px; text-align: right;">${pctStr}%</span>
                </div>
            </td>
        </tr>
    `;
}
