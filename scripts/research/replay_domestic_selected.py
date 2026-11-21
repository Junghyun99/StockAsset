"""Replay the selected domestic engine constants with the preserved 3% scenario."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.research.compare_domestic_vr import DATA, load, simulate, metrics
from src.core.engine.qld_vr import DomesticQldVrBuyDeadbandEngine


def main():
    one, two = load('133690'), load('418660')
    prices = pd.concat([one.Close.rename('133690.KS'), two.Close.rename('418660.KS')], axis=1).dropna()
    vols = (one.Close.pct_change(fill_method=None).rolling(20).std(ddof=1).shift(1)*np.sqrt(252)).reindex(prices.index)
    cls = DomesticQldVrBuyDeadbandEngine
    rows = []
    for name, ticker, bh in [(cls.__name__, cls.TRADE_TICKER, False), ('BH_1x', '133690.KS', True)]:
        frame = simulate(prices, vols, str(prices.index[0].date()), str(prices.index[-1].date()),
                         ticker=ticker, target=cls.VOLATILITY_TARGET, band=cls.BUY_DEADBAND,
                         bh=bh, cash_rate=.03)
        rows.append(dict(strategy=name, cash_rate=.03, risk_free_rate=.03,
                         target=cls.VOLATILITY_TARGET if not bh else None,
                         buy_deadband=cls.BUY_DEADBAND if not bh else None, **metrics(frame,.03)))
    result = pd.DataFrame(rows)
    result.to_csv(DATA/'selected_candidate.csv', index=False)
    print(result.to_string(index=False))


if __name__ == '__main__':
    main()
