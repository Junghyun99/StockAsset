"""Constant effective annual cash/risk-free rate scenarios, not historical rate estimates."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.research.compare_domestic_vr import DATA, load, simulate, metrics


def main():
    one,two=load('133690'),load('418660')
    prices=pd.concat([one.Close.rename('133690.KS'),two.Close.rename('418660.KS')],axis=1).dropna()
    vols=one.Close.pct_change(fill_method=None).rolling(20).std(ddof=1).shift(1)*np.sqrt(252)
    vols=vols.reindex(prices.index)
    assert vols.gt(0).all()
    start,end=prices.index[0].strftime('%Y-%m-%d'),prices.index[-1].strftime('%Y-%m-%d')
    periods=[('full',start,end)]+[(str(y),max(start,f'{y}-01-01'),min(end,f'{y}-12-31')) for y in range(2022,2027)]
    rows=[];grid=[]
    for rate in [0,.02,.03,.04]:
        for period,begin,finish in periods:
            for name,ticker,bh in [('VR_22.5_3','418660.KS',False),('VR_17.5_5','418660.KS',False),('BH_1x','133690.KS',True),('BH_2x','418660.KS',True)]:
                target,band=(.175,.05) if name=='VR_17.5_5' else (.225,.03)
                frame=simulate(prices,vols,begin,finish,ticker=ticker,bh=bh,cash_rate=rate,target=target,band=band)
                rows.append(dict(rate=rate,period=period,strategy=name,**metrics(frame,risk_free_rate=rate)))
                if period=='full':
                    frame.to_csv(DATA/f'interest_{rate:.2f}_{name}_daily.csv')
        for target in [.175,.20,.225,.25,.30]:
            for band in [.02,.03,.05]:
                frame=simulate(prices,vols,start,end,target=target,band=band,cash_rate=rate)
                grid.append(dict(rate=rate,target=target,buy_deadband=band,**metrics(frame,risk_free_rate=rate)))
    summary=pd.DataFrame(rows);sensitivity=pd.DataFrame(grid)
    # Zero-rate replay must reproduce the previously published baseline, not a new model.
    old=pd.read_csv(DATA/'summary.csv');old['period']=old['period'].astype(str)
    joined=summary.query('rate==0').merge(old,on=['period','strategy'],suffixes=('_new','_old'))
    assert len(joined)==len(old)
    for col in ['cagr','mdd','sharpe','final_value','trades','cap_sells','pool_blocked']:
        np.testing.assert_allclose(joined[col+'_new'],joined[col+'_old'],rtol=1e-10,atol=1e-10)
    summary.to_csv(DATA/'interest_summary.csv',index=False)
    sensitivity.to_csv(DATA/'interest_sensitivity.csv',index=False)
    print(summary.query('period=="full"').to_string(index=False))
    for rate in [0,.02,.03,.04]:
        bh=summary.query('rate==@rate and period=="full" and strategy=="BH_1x"').iloc[0]
        g=sensitivity.query('rate==@rate')
        winners=g[(g.cagr>bh.cagr)&(g.mdd>bh.mdd)&(g.sharpe>bh.sharpe)]
        print('RATE',rate,'ALL THREE WINNERS',len(winners))
        print(winners[['target','buy_deadband','cagr','mdd','sharpe']].to_string(index=False))
        print('BEST SHARPE',g.sort_values('sharpe',ascending=False).iloc[0].to_dict())


if __name__=='__main__':
    main()
