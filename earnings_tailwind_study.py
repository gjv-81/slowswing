"""earnings_tailwind_study.py — see STS_EARNINGS_TAILWIND_PREREG.md. Output: earnings_tailwind_results.xlsx"""
import os, glob, numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from exh_build import load, score_and_signals
A="uw_archive/earnings_hist"
SPY=pd.read_csv("daily_data_v2/SPY.csv",index_col=0,parse_dates=True).sort_index(); SPY=SPY[~SPY.index.duplicated()]
rows=[]
for f in sorted(glob.glob("daily_data_v2/*.csv")):
    t=os.path.basename(f)[:-4]
    if t in ("SPY","RSP"): continue
    px,_=load(t)
    if px is None or len(px)<300: continue
    ef=f"{A}/{t}.csv"
    if not os.path.exists(ef): continue
    e=pd.read_csv(ef)
    if "source" not in e.columns or "report_date" not in e.columns: continue
    e=e[e.source=="company"].copy()
    e["report_date"]=pd.to_datetime(e["report_date"],errors="coerce"); e=e.dropna(subset=["report_date"])
    idx=px.index; O,H,C=px.Open,px.High,px.Close
    # reaction session index for each report
    react_pos={}
    for _,r in e.iterrows():
        pos=idx.searchsorted(r.report_date)
        if pos>=len(idx): continue
        if str(r.report_time)!="premarket":           # postmarket / unknown -> next session
            if idx[pos]==r.report_date: pos+=1
        if pos>=len(idx) or pos<1: continue
        est,act=pd.to_numeric(r.street_mean_est,errors="coerce"),pd.to_numeric(r.actual_eps,errors="coerce")
        react_pos[pos]=dict(react=C.iloc[pos]/C.iloc[pos-1]-1, beat=(None if pd.isna(est) or pd.isna(act) else bool(act>est)))
    if not react_pos: continue
    rp=np.array(sorted(react_pos)); so=SPY.Open.reindex(idx).values; sc=SPY.Close.reindex(idx).values
    score,sig=score_and_signals(px)
    for setup in ("S2","B2","DLB","D200G"):
        for i in sig[setup]:
            if i+61>=len(idx): continue
            e_px=O.iloc[i+1]
            if not np.isfinite(e_px) or not np.isfinite(so[i+1]): continue
            r20=C.iloc[i+20]/e_px-1; r60=C.iloc[i+60]/e_px-1
            xs20=r20-(sc[i+20]/so[i+1]-1); xs60=r60-(sc[i+60]/so[i+1]-1)
            peak20=H.iloc[i+1:i+21].max()/e_px-1
            r5=C.iloc[i+5]/e_px-1; r10=C.iloc[i+10]/e_px-1
            xs5=r5-(sc[i+5]/so[i+1]-1); xs10=r10-(sc[i+10]/so[i+1]-1)
            peak5=H.iloc[i+1:i+6].max()/e_px-1; peak10=H.iloc[i+1:i+11].max()/e_px-1
            # most recent reaction session within prior 10 sessions (i-9..i)
            cand=rp[(rp<=i)&(rp>=i-9)]
            if len(cand):
                p=int(cand.max()); d=react_pos[p]; react=d["react"]; faded=C.iloc[i]<C.iloc[p]
                cell=("E_UP_FADED" if faded else "E_UP_HELD") if react>=0.04 else ("E_DOWN" if react<=-0.04 else "E_FLAT")
                beat=d["beat"]; since=i-p
            else:
                cell="CONTROL"; react=np.nan; faded=None; beat=None; since=None
            rows.append(dict(ticker=t,date=idx[i],setup=setup,cell=cell,react=react,beat=beat,faded=faded,since=since,
                             r20=r20*100,xs20=xs20*100,xs60=xs60*100,peak20=peak20*100,year=idx[i].year,
                             r5=r5*100,xs5=xs5*100,r10=r10*100,xs10=xs10*100,peak5=peak5*100,peak10=peak10*100))
df=pd.DataFrame(rows); df.to_parquet("earnings_tailwind_rows.parquet",index=False)
def tab(g,by):
    return g.groupby(by).agg(n=("ticker","size"),xs20=("xs20","mean"),win20=("r20",lambda s:(s>0).mean()*100),
                             r20=("r20","mean"),xs60=("xs60","mean"),peak20=("peak20","mean"),t5=("peak20",lambda s:(s>=5).mean()*100)).round(2)
order=["CONTROL","E_UP_FADED","E_UP_HELD","E_FLAT","E_DOWN"]
pool=df[df.setup.isin(["DLB","D200G","B2"])]
out={}
print(f"signals: {len(df)}  pooled DLB/D200G/B2: {len(pool)}")
out["pooled"]=tab(pool,"cell").reindex(order); print("\n=== POOLED DLB+D200G+B2 ===\n",out["pooled"].to_string())
out["by setup"]=tab(df,["setup","cell"]); print("\n=== BY SETUP ===\n",out["by setup"].to_string())
pool=pool.assign(era=np.where(pool.year<=2020,"2016-2020","2021-2026"))
out["by era"]=tab(pool,["era","cell"]); print("\n=== BY ERA (pooled) ===\n",out["by era"].to_string())
up=pool[pool.cell.isin(["E_UP_FADED","E_UP_HELD"])].assign(beat=lambda d:d.beat.map({True:"beat",False:"miss"}).fillna("unknown"))
out["gap-up by beat"]=tab(up,["cell","beat"]); print("\n=== GAP-UP CELLS BY BEAT/MISS ===\n",out["gap-up by beat"].to_string())
c,p=out["pooled"].loc["CONTROL"],out["pooled"].loc["E_UP_FADED"]; h=out["pooled"].loc["E_UP_HELD"]
ok=(p.n>=60) and (p.xs20>=c.xs20+2.0) and (p.win20>=c.win20+5) and (p.xs60>=c.xs60) and (h.xs20>=c.xs20)
print("\nPRE-REGISTERED VERDICT:", "PASS" if ok else "FAIL", f"(n={int(p.n)}, xs20 {p.xs20:+.2f} vs control {c.xs20:+.2f}, win {p.win20:.1f} vs {c.win20:.1f}, xs60 {p.xs60:+.2f} vs {c.xs60:+.2f}, held {h.xs20:+.2f})")
with pd.ExcelWriter("earnings_tailwind_results.xlsx") as w:
    for k,v in out.items(): v.to_excel(w,sheet_name=k[:31])
