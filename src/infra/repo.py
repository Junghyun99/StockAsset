# src/infra/repo.py
import json
import os
from typing import List, Dict, Optional
from dataclasses import asdict
from datetime import datetime
from src.core.models import MarketData, Portfolio, TradeSignal, MarketRegime, TradeExecution
from src.core.interfaces import IRepository

class JsonRepository(IRepository):
    _GROUP_META = {
        'A': {'label': 'Growth', 'color': '#0d6efd'},
        'B': {'label': 'Safety', 'color': '#198754'},
        'C': {'label': 'Cash',   'color': '#ffc107'},
    }

    def __init__(self, root_path: str = "docs/data", max_summary_records: int = 2000, max_history_records: int = 100, asset_groups: dict = None):
        self.root = root_path
        self.max_summary_records = max_summary_records
        self.max_history_records = max_history_records
        self._asset_groups = asset_groups or {}
        os.makedirs(self.root, exist_ok=True)

        self.status_file = os.path.join(self.root, "status.json")
        self.summary_file = os.path.join(self.root, "summary.json")
        self.history_file = os.path.join(self.root, "history.json")

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
        for group, tickers in self.asset_groups.items():
            meta = self._GROUP_META.get(group, {'label': group, 'color': '#adb5bd'})
            config[group] = {
                'tickers': tickers,
                'label': meta['label'],
                'color': meta['color'],
            }
        self._save_json(os.path.join(self.root, "asset_groups.json"), config)

    def save_daily_summary(self, market: MarketData, signal: TradeSignal, pf: Portfolio, regime: MarketRegime):
        """일별 요약 저장 (Append 방식)"""
        # 각 그룹 순수 주식 평가액
        val_a = pf.get_group_value(self.asset_groups.get('A', []))
        val_b = pf.get_group_value(self.asset_groups.get('B', []))

        # [수정] 그룹 C = SHV 등 종목 평가액 + 현재 보유 현금(예수금)
        val_c_pure_stock = pf.get_group_value(self.asset_groups.get('C', []))
        val_c_total = val_c_pure_stock + pf.total_cash

        record = {
            "date": market.date,

            # [자산 정보]
            "total_value": pf.total_value,
            "cash_balance": pf.total_cash,  # [추가]
            "group_a": val_a,
            "group_b": val_b,
            "group_c": val_c_total,
            # [시장 지표]
            "spy_price": market.spy_price,
            "spy_ma180": market.spy_ma180,          # [추가]
            "spy_volatility": market.spy_volatility, # [추가]
            "spy_momentum": market.spy_momentum,     # [추가]
            "mdd": market.spy_mdd,

            # [전략 상태]
            "regime": regime.value,          # MarketRegime enum 값 (예: "Bull", "Bear", "Crash")
            "reason": signal.reason,         # 상세 사유 (예: "Bull (모니터링)", "데이터 이상 - NaN: ...")
            "target_exposure": signal.target_exposure
        }

        data = self._load_json(self.summary_file, default=[])
        data.append(record)

        if self.max_summary_records > 0:
            data = data[-self.max_summary_records:]

        self._save_json(self.summary_file, data)
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
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tx_id = f"tx_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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
    def update_status(self,
                      regime: MarketRegime,
                      exposure: float,
                      pf: Portfolio,
                      market_data: MarketData, # [필수] 데이터 매핑을 위해 필요
                      reason: str,
                      sim_date: str = None,          # [백테스트] 시뮬레이션 날짜 (없으면 현재 시각)
                      rebalancing_date: str = None): # 리밸런싱 실행일 (None이면 기존 값 유지)

        last_updated = sim_date if sim_date else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
                }
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

    def _save_json(self, path: str, data):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)