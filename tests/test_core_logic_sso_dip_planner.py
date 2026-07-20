# tests/test_core_logic_sso_dip_planner.py
"""SsoDipPlanner 단위 테스트."""
import pytest
from src.core.logic.sso_dip_signals import SsoDipSignals
from src.core.logic.sso_dip_planner import (
    SsoDipPlanner, SsoDipState, SignalLevel,
    BUY_STAGES, SELL_CONDITION, IDLE_TARGET, SELL_TARGET,
)
from src.core.models import Portfolio


def _sig(rsi: float = 50.0, dev: float = 0.0) -> SsoDipSignals:
    """지표 스냅샷 헬퍼."""
    return SsoDipSignals(
        date="2024-06-01", weekly_rsi=rsi, ma200_deviation=dev,
        spy_price=500.0, spy_ma200=500.0,
    )


def _pf(cash: float = 10000.0, sso: int = 0, spyi: int = 0,
         sso_price: float = 80.0, spyi_price: float = 55.0) -> Portfolio:
    """포트폴리오 헬퍼."""
    return Portfolio(
        total_cash=cash,
        holdings={"SSO": sso, "SPYI": spyi},
        current_prices={"SSO": sso_price, "SPYI": spyi_price},
    )


class TestSignalDetection:
    """신호 탐지 테스트."""

    def test_no_signal_in_normal_market(self):
        """정상 시장 → IDLE."""
        planner = SsoDipPlanner()
        state = SsoDipState()
        _, _, new_state = planner.plan(_sig(rsi=55, dev=0.02), _pf(), state)
        assert new_state.level == SignalLevel.IDLE

    def test_stage1_triggers(self):
        """RSI≤48 AND 괴리율≤-10% → STAGE_1."""
        planner = SsoDipPlanner()
        state = SsoDipState()
        _, _, new_state = planner.plan(_sig(rsi=45, dev=-0.12), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_1

    def test_stage2_triggers(self):
        """RSI≤42 AND 괴리율≤-18% → STAGE_2."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        _, _, new_state = planner.plan(_sig(rsi=40, dev=-0.20), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_2

    def test_stage3_triggers(self):
        """RSI≤36 AND 괴리율≤-26% → STAGE_3."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        _, _, new_state = planner.plan(_sig(rsi=34, dev=-0.28), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_3

    def test_no_downgrade(self):
        """단계2에서 단계1 조건 → 단계2 유지 (하향 강등 없음)."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_2)
        _, _, new_state = planner.plan(_sig(rsi=45, dev=-0.12), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_2

    def test_sell_signal(self):
        """RSI≥72 AND 괴리율≥+13% → SELL."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        # SSO 비중이 40% 초과여야 매도 상태 유지 (100주×$80=$8000, total=$8000)
        _, _, new_state = planner.plan(
            _sig(rsi=78, dev=0.18), _pf(cash=0, sso=100, spyi=0), state,
        )
        assert new_state.level == SignalLevel.SELL

    def test_sell_completes_to_idle(self):
        """매도 완료(SELL_TARGET 이하 도달) → IDLE 복귀."""
        planner = SsoDipPlanner()
        # SSO 20% = $2000 / $10000 (25주×$80=$2000, 145주×$55.17=$8000)
        state = SsoDipState(level=SignalLevel.SELL)
        _, _, new_state = planner.plan(
            _sig(rsi=65, dev=0.05),
            _pf(cash=0, sso=25, spyi=145, sso_price=80.0, spyi_price=55.17),
            state,
        )
        assert new_state.level == SignalLevel.IDLE

    def test_direct_jump_to_stage3(self):
        """IDLE에서 직접 단계3 조건 → STAGE_3."""
        planner = SsoDipPlanner()
        state = SsoDipState()
        _, _, new_state = planner.plan(_sig(rsi=34, dev=-0.28), _pf(), state)
        assert new_state.level == SignalLevel.BUY_STAGE_3

    def test_sell_overridden_by_buy_signal(self):
        """SELL 중 급락(매수 조건 충족) → BUY_STAGE로 전환."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.SELL)
        _, _, new_state = planner.plan(
            _sig(rsi=34, dev=-0.28),
            _pf(cash=0, sso=100, spyi=0),
            state,
        )
        assert new_state.level == SignalLevel.BUY_STAGE_3

    def test_sell_persists_without_buy_signal(self):
        """SELL 중 매수 조건 미충족 → SELL 유지."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.SELL)
        _, _, new_state = planner.plan(
            _sig(rsi=55, dev=0.0),
            _pf(cash=0, sso=100, spyi=0),
            state,
        )
        assert new_state.level == SignalLevel.SELL


class TestDCA:
    """분할매수/매도 금액 계산 테스트."""

    def test_buy_stage1_speed(self):
        """단계1 속도계수 10% 검증."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        # SSO 0%, 목표 40%, 총자산 $10000
        # delta = (0.4 - 0.0) × 0.1 × 10000 = $400
        orders, _, _ = planner.plan(
            _sig(rsi=45, dev=-0.12),
            _pf(cash=10000, sso=0, spyi=0),
            state,
        )
        sso_buy = [o for o in orders if o.ticker == "SSO" and o.action.value == "BUY"]
        assert len(sso_buy) == 1
        assert sso_buy[0].quantity == 5  # $400 / $80 = 5주

    def test_buy_stage3_speed(self):
        """단계3 속도계수 40% 검증."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_3)
        # SSO 0%, 목표 80%, 총자산 $10000
        # delta = (0.8 - 0.0) × 0.4 × 10000 = $3200
        orders, _, _ = planner.plan(
            _sig(rsi=34, dev=-0.28),
            _pf(cash=10000, sso=0, spyi=0),
            state,
        )
        sso_buy = [o for o in orders if o.ticker == "SSO" and o.action.value == "BUY"]
        assert len(sso_buy) == 1
        assert sso_buy[0].quantity == 40  # $3200 / $80 = 40주

    def test_sell_speed(self):
        """매도 속도계수 10% 검증."""
        planner = SsoDipPlanner()
        # SSO 100%, 목표 20%
        # 총자산 = 100주×$80 = $8000
        # delta = (0.2 - 1.0) × 0.1 × 8000 ≈ -$640 → ceil(640.x/80) = 9주 (부동소수점)
        state = SsoDipState(level=SignalLevel.SELL)
        orders, _, _ = planner.plan(
            _sig(rsi=65, dev=0.05),
            _pf(cash=0, sso=100, spyi=0),
            state,
        )
        sso_sell = [o for o in orders if o.ticker == "SSO" and o.action.value == "SELL"]
        assert len(sso_sell) == 1
        assert sso_sell[0].quantity == 9

    def test_spyi_counterpart_on_buy(self):
        """SSO 매수 시 SPYI 매도로 자금 확보."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        orders, _, _ = planner.plan(
            _sig(rsi=45, dev=-0.12),
            _pf(cash=0, sso=0, spyi=200, spyi_price=55.0),
            state,
        )
        spyi_sell = [o for o in orders if o.ticker == "SPYI" and o.action.value == "SELL"]
        assert len(spyi_sell) == 1

    def test_spyi_buy_on_sell(self):
        """SSO 매도 시 잔여 현금으로 SPYI 매수."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.SELL)
        orders, _, _ = planner.plan(
            _sig(rsi=65, dev=0.05),
            _pf(cash=0, sso=100, spyi=0),
            state,
        )
        spyi_buy = [o for o in orders if o.ticker == "SPYI" and o.action.value == "BUY"]
        assert len(spyi_buy) == 1

    def test_no_orders_when_target_reached(self):
        """목표 비중 도달 시 주문 없음."""
        planner = SsoDipPlanner()
        # SSO 정확히 40% = $4000 / $10000
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        orders, _, _ = planner.plan(
            _sig(rsi=45, dev=-0.12),
            _pf(cash=0, sso=50, spyi=109, sso_price=80.0, spyi_price=55.05),
            state,
        )
        sso_orders = [o for o in orders if o.ticker == "SSO"]
        assert len(sso_orders) == 0


class TestSpyiSweep:
    """잔여 현금 → SPYI 스윕 테스트."""

    def test_idle_cash_sweeps_to_spyi(self):
        """IDLE + 현금만 → SSO 20% 매수 + 잔여 SPYI 스윕."""
        planner = SsoDipPlanner()
        state = SsoDipState()
        # IDLE 목표 20%, speed 10%: delta = (0.2 - 0.0) × 0.1 × 10000 = $200
        # SSO 매수: floor(200/80) = 2주 × $80 = $160
        # 잔여 현금: 10000 - 160 = $9840 → SPYI floor(9840/55) = 178주
        orders, reason, _ = planner.plan(
            _sig(rsi=55, dev=0.02),
            _pf(cash=10000, sso=0, spyi=0),
            state,
        )
        sso_buy = [o for o in orders if o.ticker == "SSO" and o.action.value == "BUY"]
        assert len(sso_buy) == 1
        assert sso_buy[0].quantity == 2
        spyi_buy = [o for o in orders if o.ticker == "SPYI" and o.action.value == "BUY"]
        assert len(spyi_buy) == 1
        assert "SPYI 스윕" in reason

    def test_remaining_cash_after_sso_buy(self):
        """SSO 매수 후 남은 현금도 SPYI로 스윕."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        # delta = (0.4 - 0.0) × 0.1 × 10000 = $400 → SSO 5주 × $80 = $400
        # 남은 현금 = 10000 - 400 = $9600 → SPYI floor(9600/55) = 174주
        orders, _, _ = planner.plan(
            _sig(rsi=45, dev=-0.12),
            _pf(cash=10000, sso=0, spyi=0),
            state,
        )
        spyi_buy = [o for o in orders if o.ticker == "SPYI" and o.action.value == "BUY"]
        assert len(spyi_buy) == 1
        assert spyi_buy[0].quantity == 174

    def test_no_sweep_when_fully_invested(self):
        """현금 0 + 전액 투자 → 스윕 주문 없음."""
        planner = SsoDipPlanner()
        state = SsoDipState(level=SignalLevel.BUY_STAGE_1)
        orders, _, _ = planner.plan(
            _sig(rsi=45, dev=-0.12),
            _pf(cash=0, sso=50, spyi=109, sso_price=80.0, spyi_price=55.05),
            state,
        )
        spyi_buy = [o for o in orders if o.ticker == "SPYI" and o.action.value == "BUY"]
        assert len(spyi_buy) == 0

    def test_idle_with_target_ratio_reached(self):
        """IDLE + SSO 20% 도달 → SSO 주문 없음."""
        planner = SsoDipPlanner()
        state = SsoDipState()
        # SSO 19.99% = 25주×$80=$2000, SPYI 146주×$54.795=$7999.07, total≈$9999
        orders, _, _ = planner.plan(
            _sig(rsi=55, dev=0.02),
            _pf(cash=0, sso=25, spyi=146, sso_price=80.0, spyi_price=54.795),
            state,
        )
        sso_orders = [o for o in orders if o.ticker == "SSO"]
        assert len(sso_orders) == 0


class TestStateSerialize:
    """상태 직렬화/역직렬화."""

    def test_roundtrip(self):
        state = SsoDipState(level=SignalLevel.BUY_STAGE_2)
        restored = SsoDipState.from_dict(state.to_dict())
        assert restored.level == SignalLevel.BUY_STAGE_2

    def test_from_empty_dict(self):
        state = SsoDipState.from_dict({})
        assert state.level == SignalLevel.IDLE

    def test_from_none(self):
        state = SsoDipState.from_dict(None)
        assert state.level == SignalLevel.IDLE
