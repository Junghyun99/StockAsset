import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function loadUtils() {
    const source = await readFile(new URL('../../docs/js/utils.js', import.meta.url), 'utf8');
    return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
}

async function loadPortfolioCards(utilsUrl) {
    const source = await readFile(new URL('../../docs/js/portfolio-cards.js', import.meta.url), 'utf8');
    const transformed = source.replace(/from '\.\/utils\.js\?v=[^']+';/, `from '${utilsUrl}';`);
    return import(`data:text/javascript;base64,${Buffer.from(transformed).toString('base64')}`);
}

async function loadUi(utilsUrl) {
    const metricSource = await readFile(new URL('../../docs/js/metric-tooltips.js', import.meta.url), 'utf8');
    const metricUrl = `data:text/javascript;base64,${Buffer.from(metricSource).toString('base64')}`;
    const source = await readFile(new URL('../../docs/js/ui.js', import.meta.url), 'utf8');
    const transformed = source
        .replace(/from '\.\/utils\.js\?v=[^']+';/, `from '${utilsUrl}';`)
        .replace(/from '\.\/metric-tooltips\.js\?v=[^']+';/, `from '${metricUrl}';`);
    return import(`data:text/javascript;base64,${Buffer.from(transformed).toString('base64')}`);
}

test('loads account engine names from account metadata', async () => {
    const utils = await loadUtils();
    globalThis.fetch = async () => ({
        ok: true,
        json: async () => ({
            my_test: {
                color: '#d63384',
                market_type: 'domestic',
                engine_name: 'DomesticVolManagedEngine',
                is_active: true,
            },
        }),
    });

    await utils.loadAccountsMeta('data/');

    assert.equal(utils.ACCOUNT_ENGINE_NAMES.my_test, 'DomesticVolManagedEngine');
});

test('shows the configured engine name on a portfolio account card', async () => {
    const utilsSource = await readFile(new URL('../../docs/js/utils.js', import.meta.url), 'utf8');
    const utilsUrl = `data:text/javascript;base64,${Buffer.from(utilsSource).toString('base64')}`;
    const utils = await import(utilsUrl);
    utils.ACCOUNT_ENGINE_NAMES.my_test = 'DomesticVolManagedEngine';

    const accountSections = { innerHTML: '' };
    globalThis.document = {
        getElementById: id => id === 'account-sections' ? accountSections : { innerHTML: '' },
    };

    const { renderAccountSections } = await loadPortfolioCards(utilsUrl);
    renderAccountSections(new Map([['my_test', {
        status: {
            portfolio: { total_value: 100, holdings: [] },
            strategy: { regime: 'Bull', target_exposure: 0.5 },
        },
        summary: [],
    }]]));

    assert.match(accountSections.innerHTML, /운용 엔진.*DomesticVolManagedEngine/);
});

test('shows the engine name and missing-metadata fallback in the detail banner', async () => {
    const utilsSource = await readFile(new URL('../../docs/js/utils.js', import.meta.url), 'utf8');
    const utilsUrl = `data:text/javascript;base64,${Buffer.from(utilsSource).toString('base64')}`;
    const banner = { className: '' };
    const bannerText = { innerHTML: '' };
    const bannerUpdated = { textContent: '' };
    globalThis.document = {
        getElementById: id => ({
            'status-banner': banner,
            'banner-text': bannerText,
            'banner-updated': bannerUpdated,
        })[id],
    };

    const { renderStatusBanner } = await loadUi(utilsUrl);
    const status = {
        last_updated: '2026-07-22 10:00:00',
        strategy: { regime: 'Bull', target_exposure: 0.5, trigger_reason: 'Test' },
    };

    renderStatusBanner(status, 'DomesticVolManagedEngine');
    assert.match(bannerText.innerHTML, /운용 엔진: <strong>DomesticVolManagedEngine<\/strong>/);

    renderStatusBanner(status);
    assert.match(bannerText.innerHTML, /운용 엔진: <strong>-<\/strong>/);
});

test('uses one versioned account metadata module across dashboard consumers', async () => {
    const consumers = [
        '../../docs/js/main.js',
        '../../docs/js/ui.js',
        '../../docs/js/charts.js',
        '../../docs/js/account-compare-ui.js',
        '../../docs/js/account-compare-charts.js',
        '../../docs/js/portfolio-main.js',
        '../../docs/js/portfolio-cards.js',
        '../../docs/js/portfolio-allocation.js',
        '../../docs/js/portfolio-charts.js',
    ];

    for (const path of consumers) {
        const source = await readFile(new URL(path, import.meta.url), 'utf8');
        assert.match(source, /utils\.js\?v=20260722-2/);
    }
});
