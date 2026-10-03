"""ext_build.py : measures M1..M5, quiet flag, setup activity, outcomes for STS_EXTREMES_PREREG.md.
Reuses fast_features.parquet (has setup activity, outcomes xs1..xs5, liquidity, day_ret) and adds wk2, M measures, DLB/D200 activity."""
import glob, os, numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")
A="uw_archive"
ff=pd.read_parquet("fast_features.parquet",columns=["ticker","date","close","dollar_vol_med20","opt_vol_med21","xs1","xs3","xs5","day_ret","act_S2","act_B2","act_D200G","core"])
SPY=pd.read_csv("daily_data_v2/SPY.csv",index_col=0,parse_dates=True).sort_index(); SPY=SPY[~SPY.index.duplicated()]
from exh_build import score_and_signals, load
parts=[]
for t,g in ff.groupby("ticker"):
    px,src=load(t)
    if px is None: continue
    idx=px.index; O,C=px.Open,px.Close
    so=SPY.Open.reindex(idx); sc=SPY.Close.reindex(idx)
    out=pd.DataFrame(index=idx)
    out["xs10"]=(C.shift(-10)/O.shift(-1)-1)-(sc.shift(-10)/so.shift(-1)-1)
    out["xs20"]=(C.shift(-20)/O.shift(-1)-1)-(sc.shift(-20)/so.shift(-1)-1)
    # options measures
    for d in ("options_volume","options_volume_ext"):
        f=f"{A}/{d}/{t}.csv"
        if os.path.exists(f):
            o=pd.read_csv(f,parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index().apply(pd.to_numeric,errors="coerce")
            ca,pa=o.call_volume_ask_side,o.put_volume_ask_side
            m=lambda s:s.rolling(21,min_periods=15).median().shift(1)
            out["M1_call_surge"]=(ca/m(ca).replace(0,np.nan)).reindex(idx)
            out["M2_put_surge"]=(pa/m(pa).replace(0,np.nan)).reindex(idx)
            tot=(o.call_premium+o.put_premium).rolling(21,min_periods=15).mean().shift(1)
            out["M3_net_prem"]=((o.bullish_premium-o.bearish_premium)/tot.replace(0,np.nan)).reindex(idx)
            out["ask_call_gt_put"]=(ca>pa).astype(float).reindex(idx); out["ask_put_gt_call"]=(pa>ca).astype(float).reindex(idx)
            break
    f=f"{A}/greek_flow_daily/{t}.csv"
    if os.path.exists(f):
        gfl=pd.read_csv(f,parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index(); gfl=gfl[gfl.minutes>0]
        for col,name in (("dir_vega_flow","M4_vega"),("dir_delta_flow","M5_delta")):
            s=gfl[col]; out[name]=(s/s.abs().rolling(21,min_periods=15).median().shift(1).replace(0,np.nan)).reindex(idx)
    # DLB and D200 activity (40 day windows), from the exhaustion builder's signal logic
    score,sigs=score_and_signals(px)
    for s in ("DLB","D200"):
        a=np.zeros(len(idx),np.int8)
        for i0 in sigs[s]: a[i0:i0+40]=1
        out["act_"+s]=a
    out=out.reindex(pd.DatetimeIndex(g.date)); out["ticker"]=t; out.index.name="date"
    parts.append(out.reset_index())
m=pd.concat(parts)
df=ff.merge(m,on=["ticker","date"],how="left")
df["quiet"]=(df.day_ret.abs()<=0.01).astype(float)
df["in_setup"]=((df.act_S2==1)|(df.act_B2==1)|(df.act_D200G==1)|(df.act_DLB==1)|(df.act_D200==1)).astype(float)
df=df.replace([np.inf,-np.inf],np.nan)
df.to_parquet("ext_rows.parquet",index=False)
print(df.shape); print(df[["M1_call_surge","M2_put_surge","M3_net_prem","M4_vega","M5_delta","xs10","in_setup"]].notna().mean().round(2).to_dict()); print("in setup share",df.in_setup.mean().round(3))
