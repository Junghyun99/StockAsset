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

    const portfolioReturn = (last.total_value / first.total_value - 1) * 100;
    const spyReturn = (last.spy_price / first.spy_price - 1) * 100;
    const alpha = portfolioReturn - spyReturn;

    return { portfolioReturn, spyReturn, alpha };
}

/**
 * 최대 MDD와 발생일 계산
 * @param {Array} summaryData - summary 배열
 * @returns {{maxMDD: number, maxMDDDate: string, currentMDD: number}}
 */
export function computeDrawdown(summaryData) {
    if (!summaryData || summaryData.length === 0) {
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
 * 포트폴리오 & SPY 벤치마크 고급 지표 계산
 * @param {Array} summaryData - summary 배열 (total_value, spy_price 포함)
 * @param {number|null} initialCash - 실제 초기 자본 (status.json의 initial_cash). 없으면 summary 첫 값 사용.
 * @returns {{portfolio: Object, spy: Object}} 양쪽 지표 객체
 */
export function computeAdvancedMetrics(summaryData, initialCash = null) {
    const empty = { totalReturn: 0, cagr: 0, mdd: 0, volatility: 0, sharpe: 0, sortino: 0, calmar: 0, beta: 1.0 };
    if (!summaryData || summaryData.length < 2) {
        return { portfolio: { ...empty }, spy: { ...empty, beta: 1.0 } };
    }

    const first = summaryData[0];
    const last = summaryData[summaryData.length - 1];
    const n = summaryData.length;

    // 기간 (연 단위)
    const msPerYear = 365.25 * 24 * 60 * 60 * 1000;
    const years = Math.max((new Date(last.date) - new Date(first.date)) / msPerYear, 1 / 365);

    // 일간 수익률 배열
    const portReturns = [];
    const spyReturns = [];
    for (let i = 1; i < n; i++) {
        portReturns.push(summaryData[i].total_value / summaryData[i - 1].total_value - 1);
        spyReturns.push(summaryData[i].spy_price / summaryData[i - 1].spy_price - 1);
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
        const variance = dailyReturns.reduce((s, r) => s + Math.pow(r - meanRet, 2), 0) / (dailyReturns.length - 1);
        const volatility = Math.sqrt(variance) * Math.sqrt(252) * 100;

        // Sharpe Ratio (무위험 수익률 0 가정)
        const sharpe = volatility !== 0 ? (meanRet / Math.sqrt(variance)) * Math.sqrt(252) : 0;

        // Sortino Ratio (하방 변동성만)
        const downsideReturns = dailyReturns.filter(r => r < 0);
        const downsideVariance = downsideReturns.length > 0
            ? downsideReturns.reduce((s, r) => s + Math.pow(r, 2), 0) / (dailyReturns.length - 1)
            : 0;
        const downsideStd = Math.sqrt(downsideVariance);
        const sortino = downsideStd !== 0 ? (meanRet / downsideStd) * Math.sqrt(252) : 0;

        // Calmar Ratio (CAGR / |MDD|)
        const calmar = mdd !== 0 ? (cagr / 100) / Math.abs(mdd / 100) : 0;

        return { totalReturn, cagr, mdd, volatility, sharpe, sortino, calmar };
    }

    const portValues = summaryData.map(d => d.total_value);
    const spyValues = summaryData.map(d => d.spy_price);

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

    return { portfolio: portMetrics, spy: spyMetrics };
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
    const baseSpy = summaryData[0].spy_price;
    if (!basePort || !baseSpy) return [];
    return summaryData.map(d => {
        const portNorm = d.total_value / basePort;
        const spyNorm = d.spy_price / baseSpy;
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
export function inferNextRebalanceDate(historyData) {
    if (!historyData || historyData.length < 3) {
        return { estimatedDate: null, intervalDays: null, confidence: 'insufficient' };
    }
    // 최근 5건 거래 날짜 수집 (오름차순)
    const recent = historyData.slice(-6);
    const dates = recent.map(tx => new Date((tx.date || '').split(' ')[0]));
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

    const lastDate = dates[dates.length - 1];
    const next = new Date(lastDate);
    next.setDate(next.getDate() + medianDays);
    const yyyy = next.getFullYear();
    const mm = String(next.getMonth() + 1).padStart(2, '0');
    const dd = String(next.getDate()).padStart(2, '0');

    return {
        estimatedDate: `${yyyy}-${mm}-${dd}`,
        intervalDays: medianDays,
        confidence: historyData.length >= 5 ? 'high' : 'medium'
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
