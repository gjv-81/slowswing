#!/usr/bin/env python3.12
"""
x200_backtest.py — walk-forward test of the pre-registered X200 definition
(STS_X200_PREREG.md). Cohorts: daily_data_v2 (10y, primary) and
daily_data_slow_ext (quality mid/large expansion, transfer) if present.
RUN:  python3.12 x200_backtest.py            (price data only, no network)
"""
import glob, os
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE=Path(__file__).resolve().parent
def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def signals_for(fp):
    d=pd.read_csv(fp,index_col=0,parse_dates=True).sort_index()
    if len(d)<400: return []
    C,H,O=d["Close"],d["High"],d["Open"]
    sma=C.rolling(200).mean()
    hi52=H.rolling(252).max()
    washed=((C/hi52-1)<=-0.25).rolling(126).max()          # washed out in prior ~6mo
    below=(C<sma).rolling(60).sum()                         # bars below line in prior 60
    above=(C>sma)
    streak=above.groupby((~above).cumsum()).cumcount()+1    # consecutive closes above
    streak[~above]=0
    qqe=(rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50
    out=[]; last=-999
    idx=np.where((C.values>=25))[0]
    for i in range(260,len(d)-61):
        if C.iloc[i]<25: continue
        if not (above.iloc[i] and streak.iloc[i]>=3 and streak.iloc[i]<=10): continue
        if not (washed.iloc[i-1]==1): continue
        if not (below.iloc[i-1]>=20): continue
        if not (qqe.iloc[i]<0.20): continue
        if i-last<40: continue
        last=i
        e=float(O.iloc[i+1])
        out.append(dict(date=d.index[i],entry_date=d.index[i+1],
            w4=(float(C.iloc[i+21])/e-1)*100,
            w12=(float(C.iloc[i+61])/e-1)*100,
            dip=(float(d["Low"].iloc[i+1:i+62].min())/e-1)*100))
    return out

def run(folder,label,spy):
    rows=[]
    for fp in sorted(glob.glob(str(HERE/folder/"*.csv"))):
        t=os.path.splitext(os.path.basename(fp))[0].upper()
        if t in {"SPY","QQQ","RSP"}: continue
        try:
            for s in signals_for(fp): rows.append(dict(ticker=t,**s))
        except Exception: pass
    ev=pd.DataFrame(rows)
    if len(ev)==0: print(f"{label}: no signals"); return None
    # excess vs SPY over same 60td window
    exc=[]
    for r in ev.itertuples():
        sp=spy[spy.index>=r.entry_date]
        exc.append(r.w12-((float(sp["Close"].iloc[60])/float(sp["Open"].iloc[0])-1)*100 if len(sp)>60 else np.nan))
    ev["excess"]=exc
    print(f"\n== {label}: {len(ev)} X200 signals, {ev.ticker.nunique()} tickers, "
          f"{ev.date.min().date()} -> {ev.date.max().date()} ==")
    for col,nm in [("w4","wk4"),("w12","wk12")]:
        print(f"  {nm:5s} win={100*(ev[col]>0).mean():5.1f}%  avg={ev[col].mean():+6.2f}%  med={ev[col].median():+6.2f}%")
    print(f"  excess vs SPY (wk12): {ev.excess.mean():+.2f}%  |  med dip {ev.dip.median():.2f}%  worst {ev.dip.min():.2f}%")
    w=ev[ev.w12>0]; l=ev[ev.w12<=0]
    print(f"  wk12 avgWin {w.w12.mean():+.2f}%  avgLoss {l.w12.mean():+.2f}%  ratio {abs(w.w12.mean()/l.w12.mean()):.2f}")
    ev["yr"]=ev.date.dt.year
    print("  by year (n / wk12win / wk12avg):")
    for y,g in ev.groupby("yr"):
        print(f"    {y}: {len(g):4d} / {100*(g.w12>0).mean():5.1f}% / {g.w12.mean():+6.2f}%")
    return ev

def main():
    spy=pd.read_csv(HERE/"daily_data_v2"/"SPY.csv",index_col=0,parse_dates=True).sort_index()
    ev=run("daily_data_v2","PRIMARY (v2 universe, 10y)",spy)
    if (HERE/"daily_data_slow_ext").exists():
        run("daily_data_slow_ext","TRANSFER (quality mid/large expansion)",spy)
    if ev is not None:
        ev.to_csv(HERE/"x200_signals.csv",index=False)
        print("\nwrote x200_signals.csv")
    print("\nBARS (prereg): v2 n>=300, wk12 avg>=+8%, excess>=+2%, win>=55%.")

if __name__=="__main__":
    main()
