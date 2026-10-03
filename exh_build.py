"""
exh_build.py : rows for STS_EXHAUSTION_PREREG.md (approved Oct 3 2026).
Setups S2, B2, DLB, D200, D200G, X200G. Days 5 to 40 after the signal.
Inputs E1..E6 and C1 at the close of day t. Outcomes from open t+1 to close t+k, excess vs SPY.
Dark pool: daily cache darkpool_daily_agg.csv (exists only for score>=2 signal windows from Nov 2024).
"""
import glob, os, ast, numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")
A="uw_archive"
SPY=pd.read_csv("daily_data_v2/SPY.csv",index_col=0,parse_dates=True).sort_index(); SPY=SPY[~SPY.index.duplicated()]
RSP=pd.read_csv("daily_data_v2/RSP.csv",index_col=0,parse_dates=True).sort_index(); RSP=RSP[~RSP.index.duplicated()]
DP=pd.read_csv(f"{A}/darkpool_daily_agg.csv",parse_dates=["date"])
DP=DP.groupby(["ticker","date"]).dp_prem.sum()
START=pd.Timestamp("2024-11-01")

ZC={"high52":(-0.149772,0.156737),"dist200":(1.681650,6.240695),"mom6":(0.086250,0.361377),
    "qqe":(0.044473,0.194268),"hull":(0.027496,0.303103),"mom40":(0.020000,0.155298)}
WT={"high52":-2.20,"dist200":1.35,"mom6":1.08,"qqe":-0.99,"mom40":0.63,"hull":0.60}
zf=lambda v,k:np.clip((v-ZC[k][0])/ZC[k][1],-3,3)
def wma(s,n):
    w=np.arange(1,n+1,dtype=float); w=w/w.sum(); v=s.values.astype(float); out=np.full(len(v),np.nan)
    if len(v)>=n: out[n-1:]=np.convolve(v,w[::-1],mode="valid")
    return pd.Series(out,index=s.index)
def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def load(t):
    for d in ("daily_data_v2","daily_data_ext"):
        p=f"{d}/{t}.csv"
        if os.path.exists(p):
            px=pd.read_csv(p,index_col=0,parse_dates=True).sort_index(); px=px[~px.index.duplicated()]
            return px[["Open","High","Low","Close","Volume"]].astype(float), d
    return None,None

def score_and_signals(px):
    C,H,O=px.Close,px.High,px.Open; pc=C.shift(1)
    tr=pd.concat([H-px.Low,(H-pc).abs(),(px.Low-pc).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False).mean()
    hi52=H.rolling(252).max(); sma200=C.rolling(200).mean()
    f={"high52":C/hi52-1,"dist200":(C-sma200)/atr,"mom6":C.shift(10)/C.shift(126)-1,
       "qqe":(rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50,"mom40":C/C.shift(40)-1}
    hma=wma(2*wma(C,10)-wma(C,20),4); f["hull"]=(hma-hma.shift(1))/atr
    score=sum(WT[k]*zf(f[k],k) for k in WT)
    mask=(score>=2); first=mask&~mask.shift(1,fill_value=False)
    oh=f["high52"]*100; above=C>sma200
    out={s:[] for s in ["S2","B2","DLB","D200","D200G","X200G"]}
    last=-99
    for i in np.where(first.values&(C.values>=10))[0]:
        if i-last<20: continue
        last=i; h=oh.iloc[i]
        if h>-10: out["S2"].append(i)
        elif h>-25: out["B2"].append(i)
        elif above.iloc[i]: out["D200G"].append(i)
        else: out["DLB"].append(i)
    # D200: deep + above the line, score not required, first day condition appears, 20d refractory
    d200=(oh<=-25)&above&(C>=10); d200f=d200&~d200.shift(1,fill_value=False); last=-99
    for i in np.where(d200f.values)[0]:
        if i-last<20: continue
        last=i; out["D200"].append(i)
    streak=above.astype(int).groupby((~above).cumsum()).cumsum()
    washed=((C/hi52-1)<=-0.25).astype(int).rolling(126).max().shift(1)
    below=(~above).astype(int).rolling(60).sum().shift(1)
    gap=(O/pc-1).rolling(10).max()
    sig=(C>=25)&above&streak.between(3,10)&(washed==1)&(below>=20)&(f["qqe"]<0.20)&(gap>=0.05)
    last=-999
    for i in np.where(sig.fillna(False).values)[0]:
        if i-last>=40: out["X200G"].append(i); last=i
    return score,out

def shorts_series(t, idx):
    sv=None; si=None
    f=f"{A}/shorts_volume/{t}.csv"
    if os.path.exists(f):
        try:
            lst=ast.literal_eval(pd.read_csv(f)["si"].iloc[0]); d=pd.DataFrame(lst)
            d["d"]=pd.to_datetime(d.market_date); d=d.drop_duplicates("d").set_index("d").sort_index()
            sv=pd.to_numeric(d.short_volume_ratio,errors="coerce").reindex(idx)
        except Exception: pass
    f=f"{A}/shorts_interest/{t}.csv"
    if os.path.exists(f):
        s=pd.read_csv(f)
        if len(s) and "si_float" in s:
            pos=np.minimum(idx.searchsorted(pd.to_datetime(s.market_date))+10,len(idx)-1)
            s["avail"]=idx[pos]; s=s.sort_values("avail").drop_duplicates("avail",keep="last").set_index("avail")
            si=pd.to_numeric(s.si_float,errors="coerce").reindex(idx).ffill(limit=30)*100
    return sv,si

def main():
    tk=sorted({os.path.basename(f)[:-4] for f in glob.glob("daily_data_v2/*.csv")+glob.glob("daily_data_ext/*.csv")}-{"SPY","QQQ","IWM","RSP"})
    rows=[]
    rsp_m40=(RSP.Close/RSP.Close.shift(40)-1)
    for n,t in enumerate(tk,1):
        px,src=load(t)
        if px is None or len(px)<400: continue
        idx=px.index; O,C,V=px.Open,px.Close,px.Volume
        score,sigs=score_and_signals(px)
        if not any(len(v) for v in sigs.values()): continue
        so=SPY.Open.reindex(idx); sc=SPY.Close.reindex(idx)
        fwd={}
        for k,name in [(5,"d5"),(10,"wk2"),(20,"wk4")]:
            fwd[name]=((C.shift(-k)/O.shift(-1)-1)-(sc.shift(-k)/so.shift(-1)-1)).values
        liq=((C>=10)&((C*V).rolling(20,min_periods=15).median()>=20e6)).values
        pulse=100*((C/C.shift(40)-1)-rsp_m40.reindex(idx))
        sv,si=shorts_series(t,idx)
        sv5=sv.rolling(5).mean() if sv is not None else None
        sv20p=sv.rolling(20).mean().shift(5) if sv is not None else None
        sv60=sv.rolling(60,min_periods=40).median() if sv is not None else None
        dp=DP.loc[t].reindex(idx) if t in DP.index.get_level_values(0) else None
        for setup,poss in sigs.items():
            for i0 in poss:
                sd=idx[i0]
                if sd<START: continue
                si_pre=si.iloc[i0-1] if (si is not None and i0>=1) else np.nan
                dp0=np.nansum(dp.iloc[i0:i0+5].values) if dp is not None else np.nan
                dp_any=dp is not None and dp.iloc[i0:i0+41].notna().sum()>=20
                for j in range(i0+5,min(i0+41,len(idx))):
                    if not liq[j]: continue
                    r={"ticker":t,"setup":setup,"signal_date":sd,"date":idx[j],"day_in_window":j-i0,"core":int(src=="daily_data_v2")}
                    for name in fwd: r[name]=fwd[name][j]
                    r["E1_short_vol_chg"]=(sv5.iloc[j]/sv20p.iloc[j]-1) if sv5 is not None and sv20p.iloc[j] and sv20p.iloc[j]>0 else np.nan
                    r["sv5_below_med60"]=float(sv5.iloc[j]<sv60.iloc[j]) if sv5 is not None and pd.notna(sv60.iloc[j]) else np.nan
                    r["E2_si_chg"]=(si.iloc[j]-si_pre) if si is not None else np.nan
                    if dp_any:
                        d5=np.nansum(dp.iloc[j-4:j+1].values);
                        r["E3_dp_vs_first5"]=(d5/dp0-1) if dp0 and dp0>0 else np.nan
                        prior=[np.nansum(dp.iloc[k-4:k+1].values) for k in range(j-20,j-4)] if j-24>=i0 else []
                        prior=[p for p in prior if p>0]
                        r["E4_dp_vs_norm"]=(d5/np.median(prior)-1) if len(prior)>=5 else np.nan
                    else: r["E3_dp_vs_first5"]=np.nan; r["E4_dp_vs_norm"]=np.nan
                    r["E5_score_chg"]=score.iloc[j]-score.iloc[j-5]
                    r["E6_pulse_chg"]=pulse.iloc[j]-pulse.iloc[j-5]
                    r["C1_ret5"]=C.iloc[j]/C.iloc[j-5]-1
                    r["score_now"]=score.iloc[j]; r["pulse_now"]=pulse.iloc[j]
                    rows.append(r)
        if n%300==0: print(n,len(tk),len(rows),flush=True)
    df=pd.DataFrame(rows).replace([np.inf,-np.inf],np.nan)
    df["F1"]=((df.E1_short_vol_chg<=-0.15)&(df.sv5_below_med60==1)).astype(float).where(df.E1_short_vol_chg.notna())
    df["F2"]=((df.E3_dp_vs_first5<=-0.30)&(df.E4_dp_vs_norm<=0)).astype(float).where(df.E3_dp_vs_first5.notna()&df.E4_dp_vs_norm.notna())
    df["F3"]=(df.E5_score_chg>=0.30).astype(float)
    df["F4"]=(df.E6_pulse_chg>=1.0).astype(float)
    df["nflags"]=df[["F1","F2","F3","F4"]].sum(axis=1,min_count=4)
    df.to_parquet("exh_rows.parquet",index=False)
    print(df.shape)
    print(df.drop_duplicates(["ticker","setup","signal_date"]).groupby("setup").size())
    print("rows with all four flags computable:",int(df["nflags"].notna().sum()), "| distinct signals with dark pool:",df[df.E3_dp_vs_first5.notna()].drop_duplicates(["ticker","setup","signal_date"]).shape[0])
    print(df[["E1_short_vol_chg","E2_si_chg","E3_dp_vs_first5","E4_dp_vs_norm","E5_score_chg","E6_pulse_chg","wk4"]].notna().mean().round(2))

if __name__=="__main__": main()
