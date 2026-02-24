# Rebalancer 상세 로깅 설계

**날짜**: 2026-02-24
**대상 파일**: `src/core/logic.py`

---

## 배경

`Rebalancer.generate_signal()`은 로거를 주입받고 있으나 계산 과정에 대한 로그가 전혀 없다. 특히 "비율 유지, exposure 조정으로 주문 발생" 사유로 주문이 발생했을 때 어떤 값 차이로 인해 주문이 나왔는지 추적할 수 없다.

---

## 목표

- 현재 자산군 평가액 및 비중 로깅
- 상대 비중(ratio_A, ratio_B)과 임계치 비교 결과 로깅
- 목표 금액 계산 근거 로깅 (exposure × ratio)
- 종목별 현재가 → 목표가 → 주문 수량 계산 과정 로깅
- 최종 주문 목록 및 결정 사유 로깅

---

## 로그 출력 구조

`generate_signal` 실행 시 6개 섹션이 순서대로 출력된다.

```
[INFO] ════════════════════════════════════════
[INFO]  Rebalancer.generate_signal 시작
[INFO] ════════════════════════════════════════

[INFO] [입력] Regime=Bull | TargetExposure=0.80 | TotalValue=$10,000.00 | Cash=$2,000.00

[INFO] [포트폴리오 현황]
[INFO]   A그룹(성장): $4,200.00 (42.0%)
[INFO]   B그룹(안전): $3,800.00 (38.0%)
[INFO]   C그룹(현금): $  900.00 ( 9.0%)

[INFO] [비중 판정] ratio_A=0.525 ratio_B=0.475
[INFO]   현재 차이: 5.0% | 임계치: 15.0% → 비율 유지 (리밸런싱 불필요)

[INFO] [목표 금액]
[INFO]   A그룹: 현재 $4,200.00 → 목표 $4,000.00 (exposure 0.80 × ratio 0.50)
[INFO]   B그룹: 현재 $3,800.00 → 목표 $4,000.00 (exposure 0.80 × ratio 0.50)
[INFO]   C그룹: 현재 $  900.00 → 목표 $2,000.00 (잔여)

[INFO] [A그룹 종목별]
[INFO]   SSO: 보유 3주 $300.00 → 목표 $400.00 | diff=+$100.00 → BUY 1주 @$100.00
[INFO]   QLD: 보유 5주 $500.00 → 목표 $400.00 | diff=-$100.00 → SELL 1주 @$100.00
[INFO] [B그룹 종목별]
[INFO]   IEF: 보유 10주 $1,000.00 → 목표 $1,333.00 | diff=+$333.00 → BUY 3주 @$111.00
...

[INFO] [최종 주문] SELL 1건 + BUY 2건 (총 주문금액: $533.00 / 자산대비 5.3%)
[INFO] [결정 사유] 비율 유지, exposure 조정으로 주문 발생
[INFO] ════════════════════════════════════════
```

---

## 구현 범위

| 대상 | 변경 내용 |
|------|-----------|
| `Rebalancer.generate_signal` | 섹션 1~4, 6 로그 추가 |
| `Rebalancer._create_group_orders` | `group_name: str = ""` 파라미터 추가, 섹션 5 로그 추가 |
| `ILogger` | 변경 없음 |
| `TradeLogger` | 변경 없음 |
| `tests/` | `logger` mock으로 호출 검증 |

---

## 세부 로깅 포인트

### `generate_signal`

1. **함수 진입 구분선** — `════...════` 로 구분
2. **[입력]** — regime, target_exposure, total_value, total_cash
3. **[포트폴리오 현황]** — val_a, val_b, val_c, 전체 대비 비율
4. **[비중 판정]** — ratio_a, ratio_b, current_diff, threshold, needs_rebalance 결과
5. **[목표 금액]** — 각 그룹별 현재 금액 → 목표 금액, 계산 근거
6. **[최종 주문]** — SELL/BUY 건수, 총 주문 금액, 자산 대비 비율, reason
7. **함수 종료 구분선**

### `_create_group_orders`

- `group_name` 파라미터 추가 (기본값 `""`, 하위 호환)
- 각 ticker 루프 내에서: 보유 수량 × 가격 = 현재 평가액, 목표 금액, diff, 생성 주문 (or 주문 없음 사유)

---

## 제약 조건

- `ILogger` 인터페이스 변경 없음 (`info`, `warning`, `error`만 사용)
- `logger is None`인 경우 모든 로그 호출 무시 (기존 패턴 유지)
- 테스트 커버리지 80% 이상 유지
