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
 * 엔진별 고유 색상 팔레트
 */
export const ENGINE_COLORS = {
    TradingEngine: '#0d6efd',
    FullExposureEngine: '#dc3545',
    QldSHVEngine: '#198754',
    QldSchdEngine: '#6f42c1',
};

export const SPY_COLOR = '#fd7e14';

/**
 * 금액 포맷팅
 */
export function formatCurrency(value) {
    if (value == null) return '-';
    return '$' + value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * 퍼센트 포맷팅 (부호 포함)
 */
export function formatPercent(value) {
    if (value == null) return '-';
    const sign = value >= 0 ? '+' : '';
    return sign + value.toFixed(2) + '%';
}
