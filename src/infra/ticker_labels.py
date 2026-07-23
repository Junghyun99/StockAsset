"""설정 기반 티커 표시명 어댑터."""

from src.config import ticker_display
from src.core.interfaces import ITickerLabelProvider


class ConfigTickerLabelProvider(ITickerLabelProvider):
    def display(self, ticker: str) -> str:
        return ticker_display(ticker)
