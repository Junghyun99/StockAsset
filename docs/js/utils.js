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
 * 금액 포맷팅
 */
export function formatCurrency(value) {
    return '$' + value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * 퍼센트 포맷팅 (부호 포함)
 */
export function formatPercent(value) {
    const sign = value >= 0 ? '+' : '';
    return sign + value.toFixed(2) + '%';
}
