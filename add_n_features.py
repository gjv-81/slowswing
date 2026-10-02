"""Amendment 1 features N1..N6 (no lookahead). Output n_features.parquet keyed by ticker, date."""
import glob, os, numpy as np, pandas as pd
A="uw_archive"
ff=pd.read_parquet("fast_features.parquet",columns=["ticker","date","core"])
parts=[]
for t,g in ff.groupby("ticker"):
    idx=pd.DatetimeIndex(sorted(g.date))
    px=None
    for d in ("daily_data_v2","daily_data_ext"):
        p=f"{d}/{t}.csv"
        if os.path.exists(p): px=pd.read_csv(p,index_col=0,parse_dates=True).sort_index(); px=px[~px.index.duplicated()]; break
    if px is None: continue
    out=pd.DataFrame(index=px.index)
    # N1, N2 smirk (risk_reversal = put IV minus call IV, checked: defensive names positive, meme names negative)
    f=f"{A}/rr_skew_jan27/{t}.csv"
    if os.path.exists(f):
        r=pd.read_csv(f)
        if "risk_reversal" in r:
            s=r.assign(date=pd.to_datetime(r.date)).drop_duplicates("date").set_index("date")["risk_reversal"].astype(float)
            s=s.reindex(px.index)
            out["N1_smirk"]=s; out["N2_smirk_chg5"]=s-s.shift(5)
    # N3, N4 implied vol (UW realized column is forward looking: NOT used)
    f=f"{A}/vol_realized_3y/{t}.csv"
    if os.path.exists(f):
        v=pd.read_csv(f)
        if "implied_volatility" in v:
            iv=v.assign(date=pd.to_datetime(v.date)).drop_duplicates("date").set_index("date")["implied_volatility"].astype(float).reindex(px.index)
            lr=np.log(px.Close).diff()
            rv=lr.rolling(21,min_periods=18).std()*np.sqrt(252)     # trailing, ends at t
            out["N3_iv_minus_rv"]=iv-rv; out["N4_iv_chg5"]=iv-iv.shift(5)
    # N5 option to stock volume
    for d in ("options_volume","options_volume_ext"):
        f=f"{A}/{d}/{t}.csv"
        if os.path.exists(f):
            o=pd.read_csv(f,parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index()
            ov=(pd.to_numeric(o.call_volume,errors="coerce")+pd.to_numeric(o.put_volume,errors="coerce")).reindex(px.index)
            sv=px.Volume/100
            out["N5_opt_stock_vol"]=np.log(ov.rolling(5,min_periods=4).mean()/sv.rolling(5,min_periods=4).mean().replace(0,np.nan))
            break
    # N6 borrow fee
    f=f"{A}/borrow_daily/{t}.csv"
    if os.path.exists(f):
        b=pd.read_csv(f)
        if "fee_rate" in b:
            fee=b.assign(date=pd.to_datetime(b.date)).drop_duplicates("date").set_index("date")["fee_rate"].astype(float)
            out["N6_borrow_fee"]=fee.reindex(px.index).ffill(limit=3)
    out=out.reindex(idx); out["ticker"]=t; out.index.name="date"
    parts.append(out.reset_index())
n=pd.concat(parts)
n=n.replace([np.inf,-np.inf],np.nan)
n.to_parquet("n_features.parquet",index=False)
print(n.shape); print(n.notna().mean().round(2))
