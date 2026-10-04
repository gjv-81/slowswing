"""corners.py : STS_CORNERS_PREREG.md. Corner vs complement, 4 signals, d1..wk4. Run after sectors.csv is staged."""
import numpy as np, pandas as pd, os
from stage1_screen import nw_t
COST=0.001
H={"d1":"xs1","d3":"xs3","d5":"xs5","wk2":"xs10","wk4":"xs20"}
df=pd.read_parquet("ext_rows.parquet")
df=df[(df.close>=10)&(df.dollar_vol_med20>=20e6)&(df.opt_vol_med21>=1000)&df.xs3.notna()].copy()
# option to stock volume ratio (21d): need share volume; recompute from prices
vols=[]
for t,g in df.groupby("ticker"):
    for d in ("daily_data_v2","daily_data_ext"):
        p=f"{d}/{t}.csv"
        if os.path.exists(p):
            px=pd.read_csv(p,index_col=0,parse_dates=True).sort_index(); px=px[~px.index.duplicated()]
            v=px.Volume.rolling(21,min_periods=15).mean().reindex(pd.DatetimeIndex(g.date)).values
            vols.append(pd.Series(v,index=g.index)); break
df["sh_vol21"]=pd.concat(vols)
df["os_ratio"]=df.opt_vol_med21*100/df.sh_vol21.replace(0,np.nan)
# borrow fee
n=pd.read_parquet("n_features.parquet",columns=["ticker","date","N6_borrow_fee"])
df=df.merge(n,on=["ticker","date"],how="left")
# short interest % float (lagged) from fast_features
f10=pd.read_parquet("fast_features.parquet",columns=["ticker","date","F10a_si_float"])
df=df.merge(f10,on=["ticker","date"],how="left")
# sectors
sec=pd.read_csv("sectors.csv").dropna(subset=["sector"]).drop_duplicates("ticker")
df=df.merge(sec[["ticker","sector"]],on="ticker",how="left")
# sector relative strength (20d and 60d), per day
prices=[]
for t,g in df.groupby("ticker"):
    for d in ("daily_data_v2","daily_data_ext"):
        p=f"{d}/{t}.csv"
        if os.path.exists(p):
            px=pd.read_csv(p,index_col=0,parse_dates=True).sort_index(); px=px[~px.index.duplicated()]
            r20=(px.Close/px.Close.shift(20)-1).reindex(pd.DatetimeIndex(g.date)).values; r60=(px.Close/px.Close.shift(60)-1).reindex(pd.DatetimeIndex(g.date)).values
            prices.append(pd.DataFrame({"r20":r20,"r60":r60},index=g.index)); break
pr=pd.concat(prices); df["r20"]=pr.r20; df["r60"]=pr.r60
rsp=pd.read_csv("daily_data_v2/RSP.csv",index_col=0,parse_dates=True).sort_index(); rsp=rsp[~rsp.index.duplicated()]
rsp20=(rsp.Close/rsp.Close.shift(20)-1); rsp60=(rsp.Close/rsp.Close.shift(60)-1)
srs=df.dropna(subset=["sector"]).groupby(["date","sector"]).agg(r20=("r20","mean"),r60=("r60","mean")).reset_index()
srs["rs20"]=srs.r20-srs.date.map(rsp20); srs["rs60"]=srs.r60-srs.date.map(rsp60)
srs["rank20"]=srs.groupby("date").rs20.rank(ascending=False,method="first"); srs["rank60"]=srs.groupby("date").rs60.rank(ascending=False,method="first")
df=df.merge(srs[["date","sector","rank20","rank60"]],on=["date","sector"],how="left")
# signals
df["S1_flame"]=((df.M1_call_surge>=3)&(df.ask_call_gt_put==1)&(df.quiet==1)).astype(float).where(df.M1_call_surge.notna())
df["S2_putwarn"]=((df.M2_put_surge>=3)&(df.ask_put_gt_call==1)).astype(float).where(df.M2_put_surge.notna())
def tertile(s): return s.groupby(df.date).transform(lambda x:np.ceil(x.rank(method="first",pct=True)*3))
df["t_os"]=tertile(df.os_ratio); df["t_fee"]=tertile(df.N6_borrow_fee)
df["c_os"]=np.where(df.t_os==3,"corner",np.where(df.t_os==1,"complement","middle")); df.loc[df.t_os.isna(),"c_os"]=None
df["c_fee"]=np.where(df.t_fee==3,"corner",np.where(df.t_fee==1,"complement","middle")); df.loc[df.t_fee.isna(),"c_fee"]=None
df["c_si"]=np.where(df.F10a_si_float>=0.10,"corner",np.where(df.F10a_si_float.notna(),"complement",None))
nsec=srs.groupby("date").sector.nunique().reindex(df.date).values
df["c_sec20"]=np.where(df.rank20<=3,"corner",np.where(df.rank20>nsec-3,"complement",np.where(df.rank20.notna(),"middle",None)))
df["c_sec20_bottom"]=np.where(df.rank20>nsec-3,"corner",np.where(df.rank20<=3,"complement",np.where(df.rank20.notna(),"middle",None)))
df["c_sec60"]=np.where(df.rank60<=3,"corner",np.where(df.rank60>nsec-3,"complement",np.where(df.rank60.notna(),"middle",None)))
# half splits
df["c_os_half"]=np.where(df.os_ratio.groupby(df.date).rank(pct=True)>0.5,"corner",np.where(df.os_ratio.notna(),"complement",None))
df["c_fee_half"]=np.where(df.N6_borrow_fee.groupby(df.date).rank(pct=True)>0.5,"corner",np.where(df.N6_borrow_fee.notna(),"complement",None))
df.to_parquet("corner_rows.parquet",index=False)

def st(x):
    x=x.dropna()-COST; w=x[x>0]; l=x[x<=0]
    return dict(n=int(len(x)),avg=x.mean()*100,win=(x>0).mean()*100,med=x.median()*100,ratio=(w.mean()/abs(l.mean())) if len(l) and len(w) else np.nan)
def effect(part,sigcol,extreme=None):
    """signal days vs non signal days inside a partition, per day differences. extreme: ('M1_call_surge', top1%) within partition."""
    if extreme:
        r=part.groupby("date")[extreme].rank(method="first",pct=True); cnt=part.groupby("date")[extreme].transform("size")
        on=part[(r>0.99)&(cnt>=100)]; off=part[(r<=0.99)&(r>0.01)&(cnt>=100)]
    else:
        on=part[part[sigcol]==1]; off=part[part[sigcol]==0]
    out={}
    for h,c in H.items():
        e=on.groupby("date")[c].mean(); m=off.groupby("date")[c].mean(); d=(e-m).dropna()
        s=st(on[c]); out[h]={"n":s["n"],"tickers":on.ticker.nunique(),"days":int(d.shape[0]),"avg":s["avg"],"win":s["win"],"med":s["med"],"ratio":s["ratio"],"diff":d.mean()*100,"series":d}
    return out
SIG=[("S1 flame style","S1_flame",None,+1),("S2 put warning","S2_putwarn",None,-1),("S3 extreme call top1%",None,"M1_call_surge",+1),("S4 extreme put top1%",None,"M2_put_surge",-1)]
CORN=[("C1 options venue (top third O/S)","c_os",("d3",)),("C2 leading sectors (top 3 by 20d RS)","c_sec20",("d3","wk2")),("C3a hard to borrow (top third fee)","c_fee",("d3",)),("C3b short interest >= 10%","c_si",("d3",)),
      ("R: C2 bottom 3 sectors","c_sec20_bottom",()),("R: C2 60d RS","c_sec60",()),("R: C1 half split","c_os_half",()),("R: C3 half split","c_fee_half",())]
rows=[]; detail=[]
for cname,ccol,graded in CORN:
    for sname,scol,ext,sign in SIG:
        parts={k:df[df[ccol]==k] for k in ("corner","complement","middle")}
        eff={k:effect(v,scol,ext) for k,v in parts.items() if len(v)}
        for h in H:
            row={"corner":cname,"signal":sname,"horizon":h,"graded":h in graded}
            for k in ("corner","complement","middle"):
                if k in eff:
                    e=eff[k][h]
                    for kk in ("n","tickers","days","avg","win","med","ratio","diff"): row[f"{k}_{kk}"]=e[kk]
            if "corner" in eff and "complement" in eff and len(eff["corner"][h]["series"])>=20 and len(eff["complement"][h]["series"])>=20:
                dc=eff["corner"][h]["series"]; dm=eff["complement"][h]["series"]
                dd=(dc-dm).dropna()
                lag=3 if h in("d1","d3","d5") else (10 if h=="wk2" else 20)
                t_c,_=nw_t(dc.values,lag); t_dd,_=nw_t(dd.values,lag)
                row["corner_t"]=t_c; row["corner_minus_complement"]=dd.mean()*100; row["dd_t"]=t_dd
                dates=dc.index; mid=dates[len(dates)//2]
                row["corner_diff_h1"]=dc[dates<mid].mean()*100; row["corner_diff_h2"]=dc[dates>=mid].mean()*100
                if h in graded:
                    size=0.40 if h=="d3" else 0.75; gap=0.30 if h=="d3" else 0.50
                    c1=sign*row["corner_diff"]>=size and abs(t_c)>=2.5 and np.sign(row["corner_diff_h1"])==np.sign(row["corner_diff_h2"])==sign and eff["corner"][h]["n"]>=150 and eff["corner"][h]["tickers"]>=40
                    c2=sign*row["corner_minus_complement"]>=gap and abs(t_dd)>=2.0
                    mid_ok=True
                    if "middle" in eff and eff["middle"][h]["n"]>=50:
                        m=eff["middle"][h]["diff"]; lo,hi=sorted([row["corner_diff"],row["complement_diff"]]); mid_ok=lo<=m<=hi
                    row["c1 signal works in corner"]=bool(c1); row["c2 corner beats complement"]=bool(c2); row["c3 gradient"]=bool(mid_ok); row["PASS"]=bool(c1 and c2 and mid_ok)
            rows.append(row)
R=pd.DataFrame(rows); R.to_csv("corners_results.csv",index=False)
pd.set_option("display.width",270); pd.set_option("display.max_columns",40)
g=R[R.graded==True]
print(g[["corner","signal","horizon","corner_n","corner_diff","corner_t","complement_diff","middle_diff","corner_minus_complement","dd_t","corner_diff_h1","corner_diff_h2","PASS"]].round(3).to_string())
print("\ncoverage:",{c:int(df[c].notna().sum()) for c in ("c_os","c_sec20","c_fee","c_si")}, "sectors:",df.sector.nunique())
