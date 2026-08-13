# Force Dip Stage Design

## Goal

운영자가 놓친 진입 시점을 보정할 때, 국내 QLD DipBuy 전략을 임의 주문으로 우회하지 않고 다음 자동 실행부터 기존 Stage 1~3 분할매수 캠페인으로 시작할 수 있게 한다.

## Design

`python -m scripts.force_dip_stage`는 계정, Stage, 사유를 받아 해당 계정의 `strategy_state.json`에 초기 캠페인 상태를 저장한다. 초기 상태는 `level=BUY_STAGE_n`, `tranche_total=0`, `tranche_completed=0`, `tranche_amount=0`이다. 다음 실행의 `SsoDipPlanner._transition()`은 이 상태를 보고 당시 실시간 잔고와 가격으로 트랜치 금액과 횟수를 계산하므로, CLI는 수량이나 금액을 계산하지 않는다.

안전장치로 활성 매수/매도 캠페인이 있으면 명령을 거부한다. 지원 단계는 1~3이며 사유는 필수다. 저장된 상태에 강제 진입 시각과 사유를 함께 보존해 대시보드 데이터와 운영 JSON에서 자동 신호와 구별할 수 있게 한다.

## State Flow

1. CLI가 `BUY_STAGE_1`, 트랜치 미생성 상태를 저장한다.
2. 다음 봇 실행은 IDLE 원시 신호여도 저장 상태가 IDLE이 아니므로 해당 Stage의 `_new_buy_state()`를 생성한다.
3. 첫 주문이 체결된 경우에만 기존 `record_filled_tranche()`가 `0/10`을 `1/10`으로 갱신한다.
4. 이후 원시 신호가 IDLE이어도 저장된 캠페인은 목표 비중까지 계속된다.

## Scope

엔진의 매수·매도 조건과 주문 체결 흐름은 바꾸지 않는다. 상태 변경 자체는 주문·현금 이동이 아니므로 `history.json`이나 `order_events.json`에는 가짜 체결을 기록하지 않는다.
