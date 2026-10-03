"""
vol_setup_build.py : rows for STS_VOL_SETUP_PREREG.md (approved Oct 3 2026).
Setups S2, B2, D200G (slow lane code) and X200G (frozen x200g_observe.py logic).
One row per ticker per day inside a signal's first 40 trading days (Analysis B);
is_signal_day marks the first day (Analysis A).
Inputs V1..V6 at the close of day t; outcomes from next open to close t+k, excess vs SPY.
"""
import glob, os, numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")
A="uw_archive"
SPY=pd.read_csv("daily_data_v2/SPY.csv",index_col=0,parse_dates=True).sort_index(); SPY=SPY[~SPY.index.duplicated()]

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

def signals(px):
    """returns dict setup -> list of signal day positions"""
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
    out={"S2":[],"B2":[],"D200G":[],"X200G":[]}
    last=-99
    for i in np.where(first.values&(C.values>=10))[0]:
        if i-last<20: continue
        last=i; h=oh.iloc[i]
        if h>-10: out["S2"].append(i)
        elif h>-25: out["B2"].append(i)
        elif above.iloc[i]: out["D200G"].append(i)
    # X200G (frozen): price>=25, above 200, streak 3..10, washed >=25% in prior 126, >=20 of prior 60 below, qqe<0.20, gap>=5% in last 10 bars
    streak=above.astype(int).groupby((~above).cumsum()).cumsum()
    washed=((C/hi52-1)<=-0.25).astype(int).rolling(126).max().shift(1)
    below=(~above).astype(int).rolling(60).sum().shift(1)
    gap=(O/pc-1).rolling(10).max()
    sig=(C>=25)&above&streak.between(3,10)&(washed==1)&(below>=20)&(f["qqe"]<0.20)&(gap>=0.05)
    last=-999
    for i in np.where(sig.fillna(False).values)[0]:
        if i-last>=40: out["X200G"].append(i); last=i
    return out

def vol_inputs(t, px):
    idx=px.index; out=pd.DataFrame(index=idx)
    f=f"{A}/vol_realized_5y/{t}.csv"
    if not os.path.exists(f): return None
    v=pd.read_csv(f)
    if "implied_volatility" not in v: return None
    iv=v.assign(date=pd.to_datetime(v.date)).drop_duplicates("date").set_index("date")["implied_volatility"].astype(float).reindex(idx)
    out["V1_iv"]=iv
    out["V2_ivrank6m"]=iv.rolling(126,min_periods=100).apply(lambda a:(a[:-1]<a[-1]).mean()*100,raw=True)
    out["V2b_ivrank12m"]=iv.rolling(252,min_periods=200).apply(lambda a:(a[:-1]<a[-1]).mean()*100,raw=True)
    rv=np.log(px.Close).diff().rolling(21,min_periods=18).std()*np.sqrt(252)
    out["V3_iv_minus_rv"]=iv-rv
    out["V4_iv_chg5"]=iv-iv.shift(5)
    f=f"{A}/rr_skew_jan27/{t}.csv"
    if os.path.exists(f):
        r=pd.read_csv(f)
        if "risk_reversal" in r:
            s=r.assign(date=pd.to_datetime(r.date)).drop_duplicates("date").set_index("date")["risk_reversal"].astype(float).reindex(idx)
            out["V5_smirk"]=s; out["V6_smirk_chg5"]=s-s.shift(5)
    f=f"{A}/borrow_daily/{t}.csv"
    if os.path.exists(f):
        b=pd.read_csv(f)
        if "fee_rate" in b:
            out["borrow_fee"]=b.assign(date=pd.to_datetime(b.date)).drop_duplicates("date").set_index("date")["fee_rate"].astype(float).reindex(idx).ffill(limit=3)
    return out

def main():
    tk=sorted({os.path.basename(f)[:-4] for f in glob.glob("daily_data_v2/*.csv")+glob.glob("daily_data_ext/*.csv")}-{"SPY","QQQ","IWM","RSP"})
    rows=[]
    for n,t in enumerate(tk,1):
        px,src=load(t)
        if px is None or len(px)<400: continue
        vi=vol_inputs(t,px)
        if vi is None: continue
        O,C,V=px.Open,px.Close,px.Volume; idx=px.index
        so=SPY.Open.reindex(idx); sc=SPY.Close.reindex(idx)
        fwd={}
        for k,name in [(1,"d1"),(2,"d2"),(3,"d3"),(4,"d4"),(5,"d5"),(10,"wk2"),(20,"wk4")]:
            fwd[name]=((C.shift(-k)/O.shift(-1)-1)-(sc.shift(-k)/so.shift(-1)-1)).values
        liq=((C>=10)&((C*V).rolling(20,min_periods=15).median()>=20e6)).values
        sigs=signals(px)
        for setup,poss in sigs.items():
            for sid,i0 in enumerate(poss):
                if idx[i0]<pd.Timestamp("2023-12-01"): continue
                for j in range(i0,min(i0+40,len(idx))):
                    if not liq[j]: continue
                    r={"ticker":t,"setup":setup,"signal_date":idx[i0],"date":idx[j],"day_in_window":j-i0,
                       "is_signal_day":int(j==i0),"core":int(src=="daily_data_v2")}
                    for name in fwd: r[name]=fwd[name][j]
                    for c in vi.columns: r[c]=vi[c].iloc[j]
                    rows.append(r)
        if n%300==0: print(n,len(tk),len(rows),flush=True)
    df=pd.DataFrame(rows)
    df=df.replace([np.inf,-np.inf],np.nan)
    df.to_parquet("vol_setup_rows.parquet",index=False)
    print(df.shape)
    print(df[df.is_signal_day==1].groupby("setup").size())
    print(df.groupby("setup").size())
    print(df[["V1_iv","V2_ivrank6m","V5_smirk","d3"]].notna().mean())

if __name__=="__main__": main()
