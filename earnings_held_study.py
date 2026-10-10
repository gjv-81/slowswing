"""earnings_held_study.py — holdout confirmation for STS_EARNINGS_HELD_PREREG.md (daily_data_ext minus daily_data_v2)."""
import os, glob, numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from exh_build import score_and_signals
A="uw_archive/earnings_hist"
SPY=pd.read_csv("daily_data_v2/SPY.csv",index_col=0,parse_dates=True).sort_index(); SPY=SPY[~SPY.index.duplicated()]
v2=set(os.path.basename(f)[:-4] for f in glob.glob("daily_data_v2/*.csv"))
rows=[]
for f in sorted(glob.glob("daily_data_ext/*.csv")):
    t=os.path.basename(f)[:-4]
    if t in v2 or t in ("SPY","RSP"): continue
    try:
        px=pd.read_csv(f,index_col=0,parse_dates=True).sort_index(); px=px[~px.index.duplicated()]
        px=px[["Open","High","Low","Close","Volume"]].astype(float)
    except Exception: continue
    if len(px)<300: continue
    ef=f"{A}/{t}.csv"
    if not os.path.exists(ef): continue
    e=pd.read_csv(ef)
    if "source" not in e.columns or "report_date" not in e.columns: continue
    e=e[e.source=="company"].copy(); e["report_date"]=pd.to_datetime(e["report_date"],errors="coerce"); e=e.dropna(subset=["report_date"])
    idx=px.index; O,H,C=px.Open,px.High,px.Close
    react_pos={}
    for _,r in e.iterrows():
        pos=idx.searchsorted(r.report_date)
        if pos>=len(idx): continue
        if str(r.report_time)!="premarket":
            if idx[pos]==r.report_date: pos+=1
        if pos>=len(idx) or pos<1: continue
        react_pos[pos]=C.iloc[pos]/C.iloc[pos-1]-1
    if not react_pos: continue
    rp=np.array(sorted(react_pos)); so=SPY.Open.reindex(idx).values; sc=SPY.Close.reindex(idx).values
    score,sig=score_and_signals(px)
    for setup in ("S2","B2","DLB","D200G"):
        for i in sig[setup]:
            if i+61>=len(idx): continue
            e_px=O.iloc[i+1]
            if not np.isfinite(e_px) or not np.isfinite(so[i+1]) or not np.isfinite(sc[i+20]): continue
            r20=C.iloc[i+20]/e_px-1; xs20=r20-(sc[i+20]/so[i+1]-1); r60=C.iloc[i+60]/e_px-1; xs60=r60-(sc[i+60]/so[i+1]-1)
            peak20=H.iloc[i+1:i+21].max()/e_px-1
            cand=rp[(rp<=i)&(rp>=i-9)]
            if len(cand):
                p=int(cand.max()); react=react_pos[p]; since=i-p; held=C.iloc[i]>=C.iloc[p]
                if react>=0.04: cell=("HELD_3_9" if since>=3 else "HELD_0_2") if held else "FADED"
                elif react<=-0.04: cell="E_DOWN"
                else: cell="E_FLAT"
            else: cell="CONTROL"; since=None
            rows.append(dict(ticker=t,date=idx[i],setup=setup,cell=cell,since=since,r20=r20*100,xs20=xs20*100,xs60=xs60*100,peak20=peak20*100,year=idx[i].year))
df=pd.DataFrame(rows); df.to_parquet("earnings_held_rows.parquet",index=False)
order=["CONTROL","HELD_3_9","HELD_0_2","FADED","E_FLAT","E_DOWN"]
def tab(g,by):
    return g.groupby(by).agg(n=("ticker","size"),xs20=("xs20","mean"),win20=("r20",lambda s:(s>0).mean()*100),r20=("r20","mean"),xs60=("xs60","mean"),peak20=("peak20","mean"),t5=("peak20",lambda s:(s>=5).mean()*100)).round(2)
pool=df[df.setup.isin(["DLB","D200G","B2"])].assign(era=lambda d:np.where(d.year<=2020,"2016-2020","2021-2026"))
print(f"holdout tickers: {df.ticker.nunique()}  signals: {len(df)}  pooled: {len(pool)}")
P=tab(pool,"cell").reindex(order); print("\n=== HOLDOUT, POOLED DLB+D200G+B2 ===\n",P.to_string())
E=tab(pool,["era","cell"]); print("\n=== BY ERA ===\n",E.to_string())
S=tab(df,["setup","cell"]); print("\n=== BY SETUP ===\n",S.to_string())
c,p,h0=P.loc["CONTROL"],P.loc["HELD_3_9"],P.loc["HELD_0_2"]
era_ok=all(E.loc[(e,"HELD_3_9"),"xs20"]>=E.loc[(e,"CONTROL"),"xs20"] for e in ("2016-2020","2021-2026") if (e,"HELD_3_9") in E.index)
ok=(p.n>=60) and (p.xs20>=c.xs20+2.0) and (p.win20>=c.win20+5) and era_ok and (h0.xs20>=c.xs20-2)
print("\nPRE-REGISTERED VERDICT:", "PASS" if ok else "FAIL", f"(n={int(p.n)}, xs20 {p.xs20:+.2f} vs control {c.xs20:+.2f}, win {p.win20:.1f} vs {c.win20:.1f}, both eras ok={era_ok}, HELD_0_2 {h0.xs20:+.2f})")
with pd.ExcelWriter("earnings_held_results.xlsx") as w:
    P.to_excel(w,sheet_name="pooled"); E.to_excel(w,sheet_name="by era"); S.to_excel(w,sheet_name="by setup")
