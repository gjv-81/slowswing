#!/usr/bin/env python3.12
"""
flame_backtest.py — does UNUSUAL CALL BUYING during a signal's life predict
better short-term forward returns? Run AFTER flame_download.py.

PRE-COMMITTED DESIGN (set before looking at results):
  - Universe of days: every trading day in [entry .. entry+40td] of each
    DLB/D200G signal from the pilot window (the actionable life of a signal).
  - FLAME day (primary definition): call_vol >= 3x its own trailing-21-day
    median call_vol AND call_vol > put_vol that day. (Sensitivity: 2x and 4x
    reported alongside; premium-based variant reported for reference.)
  - Outcome: stock's forward 5td / 10td / 20td return from that day's close,
    compared with NON-flame days of the SAME signals (matched population).
  - READING RULES: the flame earns further work only if flame-day forward
    returns beat non-flame days by a clear margin (>= +1.5% at 10td or a
    consistent monotone gap across horizons) with n >= 150 flame days.
    Overlapping windows -> treat significance informally; this is a screen,
    not proof. Survivorship note: v2 universe = current constituents.

OUTPUT: console tables + STS_flame_study.xlsx
"""
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE=Path(__file__).resolve().parent
OPT=HERE/"options_pilot_daily.csv"
SIG=HERE/"options_pilot"/"_signals.csv"
DATA=HERE/"daily_data_v2"

opt=pd.read_csv(OPT,parse_dates=["date"])
sig=pd.read_csv(SIG)
sig["signals"]=sig["signals"].apply(eval)          # list of date strings
print(f"option days: {len(opt)} across {opt.ticker.nunique()} tickers")

rows=[]
for _,s in sig.iterrows():
    t=s["ticker"]
    o=opt[opt.ticker==t].set_index("date").sort_index()
    if len(o)<25: continue
    try:
        px=pd.read_csv(DATA/f"{t}.csv",index_col=0,parse_dates=True).sort_index()["Close"]
    except Exception: continue
    o=o.reindex(o.index.union(px.index)).sort_index()
    med=o["call_vol"].rolling(21,min_periods=10).median().shift(1)   # trailing, no look-ahead
    ratio=o["call_vol"]/med
    for sd in s["signals"]:
        sd=pd.Timestamp(sd)
        life=px.index[(px.index>sd)][:41]           # entry next day .. +40td
        for i,dt in enumerate(life):
            if dt not in o.index or not np.isfinite(o.loc[dt,"call_vol"]): continue
            r=ratio.loc[dt] if dt in ratio.index else np.nan
            if not np.isfinite(r): continue
            cv,pv=o.loc[dt,"call_vol"],o.loc[dt,"put_vol"]
            fut=px[px.index>dt]
            f5 =(fut.iloc[4] /px.loc[dt]-1)*100 if len(fut)>4  else np.nan
            f10=(fut.iloc[9] /px.loc[dt]-1)*100 if len(fut)>9  else np.nan
            f20=(fut.iloc[19]/px.loc[dt]-1)*100 if len(fut)>19 else np.nan
            rows.append(dict(ticker=t,sig=str(sd.date()),day=i,ratio=r,
                             cgtp=cv>pv,f5=f5,f10=f10,f20=f20))
ev=pd.DataFrame(rows).dropna(subset=["f10"])
print(f"signal-days analyzed: {len(ev)}\n")

def table(name,mask):
    g,ng=ev[mask],ev[~mask]
    out=[]
    for lab,d in [("FLAME",g),("no flame",ng)]:
        out.append(dict(cohort=lab,n=len(d),
            f5=round(d.f5.mean(),2),f10=round(d.f10.mean(),2),f20=round(d.f20.mean(),2),
            win10=round(100*(d.f10>0).mean(),1)))
    tt=pd.DataFrame(out)
    diff=tt.loc[0,"f10"]-tt.loc[1,"f10"] if tt.loc[0,"n"] else np.nan
    print(f"== {name} ==  (10td gap: {diff:+.2f}%)");print(tt.to_string(index=False));print()
    return tt

t3=table("PRIMARY: call_vol >= 3x trailing median + calls>puts",(ev.ratio>=3)&ev.cgtp)
t2=table("sensitivity 2x",(ev.ratio>=2)&ev.cgtp)
t4=table("sensitivity 4x",(ev.ratio>=4)&ev.cgtp)

with pd.ExcelWriter(HERE/"STS_flame_study.xlsx",engine="openpyxl") as xw:
    r=0
    for nm,tt in [("PRIMARY 3x",t3),("2x",t2),("4x",t4)]:
        pd.DataFrame([{"":nm}]).to_excel(xw,sheet_name="Flame",index=False,header=False,startrow=r);r+=1
        tt.to_excel(xw,sheet_name="Flame",index=False,startrow=r);r+=len(tt)+2
print("wrote STS_flame_study.xlsx")
print("READING RULE: needs >= +1.5% 10td gap (or monotone) with n>=150 flame days.")
