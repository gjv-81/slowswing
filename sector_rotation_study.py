"""
sector_rotation_study.py — does sector leadership at the signal date carry information?

For every retired setup in STS_holy_grail.xlsx: rank its sector's SPDR ETF vs SPY on
1-week (5d), 1-month (21d) and 3-month (63d) relative return, measured through the
session BEFORE entry (no look-ahead). Bucket: Leading (rank 1-4) / Middle (5-7) /
Lagging (8-11). Also rotation: rank rising / flat / falling vs 10 sessions earlier.
Report avg 4-wk return, win rate, excess vs SPY over the same 4 weeks, avg peak, avg dip.
Output: sector_rotation_study.xlsx. Data: daily_data_10y/*.csv (Yahoo, adjusted).
"""
import pandas as pd, numpy as np, os, sys
DIR=os.path.dirname(os.path.abspath(__file__)); D=os.path.join(DIR,"daily_data_10y")
ETF={"Technology":"XLK","Financial Services":"XLF","Healthcare":"XLV","Energy":"XLE","Industrials":"XLI",
     "Consumer Cyclical":"XLY","Consumer Defensive":"XLP","Utilities":"XLU","Basic Materials":"XLB",
     "Real Estate":"XLRE","Communication Services":"XLC"}
HORIZ={"1wk":5,"1mo":21,"3mo":63}
def load(t): return pd.read_csv(os.path.join(D,f"{t}.csv"),index_col=0,parse_dates=True)["Close"].dropna()
px={t:load(t) for t in list(ETF.values())+["SPY"]}
close=pd.DataFrame(px).dropna()
rel=close.div(close["SPY"],axis=0).drop(columns="SPY")          # each sector relative to SPY
xl=pd.ExcelFile(os.path.join(DIR,"STS_holy_grail.xlsx"))
tr=xl.parse("Tracker"); qg=xl.parse("QualGate")
sec=dict(zip(qg["ticker"].astype(str).str.upper(), qg["sector"]))
tr=tr[tr["phase"].astype(str)=="Retired"].copy()
tr["entry_date"]=pd.to_datetime(tr["entry_date"],errors="coerce"); tr=tr.dropna(subset=["entry_date","wk4_ret_pct"])
tr["sector"]=tr["ticker"].astype(str).str.upper().map(sec); tr["etf"]=tr["sector"].map(ETF)
tr=tr.dropna(subset=["etf"]); tr["published"]=tr["setup"].isin(["D200G","DLB","B2"])
spy=close["SPY"]
def spy_fwd(d,n=20):
    a=spy[spy.index>=d]
    return (a.iloc[min(n,len(a)-1)]/a.iloc[0]-1)*100 if len(a)>1 else np.nan
rows=[]
for _,r in tr.iterrows():
    asof=rel.index[rel.index<r["entry_date"]]
    if len(asof)<80: continue
    i=rel.index.get_loc(asof[-1]); out={}
    for h,n in HORIZ.items():
        perf=(rel.iloc[i]/rel.iloc[i-n]-1)*100                   # sector vs SPY over n sessions
        rank=perf.rank(ascending=False).astype(int)
        perf_prev=(rel.iloc[i-10]/rel.iloc[i-10-n]-1)*100; rank_prev=perf_prev.rank(ascending=False).astype(int)
        e=r["etf"]; out[f"{h}_rel"]=round(perf[e],2); out[f"{h}_rank"]=rank[e]; out[f"{h}_rankchg"]=rank_prev[e]-rank[e]
    rows.append({**{k:r[k] for k in ["entry_date","ticker","setup","qualgate","sector","etf","wk2_ret_pct","wk4_ret_pct","maxdip_4wk_pct","mfe_pct","published"]},
                 "spy_wk4":spy_fwd(r["entry_date"]),**out})
df=pd.DataFrame(rows); df["excess_wk4"]=df["wk4_ret_pct"]-df["spy_wk4"]
def bucket(rk): return "Leading (1-4)" if rk<=4 else "Middle (5-7)" if rk<=7 else "Lagging (8-11)"
def rot(c): return "Rising" if c>=2 else "Falling" if c<=-2 else "Flat"
def table(g,key):
    t=g.groupby(key).agg(n=("ticker","size"),avg_wk4=("wk4_ret_pct","mean"),win_wk4=("wk4_ret_pct",lambda s:(s>0).mean()*100),
        excess_vs_spy=("excess_wk4","mean"),avg_peak=("mfe_pct","mean"),avg_dip=("maxdip_4wk_pct","mean"),
        touched5=("mfe_pct",lambda s:(s>=5).mean()*100),touched10=("mfe_pct",lambda s:(s>=10).mean()*100)).round(1)
    return t
out={}
print(f"\nRetired setups with sector + 4-wk data: {len(df)}  (published Phoenix/Cruise: {int(df.published.sum())})")
print("SPY 4-wk forward return over the same windows, avg: %.1f%%"%df.spy_wk4.mean())
for h in HORIZ:
    df[f"{h}_bucket"]=df[f"{h}_rank"].map(bucket); df[f"{h}_rot"]=df[f"{h}_rankchg"].map(rot)
    t=table(df,f"{h}_bucket").reindex(["Leading (1-4)","Middle (5-7)","Lagging (8-11)"]); out[f"{h} leadership"]=t
    print(f"\n=== Sector leadership at signal — {h} relative to SPY ===\n{t.to_string()}")
    t2=table(df,f"{h}_rot").reindex(["Rising","Flat","Falling"]); out[f"{h} rotation"]=t2
    print(f"\n--- rotation ({h} rank vs 10 sessions earlier) ---\n{t2.to_string()}")
# by setup type x 1mo bucket
t3=table(df,["setup","1mo_bucket"]); out["setup x 1mo"]=t3; print("\n=== by setup x 1-month leadership ===\n",t3.to_string())
t4=table(df,"sector").sort_values("n",ascending=False); out["by sector"]=t4; print("\n=== by sector (all retired) ===\n",t4.to_string())
with pd.ExcelWriter(os.path.join(DIR,"sector_rotation_study.xlsx")) as w:
    for k,v in out.items(): v.to_excel(w,sheet_name=k[:31])
    df.sort_values("entry_date").to_excel(w,sheet_name="detail",index=False)
print("\nwrote sector_rotation_study.xlsx")
