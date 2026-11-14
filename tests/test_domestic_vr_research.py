import numpy as np
import pandas as pd
import pytest
from scripts.research.compare_domestic_vr import INITIAL, FEE, SLIP, metrics, simulate


def test_buy_hold_full_allocation_and_entry_cost():
    idx=pd.date_range('2024-01-01',periods=3)
    prices=pd.DataFrame({'133690.KS':[100.,80.,120.]},index=idx)
    frame=simulate(prices,pd.Series(.2,index=idx),'2024-01-01','2024-01-03',ticker='133690.KS',bh=True)
    quantity=int(INITIAL/(100*(1+SLIP)*(1+FEE)))
    residual=INITIAL-quantity*100*(1+SLIP)*(1+FEE)
    assert frame.iloc[-1].equity == pytest.approx(residual+quantity*120)
    assert frame.trades.sum()==1
    assert frame.iloc[0].equity < INITIAL


def test_recovery_uses_pre_trough_peak_and_tracks_unfinished_drawdown():
    idx=pd.date_range('2024-01-01',periods=6)
    frame=pd.DataFrame({'equity':np.array([1.1,.7,.9,1.1,1.2,1.1])*INITIAL,'weight':.6,
                        'trades':0,'cap_sell':0,'upper_sell':0,'pool_blocked':False,
                        'budget_blocked':False,'fees':0},index=idx)
    result=metrics(frame)
    assert result['mdd']==pytest.approx(.7/1.1-1)
    assert result['mdd_recovery']=='2024-01-04'
    assert result['mdd_recovery_calendar_days']==3
    assert result['longest_underwater_sessions']==2
