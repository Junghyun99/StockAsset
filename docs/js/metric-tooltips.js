// docs/js/metric-tooltips.js
// 지표별 툴팁 콘텐츠 (설명 + 평가 기준)
// Bootstrap Tooltip의 html: true 옵션으로 렌더링됨

export const METRIC_TOOLTIPS = {

    // ── Performance 비교 테이블 ─────────────────────────────
    totalReturn: `<strong>Total Return (누적 수익률)</strong><br>
투자 시작부터 현재까지의 전체 수익률.<br>
기간 길이를 보정하지 않으므로 장기 비교엔 CAGR 사용 권장.<br><br>
✅ <strong>좋음</strong>: +50% 이상<br>
⚠️ <strong>보통</strong>: +10 ~ +50%<br>
❌ <strong>나쁨</strong>: 음수`,

    cagr: `<strong>CAGR (연평균 성장률)</strong><br>
복리로 환산한 연평균 수익률. 투자 기간 차이를<br>보정해 다른 전략과 공정하게 비교 가능.<br><br>
✅ <strong>좋음</strong>: 15% 이상<br>
⚠️ <strong>보통</strong>: 7 ~ 15%<br>
❌ <strong>나쁨</strong>: 7% 미만`,

    mdd: `<strong>Max Drawdown (최대 낙폭)</strong><br>
고점 대비 가장 크게 떨어진 손실폭. 최악의<br>시나리오에서 버텨야 할 고통의 크기.<br><br>
✅ <strong>좋음</strong>: -10% 이내<br>
⚠️ <strong>보통</strong>: -10 ~ -25%<br>
❌ <strong>나쁨</strong>: -25% 초과`,

    volatility: `<strong>Volatility (연환산 변동성)</strong><br>
일간 수익률의 표준편차를 연율화한 값.<br>높을수록 수익이 들쭉날쭉하여 심리적 부담이 큼.<br><br>
✅ <strong>좋음</strong>: 15% 미만<br>
⚠️ <strong>보통</strong>: 15 ~ 25%<br>
❌ <strong>나쁨</strong>: 25% 초과`,

    sharpe: `<strong>Sharpe Ratio (샤프 비율)</strong><br>
무위험 수익률을 초과한 수익을 변동성으로 나눈 값.<br>단위 리스크당 얼마나 벌었는지를 측정.<br><br>
✅ <strong>좋음</strong>: 1.5 이상<br>
⚠️ <strong>보통</strong>: 0.5 ~ 1.5<br>
❌ <strong>나쁨</strong>: 0.5 미만`,

    sortino: `<strong>Sortino Ratio (소르티노 비율)</strong><br>
Sharpe와 유사하나 하방 변동성(손실)만 패널티 적용.<br>상승 변동성을 좋은 것으로 간주해 더 정교한 평가.<br><br>
✅ <strong>좋음</strong>: 2.0 이상<br>
⚠️ <strong>보통</strong>: 1.0 ~ 2.0<br>
❌ <strong>나쁨</strong>: 1.0 미만`,

    calmar: `<strong>Calmar Ratio (칼마 비율)</strong><br>
CAGR ÷ |Max Drawdown|. 낙폭 대비 얼마나<br>성장했는지를 나타내는 리스크 조정 수익 지표.<br><br>
✅ <strong>좋음</strong>: 1.0 이상<br>
⚠️ <strong>보통</strong>: 0.5 ~ 1.0<br>
❌ <strong>나쁨</strong>: 0.5 미만`,

    beta: `<strong>Beta (베타)</strong><br>
시장(SPY) 대비 수익률 민감도.<br>
1 = 시장과 동일 움직임 / &lt;1 = 방어적 / &gt;1 = 공격적.<br><br>
이 전략 목표: Bear/Crash 시 Beta &lt; 1 유지`,

    alpha: `<strong>Alpha (초과 수익)</strong><br>
포트폴리오 수익률 − SPY 수익률의 차이.<br>벤치마크를 얼마나 이겼는지 보여주는 핵심 지표.<br><br>
✅ <strong>좋음</strong>: 양수 (벤치마크 초과)<br>
❌ <strong>나쁨</strong>: 음수 (벤치마크 미달)`,

    ir: `<strong>Information Ratio (정보 비율)</strong><br>
Alpha를 추적 오차(Tracking Error)로 나눈 값.<br>초과 수익의 크기뿐 아니라 일관성까지 측정.<br><br>
✅ <strong>좋음</strong>: 0.5 이상<br>
⚠️ <strong>보통</strong>: 0 ~ 0.5<br>
❌ <strong>나쁨</strong>: 음수`,

    // ── Win/Loss 카드 ────────────────────────────────────────
    winRate: `<strong>Win Rate (승률)</strong><br>
전체 월 중 수익이 발생한 월의 비율.<br>높을수록 꾸준히 수익이 나는 전략임을 의미.<br><br>
✅ <strong>좋음</strong>: 60% 이상<br>
⚠️ <strong>보통</strong>: 45 ~ 60%<br>
❌ <strong>나쁨</strong>: 45% 미만`,

    avgWin: `<strong>Avg Win (평균 이익 월)</strong><br>
수익이 발생한 달의 평균 수익률.<br>Avg Loss와 함께 기대값 계산의 핵심 요소.<br><br>
Avg Win이 클수록 리스크 대비 잠재 보상이 큼.`,

    avgLoss: `<strong>Avg Loss (평균 손실 월)</strong><br>
손실이 발생한 달의 평균 손실률.<br>Avg Win ÷ |Avg Loss| = 손익비 (Reward/Risk Ratio).<br><br>
✅ <strong>좋음</strong>: 손익비 2 이상 (Avg Win이 2배 이상)`,

    profitFactor: `<strong>Profit Factor (수익 팩터)</strong><br>
총 이익 합계 ÷ 총 손실 합계.<br>1 이하면 장기적으로 손실, 1 이상이면 이익 구조.<br><br>
✅ <strong>좋음</strong>: 2.0 이상<br>
⚠️ <strong>보통</strong>: 1.0 ~ 2.0<br>
❌ <strong>나쁨</strong>: 1.0 미만`,

    // ── 롤링 수익률 카드 ─────────────────────────────────────
    rolling1m: `<strong>1M Return (최근 1개월 수익률)</strong><br>
직전 약 21 거래일(1개월) 기준 수익률.<br>단기 모멘텀과 최근 시장 반응을 빠르게 확인.`,

    rolling3m: `<strong>3M Return (최근 3개월 수익률)</strong><br>
직전 약 63 거래일(3개월) 기준 수익률.<br>분기 단위 성과 점검에 활용.`,

    rolling6m: `<strong>6M Return (최근 6개월 수익률)</strong><br>
직전 약 126 거래일(6개월) 기준 수익률.<br>중기 추세 및 반기 성과 확인에 활용.`,

    rolling1y: `<strong>1Y Return (최근 1년 수익률)</strong><br>
직전 약 252 거래일(1년) 기준 수익률.<br>연환산 성과와 비교하여 최근 1년이 장기 평균 대비<br>좋은지/나쁜지 판단 가능.`,

    // ── Current DD / Calmar / YTD 카드 ──────────────────────
    currentDD: `<strong>Current DD (현재 드로다운)</strong><br>
직전 고점 대비 현재까지 하락한 비율과 경과 일수.<br>0%면 신고점 경신 중, 클수록 회복까지 갈 길이 멈.<br><br>
⚠️ <strong>주의</strong>: -15% 이상 지속되면 전략 점검 필요`,

    ytd: `<strong>YTD Return (연초 대비 수익률)</strong><br>
올해 1월 1일 이후 현재까지의 수익률.<br>같은 연도 내 SPY와 비교하여 상대 성과를 판단.<br><br>
✅ <strong>좋음</strong>: SPY YTD 초과<br>
❌ <strong>나쁨</strong>: SPY YTD 미달`,

    // ── Overview 탭 Risk Indicators ──────────────────────────
    vix: `<strong>VIX (변동성 지수 / 공포 지수)</strong><br>
S&amp;P500 옵션 시장에서 추출한 향후 30일<br>예상 변동성. 시장 불안 심리의 바로미터.<br><br>
✅ <strong>안정</strong>: 15 미만<br>
⚠️ <strong>경계</strong>: 15 ~ 25<br>
❌ <strong>공포</strong>: 25 이상 (이 전략은 Bear/Crash 국면 전환)`,

    spyMdd: `<strong>SPY MDD (현재 SPY 드로다운)</strong><br>
SPY(S&amp;P500 ETF)의 직전 고점 대비 현재 낙폭.<br>Bear/Crash 국면 판단의 주요 입력값.<br><br>
⚠️ <strong>경고</strong>: -10% 이하 → Bear 국면 진입 가능<br>
❌ <strong>위험</strong>: -20% 이하 → Crash 국면 가능`,

    spyVolatility: `<strong>SPY Volatility (SPY 변동성)</strong><br>
SPY 일간 수익률의 표준편차를 연율화한 값.<br>포트폴리오의 목표 익스포저(변동성 타겟팅) 계산에 사용.<br><br>
✅ <strong>낮음</strong>: 15% 미만 → 높은 익스포저 허용<br>
❌ <strong>높음</strong>: 25% 이상 → 익스포저 축소`,

    // ── 국면별 성과 분석 테이블 헤더 ────────────────────────
    regimeCumReturn: `<strong>누적 수익률</strong><br>
해당 국면 기간 동안의 포트폴리오 누적 수익률.<br>국면이 여러 번 발생했으면 모든 구간을 합산.`,

    regimeAnnReturn: `<strong>연환산 수익률</strong><br>
해당 국면의 누적 수익률을 CAGR로 환산한 값.<br>국면 지속 기간 차이를 보정해 Bull/Bear 간 비교 가능.`,

    regimeMDD: `<strong>국면 내 MDD</strong><br>
해당 국면 기간 중 발생한 최대 낙폭.<br>핵심 가설 검증: Bear/Crash 시 포트폴리오 MDD가<br>SPY MDD보다 작으면 전략 유효성 확인.`,

    regimePct: `<strong>전체 비율</strong><br>
전체 운용 기간 중 해당 국면이 차지하는 일수 비율.<br>Bull이 60% 이상이면 전반적 상승장이었음을 의미.`,
};
