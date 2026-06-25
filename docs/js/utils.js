// docs/js/utils.js
// 공용 헬퍼 함수

/**
 * 시장 국면에 따른 텍스트 색상 클래스 반환
 * @param {string} regime - 예: "Bull", "Bear_Weak", "Crash"
 * @returns {string} CSS 클래스 문자열
 */
export function getRegimeColorClass(regime) {
    regime = regime.toLowerCase();
    if (regime.includes('bull')) return 'text-success';
    if (regime.includes('bear')) return 'text-danger';
    if (regime.includes('sideways')) return 'text-warning';
    if (regime.includes('crash')) return 'text-white bg-danger px-2 rounded';
    return 'text-muted';
}

/**
 * 시장 국면에 따른 배너 CSS 클래스 반환
 */
export function getRegimeBannerClass(regime) {
    regime = regime.toLowerCase();
    if (regime.includes('bull')) return 'status-banner-bull';
    if (regime.includes('crash')) return 'status-banner-crash';
    if (regime.includes('bear')) return 'status-banner-bear';
    if (regime.includes('sideways')) return 'status-banner-sideways';
    return 'status-banner-default';
}

/**
 * summary 데이터를 기간으로 필터링
 * @param {Array} data - summary 배열
 * @param {string} range - '1M', '3M', '6M', '1Y', 'ALL'
 * @returns {Array} 필터링된 배열
 */
export function filterByDateRange(data, range) {
    if (range === 'ALL' || !data.length) return data;

    const lastDate = new Date(data[data.length - 1].date);
    let cutoff = new Date(lastDate);

    switch (range) {
        case '1M': cutoff.setMonth(cutoff.getMonth() - 1); break;
        case '3M': cutoff.setMonth(cutoff.getMonth() - 3); break;
        case '6M': cutoff.setMonth(cutoff.getMonth() - 6); break;
        case '1Y': cutoff.setFullYear(cutoff.getFullYear() - 1); break;
        default: return data;
    }

    return data.filter(d => new Date(d.date) >= cutoff);
}

/**
 * 벤치마크 기준가 시계열을 반환한다.
 *
 * 윈도우의 모든 레코드가 S&P500 벤치마크가(계좌 통화에 일치)를 가질 때만
 * 그 값을 사용하고, 하나라도 없으면(구버전/forward-only 과도기) 전체를
 * 레거시 spy_price로 폴백한다. → 통화가 섞이는 경계 스파이크를 방지한다.
 *
 * 국내 계좌는 KRW 표시 S&P500(360750)이라 포트폴리오와 환 노출이 일치하고,
 * 해외 계좌는 SPY(USD)라 기존 spy_price와 동일해 연속성이 유지된다.
 * @param {Array} data - summary 배열
 * @returns {{prices: number[], usingBenchmark: boolean}}
 */
export function benchmarkPriceSeries(data) {
    const arr = data || [];
    const usingBenchmark = arr.length > 0 &&
        arr.every(d => Number.isFinite(d?.benchmarks?.['S&P500']));
    const prices = usingBenchmark
        ? arr.map(d => d.benchmarks['S&P500'])
        : arr.map(d => d.spy_price);
    return { prices, usingBenchmark };
}

/**
 * 누적 수익률 계산
 * @param {Array} summaryData - summary 배열
 * @returns {{portfolioReturn: number, spyReturn: number, alpha: number}}
 */
export function computeReturns(summaryData) {
    if (!summaryData || summaryData.length < 2) {
        return { portfolioReturn: 0, spyReturn: 0, alpha: 0 };
    }
    const first = summaryData[0];
    const last = summaryData[summaryData.length - 1];
    const { prices } = benchmarkPriceSeries(summaryData);

    const portfolioReturn = first.total_value ? (last.total_value / first.total_value - 1) * 100 : 0;
    const spyReturn = prices[0] ? (prices[prices.length - 1] / prices[0] - 1) * 100 : 0;
    const alpha = portfolioReturn - spyReturn;

    return { portfolioReturn, spyReturn, alpha };
}

/**
 * 최대 MDD와 발생일 계산
 * @param {Array} summaryData - summary 배열
 * @returns {{maxMDD: number, maxMDDDate: string, currentMDD: number}}
 */
export function computeDrawdown(summaryData) {
    summaryData = summaryData ? summaryData.filter(d => d.total_value > 0) : [];
    if (summaryData.length === 0) {
        return { maxMDD: 0, maxMDDDate: '-', currentMDD: 0 };
    }

    let maxMDD = 0;
    let maxMDDDate = summaryData[0].date;

    summaryData.forEach(d => {
        if (d.mdd < maxMDD) {
            maxMDD = d.mdd;
            maxMDDDate = d.date;
        }
    });

    const currentMDD = summaryData[summaryData.length - 1].mdd;

    return { maxMDD, maxMDDDate, currentMDD };
}

/**
 * 거래 내역 통계 계산
 * @param {Array} historyData - history 배열
 * @returns {{count: number, totalVolume: number, totalFees: number}}
 */
export function computeTradeStats(historyData) {
    if (!historyData || historyData.length === 0) {
        return { count: 0, totalVolume: 0, totalFees: 0 };
    }

    let totalVolume = 0;
    let totalFees = 0;

    historyData.forEach(tx => {
        totalVolume += tx.total_trade_amount || 0;
        // total_fee가 있으면 사용, 없으면 executions에서 합산
        if (tx.total_fee !== undefined) {
            totalFees += tx.total_fee;
        } else if (tx.executions) {
            totalFees += tx.executions.reduce((sum, ex) => sum + (ex.fee || 0), 0);
        }
    });

    return { count: historyData.length, totalVolume, totalFees };
}

/**
 * 자산 그룹 분류 (asset_groups.json에서 로드한 설정 기반)
 * @param {string} ticker
 * @param {Object} groupConfig - asset_groups.json 내용 (group -> {tickers, label, color})
 * @returns {{group: string, label: string, color: string}}
 */
export function getAssetGroup(ticker, groupConfig) {
    if (groupConfig) {
        for (const [group, info] of Object.entries(groupConfig)) {
            if (info.tickers.includes(ticker)) {
                return { group, label: info.label, color: info.color };
            }
        }
    }
    return { group: '?', label: 'Other', color: '#adb5bd' };
}

/**
 * 무위험 수익률(연율). 현재 3개월 단기국채 금리 기준.
 * 금리는 천천히 변하므로 상수로 두고 필요 시 수동 갱신한다
 * (Sharpe/Sortino의 초과수익 분자에만 영향, 통화별로 다름).
 */
export const RISK_FREE_RATE_ANNUAL = {
    overseas: 0.038,  // 미국 3개월 T-bill
    domestic: 0.027,  // 한국 3개월 단기국채
};

/**
 * 포트폴리오 & SPY 벤치마크 고급 지표 계산
 * @param {Array} summaryData - summary 배열 (total_value, spy_price 포함)
 * @param {number|null} initialCash - 실제 초기 자본 (status.json의 initial_cash). 없으면 summary 첫 값 사용.
 * @param {string|null} marketType - 'overseas'|'domestic'. 통화별 무위험 수익률 선택용(미지정 시 Rf=0).
 * @returns {{portfolio: Object, spy: Object}} 양쪽 지표 객체
 */
export function computeAdvancedMetrics(summaryData, initialCash = null, marketType = null) {
    const empty = { totalReturn: 0, cagr: 0, mdd: 0, volatility: 0, sharpe: 0, sortino: 0, calmar: 0, beta: 1.0, ir: 0 };
    // total_value=0 레코드는 브로커 API 오류로 인한 잘못된 데이터이므로 제외
    summaryData = summaryData ? summaryData.filter(d => d.total_value > 0) : [];
    if (summaryData.length < 2) {
        return { portfolio: { ...empty }, spy: { ...empty, beta: 1.0, ir: 0 }, benchmarks: {} };
    }

    const first = summaryData[0];
    const last = summaryData[summaryData.length - 1];
    const n = summaryData.length;

    // 기간 (연 단위)
    const msPerYear = 365.25 * 24 * 60 * 60 * 1000;
    const years = Math.max((new Date(last.date) - new Date(first.date)) / msPerYear, 1 / 365);

    // 무위험 수익률 일간 환산 (3개월 단기국채 연율 → 일률). marketType 미지정 시 0.
    const rfAnnual = RISK_FREE_RATE_ANNUAL[marketType] ?? 0;
    const rfDaily = Math.pow(1 + rfAnnual, 1 / 252) - 1;

    // 벤치마크 기준가 시계열 (S&P500 우선, 구버전 폴백 spy_price)
    const { prices: benchPrices } = benchmarkPriceSeries(summaryData);

    // 일간 수익률 배열
    const portReturns = [];
    const spyReturns = [];
    for (let i = 1; i < n; i++) {
        portReturns.push(summaryData[i].total_value / summaryData[i - 1].total_value - 1);
        spyReturns.push(benchPrices[i] / benchPrices[i - 1] - 1);
    }

    function calcMetrics(values, dailyReturns, baseValue = null) {
        const firstVal = baseValue !== null ? baseValue : values[0];
        const lastVal = values[values.length - 1];
        const totalReturn = (lastVal / firstVal - 1) * 100;
        const cagr = (Math.pow(lastVal / firstVal, 1 / years) - 1) * 100;

        // MDD
        let peak = -Infinity;
        let mdd = 0;
        values.forEach(v => {
            if (v > peak) peak = v;
            const dd = (v - peak) / peak;
            if (dd < mdd) mdd = dd;
        });
        mdd = mdd * 100;

        // Volatility (연환산)
        const meanRet = dailyReturns.reduce((s, r) => s + r, 0) / dailyReturns.length;
        const variance = dailyReturns.length > 1
            ? dailyReturns.reduce((s, r) => s + Math.pow(r - meanRet, 2), 0) / (dailyReturns.length - 1)
            : 0;
        const volatility = Math.sqrt(variance) * Math.sqrt(252) * 100;

        // Sharpe Ratio (무위험 수익률 초과수익 기준)
        const std = Math.sqrt(variance);
        const excessMean = meanRet - rfDaily;
        const sharpe = std !== 0 ? (excessMean / std) * Math.sqrt(252) : 0;

        // Sortino Ratio (MAR = 무위험 수익률, 하방 편차만)
        const downsideReturns = dailyReturns.filter(r => r < rfDaily);
        const downsideVariance = downsideReturns.length > 0 && dailyReturns.length > 1
            ? downsideReturns.reduce((s, r) => s + Math.pow(r - rfDaily, 2), 0) / (dailyReturns.length - 1)
            : 0;
        const downsideStd = Math.sqrt(downsideVariance);
        const sortino = downsideStd !== 0 ? (excessMean / downsideStd) * Math.sqrt(252) : 0;

        // Calmar Ratio (CAGR / |MDD|)
        const calmar = mdd !== 0 ? (cagr / 100) / Math.abs(mdd / 100) : 0;

        return { totalReturn, cagr, mdd, volatility, sharpe, sortino, calmar };
    }

    const portValues = summaryData.map(d => d.total_value);
    const spyValues = benchPrices;

    const portMetrics = calcMetrics(portValues, portReturns, initialCash);
    const spyMetrics = calcMetrics(spyValues, spyReturns);

    // Beta = Cov(port, spy) / Var(spy)
    const meanPort = portReturns.reduce((s, r) => s + r, 0) / portReturns.length;
    const meanSpy = spyReturns.reduce((s, r) => s + r, 0) / spyReturns.length;
    let cov = 0, varSpy = 0;
    for (let i = 0; i < portReturns.length; i++) {
        cov += (portReturns[i] - meanPort) * (spyReturns[i] - meanSpy);
        varSpy += Math.pow(spyReturns[i] - meanSpy, 2);
    }
    const beta = varSpy !== 0 ? cov / varSpy : 1.0;

    portMetrics.beta = beta;
    spyMetrics.beta = 1.0;

    // Information Ratio = AnnualizedAlpha / TrackingError
    const excessReturns = portReturns.map((r, i) => r - spyReturns[i]);
    let ir = 0;
    if (excessReturns.length > 1) {
        const meanExcess = excessReturns.reduce((s, r) => s + r, 0) / excessReturns.length;
        const trackingVariance = excessReturns.reduce((s, r) => s + Math.pow(r - meanExcess, 2), 0) / (excessReturns.length - 1);
        const trackingError = Math.sqrt(trackingVariance) * Math.sqrt(252);
        ir = trackingError > 0 ? (meanExcess * 252) / trackingError : 0;
    }
    portMetrics.ir = ir;
    spyMetrics.ir = 0;

    // 각 벤치마크(존재 시)별 인덱스 지표 + 포트폴리오의 해당 지수 대비 상대지표.
    // S&P500 전용 spy_price 폴백은 적용하지 않는다(다른 지수/통화 오염 방지) —
    // 전 구간에 값이 있는 벤치마크만 컬럼으로 포함한다.
    const BENCHMARK_NAMES = ['S&P500', 'NASDAQ100', 'KOSPI200'];
    const benchmarks = {};
    for (const name of BENCHMARK_NAMES) {
        if (!summaryData.every(d => Number.isFinite(d?.benchmarks?.[name]))) continue;
        const bPrices = summaryData.map(d => d.benchmarks[name]);
        const bReturns = [];
        for (let i = 1; i < n; i++) bReturns.push(bPrices[i] / bPrices[i - 1] - 1);
        const m = calcMetrics(bPrices, bReturns);

        // 포트폴리오 vs 이 인덱스: Beta
        const meanB = bReturns.reduce((s, r) => s + r, 0) / bReturns.length;
        let covB = 0, varB = 0;
        for (let i = 0; i < portReturns.length; i++) {
            covB += (portReturns[i] - meanPort) * (bReturns[i] - meanB);
            varB += Math.pow(bReturns[i] - meanB, 2);
        }
        m.portBeta = varB !== 0 ? covB / varB : 1.0;

        // 포트폴리오 vs 이 인덱스: Information Ratio
        const exc = portReturns.map((r, i) => r - bReturns[i]);
        let portIR = 0;
        if (exc.length > 1) {
            const me = exc.reduce((s, r) => s + r, 0) / exc.length;
            const tv = exc.reduce((s, r) => s + Math.pow(r - me, 2), 0) / (exc.length - 1);
            const te = Math.sqrt(tv) * Math.sqrt(252);
            portIR = te > 0 ? (me * 252) / te : 0;
        }
        m.portIR = portIR;

        // 포트폴리오 누적 초과수익 vs 이 인덱스
        m.alpha = portMetrics.totalReturn - m.totalReturn;
        benchmarks[name] = m;
    }

    return { portfolio: portMetrics, spy: spyMetrics, benchmarks };
}

/**
 * 엔진별 고유 색상 팔레트 (런타임에 loadEngineMeta()로 채워짐)
 */
export const ENGINE_COLORS = {};

/**
 * 엔진별 시장 유형 ('overseas' | 'domestic') 런타임 맵
 */
export const ENGINE_MARKET_TYPES = {};

/**
 * engines_meta.json을 fetch하여 ENGINE_COLORS, ENGINE_MARKET_TYPES를 채운다.
 * loadCompareMode() 시작 시 반드시 먼저 호출해야 한다.
 * @param {string} basePath - engines_meta.json이 있는 경로 (예: 'data/backtest/compare/')
 */
export async function loadEngineMeta(basePath) {
    try {
        const res = await fetch(`${basePath}engines_meta.json?v=${Date.now()}`);
        if (!res.ok) return;
        const meta = await res.json();
        for (const [name, info] of Object.entries(meta)) {
            ENGINE_COLORS[name] = info.color;
            ENGINE_MARKET_TYPES[name] = info.market_type || 'overseas';
        }
    } catch (e) {
        console.warn('engines_meta.json 로드 실패 — 폴백 색상(#6c757d) 사용');
    }
}

/**
 * 계좌별 고유 색상 팔레트 (런타임에 loadAccountsMeta()로 채워짐)
 */
export const ACCOUNT_COLORS = {};

/**
 * 계좌별 시장 유형 ('overseas' | 'domestic') 런타임 맵
 */
export const ACCOUNT_MARKET_TYPES = {};

/**
 * accounts_meta.json을 fetch하여 ACCOUNT_COLORS, ACCOUNT_MARKET_TYPES를 채운다.
 * loadLiveMode() 시작 시 먼저 호출된다.
 * @param {string} basePath - accounts_meta.json이 있는 경로 (예: 'data/')
 */
export async function loadAccountsMeta(basePath) {
    try {
        const res = await fetch(`${basePath}accounts_meta.json?v=${Date.now()}`);
        if (!res.ok) return;
        const meta = await res.json();
        for (const [id, info] of Object.entries(meta)) {
            ACCOUNT_COLORS[id] = info.color;
            ACCOUNT_MARKET_TYPES[id] = info.market_type || 'overseas';
        }
    } catch (e) {
        console.warn('accounts_meta.json 로드 실패 — 폴백 색상(#6c757d) 사용');
    }
}

/**
 * 금액 포맷팅 (KRW)
 */
export function formatKRW(value) {
    if (value == null) return '-';
    return '₩' + Math.round(value).toLocaleString('ko-KR');
}

export const SPY_COLOR = '#fd7e14';

/**
 * 금액 포맷팅
 */
export function formatCurrency(value) {
    if (value == null) return '-';
    return '$' + value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * market_type에 따라 KRW 또는 USD 포맷 선택
 * @param {number} value
 * @param {'domestic'|'overseas'} marketType
 */
export function formatAmount(value, marketType) {
    return marketType === 'domestic' ? formatKRW(value) : formatCurrency(value);
}

/**
 * 퍼센트 포맷팅 (부호 포함)
 */
export function formatPercent(value) {
    if (value == null) return '-';
    const sign = value >= 0 ? '+' : '';
    return sign + value.toFixed(2) + '%';
}

// ============================================================
// 파생 계산 함수들 (대시보드 확장용, 순수 함수)
// 모두 기존 summary/status/history JSON에서 파생 가능
// ============================================================

/**
 * 일일 수익률 배열 (total_value[i] / total_value[i-1] - 1)
 * @param {Array} summaryData
 * @returns {number[]} 길이 n-1 배열
 */
export function computeDailyReturns(summaryData) {
    if (!summaryData || summaryData.length < 2) return [];
    const result = [];
    for (let i = 1; i < summaryData.length; i++) {
        const prev = summaryData[i - 1].total_value;
        const curr = summaryData[i].total_value;
        result.push(prev > 0 ? curr / prev - 1 : 0);
    }
    return result;
}

/**
 * 월별 수익률 복리 집계
 * @param {Array} summaryData
 * @returns {Array<{year:number, month:number, return:number}>}
 */
export function computeMonthlyReturns(summaryData) {
    if (!summaryData || summaryData.length < 2) return [];

    // { 'YYYY-MM': [dailyReturn, ...] }
    const bucket = {};
    for (let i = 1; i < summaryData.length; i++) {
        const prev = summaryData[i - 1].total_value;
        const curr = summaryData[i].total_value;
        const r = prev > 0 ? curr / prev - 1 : 0;
        const ym = summaryData[i].date.slice(0, 7); // YYYY-MM
        if (!bucket[ym]) bucket[ym] = [];
        bucket[ym].push(r);
    }

    return Object.keys(bucket).sort().map(ym => {
        const compounded = bucket[ym].reduce((acc, r) => acc * (1 + r), 1) - 1;
        const [y, m] = ym.split('-');
        return { year: parseInt(y, 10), month: parseInt(m, 10), return: compounded };
    });
}

/**
 * 누적 손익 (달러 금액)
 * @param {Array} summaryData
 * @param {number|null} initialCash - 없으면 summaryData[0].total_value 폴백
 * @returns {Array<{date:string, pnl:number}>}
 */
export function computeCumulativePnl(summaryData, initialCash = null) {
    if (!summaryData || summaryData.length === 0) return [];
    const base = initialCash != null ? initialCash : summaryData[0].total_value;
    return summaryData.map(d => ({ date: d.date, pnl: d.total_value - base }));
}

/**
 * SPY 대비 초과수익률(Alpha) 누적 라인
 * 각 시점의 (port_norm - spy_norm) * 100 (%). 첫날 = 0.
 * @param {Array} summaryData
 * @returns {Array<{date:string, alpha:number}>}
 */
export function computeAlphaSeries(summaryData) {
    if (!summaryData || summaryData.length === 0) return [];
    const basePort = summaryData[0].total_value;
    const { prices } = benchmarkPriceSeries(summaryData);
    const baseSpy = prices[0];
    if (!basePort || !baseSpy) return [];
    return summaryData.map((d, i) => {
        const portNorm = d.total_value / basePort;
        const spyNorm = prices[i] / baseSpy;
        return { date: d.date, alpha: (portNorm - spyNorm) * 100 };
    });
}

/**
 * 롤링 수익률: 마지막 시점 기준 N 거래일 전 대비 수익률 (%)
 * @param {Array} summaryData
 * @param {number} days - 1M≈21, 3M≈63, 6M≈126, 1Y≈252
 * @returns {number|null}
 */
export function computeRollingReturn(summaryData, days) {
    if (!summaryData || summaryData.length < days + 1) return null;
    const last = summaryData[summaryData.length - 1].total_value;
    const past = summaryData[summaryData.length - 1 - days].total_value;
    if (!past) return null;
    return (last / past - 1) * 100;
}

/**
 * 드로다운 시계열 계산 (Underwater Chart용)
 * drawdown(t) = (total_value(t) / max(total_value[0..t]) - 1) × 100
 * @param {Array} summaryData
 * @returns {Array<{date:string, drawdown:number}>} 항상 0 이하
 */
export function computeDrawdownSeries(summaryData) {
    if (!summaryData || summaryData.length === 0) return [];
    let peak = -Infinity;
    return summaryData.map(d => {
        const val = d.total_value ?? 0;
        if (val > peak) peak = val;
        const dd = peak > 0 ? (val / peak - 1) * 100 : 0;
        return { date: d.date, drawdown: dd };
    });
}

/**
 * 현재 드로다운 진행일 및 깊이
 * 마지막 peak 이후 경과한 거래일 수와 peak 대비 현재값의 낙폭(%)
 * @param {Array} summaryData
 * @returns {{days:number, depthPct:number, peakDate:string, peakValue:number}}
 */
export function computeCurrentDrawdownDays(summaryData) {
    if (!summaryData || summaryData.length === 0) {
        return { days: 0, depthPct: 0, peakDate: '-', peakValue: 0 };
    }
    let peak = -Infinity;
    let peakIdx = 0;
    summaryData.forEach((d, i) => {
        if (d.total_value > peak) {
            peak = d.total_value;
            peakIdx = i;
        }
    });
    const last = summaryData[summaryData.length - 1];
    const days = summaryData.length - 1 - peakIdx;
    const depthPct = peak > 0 ? (last.total_value / peak - 1) * 100 : 0;
    return {
        days,
        depthPct,
        peakDate: summaryData[peakIdx].date,
        peakValue: peak
    };
}

/**
 * 국면별 체류 일수 분포
 * @param {Array} summaryData
 * @returns {Object<string, number>}
 */
export function computeRegimeDistribution(summaryData) {
    const dist = {};
    if (!summaryData) return dist;
    summaryData.forEach(d => {
        const key = d.regime || 'Unknown';
        dist[key] = (dist[key] || 0) + 1;
    });
    return dist;
}

/**
 * 현재 국면이 얼마나 유지되었는지 (마지막부터 역방향 스캔)
 * @param {Array} summaryData
 * @returns {{regime:string, days:number, startDate:string}}
 */
export function computeCurrentRegimeStreak(summaryData) {
    if (!summaryData || summaryData.length === 0) {
        return { regime: '-', days: 0, startDate: '-' };
    }
    const current = summaryData[summaryData.length - 1].regime;
    let startIdx = summaryData.length - 1;
    for (let i = summaryData.length - 1; i >= 0; i--) {
        if (summaryData[i].regime === current) {
            startIdx = i;
        } else {
            break;
        }
    }
    return {
        regime: current,
        days: summaryData.length - startIdx,
        startDate: summaryData[startIdx].date
    };
}

/**
 * 거래 사유별 분포 (정규화 후 카운트)
 * "Regime Change: Bull -> Bear (...)" 같은 긴 문자열에서 괄호/콜론 앞부분만 사용
 * @param {Array} historyData
 * @returns {Object<string, number>}
 */
export function computeTradeReasonDistribution(historyData) {
    const dist = {};
    if (!historyData) return dist;
    historyData.forEach(tx => {
        let reason = tx.reason || 'Unknown';
        // 첫 콜론/괄호 앞부분만 그룹 키로 사용
        const cutColon = reason.indexOf(':');
        const cutParen = reason.indexOf('(');
        let cut = -1;
        if (cutColon >= 0) cut = cutColon;
        if (cutParen >= 0 && (cut < 0 || cutParen < cut)) cut = cutParen;
        const key = (cut > 0 ? reason.slice(0, cut) : reason).trim();
        dist[key] = (dist[key] || 0) + 1;
    });
    return dist;
}

/**
 * 월별 거래 빈도 (YYYY-MM별 건수)
 * @param {Array} historyData
 * @returns {Array<{month:string, count:number}>}
 */
export function computeMonthlyTradeFrequency(historyData) {
    const bucket = {};
    if (!historyData) return [];
    historyData.forEach(tx => {
        const ym = (tx.date || '').slice(0, 7);
        if (!ym) return;
        bucket[ym] = (bucket[ym] || 0) + 1;
    });
    return Object.keys(bucket).sort().map(m => ({ month: m, count: bucket[m] }));
}

/**
 * 티커별 거래 기여 집계
 * @param {Array} historyData
 * @returns {Array<{ticker:string, trades:number, totalVolume:number, totalFees:number}>}
 */
export function computeTickerContribution(historyData) {
    const agg = {};
    if (!historyData) return [];
    historyData.forEach(tx => {
        (tx.executions || []).forEach(ex => {
            const t = ex.ticker;
            if (!agg[t]) agg[t] = { ticker: t, trades: 0, totalVolume: 0, totalFees: 0 };
            agg[t].trades += 1;
            agg[t].totalVolume += (ex.quantity || 0) * (ex.price || 0);
            agg[t].totalFees += ex.fee || 0;
        });
    });
    return Object.values(agg).sort((a, b) => b.totalVolume - a.totalVolume);
}

/**
 * 실패/미체결 주문 추출
 * @param {Array} historyData
 * @returns {Array<{date:string, ticker:string, action:string, quantity:number, status:string, reason:string}>}
 */
export function computeFailedExecutions(historyData) {
    const result = [];
    if (!historyData) return result;
    historyData.forEach(tx => {
        (tx.executions || []).forEach(ex => {
            if (ex.status && ex.status !== 'FILLED') {
                result.push({
                    date: (tx.date || '').split(' ')[0],
                    ticker: ex.ticker,
                    action: ex.action,
                    quantity: ex.quantity,
                    status: ex.status,
                    reason: tx.reason
                });
            }
        });
    });
    return result;
}

/**
 * 다음 리밸런싱 일자 추정 (최근 5건 거래 간격의 중앙값 기반)
 * @param {Array} historyData
 * @returns {{estimatedDate:string|null, intervalDays:number|null, confidence:string}}
 */
export function inferNextRebalanceDate(historyData, lastRebalanceDate = null) {
    if (!historyData || historyData.length < 3) {
        return { estimatedDate: null, intervalDays: null, confidence: 'insufficient' };
    }
    // 최근 5건 거래 날짜 수집 (오름차순) — 로컬 자정 기준 파싱(TZ 시프트 방지)
    const recent = historyData.slice(-6);
    const dates = recent.map(tx => _parseLocalDate((tx.date || '').split(' ')[0]));
    const intervals = [];
    for (let i = 1; i < dates.length; i++) {
        const diff = (dates[i] - dates[i - 1]) / (1000 * 60 * 60 * 24);
        if (diff > 0) intervals.push(diff);
    }
    if (intervals.length === 0) {
        return { estimatedDate: null, intervalDays: null, confidence: 'insufficient' };
    }
    // 중앙값
    intervals.sort((a, b) => a - b);
    const mid = Math.floor(intervals.length / 2);
    const medianDays = intervals.length % 2 === 0
        ? Math.round((intervals[mid - 1] + intervals[mid]) / 2)
        : Math.round(intervals[mid]);

    // 앵커 우선순위: status.last_rebalancing_date(권위) > history 마지막 거래일
    const anchor = lastRebalanceDate ? _parseLocalDate((lastRebalanceDate || '').split(' ')[0]) : null;
    const lastDate = (anchor && !isNaN(anchor.getTime())) ? anchor : dates[dates.length - 1];
    const next = new Date(lastDate);
    next.setDate(next.getDate() + medianDays);
    const yyyy = next.getFullYear();
    const mm = String(next.getMonth() + 1).padStart(2, '0');
    const dd = String(next.getDate()).padStart(2, '0');

    const ly = lastDate.getFullYear();
    const lm = String(lastDate.getMonth() + 1).padStart(2, '0');
    const ld = String(lastDate.getDate()).padStart(2, '0');

    return {
        estimatedDate: `${yyyy}-${mm}-${dd}`,
        intervalDays: medianDays,
        anchorDate: `${ly}-${lm}-${ld}`,
        anchorSource: (anchor && !isNaN(anchor.getTime())) ? 'status' : 'history',
        confidence: historyData.length >= 5 ? 'high' : 'medium'
    };
}

/**
 * 봇 실행 누락(스케줄 갭) 감지 — summary 날짜 시퀀스의 영업일 갭을 분석.
 * summary는 봇 실행 1회당 1건이 누적되므로, 연속 영업일 사이의 빈 영업일은
 * 실행 누락(또는 한국 공휴일)을 의미한다. 주말은 정상 제외한다.
 * @param {Array} summaryData - summary 배열 (date 필드 필요)
 * @returns {{totalRuns, lastRunDate, gaps, recentGap, missedTotal, consecutiveOkDays}}
 */
export function computeExecutionGaps(summaryData) {
    const empty = { totalRuns: 0, lastRunDate: null, gaps: [], recentGap: null, missedTotal: 0, consecutiveOkDays: 0 };
    if (!summaryData || summaryData.length === 0) return empty;

    const dates = summaryData.map(d => d.date).filter(Boolean);
    if (dates.length === 0) return empty;

    // 영업일 갭을 1회만 계산해 재사용(중복 파싱/연산 제거)
    const gaps = [];
    const missingDays = [];
    for (let i = 1; i < dates.length; i++) {
        const missing = _businessDaysStrictlyBetween(_parseLocalDate(dates[i - 1]), _parseLocalDate(dates[i]));
        missingDays.push(missing);
        if (missing > 0) {
            gaps.push({ from: dates[i - 1], to: dates[i], missingBusinessDays: missing });
        }
    }

    // 최근부터 역순으로 연속 정상(갭 0) 실행일수 집계
    let consecutiveOkDays = dates.length >= 1 ? 1 : 0;
    for (let i = missingDays.length - 1; i >= 0; i--) {
        if (missingDays[i] === 0) consecutiveOkDays++;
        else break;
    }

    return {
        totalRuns: dates.length,
        lastRunDate: dates[dates.length - 1],
        gaps,
        recentGap: gaps.length ? gaps[gaps.length - 1] : null,
        missedTotal: gaps.reduce((s, g) => s + g.missingBusinessDays, 0),
        consecutiveOkDays,
    };
}

/** "YYYY-MM-DD" → 로컬 자정 Date (TZ 흔들림 방지) */
function _parseLocalDate(s) {
    const [y, m, d] = (s || '').split('-').map(Number);
    return new Date(y || 1970, (m || 1) - 1, d || 1);
}

/** start와 end 사이(양끝 제외)의 영업일(월~금) 수 */
function _businessDaysStrictlyBetween(start, end) {
    let count = 0;
    const d = new Date(start);
    d.setDate(d.getDate() + 1);
    while (d < end) {
        const wd = d.getDay();
        if (wd !== 0 && wd !== 6) count++;
        d.setDate(d.getDate() + 1);
    }
    return count;
}

/**
 * 리밸런싱 트리거 근접도 — rebalancer.py의 상대이탈 판정 로직을 그대로 재현.
 *   ratio_a = val_a / (val_a + val_b)  (현금 그룹 C 제외, risky 기준)
 *   rel_dev = |ratio - target| / target,  트리거 = max(rel_dev_a, rel_dev_b) > threshold
 * @param {Array} summaryData - summary 배열 (group_a/group_b/target_ratio_a/rebalance_threshold 필요)
 * @returns {{available, ratioA, targetA, threshold, maxDev, proximityPct, willTrigger, date}}
 */
export function computeRebalanceProximity(summaryData) {
    if (!summaryData || summaryData.length === 0) return { available: false };
    const last = summaryData[summaryData.length - 1];
    const valA = last.group_a || 0;
    const valB = last.group_b || 0;
    const risky = valA + valB;
    const targetA = last.target_ratio_a;
    const threshold = last.rebalance_threshold;
    if (!risky || targetA == null || threshold == null || targetA <= 0) {
        return { available: false };
    }
    const targetB = 1 - targetA;
    const ratioA = valA / risky;
    const ratioB = valB / risky;
    const relDevA = Math.abs(ratioA - targetA) / targetA;
    const relDevB = targetB > 0 ? Math.abs(ratioB - targetB) / targetB : 0;
    const maxDev = Math.max(relDevA, relDevB);
    const proximityPct = threshold > 0 ? Math.min((maxDev / threshold) * 100, 100) : 0;

    return {
        available: true,
        ratioA, targetA, threshold, maxDev, proximityPct,
        willTrigger: maxDev > threshold,
        date: last.date,
    };
}

/**
 * 상태 JSON의 last_updated 신선도 라벨
 * @param {string} lastUpdatedISO - "YYYY-MM-DD HH:MM:SS"
 * @param {Date} now - 테스트용 주입 가능
 * @returns {{label:string, colorClass:string, ageHours:number}}
 */
export function getStatusFreshness(lastUpdatedISO, now = new Date()) {
    if (!lastUpdatedISO) {
        return { label: '데이터 없음', colorClass: 'bg-secondary', ageHours: Infinity };
    }
    // "YYYY-MM-DD HH:MM:SS"를 ISO로 변환
    const iso = lastUpdatedISO.includes('T') ? lastUpdatedISO : lastUpdatedISO.replace(' ', 'T');
    const ts = new Date(iso);
    if (isNaN(ts.getTime())) {
        return { label: '형식 오류', colorClass: 'bg-secondary', ageHours: Infinity };
    }
    const ageMs = now - ts;
    const ageHours = ageMs / (1000 * 60 * 60);

    let label, colorClass;
    if (ageHours < 0) {
        label = '미래 시각';
        colorClass = 'bg-warning text-dark';
    } else if (ageHours < 1) {
        label = '방금 전';
        colorClass = 'bg-success';
    } else if (ageHours < 24) {
        label = `${Math.floor(ageHours)}시간 전`;
        colorClass = 'bg-success';
    } else if (ageHours < 48) {
        label = '어제';
        colorClass = 'bg-info text-dark';
    } else if (ageHours < 24 * 7) {
        label = `${Math.floor(ageHours / 24)}일 전`;
        colorClass = 'bg-warning text-dark';
    } else {
        label = '오래됨';
        colorClass = 'bg-danger';
    }
    return { label, colorClass, ageHours };
}

/**
 * 국면별 성과 분석 (일간 복리 합산 방식)
 * @param {Array} summaryData - summary 배열 (regime, total_value 필드 필요)
 * @returns {Array<{regime, days, cumulativeReturn, annualized, mdd, periodPct}>}
 */
export function computeRegimePerformance(summaryData) {
    if (!summaryData || summaryData.length < 2) return [];

    // 분모를 수익률 일수(n-1)로 설정해야 전체 비율 합이 100%가 됨
    const totalActiveDays = summaryData.length - 1;

    // 국면별 일간 수익률만 수집 (절대 자산가 미사용 — 비연속 국면 MDD 오류 방지)
    const buckets = {};
    for (let i = 1; i < summaryData.length; i++) {
        const regime = summaryData[i].regime || 'Unknown';
        const r = summaryData[i - 1].total_value > 0
            ? summaryData[i].total_value / summaryData[i - 1].total_value - 1
            : 0;
        if (!buckets[regime]) buckets[regime] = [];
        buckets[regime].push(r);
    }

    return Object.entries(buckets).map(([regime, returns]) => {
        const days = returns.length;

        // 누적 수익률 (복리)
        const cumulativeReturn = (returns.reduce((acc, r) => acc * (1 + r), 1) - 1) * 100;

        // 연환산 수익률 (평균 일간 수익률 기준)
        const avgDaily = returns.reduce((s, r) => s + r, 0) / days;
        const annualized = (Math.pow(1 + avgDaily, 252) - 1) * 100;

        // 국면 내 MDD: 복리 누적 곡선 기준으로 계산 (비연속 국면에서도 정확)
        let peak = 1;
        let current = 1;
        let mdd = 0;
        returns.forEach(r => {
            current = current * (1 + r);
            if (current > peak) peak = current;
            const dd = (current - peak) / peak;
            if (dd < mdd) mdd = dd;
        });
        mdd = mdd * 100;

        // 전체 기간 비율 (분모: 수익률 일수 = n-1)
        const periodPct = (days / totalActiveDays) * 100;

        return { regime, days, cumulativeReturn, annualized, mdd, periodPct };
    });
}

/**
 * YTD(연초 이후) 수익률 계산
 * @param {Array} summaryData - summary 배열 (date, total_value, spy_price 필드 필요)
 * @returns {{portfolio: number|null, spy: number|null}}
 */
export function computeYTDReturn(summaryData) {
    if (!summaryData || summaryData.length === 0) return { portfolio: null, spy: null };
    // 백테스트 지원: 실제 캘린더 연도 대신 데이터셋의 마지막 날짜 기준 연도 사용
    const latestDate = summaryData[summaryData.length - 1].date;
    if (!latestDate) return { portfolio: null, spy: null };
    const dataYear = latestDate.slice(0, 4);
    const ytdData = summaryData.filter(d => d.date && d.date.startsWith(dataYear));
    if (ytdData.length < 2) return { portfolio: null, spy: null };
    const first = ytdData[0];
    const last = ytdData[ytdData.length - 1];
    const { prices } = benchmarkPriceSeries(ytdData);
    if (!first.total_value || !prices[0]) return { portfolio: null, spy: null };
    return {
        portfolio: (last.total_value / first.total_value - 1) * 100,
        spy: (prices[prices.length - 1] / prices[0] - 1) * 100,
    };
}

/**
 * groupConfig.aliases에서 티커의 한글명(alias)을 반환.
 * alias가 없으면 raw ticker를 그대로 반환.
 * @param {string} ticker
 * @param {Object|null} groupConfig - asset_groups.json 내용
 * @returns {string}
 */
export function getTickerAlias(ticker, groupConfig) {
    if (groupConfig && groupConfig.aliases && groupConfig.aliases[ticker]) {
        return groupConfig.aliases[ticker];
    }
    return ticker;
}

/**
 * 배당 수익률 요약 계산 (추정치, yfinance 배당락일 기준)
 * @param {Array} summaryData - summary 배열 (daily_dividend, total_value 필드)
 * @returns {{totalDividend: number, annualizedYield: number, ytdDividend: number}}
 */
export function computeDividendYield(summaryData) {
    if (!summaryData || summaryData.length < 2) {
        return { totalDividend: 0, annualizedYield: 0, ytdDividend: 0 };
    }

    const first = summaryData[0];
    const last = summaryData[summaryData.length - 1];

    if (!first || !last || !first.date || !last.date) {
        return { totalDividend: 0, annualizedYield: 0, ytdDividend: 0 };
    }

    const totalDividend = summaryData.reduce((s, d) => s + (d.daily_dividend || 0), 0);

    const avgValue = summaryData.reduce((s, d) => s + (d.total_value || 0), 0) / summaryData.length;

    const msPerYear = 365.25 * 24 * 60 * 60 * 1000;
    const firstDate = new Date(first.date);
    const lastDate = new Date(last.date);

    if (isNaN(firstDate.getTime()) || isNaN(lastDate.getTime())) {
        return { totalDividend, annualizedYield: 0, ytdDividend: 0 };
    }

    const years = Math.max((lastDate - firstDate) / msPerYear, 1 / 365);

    const annualizedYield = avgValue > 0 ? (totalDividend / avgValue / years) * 100 : 0;

    const dataYear = last.date.slice(0, 4);
    const ytdDividend = summaryData
        .filter(d => d.date && d.date.startsWith(dataYear))
        .reduce((s, d) => s + (d.daily_dividend || 0), 0);

    return { totalDividend, annualizedYield, ytdDividend };
}

/**
 * 승률/손익비 통계 (월 단위)
 * @param {Array} summaryData - summary 배열
 * @returns {{winRate:number, avgWin:number, avgLoss:number, profitFactor:number, totalMonths:number}}
 */
export function computeWinLossStats(summaryData) {
    const monthly = computeMonthlyReturns(summaryData);
    if (monthly.length === 0) {
        return { winRate: 0, avgWin: 0, avgLoss: 0, profitFactor: 0, totalMonths: 0 };
    }

    const wins = monthly.filter(m => m.return > 0);
    const losses = monthly.filter(m => m.return < 0);

    const grossWin = wins.reduce((s, m) => s + m.return, 0);
    const grossLoss = Math.abs(losses.reduce((s, m) => s + m.return, 0));

    return {
        winRate: (wins.length / monthly.length) * 100,
        avgWin: wins.length > 0 ? (grossWin / wins.length) * 100 : 0,
        avgLoss: losses.length > 0 ? (-grossLoss / losses.length) * 100 : 0,
        profitFactor: grossLoss > 0 ? grossWin / grossLoss : Infinity,
        totalMonths: monthly.length,
    };
}

/**
 * 연간 수익률 계산 (포트폴리오 vs SPY)
 * @param {Array} summaryData - summary 배열 (date, total_value, spy_price 필드 필요)
 * @returns {Array<{year:string, portfolioReturn:number, spyReturn:number, isYTD:boolean}>}
 */
export function computeAnnualReturns(summaryData) {
    if (!summaryData || summaryData.length < 2) return [];

    const years = {};
    summaryData.forEach(d => {
        const year = d.date.slice(0, 4);
        if (!years[year]) years[year] = [];
        years[year].push(d);
    });

    const currentYear = summaryData[summaryData.length - 1].date.slice(0, 4);

    return Object.entries(years)
        .sort(([a], [b]) => a.localeCompare(b))
        .filter(([, days]) => days.length >= 2)
        .map(([year, days]) => {
            const firstDay = days[0];
            const lastDay = days[days.length - 1];
            const { prices } = benchmarkPriceSeries(days);
            return {
                year,
                portfolioReturn: firstDay.total_value ? (lastDay.total_value / firstDay.total_value - 1) * 100 : 0,
                spyReturn: prices[0] ? (prices[prices.length - 1] / prices[0] - 1) * 100 : 0,
                isYTD: year === currentYear,
            };
        });
}
