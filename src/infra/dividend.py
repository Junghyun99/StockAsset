"""Live dividend settlement adapters."""
from src.core.interfaces import IDividendSettlement


class NoOpDividendSettlement(IDividendSettlement):
    """Live accounts already reflect cash movements at the broker."""

    def receive_dividend(self, amount: float) -> float:
        return 0.0
