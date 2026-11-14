"""Reproduce domestic VR price-return research using PR414 engine/planner/broker.

Input: research/domestic_vr/prices.csv (Naver daily Close snapshot).
No synthetic pre-listing prices, dividends, cash interest, taxes or terminal sale.
"""
import math
import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.core.engine.qld_vr import DomesticQldVrBuyDeadbandEngine
from src.core.engine.data_pipeline import CollectedData
from src.core.logic.tqqq_vr import VrState
from src.core.models import Order, OrderAction
from src.backtest.components import BacktestBroker

DATA = ROOT / 'research/domestic_vr'
INITIAL = 10_000_000
FEE, SLIP = .0025, .001


def load(code):
    prices = pd.read_csv(DATA / 'prices.csv', index_col='date', parse_dates=True)
    frame = prices[[code+'.KS']].dropna().rename(columns={code+'.KS':'Close'})
    assert frame.index.is_unique and frame.Close.gt(0).all()
    return frame


def metrics(frame):
    equity = np.r_[INITIAL, frame.equity.to_numpy()]
    daily = equity[1:]/equity[:-1]-1
    peaks = np.maximum.accumulate(equity)
    dd = equity/peaks-1
    trough = int(np.argmin(dd))
    peak = int(np.argmax(equity[:trough+1]))
    recovered = np.flatnonzero(equity[trough:] >= equity[peak])
    recovery = trough+int(recovered[0]) if len(recovered) else None
    # Index zero is the initial capital immediately before first-session trading.
    dates = [frame.index[0], *frame.index]
    longest = streak = 0
    for below in dd[1:] < -1e-12:
        streak = streak+1 if below else 0
        longest = max(longest, streak)
    days = (frame.index[-1]-frame.index[0]).days
    return dict(cagr=(equity[-1]/INITIAL)**(365.25/days)-1,
                mdd=float(dd.min()), sharpe=float(np.mean(daily)/np.std(daily, ddof=1)*np.sqrt(252)),
                final_value=equity[-1], average_weight=frame.weight.mean(),
                trades=int(frame.trades.sum()), cap_sells=int(frame.cap_sell.sum()),
                upper_sells=int(frame.upper_sell.sum()), pool_blocked=int(frame.pool_blocked.sum()),
                budget_blocked=int(frame.budget_blocked.sum()),
                pool_longest=int(longest_run(frame.pool_blocked)),
                longest_underwater_sessions=longest,
                mdd_peak=str(dates[peak].date()), mdd_trough=str(dates[trough].date()),
                mdd_recovery=str(dates[recovery].date()) if recovery is not None else None,
                mdd_recovery_calendar_days=(dates[recovery]-dates[peak]).days if recovery is not None else None,
                fees=frame.fees.sum())


def longest_run(values):
    longest = run = 0
    for value in values:
        run = run+1 if value else 0
        longest = max(longest, run)
    return longest


def simulate(prices, caps, start, end, ticker='418660.KS', target=.225, band=.03, bh=False):
    sim = prices.loc[start:end]
    broker = BacktestBroker(INITIAL)
    repo = Mock(); repo.load_last_regime.return_value = None; repo.load_strategy_state.return_value = {}
    engine = DomesticQldVrBuyDeadbandEngine(broker=broker, repo=repo, logger=Mock())
    engine.planner.buy_deadband = band
    state = VrState()
    rows = []
    for i, (date, row) in enumerate(sim.iterrows()):
        price = float(row[ticker]); cap = float(min(1, target/(2*caps.loc[date])))
        broker.set_prices({ticker: price}); broker.set_date(date)
        pool_blocked = budget_blocked = False
        reason = 'hold'
        if bh:
            fills = []
            if i == 0:
                # Full-capital B&H benchmark, costs deducted; integer-share residual stays cash.
                qty = math.floor(broker.cash/(price*(1+SLIP)*(1+FEE)))
                fills = [broker._process_order_internal(Order(ticker, OrderAction.BUY, qty, price))]
                reason = 'initial buy and hold'
        else:
            portfolio = broker.get_portfolio()
            orders, reason, proposed = engine.planner.plan(date.strftime('%Y-%m-%d'), cap, portfolio, state)
            batch = broker.execute_orders(orders)
            fills = batch.actual_executions
            pool_blocked = ('buy blocked (pool=0,' in reason or
                            bool(orders and orders[0].action == OrderAction.BUY and not fills))
            budget_blocked = 'buy blocked (' in reason and 'budget=0,' in reason
            state = engine.planner.settle(proposed, batch)
            assert not state.reconciliation_required
        equity = broker.cash + broker.holdings.get(ticker, 0)*price
        assert broker.cash >= -1e-5
        rows.append(dict(date=date, equity=equity, cash=broker.cash,
                         weight=broker.holdings.get(ticker, 0)*price/equity,
                         cap=cap, value=state.value, reason=reason,
                         trades=len(fills), cap_sell=int(bool(fills) and reason=='VR: volatility cap sell'),
                         upper_sell=int(bool(fills) and reason=='VR: upper band sell'),
                         pool_blocked=pool_blocked, budget_blocked=budget_blocked,
                         fees=sum(f.fee for f in fills)))
    return pd.DataFrame(rows).set_index('date')


def main():
    one, two = load('133690'), load('418660')
    prices = pd.concat([one.Close.rename('133690.KS'), two.Close.rename('418660.KS')], axis=1).dropna()
    # Actual domestic engine computes indicators, including strict prior-session filtering.
    repo = Mock(); repo.load_last_regime.return_value=None; repo.load_strategy_state.return_value={}
    engine = DomesticQldVrBuyDeadbandEngine(broker=Mock(), repo=repo, logger=Mock())
    vols = {}
    for date in prices.index:
        engine.cycle_date = date.strftime('%Y-%m-%d')
        engine.calculate_strategy_indicators(CollectedData({'reference':one.loc[:date].tail(30)},20,engine.data_spec()))
        vols[date] = engine.realized_vol
    vols = pd.Series(vols)
    assert vols.gt(0).all() and np.isfinite(vols).all()
    start, end = prices.index[0].strftime('%Y-%m-%d'), prices.index[-1].strftime('%Y-%m-%d')
    periods = [('full',start,end)] + [(str(y),max(start,f'{y}-01-01'),min(end,f'{y}-12-31')) for y in range(2022,2027)]
    summaries = []
    for period, begin, finish in periods:
        for name, ticker, bh in [('VR_22.5_3','418660.KS',False),('BH_1x','133690.KS',True),('BH_2x','418660.KS',True)]:
            frame = simulate(prices,vols,begin,finish,ticker=ticker,bh=bh)
            summaries.append(dict(period=period,strategy=name,start=str(frame.index[0].date()),end=str(frame.index[-1].date()),sessions=len(frame),**metrics(frame)))
            frame.to_csv(DATA/f'{period}_{name}_daily.csv')
    grid = []
    for target in [.175,.20,.225,.25,.30]:
        for band in [.02,.03,.05]:
            frame=simulate(prices,vols,start,end,target=target,band=band)
            grid.append(dict(target=target,buy_deadband=band,**metrics(frame)))
    pd.DataFrame(summaries).to_csv(DATA/'summary.csv',index=False)
    pd.DataFrame(grid).to_csv(DATA/'sensitivity.csv',index=False)
    print(pd.DataFrame(summaries).to_string(index=False))
    print('GRID');print(pd.DataFrame(grid)[['target','buy_deadband','cagr','mdd','sharpe','trades']].to_string(index=False))


if __name__ == '__main__':
    main()
