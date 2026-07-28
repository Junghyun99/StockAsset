// docs/js/strategy-view.js
// 엔진별 전략 상태 탭 렌더링.
// accounts_meta.json의 engine_name으로 엔진 패밀리를 식별해 각기 다른 핵심 메트릭을 표시한다.
// 데이터 소스 (백엔드가 이미 매 실행마다 저장):
//   - status.json   -> strategy.decision_factors[] (최신 스냅샷, label/format/threshold 포함)
//   - summary.json  -> factors 맵 (시계열, 매일 key:value로 저장됨)
//   - strategy_state.json -> DipBuy 계열 트랜치 진행 상태 (level/completed/total 등)

import { ACCOUNT_ENGINE_NAMES, formatPercent } from './utils.js?v=20260727-1';

// 엔진 패밀리 분류 (accounts.yaml의 실사용 엔진 기준)
const ENGINE_FAMILY = {
    'DomesticQldDipBuyEngine': 'dipbuy',
    'DomesticVolManagedEngine': 'volmanaged',
    'DomesticAsset5RealEngine': 'fullexposure',
};

// DipBuy 계열 신호 단계 메타데이터 (SsoDipPlanner.BUY_STAGES와 대응)
const DIP_LEVELS = {
    'IDLE':          { label: '대기', color: 'secondary', target_ratio: 0.20 },
    'BUY_STAGE_1':   { label: '매수 1단계', color: 'info',    target_ratio: 0.40 },
    'BUY_STAGE_2':   { label: '매수 2단계', color: 'primary', target_ratio: 0.60 },
    'BUY_STAGE_3':   { label: '매수 3단계', color: 'danger',  target_ratio: 0.80 },
    'SELL':          { label: '분할 매도', color: 'warning', target_ratio: 0.20 },
};

// DipBuy 매수 신호 임계선 (sso_dip_planner.py:19-27)
const RSI_THRESHOLDS = [48, 42, 36];      // STAGE 1/2/3 진입선
const DEVIATION_THRESHOLDS = [-0.10, -0.18, -0.26]; // 200일선 괴리율 STAGE 1/2/3 진입선

// 활성 차트 인스턴스 (탭 재진입 시 파괴 후 재생성)
let _activeCharts = [];

// ============================================================
// 진입점: 엔진 식별 → 패밀리별 디스패치
// ============================================================
export function renderStrategyTab(statusData, summaryData, strategyState, accountId) {
    const contentEl = document.getElementById('strategy-tab-content');
    if (!contentEl) return;

    const engineName = ACCOUNT_ENGINE_NAMES[accountId] || statusData?.strategy?.engine_name || '알 수 없음';
    const family = ENGINE_FAMILY[engineName] || 'unknown';

    // 엔진명 배지 갱신
    const badgeEl = document.getElementById('strategy-engine-name');
    if (badgeEl) badgeEl.textContent = engineName;

    // 기존 차트 정리
    _destroyCharts();
    contentEl.innerHTML = '';

    try {
        if (family === 'dipbuy') {
            _renderDipBuyFamily(contentEl, statusData, summaryData, strategyState, engineName);
        } else if (family === 'volmanaged') {
            _renderVolManagedFamily(contentEl, statusData, summaryData, engineName);
        } else if (family === 'fullexposure') {
            _renderFullExposureFamily(contentEl, statusData, summaryData, engineName);
        } else {
            contentEl.innerHTML = `
                <div class="alert alert-info mb-0">
                    <i class="fas fa-info-circle me-2"></i>
                    이 엔진(<code>${engineName}</code>)은 전략 상세 탭을 지원하지 않습니다.
                </div>`;
        }
    } catch (err) {
        console.error('[strategy-view] 렌더링 실패:', err);
        contentEl.innerHTML = `
            <div class="alert alert-danger mb-0">
                <i class="fas fa-exclamation-triangle me-2"></i>
                전략 탭 렌더링 중 오류가 발생했습니다: ${err.message}
            </div>`;
    }
}

// ============================================================
// 패밀리 1: DipBuy (DomesticQldDipBuyEngine) — "눌림, 어느 단계?"
// 핵심: 주봉 RSI + 200일선 괴리율로 매수 단계 판정, 트랜치 분할 진행률
// ============================================================
function _renderDipBuyFamily(contentEl, statusData, summaryData, strategyState, engineName) {
    const decisionFactors = _indexFactors(statusData);
    const stateKey = 'domestic_qld_dip_buy';
    const state = strategyState?.[stateKey] || {};

    const level = state.level || decisionFactors['signal_level']?.value || 'IDLE';
    const levelMeta = DIP_LEVELS[level] || DIP_LEVELS['IDLE'];
    const trancheTotal = state.tranche_total || 0;
    const trancheCompleted = state.tranche_completed || 0;
    const trancheProgress = trancheTotal > 0 ? (trancheCompleted / trancheTotal) * 100 : 0;

    const rsi = decisionFactors['weekly_rsi']?.value;
    const deviation = decisionFactors['ma200_deviation']?.value;
    const leverRatio = decisionFactors['lever_ratio']?.value;

    // 헤더 설명
    contentEl.innerHTML = `
        <p class="text-muted mb-3">
            <i class="fas fa-info-circle me-1"></i>
            주봉 RSI + 200일선 괴리율로 눌림 단계를 판정하고, 단계별로 레버리지 ETF를 분할 매수합니다.
            깊은 눌림일수록 더 높은 목표 비중으로 진입합니다.
        </p>
        <div class="row g-3 mb-4" id="strategy-cards"></div>
        <h6 class="mb-3"><i class="fas fa-chart-line me-2"></i>전략 지표 추이</h6>
        <div class="row g-3">
            <div class="col-12"><div class="card border-0 shadow-sm"><div class="card-body p-3" style="height:320px;"><canvas id="strategy-rsi-chart"></canvas></div></div></div>
            <div class="col-12"><div class="card border-0 shadow-sm"><div class="card-body p-3" style="height:320px;"><canvas id="strategy-deviation-chart"></canvas></div></div></div>
        </div>
    `;

    // 현재 상태 카드 그리드
    const cardsEl = document.getElementById('strategy-cards');
    cardsEl.innerHTML = `
        ${_card('현재 신호 단계', `
            <span class="badge bg-${levelMeta.color} fs-6">${levelMeta.label}</span>
            <div class="small text-muted mt-2">목표 레버리지 비중 ${formatPercent(levelMeta.target_ratio)}</div>
        `)}
        ${_card('분할 매수 진행률', trancheTotal > 0 ? `
            <div class="h5 mb-1">${trancheCompleted} / ${trancheTotal} 단계</div>
            <div class="progress" style="height:8px;">
                <div class="progress-bar bg-${levelMeta.color}" style="width:${trancheProgress}%"></div>
            </div>
            <div class="small text-muted mt-1">${trancheProgress.toFixed(0)}% 완료</div>
        ` : `
            <div class="h5 text-muted mb-0">진행중인 트랜치 없음</div>
            <div class="small text-muted mt-1">신호 대기 상태</div>
        `)}
        ${_metricCard('주봉 RSI(14)', rsi, 'number', {
            valueFormatter: v => v?.toFixed(1) ?? '-',
            subtext: 'STAGE 진입선: 48 / 42 / 36',
            breached: rsi != null && rsi < 48,
        })}
        ${_metricCard('200일선 괴리율', deviation, 'percent', {
            valueFormatter: v => formatPercent(v),
            subtext: 'STAGE 진입선: -10% / -18% / -26%',
            breached: deviation != null && deviation <= -0.10,
        })}
        ${_metricCard('현재 레버리지 비중', leverRatio, 'percent', {
            valueFormatter: v => formatPercent(v),
            subtext: `목표(현재 단계): ${formatPercent(levelMeta.target_ratio)}`,
            breached: leverRatio != null && Math.abs(leverRatio - levelMeta.target_ratio) > 0.05,
        })}
    `;

    // 시계열 차트
    _renderThresholdLineChart(
        'strategy-rsi-chart',
        summaryData,
        'weekly_rsi',
        '주봉 RSI(14)',
        '#6f42c1',
        RSI_THRESHOLDS.map((t, i) => ({ value: t, label: `STAGE ${i + 1}` })),
        { yMin: 20, yMax: 80, reverseBreach: true } // RSI는 낮을수록 매수 신호
    );
    _renderThresholdLineChart(
        'strategy-deviation-chart',
        summaryData,
        'ma200_deviation',
        '200일선 괴리율',
        '#fd7e14',
        DEVIATION_THRESHOLDS.map((t, i) => ({ value: t * 100, label: `STAGE ${i + 1}` })),
        { isPercent: true, yMin: -40, yMax: 20 }
    );
}

// ============================================================
// 패밀리 2: VolManaged (DomesticVolManagedEngine) — "레버리지, 지금 얼마?"
// 핵심: 실현변동성에 반비례해 실효 레버리지 L∈[0,2] 조절
// ============================================================
function _renderVolManagedFamily(contentEl, statusData, summaryData, engineName) {
    const decisionFactors = _indexFactors(statusData);
    const realizedVol = decisionFactors['realized_vol']?.value;
    const targetVol = decisionFactors['target_vol']?.value ?? 0.22;
    const effectiveLev = decisionFactors['effective_leverage']?.value;
    const cashWeight = decisionFactors['cash_weight']?.value;

    const volExceeded = realizedVol != null && realizedVol > targetVol;

    contentEl.innerHTML = `
        <p class="text-muted mb-3">
            <i class="fas fa-info-circle me-1"></i>
            실현변동성(21일)에 반비례해 실효 레버리지를 0~2x로 조절합니다.
            고변동성 구간에서는 현금 비중을 늘려 디레버리지하고, 평온기에는 레버리지를 올립니다.
        </p>
        <div class="row g-3 mb-4" id="strategy-cards"></div>
        <h6 class="mb-3"><i class="fas fa-chart-line me-2"></i>전략 지표 추이</h6>
        <div class="row g-3">
            <div class="col-12"><div class="card border-0 shadow-sm"><div class="card-body p-3" style="height:320px;"><canvas id="strategy-leverage-chart"></canvas></div></div></div>
            <div class="col-12"><div class="card border-0 shadow-sm"><div class="card-body p-3" style="height:320px;"><canvas id="strategy-vol-chart"></canvas></div></div></div>
        </div>
    `;

    const cardsEl = document.getElementById('strategy-cards');
    cardsEl.innerHTML = `
        ${_metricCard('실효 레버리지', effectiveLev, 'number', {
            valueFormatter: v => v != null ? v.toFixed(2) + 'x' : '-',
            subtext: '범위: 0x(현금) ~ 2x(최대)',
            gauge: { value: effectiveLev ?? 0, min: 0, max: 2, markers: [{ v: 1, label: '1x' }] },
        })}
        ${_metricCard('실현변동성(21d)', realizedVol, 'percent', {
            valueFormatter: v => formatPercent(v),
            subtext: `목표 변동성 ${formatPercent(targetVol)}`,
            breached: volExceeded,
            gauge: { value: (realizedVol ?? 0) * 100, min: 0, max: 50, markers: [{ v: targetVol * 100, label: '목표' }] },
        })}
        ${_metricCard('현금 비중', cashWeight, 'percent', {
            valueFormatter: v => formatPercent(v),
            subtext: '고변동성 회피 정도',
            gauge: { value: (cashWeight ?? 0) * 100, min: 0, max: 100 },
        })}
        ${_metricCard('목표 변동성', targetVol, 'percent', {
            valueFormatter: v => formatPercent(v),
            subtext: '전략 앵커 (TARGET_VOL)',
        })}
    `;

    // 시계열 차트
    _renderThresholdLineChart(
        'strategy-leverage-chart',
        summaryData,
        'effective_leverage',
        '실효 레버리지(x)',
        '#6f42c1',
        [
            { value: 1, label: '1x 전환점' },
            { value: 2, label: '최대 레버리지' },
        ],
        { yMin: 0, yMax: 2 }
    );
    // 실현변동성 vs 목표변동성 (목표선 annotation)
    _renderVolVsTargetChart(
        'strategy-vol-chart',
        summaryData,
        realizedVol,
        targetVol
    );
}

// ============================================================
// 패밀리 3: FullExposure/Asset5 (DomesticAsset5RealEngine) — "배분, 맞게 됐나?"
// 핵심: 정적 비율(0.7:0.3) 리밸런싱 추적
// ============================================================
function _renderFullExposureFamily(contentEl, statusData, summaryData, engineName) {
    const decisionFactors = _indexFactors(statusData);
    const targetRatioA = decisionFactors['target_ratio_a']?.value ?? 0.70;
    const currentRatioA = decisionFactors['current_ratio_a']?.value;
    const groupDeviation = decisionFactors['group_deviation']?.value;
    const rebalanceThreshold = decisionFactors['rebalance_threshold']?.value ?? 0.075;
    const regime = statusData?.strategy?.regime || '-';
    const targetExposure = statusData?.strategy?.target_exposure;

    const needsRebalance = groupDeviation != null && Math.abs(groupDeviation) > rebalanceThreshold;

    contentEl.innerHTML = `
        <p class="text-muted mb-3">
            <i class="fas fa-info-circle me-1"></i>
            자산5분법 정적 비율(A그룹 ${formatPercent(targetRatioA)} : B그룹 ${formatPercent(1 - targetRatioA)})로 리밸런싱을 유지합니다.
            이격도가 임계치를 벗어나면 리밸런싱을 실행합니다.
        </p>
        <div class="row g-3 mb-4" id="strategy-cards"></div>
        <h6 class="mb-3"><i class="fas fa-chart-line me-2"></i>전략 지표 추이</h6>
        <div class="row g-3">
            <div class="col-12"><div class="card border-0 shadow-sm"><div class="card-body p-3" style="height:320px;"><canvas id="strategy-ratioa-chart"></canvas></div></div></div>
        </div>
    `;

    const cardsEl = document.getElementById('strategy-cards');
    cardsEl.innerHTML = `
        ${_metricCard('목표 A그룹 비중', targetRatioA, 'percent', {
            valueFormatter: v => formatPercent(v),
            subtext: '전략 고정 비율 (REBALANCE_RATIO_A)',
        })}
        ${_metricCard('현재 A그룹 비중', currentRatioA, 'percent', {
            valueFormatter: v => formatPercent(v),
            subtext: currentRatioA != null
                ? `목표 대비 이격: ${formatPercent(currentRatioA - targetRatioA)}`
                : '보유 자산 없음',
        })}
        ${_metricCard('그룹 이격도', groupDeviation, 'percent', {
            valueFormatter: v => formatPercent(v),
            subtext: `리밸런싱 임계치 ±${formatPercent(rebalanceThreshold)}`,
            breached: needsRebalance,
        })}
        ${_card('현재 국면', `
            <span class="badge bg-${_regimeColor(regime)} fs-6">${regime}</span>
            <div class="small text-muted mt-2">목표 익스포저 ${formatPercent(targetExposure ?? 1.0)}</div>
            ${needsRebalance ? '<div class="badge bg-warning mt-2">리밸런싱 필요</div>' : '<div class="badge bg-success mt-2">배분 양호</div>'}
        `)}
    `;

    // A그룹 비중 vs 목표 추이
    _renderRatioATrendChart('strategy-ratioa-chart', summaryData, targetRatioA, rebalanceThreshold);
}

// ============================================================
// 공통 유틸 함수
// ============================================================

/** decision_factors 배열을 key→factor 맵으로 변환 */
function _indexFactors(statusData) {
    const arr = statusData?.strategy?.decision_factors || [];
    const map = {};
    for (const f of arr) map[f.key] = f;
    return map;
}

/** 카드 래퍼 (제목 + 본문 HTML) */
function _card(title, bodyHtml) {
    return `
        <div class="col-md-6 col-lg-4">
            <div class="card border-0 shadow-sm h-100">
                <div class="card-body">
                    <div class="text-muted small mb-2">${title}</div>
                    ${bodyHtml}
                </div>
            </div>
        </div>`;
}

/** 메트릭 카드 (값 + 게이지/임계치 표시) */
function _metricCard(title, value, format, opts = {}) {
    const { valueFormatter, subtext, breached, gauge } = opts;
    const displayValue = valueFormatter ? valueFormatter(value) : _defaultFormat(value, format);
    const valueClass = breached ? 'text-danger fw-bold' : 'text-dark';

    let gaugeHtml = '';
    if (gauge) {
        const pct = Math.max(0, Math.min(100, ((gauge.value - gauge.min) / (gauge.max - gauge.min)) * 100));
        const markers = (gauge.markers || []).map(m => {
            const left = Math.max(0, Math.min(100, ((m.v - gauge.min) / (gauge.max - gauge.min)) * 100));
            return `<div style="position:absolute;left:${left}%;top:-4px;width:2px;height:16px;background:#dc3545;" title="${m.label}"></div>`;
        }).join('');
        gaugeHtml = `
            <div class="position-relative mt-2" style="height:12px;">
                <div class="progress" style="height:8px;">
                    <div class="progress-bar ${breached ? 'bg-danger' : 'bg-primary'}" style="width:${pct}%"></div>
                </div>
                ${markers}
            </div>`;
    }

    return `
        <div class="col-md-6 col-lg-4">
            <div class="card border-0 shadow-sm h-100">
                <div class="card-body">
                    <div class="text-muted small mb-2">${title}</div>
                    <div class="h4 mb-0 ${valueClass}">${displayValue}</div>
                    ${subtext ? `<div class="small text-muted mt-1">${subtext}</div>` : ''}
                    ${gaugeHtml}
                </div>
            </div>
        </div>`;
}

function _defaultFormat(value, format) {
    if (value == null || (typeof value === 'number' && isNaN(value))) return '-';
    if (format === 'percent') return formatPercent(value);
    if (format === 'number') return typeof value === 'number' ? value.toFixed(2) : String(value);
    return String(value);
}

function _regimeColor(regime) {
    const map = { 'Bull': 'success', 'Sideways': 'secondary', 'Bear_Weak': 'warning', 'Bear_Strong': 'danger', 'Crash': 'danger' };
    return map[regime] || 'secondary';
}

/** summary.json factors에서 특정 key 시계열 추출 */
function _extractFactorSeries(summaryData, key) {
    if (!Array.isArray(summaryData)) return [];
    const series = [];
    for (const r of summaryData) {
        const v = r?.factors?.[key];
        if (v != null && typeof v === 'number' && !isNaN(v)) {
            series.push({ date: r.date, value: v });
        }
    }
    return series;
}

/** 임계선 라인 차트 (단일 지표 + 수평 annotation) */
function _renderThresholdLineChart(canvasId, summaryData, factorKey, label, color, thresholds, opts = {}) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const series = _extractFactorSeries(summaryData, factorKey);
    if (series.length === 0) {
        _renderEmptyState(canvas.parentElement, '데이터가 없습니다');
        return;
    }

    const dataPoints = series.map(s => opts.isPercent ? s.value * 100 : s.value);
    const annotation = {};
    thresholds.forEach((t, i) => {
        annotation[`line${i}`] = {
            type: 'line',
            yMin: t.value,
            yMax: t.value,
            borderColor: 'rgba(220, 53, 69, 0.5)',
            borderWidth: 1,
            borderDash: [4, 4],
            label: { content: t.label, enabled: true, position: 'end', font: { size: 10 } },
        };
    });

    const chart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: series.map(s => s.date),
            datasets: [{
                label,
                data: dataPoints,
                borderColor: color,
                backgroundColor: color + '20',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.1,
                fill: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { annotation: { annotations: annotation }, legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
                y: opts.yMin != null ? { min: opts.yMin, max: opts.yMax } : {},
            },
        },
    });
    _activeCharts.push(chart);
}

/** 실현변동성 vs 목표변동성 차트 (VolManaged 전용) */
function _renderVolVsTargetChart(canvasId, summaryData, currentRealizedVol, targetVol) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const series = _extractFactorSeries(summaryData, 'realized_vol');
    if (series.length === 0) {
        _renderEmptyState(canvas.parentElement, '데이터가 없습니다');
        return;
    }

    const chart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: series.map(s => s.date),
            datasets: [
                {
                    label: '실현변동성(21d)',
                    data: series.map(s => s.value * 100),
                    borderColor: '#dc3545',
                    backgroundColor: 'rgba(220, 53, 69, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.1,
                    fill: true,
                },
                {
                    label: '목표 변동성',
                    data: series.map(() => targetVol * 100),
                    borderColor: '#198754',
                    borderWidth: 1.5,
                    borderDash: [6, 4],
                    pointRadius: 0,
                    fill: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'top' },
                tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)}%` } },
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
                y: { ticks: { callback: v => v.toFixed(0) + '%' } },
            },
        },
    });
    _activeCharts.push(chart);
}

/** A그룹 비중 추이 + 목표선/임계대 (FullExposure 전용) */
function _renderRatioATrendChart(canvasId, summaryData, targetRatioA, rebalanceThreshold) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    if (!Array.isArray(summaryData) || summaryData.length === 0) {
        _renderEmptyState(canvas.parentElement, '데이터가 없습니다');
        return;
    }

    // summary.json엔 current_ratio_a가 없으므로 group_a 비율로 역산
    const series = [];
    for (const r of summaryData) {
        const ga = r.group_a || 0;
        const gb = r.group_b || 0;
        const total = ga + gb;
        if (total > 0) series.push({ date: r.date, value: (ga / total) * 100 });
    }
    if (series.length === 0) {
        _renderEmptyState(canvas.parentElement, '데이터가 없습니다');
        return;
    }

    const targetPct = targetRatioA * 100;
    const lower = targetPct - rebalanceThreshold * 100;
    const upper = targetPct + rebalanceThreshold * 100;

    const chart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: series.map(s => s.date),
            datasets: [
                {
                    label: 'A그룹 비중',
                    data: series.map(s => s.value),
                    borderColor: '#0d6efd',
                    backgroundColor: 'rgba(13, 110, 253, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.1,
                    fill: false,
                },
                {
                    label: `목표 ${targetPct.toFixed(0)}%`,
                    data: series.map(() => targetPct),
                    borderColor: '#198754',
                    borderWidth: 1.5,
                    borderDash: [6, 4],
                    pointRadius: 0,
                    fill: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'top' },
                annotation: {
                    annotations: {
                        band: {
                            type: 'box',
                            yMin: lower,
                            yMax: upper,
                            backgroundColor: 'rgba(25, 135, 84, 0.08)',
                            borderColor: 'transparent',
                            label: { content: '리밸런싱 허용대', enabled: true, position: 'start', font: { size: 10 } },
                        },
                    },
                },
                tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%` } },
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
                y: { min: 0, max: 100, ticks: { callback: v => v.toFixed(0) + '%' } },
            },
        },
    });
    _activeCharts.push(chart);
}

function _renderEmptyState(parentEl, msg) {
    if (!parentEl) return;
    parentEl.innerHTML = `<div class="text-muted text-center py-5"><i class="fas fa-inbox d-block mb-2 fs-2"></i>${msg}</div>`;
}

function _destroyCharts() {
    _activeCharts.forEach(c => { try { c.destroy(); } catch (e) { /* noop */ } });
    _activeCharts = [];
}
