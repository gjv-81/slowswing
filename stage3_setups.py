"""
stage3_setups.py : Stage 3 of STS_FAST_PREREG.md (+ Amendment 1).
Seven price setup families, 10 years (daily_data_v2) plus 3 years (daily_data_ext).
Signal at close of day t, entry next open, exit close t+k, excess vs SPY, 0.10% cost.
One trigger per ticker per family per 10 trading days. Liquidity: price >= $10, 20d median $ volume >= $20M.
"""
import glob, os, numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")
A="uw_archive"; COST=0.001
SPY=pd.read_csv("daily_data_v2/SPY.csv",index_col=0,parse_dates=True).sort_index()
SPY=SPY[~SPY.index.duplicated()]

def load(p):
    px=pd.read_csv(p,index_col=0,parse_dates=True).sort_index()
    return px[~px.index.duplicated()][["Open","High","Low","Close","Volume"]].astype(float)

def earnings_reaction_days(t, idx):
    f=f"{A}/earnings_hist/{t}.csv"
    if not os.path.exists(f): return None
    e=pd.read_csv(f)
    if "report_date" not in e: return None
    e=e[(e.get("source")=="company")&(e.report_time.isin(["premarket","postmarket"]))]
    out=[]
    for _,r in e.iterrows():
        d=pd.Timestamp(r.report_date)
        pos=idx.searchsorted(d)
        if pos>=len(idx): continue
        if r.report_time=="premarket": rd=pos if idx[pos]==d else None
        else: rd=pos+1 if idx[pos]==d else pos   # after hours: next session
        if rd is not None and rd<len(idx): out.append(rd)
    return sorted(set(out))

def rsi_n(C,n=2):
    d=C.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-12))

def shorts(t, idx):
    f=f"{A}/shorts_interest/{t}.csv"
    if not os.path.exists(f): return None
    s=pd.read_csv(f)
    if s.empty: return None
    pos=np.minimum(idx.searchsorted(pd.to_datetime(s.market_date))+10,len(idx)-1)
    s["avail"]=idx[pos]
    s=s.sort_values("avail").drop_duplicates("avail",keep="last").set_index("avail")
    out=pd.DataFrame({"si":pd.to_numeric(s.si_float,errors="coerce"),"dtc":pd.to_numeric(s.days_to_cover,errors="coerce")})
    return out.reindex(idx).ffill(limit=30)

def gex(t, idx):
    f=f"{A}/greek_exposure_2y/{t}.csv"
    if not os.path.exists(f): return None
    x=pd.read_csv(f,parse_dates=["date"]).drop_duplicates("date").set_index("date")
    return (pd.to_numeric(x.call_gamma,errors="coerce")+pd.to_numeric(x.put_gamma,errors="coerce")).reindex(idx)

def surge_pre_earnings(t, idx, rdays):
    """N7: ask side call volume >= 3x its prior 21d median on any of the 5 sessions before the reaction day"""
    for d in ("options_volume","options_volume_ext"):
        f=f"{A}/{d}/{t}.csv"
        if os.path.exists(f):
            o=pd.read_csv(f,parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index()
            ca=pd.to_numeric(o.call_volume_ask_side,errors="coerce")
            ratio=(ca/ca.rolling(21,min_periods=15).median().shift(1)).reindex(idx)
            cover=pd.Series(o.index.min(),index=[0]).iloc[0]
            return ratio, cover
    return None, None

def refractory(mask, gap=10):
    out=np.zeros(len(mask),bool); last=-10**9
    for i in np.where(mask)[0]:
        if i-last>=gap: out[i]=True; last=i
    return out

def run_ticker(t, src):
    px=load(f"{src}/{t}.csv")
    if len(px)<300: return []
    O,H,L,C,V=(px[c] for c in ["Open","High","Low","Close","Volume"])
    idx=px.index
    so=SPY.Open.reindex(idx); sc=SPY.Close.reindex(idx)
    fwd={}
    for k in range(1,6):
        fwd[f"xs{k}"]=(C.shift(-k)/O.shift(-1)-1)-(sc.shift(-k)/so.shift(-1)-1)
    liq=(C>=10)&((C*V).rolling(20,min_periods=15).median()>=20e6)
    pc=C.shift(1); ret=C/pc-1
    tr=pd.concat([H-L,(H-pc).abs(),(L-pc).abs()],axis=1).max(axis=1)
    sma50=C.rolling(50).mean(); sma200=C.rolling(200).mean()
    vol50=V.rolling(50).mean().shift(1)
    sig={}
    # PB pullback in an uptrend
    down=(C<pc).astype(int); run_dn=down.groupby((down==0).cumsum()).cumsum()
    lo10=L.rolling(10).min(); hi10=H.rolling(10).max(); pos10=(C-lo10)/(hi10-lo10).replace(0,np.nan)
    sig["PB"]=(C>sma200)&(sma50>sma200)&((run_dn>=3)|(pos10<=0.2))&(C/C.shift(5)-1<=-0.03)
    # BO breakout continuation
    sig["BO"]=(C>C.shift(1).rolling(251).max())&(V>=1.5*vol50)&C.shift(251).notna()
    # SQ squeeze release
    atr5=tr.rolling(5).mean(); atr50=tr.rolling(50).mean()
    sig["SQ"]=(atr5.shift(1)<=0.6*atr50.shift(1))&(C>pc)&(tr>=1.5*tr.rolling(20).mean().shift(1))
    # earnings based
    rdays=earnings_reaction_days(t,idx)
    gap=O/pc-1
    if rdays:
        rd=np.zeros(len(idx),bool); rd[rdays]=True
        sig["PEAD"]=pd.Series(rd,index=idx)&(gap>=0.04)&((C-L)/(H-L).replace(0,np.nan)>=0.5)
        near=pd.Series(rd,index=idx).astype(int).rolling(5,center=True,min_periods=1).max().astype(bool)  # within 2 sessions
        sig["GAP"]=(gap>=0.03)&(C>=O)&~near
    # WB washout bounce: first up close within 5 sessions after the washout condition
    cond=((C/C.shift(5)-1)<=-0.12)|(rsi_n(C,2)<=5)
    up=(C>pc).values; cv=cond.values; wb=np.zeros(len(idx),bool); armed=-99
    for i in range(len(idx)):
        if up[i] and 0<i-armed<=5: wb[i]=True; armed=-99; continue
        if cv[i]: armed=i
    sig["WB"]=pd.Series(wb,index=idx)
    # SQZ short squeeze candidate (2021 onward, core names with shorts data)
    sh=shorts(t,idx)
    if sh is not None:
        sig["SQZ"]=(sh.si>=0.15)&(sh.dtc>=5)&(ret>=0.03)&(V>=2*vol50)&(idx>=pd.Timestamp("2021-01-01"))
    g=gex(t,idx)
    ratio,_=surge_pre_earnings(t,idx,rdays) if rdays else (None,None)
    rows=[]
    for fam,m in sig.items():
        m=(m.fillna(False)&liq&fwd["xs5"].notna()).values
        for i in np.where(refractory(m))[0]:
            d=idx[i]
            r={"ticker":t,"family":fam,"date":d,"core":int(src=="daily_data_v2"),**{k:fwd[k].iloc[i] for k in fwd}}
            r["net_gex"]=g.iloc[i] if g is not None else np.nan
            if fam=="PEAD" and ratio is not None:
                w=ratio.iloc[max(0,i-5):i]
                r["n7_surge"]=float((w>=3).any()) if w.notna().any() else np.nan
            rows.append(r)
    return rows

def main():
    v2={os.path.basename(f)[:-4] for f in glob.glob("daily_data_v2/*.csv")}
    ex={os.path.basename(f)[:-4] for f in glob.glob("daily_data_ext/*.csv")}-v2
    jobs=[(t,"daily_data_v2") for t in sorted(v2) if t not in ("SPY","QQQ","IWM")]+[(t,"daily_data_ext") for t in sorted(ex)]
    allr=[]
    for i,(t,s) in enumerate(jobs,1):
        try: allr+=run_ticker(t,s)
        except Exception as e: print("ERR",t,repr(e)[:100])
        if i%300==0: print(i,len(jobs),len(allr),flush=True)
    ev=pd.DataFrame(allr)
    ev["era"]=np.select([ev.date<"2020-01-01",ev.date<"2023-01-01"],["E1 2016 to 2019","E2 2020 to 2022"],"E3 2023 to 2026")
    ev.to_parquet("stage3_events.parquet",index=False)
    print(ev.groupby(["family","era"]).size().unstack())

if __name__=="__main__": main()
