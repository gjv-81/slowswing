#!/usr/bin/env python3
"""
stage1_screen.py : Stage 1 of STS_FAST_PREREG.md, each feature tested ALONE.

Method (as preregistered):
  * Eligible rows: price >= $10, 20d median dollar volume >= $20M,
    21d median option volume >= 1,000 contracts, forward returns present.
  * Each day, eligible stocks with the feature are ranked into 5 buckets
    (ties broken by order; binary flags use 2 groups: flag on vs off).
  * Per day: mean excess return of each bucket, d1..d5. Spread = top minus bottom.
  * t statistic of the daily d3 spread, Newey West with lag = horizon (overlapping
    3 day returns make neighbouring days correlated; this is the honest correction).
  * Halves: window split at the feature's median date.
  * PASS: same sign in both halves AND |t| >= 2.0 (F1, F2) or 2.5 (all others)
          AND >= 3 of 4 bucket steps in the direction of the spread.
Costs (0.10%) are subtracted from bucket levels; they cancel in the spread.
"""
import numpy as np, pandas as pd, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
COST=0.0010
PRIOR={"F1_ask_call_surge","F2_dir_prem_z"}
MIN_PER_DAY=25

def nw_t(x, lag):
    x=np.asarray(x,float); x=x[np.isfinite(x)]; n=len(x)
    if n<30: return np.nan, n
    m=x.mean(); e=x-m
    g0=(e@e)/n; s=g0
    for L in range(1,lag+1):
        w=1-L/(lag+1); s+=2*w*(e[L:]@e[:-L])/n
    return m/np.sqrt(s/n), n

def screen(df, feat, binary=False):
    d=df[["date",feat]+[f"xs{k}" for k in range(1,6)]].dropna(subset=[feat,"xs5"])
    cnt=d.groupby("date")[feat].transform("size")
    d=d[cnt>=MIN_PER_DAY]
    if d.empty: return None
    if binary:
        d["b"]=d[feat].astype(int)
        nb=2
        ok=d.groupby("date")["b"].transform(lambda s:s.nunique()==2)
        d=d[ok]
        if d.empty: return None
    else:
        r=d.groupby("date")[feat].rank(method="first",pct=True)
        d["b"]=np.minimum((r*5).apply(np.ceil),5).astype(int)-1
        nb=5
    daily=d.groupby(["date","b"])[[f"xs{k}" for k in range(1,6)]].mean().unstack("b")
    out={"feature":feat,"days":daily.shape[0],"rows":len(d),"tickers":None}
    for k in range(1,6):
        lv=daily[f"xs{k}"]
        out[f"spread_d{k}"]=(lv[nb-1]-lv[0]).mean()*100
    lv3=daily["xs3"]; sp=(lv3[nb-1]-lv3[0])
    t,n=nw_t(sp.values,3); out["t_d3"]=t
    dates=sp.index; mid=dates[len(dates)//2]
    out["spread_d3_h1"]=sp[dates<mid].mean()*100; out["spread_d3_h2"]=sp[dates>=mid].mean()*100
    means=[(lv3[b].mean()-COST)*100 for b in range(nb)]
    for b in range(nb): out[f"Q{b+1}_d3"]=means[b]
    sign=np.sign(out["spread_d3"])
    steps=np.sign(np.diff(means))
    out["mono_steps"]=int((steps==sign).sum()) if nb==5 else None
    # win rates of top and bottom bucket at d3 (pooled rows)
    top=d[d.b==nb-1]["xs3"]-COST; bot=d[d.b==0]["xs3"]-COST
    out["top_win_d3"]=(top>0).mean()*100; out["bot_win_d3"]=(bot>0).mean()*100
    out["top_med_d3"]=top.median()*100; out["bot_med_d3"]=bot.median()*100
    bar=2.0 if feat in PRIOR else 2.5
    same=np.sign(out["spread_d3_h1"])==np.sign(out["spread_d3_h2"])==sign
    mono_ok=True if nb==2 else out["mono_steps"]>=3
    out["bar"]=bar
    out["PASS"]= bool(same and abs(t)>=bar and mono_ok) if np.isfinite(t) else False
    out["why"]=("" if out["PASS"] else
        ";".join(x for x,c in [("sign flips between halves",not same),(f"|t|<{bar}",not(abs(t)>=bar)),("not monotonic",not mono_ok)] if c))
    return out

def main():
    df=pd.read_parquet(HERE/"fast_features.parquet")
    elig=(df.close>=10)&(df.dollar_vol_med20>=20e6)&(df.opt_vol_med21>=1000)
    df=df[elig].copy()
    print(f"eligible rows {len(df):,} tickers {df.ticker.nunique()} days {df.date.nunique()}")
    feats=[c for c in df.columns if c[:2] in ("F1","F2","F3","F4","F5","F6","F7","F8","F9","P1","P2","P3","P4","P5","P6","P7") or c[:3] in ("F10","F11","F12") or c.startswith("I") or c.startswith("act_")]
    feats=[c for c in feats if c not in ("I",)]
    binary={"F8b_neg_gex","P4_above_200","act_S2","act_B2","act_DLB","act_D200G"}
    res=[]
    for f in feats:
        r=screen(df,f,f in binary)
        if r:
            r["tickers"]=df.loc[df[f].notna(),"ticker"].nunique()
            r["window"]=f"{df.loc[df[f].notna(),'date'].min().date()} to {df.loc[df[f].notna(),'date'].max().date()}"
            res.append(r); print(f"{f:28s} d3 spread {r['spread_d3']:+.3f}%  t {r['t_d3']:+.2f}  halves {r['spread_d3_h1']:+.3f}/{r['spread_d3_h2']:+.3f}  mono {r['mono_steps']}  {'PASS' if r['PASS'] else 'fail: '+r['why']}")
    out=pd.DataFrame(res)
    out.to_csv(HERE/"stage1_results.csv",index=False)

    # robustness (not used for pass/fail): capped returns, core vs expansion
    rob=[]
    lo,hi=df["xs3"].quantile([0.01,0.99])
    dc=df.copy()
    for k in range(1,6): dc[f"xs{k}"]=dc[f"xs{k}"].clip(*dc[f"xs{k}"].quantile([0.01,0.99]))
    for f in feats:
        row={"feature":f}
        r=screen(dc,f,f in binary); row["capped_spread_d3"]=r["spread_d3"] if r else np.nan; row["capped_t"]=r["t_d3"] if r else np.nan
        for name,sub in (("core",df[df.core==1]),("ext",df[df.core==0])):
            r=screen(sub,f,f in binary)
            row[f"{name}_spread_d3"]=r["spread_d3"] if r else np.nan; row[f"{name}_t"]=r["t_d3"] if r else np.nan
        rob.append(row)
    pd.DataFrame(rob).to_csv(HERE/"stage1_robustness.csv",index=False)
    print("done")

if __name__=="__main__": main()
