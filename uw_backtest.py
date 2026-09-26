#!/usr/bin/env python3.12
"""
uw_backtest.py — STAGE-2 pre-registered flame test on UW ask-side flow.
Registration: STS_FLAME_UW_PREREG.md (do not change bars after seeing output).

Flame day (stage-2): call_volume_ask_side >= 3x its own trailing-21d median
                     AND call_volume_ask_side > put_volume_ask_side.
Grid: {S2,B2} x {1,2,3 flat days} x d1..d5 win rates (flat = each prior day AND
flame day within +/-1%; control = same flat/setup days w/o flame; ref = day close).
PRIMARY: S2x3flat d1 (>=57% & >=+6pts, n>=40) ; B2x2flat d3 (>=+6pts, n>=30).
Also: matched same-day-move test, all four setups.
"""
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE=Path(__file__).resolve().parent
ARCH=HERE/"uw_archive"/"options_volume"
DATA=HERE/"daily_data_v2"

sigs=[]
for f in ["options_pilot/_signals.csv","options_pilot_cruise/_signals.csv"]:
    s=pd.read_csv(HERE/f); s["signals"]=s["signals"].apply(eval); sigs.append(s)
sig=pd.concat(sigs)

rows=[]
for _,s in sig.iterrows():
    t=s["ticker"]
    fp=ARCH/f"{t}.csv"
    if not fp.exists(): continue
    o=pd.read_csv(fp,parse_dates=["date"]).set_index("date").sort_index()
    need=["call_volume_ask_side","put_volume_ask_side"]
    if not all(c in o.columns for c in need): continue
    try: px=pd.read_csv(DATA/f"{t}.csv",index_col=0,parse_dates=True).sort_index()
    except Exception: continue
    C,H=px["Close"],px["High"]
    oh=(C/H.rolling(252).max()-1)*100
    d200=(C/C.rolling(200).mean()-1)*100
    med=o["call_volume_ask_side"].rolling(21,min_periods=10).median().shift(1)
    ratio=o["call_volume_ask_side"]/med.replace(0,np.nan)
    dayret=C.pct_change()*100
    for sd in s["signals"]:
        sd=pd.Timestamp(sd)
        if sd not in oh.index: continue
        ohv,dv=oh.loc[sd],d200.loc[sd]
        if ohv<=-25: setup="D200G" if dv>0 else "DLB"
        elif ohv<=-10: setup="B2"
        else: setup="S2"
        for dt in C.index[(C.index>sd)][:41]:
            if dt not in o.index: continue
            r=ratio.get(dt,np.nan)
            if not np.isfinite(r): continue
            i=C.index.get_loc(dt)
            if i<4 or i+5>=len(C): continue
            prior=[abs(dayret.iloc[i-k]) for k in range(1,4)]
            rows.append(dict(setup=setup,
                flame=(r>=3)&(o.loc[dt,"call_volume_ask_side"]>o.loc[dt,"put_volume_ask_side"]),
                d0=dayret.iloc[i],
                flat1=prior[0]<=1, flat2=prior[0]<=1 and prior[1]<=1,
                flat3=all(p<=1 for p in prior),
                **{f"f{n}":(C.iloc[i+n]/C.iloc[i]-1)*100 for n in range(1,6)}))
ev=pd.DataFrame(rows)
print(f"signal-days: {len(ev)} | ask-side flames: {ev.flame.sum()}")
print("setups:",ev.groupby("setup").size().to_dict(),"\n")

def wins(g): return "  ".join(f"d{n}:{100*(g[f'f{n}']>0).mean():5.1f}%" for n in range(1,6))
print("== FULL GRID: flat-then-flame (day itself also within ±1%), control = flat no-flame ==")
quiet=ev[ev.d0.abs()<=1]
for st in ["S2","B2","DLB","D200G"]:
    g=quiet[quiet.setup==st]
    for nm,mask in [("1flat",g.flat1),("2flat",g.flat2),("3flat",g.flat3)]:
        q=g[mask]; fl,nf=q[q.flame],q[~q.flame]
        if len(fl)<15: continue
        tag=" <-- PRIMARY" if (st=="S2" and nm=="3flat") or (st=="B2" and nm=="2flat") else ""
        print(f"{st:6s} {nm:6s} FLAME n={len(fl):4d}  {wins(fl)}{tag}")
        print(f"{'':6s} {'':6s} ctrl  n={len(nf):5d}  {wins(nf)}\n")
print("== all-days matched (same-day-move buckets), 3d gap per setup ==")
ev["b"]=pd.cut(ev.d0,[-99,-2,0,2,5,99],labels=["<-2","-2..0","0..2","2..5",">5"])
for st in ["S2","B2","DLB","D200G"]:
    e2=ev[ev.setup==st]; wf=[]
    for b in ["<-2","-2..0","0..2","2..5",">5"]:
        g=e2[e2.b==b]; fl,nf=g[g.flame],g[~g.flame]
        if len(fl)<20: continue
        wf.append((len(fl),fl.f3.mean()-nf.f3.mean()))
    if wf:
        gp=sum(n*g for n,g in wf)/sum(n for n,_ in wf)
        print(f"  {st}: flames n={int(e2.flame.sum()):4d}  matched 3d gap {gp:+.2f}%")
print("\nPRIMARY BARS: S2x3flat d1 >=57% AND >=+6pts vs ctrl (n>=40);"
      " B2x2flat d3 >=+6pts (n>=30). Neighbors must not contradict.")
