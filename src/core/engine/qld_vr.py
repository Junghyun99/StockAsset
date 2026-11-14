"""Two-times Nasdaq VR variants using the shared VR planner and lifecycle."""
from zoneinfo import ZoneInfo

from src.core.engine.registry import register_engine
from src.core.engine.tqqq_vr import TqqqVrBuyDeadbandEngine


@register_engine(color="#0891b2", backtest=True)
class QldVrBuyDeadbandEngine(TqqqVrBuyDeadbandEngine):
    ASSET_GROUPS = {"A": ["QLD"], "B": []}
    TRADE_TICKER = "QLD"
    LEVERAGE = 2.0
    BUY_DEADBAND = 0.03
    LABEL = "QLD VR 22.5% · 매수 3%p"
    STATE_KEY = "qld_vr_buy_deadband"


@register_engine(color="#059669", market_type="domestic", backtest=False)
class DomesticQldVrBuyDeadbandEngine(QldVrBuyDeadbandEngine):
    """Experimental KRW variant; select explicitly to preserve US test history."""
    ASSET_GROUPS = {"A": ["418660.KS"], "B": []}
    TRADE_TICKER = "418660.KS"
    REFERENCE_TICKER = "133690.KS"
    LABEL = "국내 나스닥 2배 VR 22.5% · 매수 3%p"
    STATE_KEY = "domestic_qld_vr_buy_deadband"
    SESSION_TIMEZONE = ZoneInfo("Asia/Seoul")
