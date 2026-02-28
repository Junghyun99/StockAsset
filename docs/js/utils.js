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
