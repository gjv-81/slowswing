#!/usr/bin/env python3.12
"""
flame_download.py — STAGE-1 pilot downloader for the "flame" (unusual options
activity) study. Talks to the LOCAL Theta Terminal (must be running:
  cd ~/STS/ThetaTerminal && java -jar ThetaTerminalv3.jar ).

WHAT IT DOES
  1. Regenerates the DLB/D200G signal set from daily_data_v2/ (same rules as the
     regime study: score>=2 + >=25% off high, first day entering the state,
     20-trading-day refractory, price >= $10) restricted to the FREE-TIER year:
     signals whose [baseline .. +12wk] window fits inside the last ~52 weeks.
  2. For every ticker's merged signal window(s) (signal-45td .. signal+65td),
     downloads the full option chain daily EOD (expiration=*) and daily OPEN
     INTEREST, month-chunked, throttled to the free tier (20 req/min, 1 at a
     time), and aggregates per ticker-day:
        call_vol, put_vol, call_prem, put_prem  (prem = sum(volume x close))
        call_oi, put_oi, n_call_contracts, n_put_contracts
  3. Saves options_pilot/<TICKER>.csv (resumable — skips finished tickers) and
     a combined options_pilot_daily.csv at the end.

RUN ORDER
  python3.12 flame_download.py --test        # 1 ticker, 1 week; prints columns
  caffeinate -i python3.12 flame_download.py # full overnight run

Then: python3.12 flame_backtest.py
"""
import argparse, os, sys, time, glob
from io import StringIO
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
DATA = HERE / "daily_data_v2"
CRUISE = "--cruise" in sys.argv          # B2/S2 signal set instead of DLB/D200G
OUT  = HERE / ("options_pilot_cruise" if CRUISE else "options_pilot")
BASE = "http://127.0.0.1:25503/v3/option/history"
PAUSE = 3.2                       # 20 req/min free tier -> ~3s spacing
BACK_TD, FWD_TD = 45, 65          # trading days around each signal to fetch

# free tier ~= trailing 1 year of EOD. Leave margin: fetch window must start
# after this date. Signals additionally need +60td forward for the backtest.
FREE_FLOOR = pd.Timestamp.today().normalize() - pd.Timedelta(days=360)

ZC={"high52":(-0.149772,0.156737),"dist200":(1.681650,6.240695),"mom6":(0.086250,0.361377),
    "qqe":(0.044473,0.194268),"hull":(0.027496,0.303103),"mom40":(0.020000,0.155298)}
W={"high52":-2.20,"dist200":1.35,"mom6":1.08,"qqe":-0.99,"mom40":0.63,"hull":0.60}
z=lambda v,k:np.clip((v-ZC[k][0])/ZC[k][1],-3,3)
def wma(s,n):
    w=np.arange(1,n+1,dtype=float); return s.rolling(n).apply(lambda x:np.dot(x,w)/w.sum(),raw=True)
def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def find_signals():
    """DLB/D200G first-day signals inside the free-tier window. Returns
    {ticker: [signal_dates]} plus each ticker's fetch window."""
    sigs={}
    for fp in sorted(glob.glob(str(DATA/"*.csv"))):
        t=os.path.splitext(os.path.basename(fp))[0].upper()
        if t in {"SPY","QQQ","RSP"}: continue
        try:
            d=pd.read_csv(fp,index_col=0,parse_dates=True).sort_index()
            if len(d)<600: continue
            C,H=d["Close"],d["High"];pc=C.shift(1)
            tr=pd.concat([H-d["Low"],(H-pc).abs(),(d["Low"]-pc).abs()],axis=1).max(axis=1)
            atr=tr.ewm(alpha=1/14,adjust=False).mean();sma=C.rolling(200).mean()
            f={}
            f["high52"]=C/H.rolling(252).max()-1; f["dist200"]=(C-sma)/atr
            f["mom6"]=C.shift(10)/C.shift(126)-1
            f["qqe"]=(rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50
            hma=wma(2*wma(C,10)-wma(C,20),4); f["hull"]=(hma-hma.shift(1))/atr
            f["mom40"]=C/C.shift(40)-1
            score=sum(W[k]*z(f[k],k) for k in W)
            oh=f["high52"]*100; dpct=(C/sma-1)*100
            if CRUISE:
                mask=(score>=2)&(oh>-25)              # B2 (-25..-10) + S2 (>-10)
            else:
                mask=(score>=2)&(oh<=-25)             # DLB or D200G (any side of line)
            m=mask&~mask.shift(1,fill_value=False)
            idxs=np.where(m&(C>=10))[0]
            last=-99; keep=[]
            for i in idxs:
                if i-last<20: continue
                last=i
                dt=d.index[i]
                # fetch window must sit inside the free year
                if dt - pd.Timedelta(days=70) < FREE_FLOOR: continue
                keep.append(dt)
            if keep:
                lo=min(keep)-pd.Timedelta(days=70)    # ~45 trading days back
                # cap at YESTERDAY: current-day chain data needs an explicit
                # expiration on this API and today's bar is incomplete anyway
                hi=min(max(keep)+pd.Timedelta(days=95),
                       pd.Timestamp.today().normalize()-pd.Timedelta(days=1))
                sigs[t]=dict(signals=[str(x.date()) for x in keep],
                             start=lo.date(), end=hi.date())
        except Exception: pass
    return sigs

def _get(url, params):
    """GET with retries — a network wobble must never kill an hours-long run."""
    import requests
    last_err="unknown"
    for attempt in range(3):
        try:
            r=requests.get(url, params=params, timeout=120)
            time.sleep(PAUSE)
            if r.status_code==200:
                return r.text, None
            last_err=f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (400,403,472):   # permanent for this request — don't retry
                return None,last_err
        except Exception as e:
            last_err=f"{type(e).__name__}: {e}"
            time.sleep(PAUSE)
        time.sleep(10*(attempt+1))               # back off before retrying
    return None,last_err

def _cols(df):
    """map likely column names case-insensitively"""
    m={c.lower():c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in m: return m[n]
        return None
    return dict(right=pick("right"), vol=pick("volume","vol"),
                close=pick("close","last","price"), oi=pick("open_interest","oi"),
                date=pick("date","timestamp","created"))

def fetch_ticker(t, start, end, test=False):
    """chunked monthly requests; returns per-day aggregate DataFrame"""
    chunks=[]
    months=pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="MS").tolist()
    months=[pd.Timestamp(start)]+months if not months or months[0]>pd.Timestamp(start) else months
    bounds=[]
    cur=pd.Timestamp(start)
    while cur<=pd.Timestamp(end):
        nxt=min(cur+pd.Timedelta(days=27), pd.Timestamp(end))
        bounds.append((cur,nxt)); cur=nxt+pd.Timedelta(days=1)
    if test: bounds=bounds[:1]
    daily={}
    for lo,hi in bounds:
        # NOTE: open_interest requires the paid Value tier (403 on FREE) — EOD only.
        # If we ever upgrade, add "open_interest" back to this tuple.
        for kind in ("eod",):
            txt,err=_get(f"{BASE}/{kind}",dict(symbol=t,expiration="*",
                        start_date=lo.strftime("%Y%m%d"),end_date=hi.strftime("%Y%m%d")))
            if err:
                print(f"    {t} {kind} {lo.date()}..{hi.date()}: {err}"); continue
            try:
                df=pd.read_csv(StringIO(txt))
            except Exception as e:
                print(f"    {t} {kind}: unparseable ({e}); first 200 chars:\n{txt[:200]}"); continue
            if test:
                print(f"\n  == {kind} columns == {list(df.columns)}")
                print(df.head(3).to_string()); continue
            c=_cols(df)
            if not c["right"] or not c["date"]:
                print(f"    {t} {kind}: unrecognized schema {list(df.columns)[:12]}"); continue
            df["_d"]=pd.to_datetime(df[c["date"]].astype(str).str[:10],errors="coerce")
            df["_r"]=df[c["right"]].astype(str).str.upper().str[0]   # C / P
            if kind=="eod" and c["vol"]:
                v=df.groupby(["_d","_r"])[c["vol"]].sum().unstack(fill_value=0)
                n=df[df[c["vol"]]>0].groupby(["_d","_r"]).size().unstack(fill_value=0)
                if c["close"]:
                    df["_prem"]=df[c["vol"]]*pd.to_numeric(df[c["close"]],errors="coerce").fillna(0)*100
                    p=df.groupby(["_d","_r"])["_prem"].sum().unstack(fill_value=0)
                else: p=None
                for dt,row in v.iterrows():
                    rec=daily.setdefault(dt,{})
                    rec["call_vol"]=rec.get("call_vol",0)+row.get("C",0)
                    rec["put_vol"]=rec.get("put_vol",0)+row.get("P",0)
                    if p is not None and dt in p.index:
                        rec["call_prem"]=rec.get("call_prem",0)+p.loc[dt].get("C",0)
                        rec["put_prem"]=rec.get("put_prem",0)+p.loc[dt].get("P",0)
                    if dt in n.index:
                        rec["n_call"]=rec.get("n_call",0)+n.loc[dt].get("C",0)
                        rec["n_put"]=rec.get("n_put",0)+n.loc[dt].get("P",0)
            elif kind=="open_interest" and c["oi"]:
                o=df.groupby(["_d","_r"])[c["oi"]].sum().unstack(fill_value=0)
                for dt,row in o.iterrows():
                    rec=daily.setdefault(dt,{})
                    rec["call_oi"]=rec.get("call_oi",0)+row.get("C",0)
                    rec["put_oi"]=rec.get("put_oi",0)+row.get("P",0)
    if test: return None
    if not daily: return None
    out=pd.DataFrame.from_dict(daily,orient="index").sort_index()
    out.index.name="date"
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--test",action="store_true",help="one ticker, one chunk, print schema")
    ap.add_argument("--cruise",action="store_true",help="B2/S2 signal set instead of DLB/D200G")
    a=ap.parse_args()
    OUT.mkdir(exist_ok=True)
    print("Building signal set from daily_data_v2/ (free-tier year only) ...")
    sigs=find_signals()
    nsig=sum(len(v["signals"]) for v in sigs.values())
    print(f"{len(sigs)} tickers, {nsig} DLB/D200G signals in the window")
    pd.DataFrame([dict(ticker=t,**v) for t,v in sigs.items()]).to_csv(OUT/"_signals.csv",index=False)
    if a.test:
        t=sorted(sigs)[0]
        print(f"\nTEST MODE — {t}, first chunk only ({sigs[t]['start']} ..)")
        fetch_ticker(t,sigs[t]["start"],sigs[t]["end"],test=True)
        print("\nIf the columns above include right/volume/close/open_interest/date,"
              " run the full download:\n  caffeinate -i python3.12 flame_download.py")
        return
    done=0
    for i,(t,v) in enumerate(sorted(sigs.items()),1):
        fp=OUT/f"{t}.csv"
        if fp.exists(): done+=1; continue
        agg=fetch_ticker(t,v["start"],v["end"])
        if agg is not None and len(agg):
            agg.to_csv(fp); done+=1
        if i%10==0: print(f"  [{i}/{len(sigs)}] saved {done}")
    # combine
    rows=[]
    for fp in glob.glob(str(OUT/"[A-Z]*.csv")):
        t=os.path.splitext(os.path.basename(fp))[0]
        d=pd.read_csv(fp); d["ticker"]=t; rows.append(d)
    if rows:
        combined="options_pilot_cruise_daily.csv" if CRUISE else "options_pilot_daily.csv"
        pd.concat(rows).to_csv(HERE/combined,index=False)
        print(f"\nDONE: {done} tickers -> {combined}"
              f"\nNext: python3.12 flame_backtest.py")

if __name__=="__main__":
    main()
