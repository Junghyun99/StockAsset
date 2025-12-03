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
        """일별 요약 저장 (Append 방식)"""
        
        record = {
            "date": market.date,
            
            # [자산 정보]
            "total_value": pf.total_value,
            "cash_balance": pf.total_cash,  # [추가]
            
            # [시장 지표]
            "spy_price": market.spy_price,
            "spy_ma180": market.spy_ma180,          # [추가]
            "spy_volatility": market.spy_volatility, # [추가]
            "spy_momentum": market.spy_momentum,     # [추가]
            "mdd": market.spy_mdd,
            
            # [전략 상태]
            "regime": signal.reason, # 혹은 mapped string (예: "Bear")
            "target_exposure": signal.target_exposure
        }
        
        data = self._load_json(self.summary_file, default=[])
        data.append(record)
        
        # 파일이 너무 커지는 것을 방지하려면 여기서 최근 N개(예: 2000개)만 유지하는 로직 추가 가능
        # data = data[-2000:] 
        
        self._save_json(self.summary_file, data)
    def save_trade_history(self, signal: TradeSignal, pf: Portfolio): # [수정] pf 인자 추가
        """매매 내역 저장 - Append"""
        if not signal.orders:
            return

        # 거래 규모 계산
        trade_amt = sum(o.quantity * o.price for o in signal.orders)
        
        # ID 생성 (타임스탬프 기반)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tx_id = f"tx_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        record = {
            "id": tx_id,                    # [추가]
            "date": now_str,
            "portfolio_value": pf.total_value, # [추가]
            "total_trade_amount": trade_amt,   # [추가]
            "reason": signal.reason,
            "orders": [asdict(o) for o in signal.orders]
        }
        
        data = self._load_json(self.history_file, default=[])
        
        # 최신 내역이 위로 오게 할지, 아래로 가게 할지 결정 (여기선 Append -> 아래)
        data.append(record)
        
        # 히스토리가 무한정 길어지는 것 방지 (예: 최근 100건만 유지) - 선택사항
        # if len(data) > 100: data = data[-100:]
        
        self._save_json(self.history_file, data)
    def update_status(self, 
                      regime: MarketRegime, 
                      exposure: float, 
                      pf: Portfolio, 
                      market_data: MarketData, # [필수] 데이터 매핑을 위해 필요
                      reason: str):            # [필수] 사유 기록
        
        status = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            
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