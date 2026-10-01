#!/usr/bin/env python3
"""
build_fast_features.py : STS fast lane, Stage 1 input table (per STS_FAST_PREREG.md).

One row per ticker per trading day. Every feature uses data available at the
close of day t only. Entry = open of t+1, exit = close of t+k (k = 1..5).
Excess = stock return minus SPY return over the same open t+1 to close t+k window.

Output: fast_features.parquet
"""
import glob, os, ast, sys
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
ARCH = HERE / "uw_archive"
START = pd.Timestamp("2024-10-01")      # first feature date kept (options warmup before it)
EPS = 1e-9

# ---------------- slow lane score (from uw_harvest2.py, unchanged) ----------------
ZC={"high52":(-0.149772,0.156737),"dist200":(1.681650,6.240695),"mom6":(0.086250,0.361377),
    "qqe":(0.044473,0.194268),"hull":(0.027496,0.303103),"mom40":(0.020000,0.155298)}
WT={"high52":-2.20,"dist200":1.35,"mom6":1.08,"qqe":-0.99,"mom40":0.63,"hull":0.60}
zf=lambda v,k:np.clip((v-ZC[k][0])/ZC[k][1],-3,3)
def wma(s,n):
    w=np.arange(1,n+1,dtype=float); w=w/w.sum()
    v=s.values.astype(float); out=np.full(len(v),np.nan)
    if len(v)>=n: out[n-1:]=np.convolve(v,w[::-1],mode="valid")
    return pd.Series(out,index=s.index)
def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def zprev(s, n=21, minp=15):
    """Z score of today vs the PRIOR n days (today excluded)."""
    m = s.rolling(n, min_periods=minp).mean().shift(1)
    sd = s.rolling(n, min_periods=minp).std().shift(1)
    return (s - m) / sd.replace(0, np.nan)

def load_px(t):
    for d in ("daily_data_v2", "daily_data_ext"):
        p = HERE / d / f"{t}.csv"
        if p.exists():
            px = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
            px = px[~px.index.duplicated()]
            px = px[px.index>=pd.Timestamp("2022-06-01")]
            return px[["Open","High","Low","Close","Volume"]].astype(float), d
    return None, None

SPY,_ = load_px("SPY")
SPY_O, SPY_C = SPY["Open"], SPY["Close"]

def setup_flags(px):
    """active S2/B2/DLB/D200G signal (first day score>=2, 20d refractory, active 40 td)."""
    C,H=px["Close"],px["High"];pc=C.shift(1)
    tr=pd.concat([H-px["Low"],(H-pc).abs(),(px["Low"]-pc).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False).mean()
    f={}
    f["high52"]=C/H.rolling(252).max()-1
    sma200=C.rolling(200).mean()
    f["dist200"]=(C-sma200)/atr
    f["mom6"]=C.shift(10)/C.shift(126)-1
    f["qqe"]=(rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50
    hma=wma(2*wma(C,10)-wma(C,20),4); f["hull"]=(hma-hma.shift(1))/atr
    f["mom40"]=C/C.shift(40)-1
    score=sum(WT[k]*zf(f[k],k) for k in WT)
    mask=(score>=2)
    first=mask&~mask.shift(1,fill_value=False)
    oh=f["high52"]*100; above=C>sma200
    out=pd.DataFrame(0,index=px.index,columns=["act_S2","act_B2","act_DLB","act_D200G"],dtype=np.int8)
    idx=np.where(first.values&(C.values>=10))[0]; last=-99
    for i0 in idx:
        if i0-last<20: continue
        last=i0
        h=oh.iloc[i0]
        if h>-10: col="act_S2"
        elif h>-25: col="act_B2"
        else: col="act_D200G" if above.iloc[i0] else "act_DLB"
        out.iloc[i0:i0+40, out.columns.get_loc(col)] = 1   # signal day through 40 td
    out["sts_score"]=score
    return out

def ticker_rows(t, core):
    px, src = load_px(t)
    if px is None or len(px) < 260: return None
    sub = "options_volume" if core else "options_volume_ext"
    o = pd.read_csv(ARCH/sub/f"{t}.csv", parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index()
    if "call_volume_ask_side" not in o.columns or len(o) < 60: return None
    o = o.apply(pd.to_numeric, errors="coerce")

    O,H,L,C,V = (px[c] for c in ["Open","High","Low","Close","Volume"])
    df = pd.DataFrame(index=px.index)
    df["close"]=C
    ret=C.pct_change()
    # ---------- forward targets ----------
    O1 = O.shift(-1)
    so1 = SPY_O.reindex(px.index).shift(-1)
    spc = SPY_C.reindex(px.index)
    for k in range(1,6):
        r = C.shift(-k)/O1 - 1
        s = spc.shift(-k)/so1 - 1
        df[f"ret{k}"] = r; df[f"xs{k}"] = r - s
        df[f"rc{k}"] = C.shift(-k)/C - 1       # close t reference (flame comparability)
    # ---------- liquidity ----------
    df["dollar_vol_med20"]=(C*V).rolling(20,min_periods=15).median()

    # ---------- options flow (own trading-day series, then aligned) ----------
    ca, pa = o["call_volume_ask_side"], o["put_volume_ask_side"]
    of = pd.DataFrame(index=o.index)
    of["opt_vol_med21"]=(o["call_volume"]+o["put_volume"]).rolling(21,min_periods=15).median()
    med = ca.rolling(21,min_periods=15).median().shift(1)
    of["F1_ask_call_surge"]=np.log((ca+1)/(med+1))
    of["F2_dir_prem_z"]=zprev(o["bullish_premium"]-o["bearish_premium"])
    of["F3_call_share_ask"]=ca/(ca+pa).replace(0,np.nan)
    net=o["net_call_premium"]-o["net_put_premium"]
    totp=(o["call_premium"]+o["put_premium"]).rolling(21,min_periods=15).mean()
    of["F4_net_prem_trend"]=net.rolling(5,min_periods=4).sum()/totp.replace(0,np.nan)
    coi,poi=o["call_open_interest"].replace(0,np.nan),o["put_open_interest"].replace(0,np.nan)
    of["F5a_call_oi_chg1"]=coi.pct_change(1); of["F5b_put_oi_chg1"]=poi.pct_change(1)
    of["F5c_call_oi_chg5"]=coi.pct_change(5); of["F5d_put_oi_chg5"]=poi.pct_change(5)
    of["flame_raw"]=((ca/med.replace(0,np.nan)>=3)&(ca>pa)).astype(float)
    df = df.join(of, how="left")

    # ---------- greek flow (Window B) ----------
    gp = ARCH/"greek_flow_daily"/f"{t}.csv"
    if gp.exists():
        g = pd.read_csv(gp, parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index()
        g = g[g["minutes"]>0]
        gf = pd.DataFrame(index=g.index)
        gf["F6_vega_flow_z"]=zprev(g["dir_vega_flow"])
        gf["F6b_last60_vega_share"]=(g["last60_dir_vega_flow"]/(g["dir_vega_flow"].abs()+EPS)).clip(-3,3)
        gf["F7_delta_flow_z"]=zprev(g["dir_delta_flow"])
        df = df.join(gf, how="left")

    # ---------- GEX ----------
    xp = ARCH/"greek_exposure_2y"/f"{t}.csv"
    if xp.exists():
        x = pd.read_csv(xp, parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index()
        net_g = pd.to_numeric(x["call_gamma"],errors="coerce")+pd.to_numeric(x["put_gamma"],errors="coerce")
        scale = net_g.abs().rolling(21,min_periods=15).mean().shift(1)
        xf = pd.DataFrame(index=x.index)
        xf["F8_net_gex"]=net_g/scale.replace(0,np.nan)
        xf["F8b_neg_gex"]=(net_g<0).astype(float)
        df = df.join(xf, how="left")

    # ---------- IV rank / proxy ----------
    rv20 = ret.rolling(20).std()
    df["F9p_rv_pctile"] = rv20.rolling(252,min_periods=200).apply(lambda a:(a[:-1]<a[-1]).mean(),raw=True)
    ip = ARCH/"iv_rank_hist"/f"{t}.csv"
    if ip.exists():
        iv = pd.read_csv(ip, parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index()
        df = df.join(pd.to_numeric(iv["iv_rank_1y"],errors="coerce").rename("F9_iv_rank"), how="left")

    # ---------- shorts (with publication lags) ----------
    tdays = px.index
    def lag_to(dates, lag):
        pos = tdays.searchsorted(pd.to_datetime(dates))
        pos = np.minimum(pos+lag, len(tdays)-1)
        return tdays[pos]
    sp = ARCH/"shorts_interest"/f"{t}.csv"
    if sp.exists():
        s = pd.read_csv(sp)
        if len(s):
            s["avail"]=lag_to(s["market_date"],10)
            s=s.sort_values("avail").drop_duplicates("avail",keep="last").set_index("avail")
            si=pd.DataFrame(index=s.index)
            si["F10a_si_float"]=pd.to_numeric(s["si_float"],errors="coerce")
            si["F10b_days_to_cover"]=pd.to_numeric(s["days_to_cover"],errors="coerce")
            si=si.reindex(tdays).ffill(limit=30)   # carry the latest published value (one cycle = ~10 td)
            df=df.join(si,how="left")
    fp = ARCH/"shorts_ftds"/f"{t}.csv"
    if fp.exists():
        f_ = pd.read_csv(fp)
        if len(f_):
            q = f_.groupby(pd.to_datetime(f_["date"]))["quantity"].sum().reindex(tdays).fillna(0)
            avgv = V.rolling(20,min_periods=15).mean()
            df["F11_ftd_rel"] = (q.rolling(10).sum()/avgv.replace(0,np.nan)).shift(15)
    vp = ARCH/"shorts_volume"/f"{t}.csv"
    if vp.exists():
        try:
            raw = pd.read_csv(vp)["si"].iloc[0]
            lst = ast.literal_eval(raw)
            sv = pd.DataFrame(lst)
            sv["d"]=pd.to_datetime(sv["market_date"]); sv=sv.drop_duplicates("d").set_index("d").sort_index()
            ratio=pd.to_numeric(sv["short_volume_ratio"],errors="coerce")
            df=df.join(zprev(ratio).rename("F12_short_vol_z"),how="left")
        except Exception: pass

    # ---------- price context ----------
    flat=(ret.abs()<=0.01).astype(int)
    grp=(flat==0).cumsum()
    run=flat.groupby(grp).cumsum()
    df["P1_prior_flat_days"]=run.shift(1)                 # consecutive flat days ending t-1
    df["P2a_ret5"]=C/C.shift(5)-1
    df["P2b_ret20"]=C/C.shift(20)-1
    df["P3_dist_52wk_high"]=C/H.rolling(252).max()-1
    df["P4_above_200"]=(C>C.rolling(200).mean()).astype(float)
    pc=C.shift(1)
    tr=pd.concat([H-L,(H-pc).abs(),(L-pc).abs()],axis=1).max(axis=1)
    df["P5_range_compress"]=tr.rolling(5).mean()/tr.rolling(50).mean()
    df["P6_gap"]=O/pc-1
    lv=np.log(V.replace(0,np.nan))
    df["P7_vol_z"]=(lv-lv.rolling(50,min_periods=40).mean().shift(1))/lv.rolling(50,min_periods=40).std().shift(1)
    df["day_ret"]=ret

    # ---------- setup membership ----------
    df = df.join(setup_flags(px), how="left")

    # ---------- declared interactions ----------
    neg = df.get("F8b_neg_gex")
    if neg is not None: df["I1_dirprem_x_neggex"]=df["F2_dir_prem_z"]*neg
    df["I2_surge_x_flat"]=df["F1_ask_call_surge"]*(df["P1_prior_flat_days"]>=1)
    df["I3_surge_x_run10"]=df["F1_ask_call_surge"]*(df["P2b_ret20"]>=0.10)

    df=df[df.index>=START]
    df["ticker"]=t; df["core"]=int(core); df["px_src"]=src
    return df

def main():
    core = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(str(ARCH/"options_volume"/"*.csv")))
    ext = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(str(ARCH/"options_volume_ext"/"*.csv")))
    jobs=[(t,True) for t in core]+[(t,False) for t in ext if t not in set(core)]
    parts=[]; skipped=0
    for i,(t,c) in enumerate(jobs,1):
        try:
            r=ticker_rows(t,c)
            if r is None: skipped+=1
            else: parts.append(r)
        except Exception as e:
            skipped+=1; print("ERR",t,repr(e)[:120])
        if i%200==0: print(f"{i}/{len(jobs)} built, skipped {skipped}", flush=True)
    df=pd.concat(parts).reset_index().rename(columns={"index":"date","Date":"date"})
    num=df.select_dtypes("float64").columns
    df[num]=df[num].replace([np.inf,-np.inf],np.nan).astype("float32")
    df.to_parquet(HERE/"fast_features.parquet",index=False)
    print(f"rows {len(df):,} tickers {df.ticker.nunique()} skipped {skipped} dates {df.date.min().date()} to {df.date.max().date()}")

if __name__=="__main__": main()
