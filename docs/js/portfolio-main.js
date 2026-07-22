// docs/js/portfolio-main.js
import { loadAccountsMeta } from './utils.js?v=20260722-2';
import { renderCurrencySummary, renderAccountSections } from './portfolio-cards.js?v=20260722-2';
import { renderAllocationSections } from './portfolio-allocation.js?v=20260722-2';
import { renderComparisonChart, updateChartRange } from './portfolio-charts.js?v=20260722-2';

document.addEventListener('DOMContentLoaded', async () => {
    const base = 'data/';
    const bust = `v=${Date.now()}`;

    try {
        await loadAccountsMeta(base);

        const accountsRes = await fetch(`${base}accounts.json?${bust}`);
        if (!accountsRes.ok) throw new Error('accounts.json not found');
        const accountIds = await accountsRes.json();

        // 각 계좌 병렬 로드
        const accountsData = new Map();
        await Promise.all(accountIds.map(async (id) => {
            const path = `${base}${id}/`;
            const [statusRes, summaryRes, groupRes] = await Promise.all([
                fetch(`${path}status.json?${bust}`),
                fetch(`${path}summary.json?${bust}`),
                fetch(`${path}asset_groups.json?${bust}`),
            ]);
            accountsData.set(id, {
                status:      statusRes.ok  ? await statusRes.json()  : {},
                summary:     summaryRes.ok ? await summaryRes.json() : [],
                groupConfig: groupRes.ok   ? await groupRes.json()   : null,
            });
        }));

        // 렌더링
        renderCurrencySummary(accountsData);
        renderAllocationSections(accountsData);
        renderAccountSections(accountsData);
        renderComparisonChart(accountsData);
        setupRangeSelector(accountsData);

        // 마지막 업데이트 시간 (첫 번째 계좌 기준)
        const first = accountsData.values().next().value;
        document.getElementById('last-updated').textContent =
            `Last Update: ${first?.status?.last_updated || 'Unknown'}`;

    } catch (err) {
        console.error('Portfolio load error:', err);
        document.getElementById('account-sections').innerHTML =
            `<div class="alert alert-warning">데이터 로드 실패: ${err.message}</div>`;
    }
});

function setupRangeSelector(accountsData) {
    const selector = document.getElementById('chart-range-selector');
    if (!selector) return;
    selector.querySelectorAll('button[data-range]').forEach(btn => {
        btn.addEventListener('click', () => {
            selector.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateChartRange(accountsData, btn.dataset.range);
        });
    });
}
