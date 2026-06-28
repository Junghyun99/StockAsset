# src/core/logic/dip_buy_planner.py
"""눌림목 분할매수 플래너 (순수, 무상태).

이동평균선 눌림목·RSI 과매도 트리거로 매수 트랜치를 적재하고, RSI 과열이
'추세 위에서 꺾일 때' 매도 트랜치를 적재한다. 매 거래일 활성 트랜치의 당일
슬라이스를 합산해 주문을 생성한다.

매수 사이징은 '트리거 시점 총자산(현금+보유평가액)의 비율'을 N등분해 고정한다.
(원작의 '현금의 %'는 앞선 레벨이 현금을 소진해 더 깊은 레벨이 작게 들어가는
비대칭이 있어, 풀사이클 백테스트에서 우위였던 총자산 기준으로 채택했다.)

매도 조건(A+B):
  - A. 추세 필터: price > ma120 (상승 추세 위에서만 트림)
  - B. 모멘텀 꺾임 확인: RSI가 70 위로 갔다가 다시 70 아래로 내려온 시점
RSI는 모멘텀(과매수도) 지표일 뿐 추세 지표가 아니므로, 단독으로 쓰면 하락장
반등(데드캣 바운스)이나 횡보장 상단에서도 발동한다. 추세 필터 + 꺾임 확인으로
바닥에서 막 매수한 물량을 V자 반등에 되파는 사고를 방지한다.

상태(DipBuyState)는 플래너 내부 필드가 아니라 호출자가 보관·영속화한다.
이로써 백테스트(엔진 재사용)와 라이브(매일 프로세스 재시작)가 동일한 코드 경로를
쓰며, 진실의 원천(source of truth)은 repo의 strategy_state.json이 된다.
"""
import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple

from src.core.models import Portfolio, Order, OrderAction
from src.core.logic.dip_buy_indicators import DipBuySignals

# 매수 트리거(엣지 트리거 루프 대상). 매도는 2단(상향 후 하향 돌파) 로직이라 별도 처리.
TRIGGERS = ("ma20", "ma60", "ma120", "dip")

RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0


@dataclass
class Tranche:
    """분할 트랜치: 트리거 시점에 고정된 1일 슬라이스 금액과 남은 일수."""
    side: str            # "BUY" | "SELL"
    per_day_amount: float
    remaining_days: int


@dataclass
class DipBuyState:
    """플래너의 영속 상태 (큐 + 매수 트리거 무장 플래그 + RSI 과매수 도달 여부)."""
    queue: List[Tranche] = field(default_factory=list)
    armed: Dict[str, bool] = field(default_factory=lambda: {t: True for t in TRIGGERS})
    rsi_was_overbought: bool = False  # 직전에 RSI>70에 도달했는지 (꺾임 확인용)

    def to_dict(self) -> dict:
        return {
            "queue": [asdict(t) for t in self.queue],
            "armed": dict(self.armed),
            "rsi_was_overbought": self.rsi_was_overbought,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DipBuyState":
        data = data or {}
        queue = [Tranche(**t) for t in data.get("queue", [])]
        armed = {t: True for t in TRIGGERS}
        armed.update(data.get("armed", {}))
        return cls(
            queue=queue,
            armed=armed,
            rsi_was_overbought=bool(data.get("rsi_was_overbought", False)),
        )


class DipBuyPlanner:
    """눌림목 트리거 → 트랜치 적재 → 당일 슬라이스 주문 (순수, 무상태)."""

    def __init__(self, ticker: str, band: float = 0.02,
                 sell_target_cash_ratio: float = 0.20):
        self.ticker = ticker
        self.band = band
        self.sell_target_cash_ratio = sell_target_cash_ratio

    def plan(self, signals: DipBuySignals, portfolio: Portfolio,
             state: DipBuyState,
             available_cash: float = None) -> Tuple[List[Order], str, DipBuyState]:
        # available_cash: 매수/매도 판단에 쓰는 '가용 현금'. 기본은 예수금(total_cash).
        # SHV 같은 현금성 자산을 저수지로 쓰는 엔진은 (예수금 + SHV평가액)을 주입한다.
        # (예수금만 보면 SHV에 현금이 들어간 순간 매수 캡·매도목표가 오작동함)
        if available_cash is None:
            available_cash = portfolio.total_cash

        # 가격 정보가 비정상이면 상태를 전혀 변경하지 않고 조기 반환한다.
        # (트랜치 소진/상태 변경 없이 다음 거래일에 동일 상태로 재시도 → 데이터
        #  일시 누락으로 분할 트랜치가 헛되이 소진되는 상태 꼬임을 방지)
        price = portfolio.current_prices.get(self.ticker, 0.0)
        if price is None or math.isnan(price) or price <= 0:
            return [], "대기(가격 정보 없음)", state

        armed = dict(state.armed)
        queue = list(state.queue)

        # 1. 매수 트리거 평가 + 적재 + 무장/재무장 (엣지 트리거)
        for key, active, make_tranche in self._evaluate_buy_conditions(signals, portfolio, available_cash):
            if active and armed.get(key, True):
                tranche = make_tranche()
                if tranche is not None:
                    queue.append(tranche)
                armed[key] = False
            elif not active:
                armed[key] = True

        # 2. 매도 트리거 평가 (A. 추세 위 price>ma120 + B. RSI 70 하향 돌파 확인)
        rsi_was_overbought = self._evaluate_sell(signals, portfolio, state, queue, available_cash)

        # 3. 당일 슬라이스 합산
        buy_amount = sum(t.per_day_amount for t in queue if t.side == "BUY")
        sell_amount = sum(t.per_day_amount for t in queue if t.side == "SELL")

        # 4. 트랜치 소진 (remaining_days 감소, 0이면 제거)
        next_queue: List[Tranche] = []
        for t in queue:
            t.remaining_days -= 1
            if t.remaining_days > 0:
                next_queue.append(t)
        new_state = DipBuyState(queue=next_queue, armed=armed,
                                rsi_was_overbought=rsi_was_overbought)

        # 5. 주문 생성 (매도 우선 → 자금 확보 후 매수). price는 위에서 검증 완료.
        orders: List[Order] = []
        reasons: List[str] = []

        if sell_amount > 0:
            held = portfolio.holdings.get(self.ticker, 0)
            qty = min(math.ceil(sell_amount / price), held)
            if qty > 0:
                orders.append(Order(self.ticker, OrderAction.SELL, qty, price))
                reasons.append(f"분할매도 {qty}주")

        if buy_amount > 0:
            capped = min(buy_amount, available_cash)
            qty = math.floor(capped / price)
            if qty > 0:
                orders.append(Order(self.ticker, OrderAction.BUY, qty, price))
                reasons.append(f"분할매수 {qty}주")

        reason = " / ".join(reasons) if reasons else "대기(트리거 없음)"
        return orders, reason, new_state

    # ── 매수 트리거 평가 ────────────────────────────────────────────────
    def _in_band(self, price: float, ma: float) -> bool:
        if ma is None or math.isnan(ma) or ma <= 0:
            return False
        return abs(price / ma - 1.0) <= self.band

    def _evaluate_buy_conditions(self, sig: DipBuySignals, pf: Portfolio, available_cash: float):
        # 사이징 기준 = 트리거 시점 총자산(현금+보유평가액).
        # '남은 현금의 %'로 하면 앞선 레벨이 현금을 소진해 더 깊고 싼 레벨이
        # 오히려 작게 들어가는 비대칭이 생긴다. 총자산 기준은 이 비대칭을 없애고
        # (깊은 레벨 ≥ 얕은 레벨), 라이브에서 계좌 규모에 맞춰 스케일된다.
        # 실제 체결은 plan()에서 가용현금으로 캡되므로 과투입은 발생하지 않는다.
        base = pf.total_value
        rsi_ok = not math.isnan(sig.rsi)

        def buy(ratio: float, days: int):
            return lambda: (
                Tranche("BUY", (base * ratio) / days, days) if available_cash > 0 else None
            )

        ma120_valid = not math.isnan(sig.ma120) and sig.ma120 > 0
        dip_active = ma120_valid and sig.price < sig.ma120 and rsi_ok and sig.rsi < RSI_OVERSOLD

        return [
            ("ma20", self._in_band(sig.price, sig.ma20), buy(0.10, 1)),
            ("ma60", self._in_band(sig.price, sig.ma60), buy(0.50, 5)),
            ("ma120", self._in_band(sig.price, sig.ma120), buy(0.50, 5)),
            ("dip", dip_active, buy(1.00, 40)),
        ]

    # ── 매도 트리거 평가 (A. 추세 필터 + B. 모멘텀 꺾임 확인) ──────────────
    def _evaluate_sell(self, sig: DipBuySignals, pf: Portfolio,
                       state: DipBuyState, queue: List[Tranche],
                       available_cash: float) -> bool:
        """RSI 70 상향 도달 후 하향 돌파 + 추세 위(price>ma120)에서 매도 트랜치 적재.

        Returns: 갱신된 rsi_was_overbought 플래그.
        """
        rsi = sig.rsi
        if math.isnan(rsi):
            return state.rsi_was_overbought  # 지표 불가 → 상태 보존

        if rsi > RSI_OVERBOUGHT:
            return True  # 과매수 도달 (아직 매도 안 함, 꺾임 대기)

        # rsi <= 70 : 과매수 구간에서 막 내려온 시점
        if state.rsi_was_overbought and self._above_trend(sig):
            tranche = self._build_sell_tranche(pf, available_cash)
            if tranche is not None:
                queue.append(tranche)
        # 과매수 에피소드 종료 → 재무장 (다시 70 넘으면 새 에피소드)
        return False

    def _above_trend(self, sig: DipBuySignals) -> bool:
        """A. 추세 필터: ma120이 유효하고 price가 그 위에 있는가."""
        return (not math.isnan(sig.ma120)) and sig.ma120 > 0 and sig.price > sig.ma120

    def _build_sell_tranche(self, pf: Portfolio, available_cash: float):
        """목표 현금비중까지 부족분을 5일 분할 매도하는 트랜치 (없으면 None).

        '현금'은 available_cash(예수금+SHV 등 현금성)를 기준으로 한다. 매도는
        QLD를 팔아 가용현금을 목표비중까지 끌어올리는 동작이다.
        """
        price = pf.current_prices.get(self.ticker, 0.0)
        if price is None or math.isnan(price) or price <= 0:
            return None
        holdings_val = pf.holdings.get(self.ticker, 0) * price
        total = available_cash + holdings_val
        if total <= 0 or holdings_val <= 0:
            return None
        target_cash = total * self.sell_target_cash_ratio
        shortfall = target_cash - available_cash
        if shortfall <= 0:
            return None
        sell_amt = min(shortfall, holdings_val)
        return Tranche("SELL", sell_amt / 5, 5)
