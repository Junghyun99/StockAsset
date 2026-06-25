// docs/js/portfolio-charts.js
import { ACCOUNT_COLORS, filterByDateRange } from './utils.js?v=20260624-3';

let comparisonChart = null;

/**
 * 누적 수익률(%) 비교 라인 차트 렌더링
 */
export function renderComparisonChart(accountsData, range = 'ALL') {
    const canvas = document.getElementById('portfolioComparisonChart');
    if (!canvas) return;

    if (comparisonChart) {
        comparisonChart.destroy();
        comparisonChart = null;
    }

    const datasets = [];
    const allDates = new Set();

    for (const [id, data] of accountsData) {
        const filtered = filterByDateRange(data.summary || [], range);
        if (filtered.length < 2) continue;

        filtered.forEach(d => allDates.add(d.date));

        const base = filtered[0].total_value;
        const returns = filtered.map(d => ({
            x: d.date,
            y: base > 0 ? ((d.total_value / base) - 1) * 100 : 0,
        }));

        datasets.push({
            label: id,
            data: returns,
            borderColor: ACCOUNT_COLORS[id] || '#6c757d',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.1,
        });
    }

    const sortedDates = [...allDates].sort();

    comparisonChart = new Chart(canvas, {
        type: 'line',
        data: { labels: sortedDates, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top' },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y >= 0 ? '+' : ''}${ctx.parsed.y.toFixed(2)}%`,
                    },
                },
            },
            scales: {
                x: {
                    ticks: {
                        maxTicksLimit: 8,
                        callback: (_, i, arr) => {
                            const step = Math.max(1, Math.floor(arr.length / 8));
                            return i % step === 0 ? sortedDates[i] : '';
                        },
                    },
                },
                y: {
                    ticks: {
                        callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%',
                    },
                },
            },
        },
    });
}

/**
 * 기간 선택 시 차트 재렌더링
 */
export function updateChartRange(accountsData, range) {
    renderComparisonChart(accountsData, range);
}
