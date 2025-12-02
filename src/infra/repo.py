# src/infra/repo.py
import json
import os
from dataclasses import asdict
from datetime import datetime
from src.core.models import MarketData, Portfolio, TradeSignal, MarketRegime

class JsonRepository:
    def __init__(self, root_path: str = "docs/data"):
        self.root = root_path
        os.makedirs(self.root, exist_ok=True)
        
        self.status_file = os.path.join(self.root, "status.json")
        self.summary_file = os.path.join(self.root, "summary.json")
        self.history_file = os.path.join(self.root, "history.json")

    def save_daily_summary(self, market: MarketData, signal: TradeSignal, pf: Portfolio):
        """일별 요약(차트용) 저장 - Append"""
        record = {
            "date": market.date,
            "spy_price": market.spy_price,
            "regime": signal.reason, # or mapped string
            "total_value": pf.total_value,
            "target_exposure": signal.target_exposure,
            "mdd": market.spy_mdd
        }
        
        data = self._load_json(self.summary_file, default=[])
        data.append(record)
        self._save_json(self.summary_file, data)

    def save_trade_history(self, signal: TradeSignal):
        """매매 내역 저장 - Append"""
        if not signal.orders:
            return

        record = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reason": signal.reason,
            "orders": [asdict(o) for o in signal.orders]
        }
        
        data = self._load_json(self.history_file, default=[])
        data.append(record)
        self._save_json(self.history_file, data)

    def update_status(self, regime: MarketRegime, exposure: float, pf: Portfolio):
        """현재 상태판(대시보드 상단용) 저장 - Overwrite"""
        status = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "regime": regime.value,
            "exposure": exposure,
            "total_value": pf.total_value,
            "cash": pf.total_cash,
            "holdings": pf.holdings
        }
        self._save_json(self.status_file, status)

    def _load_json(self, path: str, default=None):
        if not os.path.exists(path):
            return default
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default

    def _save_json(self, path: str, data):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)