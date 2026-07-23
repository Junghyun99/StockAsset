# src/infra/repo.py
import json
import math
import os
import uuid
from typing import List, Dict, Optional
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from src.core.models import MarketData, Portfolio, TradeSignal, MarketRegime, TradeExecution, DecisionFactor, OrderBatchResult, ExecutionStatus
from src.core.settlement import derive_net_deposit

_KST = timezone(timedelta(hours=9))
from src.core.interfaces import IRepository
from src.config import TICKER_ALIASES

class JsonRepository(IRepository):
    _GROUP_META = {
        'A': {'label': 'Growth', 'color': '#0d6efd'},
        'B': {'label': 'Safety', 'color': '#198754'},
        'C': {'label': 'Cash',   'color': '#ffc107'},
    }

    def __init__(self, root_path: str = "docs/data", max_summary_records: int = 2000, max_history_records: int = 100, asset_groups: dict = None, max_order_event_records: int = 100000, account_id: Optional[str] = None, engine_name: Optional[str] = None, execution_mode: str = "legacy"):
        self.root = root_path
        self.max_summary_records = max_summary_records
        self.max_history_records = max_history_records
        self.max_order_event_records = max_order_event_records
        self.account_id, self.engine_name, self.execution_mode = account_id, engine_name, execution_mode
        self._asset_groups = asset_groups or {}
        os.makedirs(self.root, exist_ok=True)

        self.status_file = os.path.join(self.root, "status.json")
        self.summary_file = os.path.join(self.root, "summary.json")
        self.history_file = os.path.join(self.root, "history.json")
        self.order_events_file = os.path.join(self.root, "order_events.json")
        self._strategy_state_file = os.path.join(self.root, "strategy_state.json")

        self.save_asset_groups_config()

    @property
    def asset_groups(self) -> dict:
        return self._asset_groups

    @asset_groups.setter
    def asset_groups(self, value: dict):
        self._asset_groups = value or {}
        self.save_asset_groups_config()

    def save_asset_groups_config(self):
        """asset_groups 설정을 JSON으로 저장하여 프론트엔드에서 동적으로 매핑할 수 있도록 함"""
        config = {}
        all_tickers = []
        for group, tickers in self.asset_groups.items():
            meta = self._GROUP_META.get(group, {'label': group, 'color': '#adb5bd'})
            config[group] = {
                'tickers': tickers,
                'label': meta['label'],
                'color': meta['color'],
            }
            all_tickers.extend(tickers)
        # 이 계정에서 사용 중인 티커만 추려서 alias 맵 추가
        aliases = {t: TICKER_ALIASES[t] for t in all_tickers if t in TICKER_ALIASES}
        if aliases:
            config['aliases'] = aliases
        self._save_json(os.path.join(self.root, "asset_groups.json"), config)

    def save_daily_summary(self, market: MarketData, signal: TradeSignal, pf: Portfolio,
                           regime: MarketRegime, expected_dividend: float = 0.0,
                           date_override: Optional[str] = None,
                           benchmarks: Optional[dict] = None,
                           executions: Optional[List[TradeExecution]] = None,
                           decision_factors: Optional[List[DecisionFactor]] = None):
        """일별 요약 저장 (Append 방식)"""
        # 각 그룹 순수 주식 평가액
        val_a = pf.get_group_value(self.asset_groups.get('A', []))
        val_b = pf.get_group_value(self.asset_groups.get('B', []))

        # [수정] 그룹 C = SHV 등 종목 평가액 + 현재 보유 현금(예수금)
        val_c_pure_stock = pf.get_group_value(self.asset_groups.get('C', []))
        val_c_total = val_c_pure_stock + pf.total_cash

        record_date = date_override or market.date
        data = self._load_json(self.summary_file, default=[])
        net_deposit = self._derive_summary_net_deposit(data, record_date, pf, executions)

        record = {
            "date": record_date,

            # [자산 정보]
            "total_value": pf.total_value,
            "cash_balance": pf.total_cash,  # [추가]
            # [결산] 직전 레코드 이후 순입금 역산치 (기간 결산의 손익/TWR 산출용)
            "net_deposit": net_deposit,
            "group_a": val_a,
            "group_b": val_b,
            "group_c": val_c_total,
            "expected_dividend": expected_dividend,
            # [시장 지표]
            "spy_price": market.spy_price,
            "spy_ma180": market.spy_ma180,          # [추가]
            "spy_volatility": market.spy_volatility, # [추가]
            "spy_momentum": market.spy_momentum,     # [추가]
            "mdd": market.spy_mdd,
            "vix": market.vix,                       # [추가] 디버깅 및 분석용

            # [벤치마크] 계좌 통화에 맞춘 비교 지수 최신가 {논리명: 가격}
            # 신호용 spy_* 필드와 별개. 미전달(백테스트 등) 시 빈 dict.
            "benchmarks": benchmarks or {},

            # [전략 상태]
            "regime": regime.value,          # MarketRegime enum 값 (예: "Bull", "Bear", "Crash")
            "reason": signal.reason,         # 상세 사유 (예: "Bull (모니터링)", "데이터 이상 - NaN: ...")
            "target_exposure": signal.target_exposure,
            # [리밸런싱 진단] 그 시점의 목표 비율·임계치를 함께 저장해
            # 이격도 시계열이 설정 변경과 무관하게 불변이 되도록 한다.
            "target_ratio_a": signal.target_ratio_a,
            "rebalance_threshold": signal.rebalance_threshold,

            # [결정요소 시계열] 엔진이 선언한 key:value 축약본 (라벨/포맷은 status.json에만)
            "factors": {f.key: f.value for f in (decision_factors or [])},
        }

        # 같은 날짜 레코드가 있으면 덮어쓰고(upsert), 없으면 추가
        idx = next((i for i, r in enumerate(data) if r.get('date') == record['date']), None)
        if idx is not None:
            data[idx] = record
        else:
            data.append(record)

        if self.max_summary_records > 0:
            data = data[-self.max_summary_records:]

        self._save_json(self.summary_file, data)

    @staticmethod
    def _derive_summary_net_deposit(data: List[dict], record_date: str, pf: Portfolio,
                                    executions: Optional[List[TradeExecution]]
                                    ) -> Optional[float]:
        """직전 요약 레코드와 현금 차이로 이번 기록분 순입금을 역산한다.

        같은 날짜 재실행(수동 재실행 등)은 그날 기존 net_deposit에 이번 실행의
        변동분만 누적한다. 마지막 레코드보다 과거 날짜를 덮어쓰는 경우(비정상
        경로)는 역산 근거가 없으므로 기존 값을 보존한다.
        """
        prev = data[-1] if data else None
        prev_cash = prev.get("cash_balance") if prev else None

        if prev is not None and prev.get("date") == record_date:
            run_nd = derive_net_deposit(pf.total_cash, prev_cash or 0.0, executions)
            return round(float(prev.get("net_deposit") or 0.0) + run_nd, 2)

        old = next((r for r in data if r.get("date") == record_date), None)
        if old is not None:
            return old.get("net_deposit")

        return derive_net_deposit(pf.total_cash, prev_cash, executions)

    def load_summaries(self) -> List[dict]:
        """일별 요약 레코드 목록을 로드한다 (기간 결산용, 날짜 오름차순 저장 순서)."""
        return self._load_json(self.summary_file, default=[])

    def save_trade_history(self, executions: List[TradeExecution], pf: Portfolio, reason: str, sim_date: str = None):
        """매매 내역 저장 - Append"""
        if not executions:
            return

        # 거래 규모 계산
        trade_amt = sum(e.price * e.quantity for e in executions)

        # ID/날짜 생성: 시뮬레이션 날짜가 주어지면 그것을, 아니면 현재 시각 사용
        if sim_date:
            date_str = sim_date
            tx_id = f"tx_{sim_date.replace('-', '')}"
        else:
            date_str = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")
            tx_id = f"tx_{datetime.now(_KST).strftime('%Y%m%d_%H%M%S')}"

        record = {
            "id": tx_id,                    # [추가]
            "date": date_str,
            "portfolio_value": pf.total_value, # [추가]
            "total_trade_amount": trade_amt,   # [추가]
            "reason": reason,
            "executions": [asdict(e) for e in executions]
        }

        data = self._load_json(self.history_file, default=[])

        # 최신 내역이 위로 오게 할지, 아래로 가게 할지 결정 (여기선 Append -> 아래)
        data.append(record)

        if self.max_history_records > 0:
            data = data[-self.max_history_records:]

        self._save_json(self.history_file, data)
    @staticmethod
    def _event_policy(status):
        if status == ExecutionStatus.FILLED:
            return False, "success"
        if status == ExecutionStatus.SKIPPED:
            return False, "info"
        if status in {ExecutionStatus.REJECTED, ExecutionStatus.ERROR}:
            return True, "danger"
        return True, "warning"

    def save_order_events(self, order_result: OrderBatchResult) -> None:
        data = self._load_json(self.order_events_file, default=[])
        for outcome in order_result.outcomes:
            execution = outcome.execution
            alertable, display_level = self._event_policy(outcome.status)
            data.append({
                "schema_version": 1, "event_id": str(uuid.uuid4()),
                "attempted_at": outcome.attempted_at, "execution_mode": self.execution_mode,
                "account_id": self.account_id, "engine": self.engine_name,
                "ticker": outcome.order.ticker, "action": outcome.order.action.value,
                "requested_quantity": outcome.order.quantity, "requested_price": outcome.order.price,
                "filled_quantity": execution.quantity if execution else 0,
                "filled_price": execution.price if execution else None,
                "fee": execution.fee if execution else None,
                "executed_at": execution.date if execution else None,
                "status": outcome.status.value,
                "broker_reason": outcome.reason or (execution.reason if execution else None),
                "alertable": alertable, "display_level": display_level, "source": "runtime",
            })
        if self.max_order_event_records > 0:
            data = data[-self.max_order_event_records:]
        self._save_json(self.order_events_file, data)

    def update_status(self,
                      regime: MarketRegime,
                      exposure: float,
                      pf: Portfolio,
                      market_data: MarketData, # [필수] 데이터 매핑을 위해 필요
                      reason: str,
                      sim_date: str = None,          # [백테스트] 시뮬레이션 날짜 (없으면 현재 시각)
                      rebalancing_date: str = None,  # 리밸런싱 실행일 (None이면 기존 값 유지)
                      decision_factors: Optional[List[DecisionFactor]] = None):

        last_updated = sim_date if sim_date else datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")

        # 리밸런싱 날짜: 전달된 값 우선, 없으면 기존 status에서 읽어 유지
        existing = self._load_json(self.status_file, default={})
        last_rebalancing = rebalancing_date if rebalancing_date is not None \
            else existing.get("last_rebalancing_date")

        status = {
            "last_updated": last_updated,
            "last_rebalancing_date": last_rebalancing,

            "strategy": {
                "regime": regime.value,
                "target_exposure": exposure,
                "trigger_reason": reason,
                "market_score": {
                    # 기존 필드
                    "vix": market_data.vix,
                    "spy_mdd": market_data.spy_mdd,
                    "spy_momentum": market_data.spy_momentum,
                    # [요청 1] 추가된 필드
                    "spy_price": market_data.spy_price,
                    "spy_ma180": market_data.spy_ma180,
                    "spy_volatility": market_data.spy_volatility
                },
                # [결정요소] 엔진이 자기서술한 핵심 요소 목록 (프론트가 그대로 렌더링)
                "decision_factors": [asdict(f) for f in (decision_factors or [])],
            },

            "portfolio": {
                "total_value": pf.total_value,
                "cash_balance": pf.total_cash,
                # [요청 2] 수익률, 수익금 필드 삭제 완료
                "holdings": [
                    {
                        "ticker": t,
                        "qty": q,
                        "price": pf.current_prices.get(t, 0),
                        "value": q * pf.current_prices.get(t, 0)
                    }
                    for t, q in pf.holdings.items() if q > 0
                ]
            }
        }

        self._save_json(self.status_file, status)

    def load_last_regime(self):
        """status.json에서 마지막 국면(regime)을 로드한다.
        프로세스 재시작 시 RegimeAnalyzer 히스테리시스 상태 복원에 사용.
        """
        status = self._load_json(self.status_file)
        if not status:
            return None
        try:
            regime_str = status["strategy"]["regime"]
            return MarketRegime(regime_str)
        except (KeyError, ValueError):
            return None
    def load_strategy_state(self, key: str) -> dict:
        """strategy_state.json에서 key에 해당하는 전략 상태를 로드한다.

        상태형 엔진의 사이클 간 상태 복원에 사용 (국면 히스테리시스와 동일 패턴).
        """
        data = self._load_json(self._strategy_state_file, default={})
        return data.get(key, {})

    def save_strategy_state(self, key: str, state: dict) -> None:
        """strategy_state.json에 key별 전략 상태를 저장한다 (다른 key 보존)."""
        data = self._load_json(self._strategy_state_file, default={})
        data[key] = state
        self._save_json(self._strategy_state_file, data)

    def get_last_rebalancing_date(self) -> Optional[str]:
        """마지막 리밸런싱 실행 날짜 반환 (status.json, 없으면 None)"""
        data = self._load_json(self.status_file, default={})
        return data.get("last_rebalancing_date")

    def get_last_summary_date(self) -> Optional[str]:
        """summary.json의 마지막 레코드 날짜 반환 (기록 없으면 None)"""
        data = self._load_json(self.summary_file, default=[])
        if not data:
            return None
        return data[-1].get("date")

    def _load_json(self, path: str, default=None):
        if not os.path.exists(path):
            return default
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            return default

    @staticmethod
    def _sanitize_for_json(obj):
        """NaN/Infinity 값을 None으로 변환하여 유효한 JSON을 보장한다."""
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: JsonRepository._sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [JsonRepository._sanitize_for_json(v) for v in obj]
        return obj

    def _save_json(self, path: str, data):
        sanitized = self._sanitize_for_json(data)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(sanitized, f, indent=4, ensure_ascii=False)
