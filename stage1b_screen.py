import numpy as np, pandas as pd
import stage1_screen as s1
s1.PRIOR=set()   # Amendment 1: bar 2.5 for all N features
df=pd.read_parquet("fast_features.parquet")
n=pd.read_parquet("n_features.parquet")
df=df.merge(n,on=["ticker","date"],how="left")
df=df[(df.close>=10)&(df.dollar_vol_med20>=20e6)&(df.opt_vol_med21>=1000)].copy()
feats=["N1_smirk","N2_smirk_chg5","N3_iv_minus_rv","N4_iv_chg5","N5_opt_stock_vol","N6_borrow_fee"]
# borrow control: drop each day's top 10% of names by borrow fee
cut=df.groupby("date")["N6_borrow_fee"].transform(lambda s:s.quantile(0.90))
easy=df[(df.N6_borrow_fee<=cut)|df.N6_borrow_fee.isna()]
rows=[]
for f in feats:
    r=s1.screen(df,f); r["tickers"]=df.loc[df[f].notna(),"ticker"].nunique()
    w=df.loc[df[f].notna(),"date"]; r["window"]=f"{w.min():%b %d %Y} to {w.max():%b %d %Y}"
    e=s1.screen(easy,f) if f!="N6_borrow_fee" else None
    r["easy_spread_d3"]=e["spread_d3"] if e else np.nan; r["easy_t"]=e["t_d3"] if e else np.nan
    r["share_kept_easy"]=(e["spread_d3"]/r["spread_d3"]) if e and r["spread_d3"] else np.nan
    for name,sub in (("core",df[df.core==1]),("ext",df[df.core==0])):
        x=s1.screen(sub,f); r[f"{name}_spread_d3"]=x["spread_d3"] if x else np.nan; r[f"{name}_t"]=x["t_d3"] if x else np.nan
    dc=df.copy()
    for k in range(1,6): dc[f"xs{k}"]=dc[f"xs{k}"].clip(*dc[f"xs{k}"].quantile([0.01,0.99]))
    c=s1.screen(dc,f); r["capped_spread_d3"]=c["spread_d3"]; r["capped_t"]=c["t_d3"]
    rows.append(r)
    print(f"{f:20s} d3 {r['spread_d3']:+.3f}% t {r['t_d3']:+.2f} halves {r['spread_d3_h1']:+.3f}/{r['spread_d3_h2']:+.3f} mono {r['mono_steps']} easy {r['easy_spread_d3']:+.3f} (t {r['easy_t']:+.2f}) capped t {r['capped_t']:+.2f} {'PASS' if r['PASS'] else 'fail: '+r['why']}")
pd.DataFrame(rows).to_csv("stage1b_results.csv",index=False)
