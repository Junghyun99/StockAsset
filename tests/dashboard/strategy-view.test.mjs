import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

/**
 * strategy-view.js 회귀 테스트.
 *
 * 재현하는 버그:
 *  1. main.js와 strategy-view.js가 utils.js를 서로 다른 ?v=로 import해 ESM 모듈이
 *     중복 인스턴스화됐고, loadAccountsMeta()가 채운 ACCOUNT_ENGINE_NAMES를
 *     strategy-view.js가 볼 수 없어 모든 계좌가 "지원하지 않습니다"로 렌더링됨.
 *  2. formatPercent()는 이미 100을 곱한 값을 받는 규약인데 비율(0.70)을 그대로 넘겨
 *     "+0.70%"처럼 100배 틀린 값이 표시됨.
 */

async function loadModules() {
    const utilsSource = await readFile(new URL('../../docs/js/utils.js', import.meta.url), 'utf8');
    const utilsUrl = `data:text/javascript;base64,${Buffer.from(utilsSource).toString('base64')}`;
    const utils = await import(utilsUrl);

    const viewSource = await readFile(new URL('../../docs/js/strategy-view.js', import.meta.url), 'utf8');
    // 프로덕션에서 main.js와 동일 인스턴스를 공유하는 상황을 재현
    const transformed = viewSource.replace(/from '\.\/utils\.js\?v=[^']+';/, `from '${utilsUrl}';`);
    const view = await import(`data:text/javascript;base64,${Buffer.from(transformed).toString('base64')}`);

    return { utils, view };
}

/** getElementById만 지원하는 최소 DOM 스텁 (canvas는 null -> 차트 렌더링 스킵) */
function stubDom() {
    const elements = new Map();
    for (const id of ['strategy-tab-content', 'strategy-engine-name', 'strategy-cards']) {
        elements.set(id, { innerHTML: '', textContent: '', parentElement: null });
    }
    globalThis.document = { getElementById: (id) => elements.get(id) ?? null };
    globalThis.Chart = class { destroy() {} };
    return elements;
}

const ACCOUNTS_META = {
    my_test: { market_type: 'domestic', engine_name: 'DomesticQldDipBuyEngine' },
    my_isa: { market_type: 'domestic', engine_name: 'DomesticVolManagedEngine' },
    my_pension: { market_type: 'domestic', engine_name: 'DomesticAsset5RealEngine' },
};

async function setup() {
    const { utils, view } = await loadModules();
    globalThis.fetch = async () => ({ ok: true, json: async () => ACCOUNTS_META });
    await utils.loadAccountsMeta('data/');
    return { utils, view, elements: stubDom() };
}

function status(factors, extra = {}) {
    return { strategy: { regime: 'Bull', target_exposure: 1.0, decision_factors: factors, ...extra } };
}

test('DipBuy 계좌가 전략 상세를 렌더링한다 (unknown 폴백이 아님)', async () => {
    const { view, elements } = await setup();
    view.renderStrategyTab(status([
        { key: 'weekly_rsi', value: 42.0, format: 'number' },
        { key: 'ma200_deviation', value: -0.034, format: 'percent' },
        { key: 'signal_level', value: 'IDLE', format: 'text' },
        { key: 'lever_ratio', value: 0.1917, format: 'percent' },
    ]), [], { domestic_qld_dip_buy: { level: 'IDLE', tranche_total: 0, tranche_completed: 0 } }, 'my_test');

    assert.equal(elements.get('strategy-engine-name').textContent, 'DomesticQldDipBuyEngine');
    const html = elements.get('strategy-tab-content').innerHTML;
    assert.ok(!html.includes('지원하지 않습니다'), '전략 탭이 unknown 폴백으로 떨어졌다');
    assert.ok(html.includes('주봉 RSI'));
});

test('VolManaged 계좌가 전략 상세를 렌더링한다', async () => {
    const { view, elements } = await setup();
    view.renderStrategyTab(status([
        { key: 'realized_vol', value: 0.2307, format: 'percent' },
        { key: 'target_vol', value: 0.22, format: 'percent' },
        { key: 'effective_leverage', value: 0.9537, format: 'number' },
        { key: 'cash_weight', value: 0.0463, format: 'percent' },
    ]), [], {}, 'my_isa');

    assert.equal(elements.get('strategy-engine-name').textContent, 'DomesticVolManagedEngine');
    assert.ok(elements.get('strategy-cards').innerHTML.includes('실효 레버리지'));
});

test('Asset5 계좌가 전략 상세를 렌더링한다', async () => {
    const { view, elements } = await setup();
    view.renderStrategyTab(status([
        { key: 'target_ratio_a', value: 0.7, format: 'percent' },
        { key: 'rebalance_threshold', value: 0.075, format: 'percent' },
    ]), [], {}, 'my_pension');

    assert.equal(elements.get('strategy-engine-name').textContent, 'DomesticAsset5RealEngine');
    assert.ok(elements.get('strategy-cards').innerHTML.includes('목표 A그룹 비중'));
});

test('비율 값이 100배 오차 없이 퍼센트로 표시된다', async () => {
    const { view, elements } = await setup();
    view.renderStrategyTab(status([
        { key: 'target_ratio_a', value: 0.7, format: 'percent' },
        { key: 'rebalance_threshold', value: 0.075, format: 'percent' },
    ]), [], {}, 'my_pension');

    const cards = elements.get('strategy-cards').innerHTML;
    assert.ok(cards.includes('70.0%'), `목표 A그룹 비중이 70.0%로 표시되지 않음: ${cards}`);
    assert.ok(cards.includes('7.5%'), '리밸런싱 임계치가 7.5%로 표시되지 않음');
    assert.ok(!cards.includes('+0.70%'), 'formatPercent 규약 오용으로 100배 축소된 값이 남아있다');
});

test('accounts_meta 로드 실패 시 status.json의 engine_name으로 폴백한다', async () => {
    const { view, elements } = await setup();
    view.renderStrategyTab(
        status([{ key: 'target_vol', value: 0.22, format: 'percent' }],
               { engine_name: 'DomesticVolManagedEngine' }),
        [], {}, 'unknown_account');

    assert.equal(elements.get('strategy-engine-name').textContent, 'DomesticVolManagedEngine');
    assert.ok(!elements.get('strategy-tab-content').innerHTML.includes('지원하지 않습니다'));
});

test('미지원 엔진은 안내 문구를 표시한다', async () => {
    const { view, elements } = await setup();
    view.renderStrategyTab(status([], { engine_name: 'SomeOtherEngine' }), [], {}, 'x');

    assert.ok(elements.get('strategy-tab-content').innerHTML.includes('지원하지 않습니다'));
});

test('formatRatio는 비율을 퍼센트로 변환하고 formatPercent 규약은 유지된다', async () => {
    const { utils } = await setup();
    assert.equal(utils.formatRatio(0.7), '70.0%');
    assert.equal(utils.formatRatio(-0.034), '-3.4%');
    assert.equal(utils.formatRatio(0.05, 1, true), '+5.0%');
    assert.equal(utils.formatRatio(null), '-');
    assert.equal(utils.formatRatio(NaN), '-');
    // 기존 호출부(ui.js 등)가 의존하는 "이미 x100된 값" 규약은 그대로다
    assert.equal(utils.formatPercent(12.34), '+12.34%');
});
