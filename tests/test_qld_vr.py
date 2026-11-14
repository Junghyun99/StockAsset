from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from src.core.engine import QldVrBuyDeadbandEngine, DomesticQldVrBuyDeadbandEngine, TqqqVrEngine
from src.core.engine.data_pipeline import CollectedData
from src.core.engine.registry import _ENGINE_MARKET_TYPES
from src.core.logic.tqqq_vr import VrState
from src.core.models import Portfolio
from src.backtest.runner import select_compare_engines


def make_engine(cls):
    repo = Mock()
    repo.load_last_regime.return_value = None
    repo.load_strategy_state.return_value = {}
    return cls(broker=Mock(), repo=repo, logger=Mock())


@pytest.mark.parametrize('cls,ticker,reference,market,zone', [
    (QldVrBuyDeadbandEngine, 'QLD', 'QQQ', 'overseas', 'America/New_York'),
    (DomesticQldVrBuyDeadbandEngine, '418660.KS', '133690.KS', 'domestic', 'Asia/Seoul'),
])
def test_two_times_reference_orders_and_state(cls, ticker, reference, market, zone):
    e = make_engine(cls)
    e.cycle_date = '2026-02-04'
    idx = pd.bdate_range(end=e.cycle_date, periods=30)
    prices = 100*np.cumprod(1+np.tile([.03, -.04], 15))
    frame = pd.DataFrame({('Close', reference): prices}, index=idx)
    data = CollectedData({'reference': frame}, 20, e.data_spec())
    cap = e.calculate_strategy_indicators(data)
    expected = pd.Series(prices[:-1]).tail(21).pct_change().dropna().std()*np.sqrt(252)
    assert cap == pytest.approx(.225/(2*expected))
    frame.iloc[-1] = 1e8
    assert e.calculate_strategy_indicators(data) == cap  # no current-session lookahead
    orders, _, proposed = e.planner.plan(e.cycle_date, cap,
                                         Portfolio(10000, {}, {ticker: 100}), VrState())
    assert orders and all(o.ticker == ticker for o in orders)
    assert proposed.anchor == e.cycle_date
    assert e.planner.buy_deadband == .03
    assert _ENGINE_MARKET_TYPES[cls.__name__] == market
    assert str(e.SESSION_TIMEZONE) == zone
    assert e.STATE_KEY != TqqqVrEngine.STATE_KEY
    # Creating another engine must not mutate an existing planner's ticker.
    assert make_engine(TqqqVrEngine).planner.TICKER == 'TQQQ'
    assert e.planner.TICKER == ticker


def test_domestic_selection_is_explicit():
    defaults = dict(select_compare_engines())
    assert 'QldVrBuyDeadbandEngine' in defaults
    assert 'DomesticQldVrBuyDeadbandEngine' not in defaults
    assert dict(select_compare_engines(['DomesticQldVrBuyDeadbandEngine'])) == {
        'DomesticQldVrBuyDeadbandEngine': DomesticQldVrBuyDeadbandEngine}
    for names in ([], ['typo']):
        with pytest.raises(ValueError):
            select_compare_engines(names)
