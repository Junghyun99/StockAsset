import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function loadUtils() {
    const source = await readFile(new URL('../../docs/js/utils.js', import.meta.url), 'utf8');
    return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
}

async function loadCharts() {
    const utilsSource = await readFile(new URL('../../docs/js/utils.js', import.meta.url), 'utf8');
    const utilsUrl = `data:text/javascript;base64,${Buffer.from(utilsSource).toString('base64')}`;
    const chartsSource = await readFile(new URL('../../docs/js/charts.js', import.meta.url), 'utf8');
    const source = chartsSource.replace(/from '\.\/utils\.js\?v=[^']+';/, `from '${utilsUrl}';`);
    return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
}

test('returns Other for an ungrouped ticker when aliases metadata exists', async () => {
    const { getAssetGroup } = await loadUtils();
    const group = getAssetGroup('494310.KS', {
        A: { tickers: ['418660.KS'], label: 'Growth', color: '#0d6efd' },
        aliases: { '418660.KS': 'TIGER Nasdaq 100' },
    });

    assert.deepEqual(group, { group: '?', label: 'Other', color: '#adb5bd' });
});

test('excludes aliases metadata from group bar datasets', async () => {
    let chartConfig;
    globalThis.Chart = class {
        constructor(_canvas, config) {
            chartConfig = config;
        }
    };
    globalThis.document = { getElementById: () => ({}) };

    const { renderGroupBarChart } = await loadCharts();
    renderGroupBarChart({
        portfolio: {
            holdings: [{ ticker: '418660.KS', value: 100 }],
            cash_balance: 50,
            total_value: 150,
        },
    }, {
        A: { tickers: ['418660.KS'], label: 'Growth', color: '#0d6efd' },
        B: { tickers: [], label: 'Safety', color: '#198754' },
        C: { tickers: [], label: 'Cash', color: '#ffc107' },
        aliases: { '418660.KS': 'TIGER Nasdaq 100' },
    });

    assert.deepEqual(chartConfig.data.datasets.map(dataset => dataset.label), [
        'A: Growth ($100.00)',
        'B: Safety ($0.00)',
        'C: Cash ($50.00)',
    ]);
});
