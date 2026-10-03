#!/usr/bin/env python3.12
"""
x200g_observe.py — nightly OBSERVATION-ONLY scanner for X200-G
(gap-driven 200-day reclaim; prereg: STS_X200G_PREREG.md, frozen 2026-09-30).

Runs after the price refresh. Scans daily_data_v2/ + daily_data_slow_ext/
for tonight's X200-G signals, appends them to x200g_log.csv (the prospective
validation cohort), and adds a tagged line to Telegram. NOT published to the
site, NOT in the paper book, NOT a trade signal — evidence collection for the
~Q1-2027 promotion decision (bars: wk12 win >= 55%, excess >= +2%, n >= 20).
"""
import glob, os, datetime
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE=Path(__file__).resolve().parent
LOG=HERE/"x200g_log.csv"
TG_TOKEN="8608595671:AAHwVnhGeP3iiX9jk9EV4CPGAmArrbT-DkI"
TG_CHAT="6499078442"

def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def check(fp):
    d=pd.read_csv(fp,index_col=0,parse_dates=True).sort_index()
    if len(d)<400: return None
    C,H,O=d["Close"],d["High"],d["Open"]
    i=len(d)-1
    if float(C.iloc[i])<25: return None
    sma=C.rolling(200).mean()
    if not float(C.iloc[i])>float(sma.iloc[i]): return None
    above=(C>sma)
    streak=0
    for k in range(i,-1,-1):
        if above.iloc[k]: streak+=1
        else: break
    if not (3<=streak<=10): return None
    hi52=H.rolling(252).max()
    washed=((C/hi52-1)<=-0.25).iloc[i-126:i].max()
    if not washed: return None
    below=(~above).iloc[i-60:i].sum()
    if below<20: return None
    qqe=float(((rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50).iloc[i])
    if qqe>=0.20: return None
    gaps=(O.iloc[i-9:i+1].values/C.iloc[i-10:i].values-1)*100
    mx=float(np.nanmax(gaps))
    if mx<5: return None
    return dict(close=round(float(C.iloc[i]),2),gap=round(mx,1),
                streak=streak,qqe=round(qqe,2),date=str(d.index[i].date()))

def main():
    today=datetime.date.today().isoformat()
    prev=set()
    if LOG.exists():
        lg=pd.read_csv(LOG,parse_dates=["signal_date"])
        cutoff=pd.Timestamp(today)-pd.Timedelta(days=60)   # 40td refractory approx
        prev={r.ticker for r in lg.itertuples() if r.signal_date>=cutoff}
    hits=[]
    seen=set()
    for fp in sorted(glob.glob(str(HERE/"daily_data_v2"/"*.csv"))
                     +glob.glob(str(HERE/"daily_data_slow_ext"/"*.csv"))):
        t=os.path.splitext(os.path.basename(fp))[0].upper()
        if t in seen or t in {"SPY","QQQ","RSP"} or t in prev: continue
        seen.add(t)
        try:
            r=check(fp)
            if r: hits.append(dict(ticker=t,**r))
        except Exception: pass
    if hits:
        df=pd.DataFrame(hits); df["signal_date"]=df["date"]; df["scan_date"]=today
    else:
        df=pd.DataFrame([dict(ticker="NO SIGNAL",close="",gap="",streak="",qqe="",
                              date=today,signal_date=today,scan_date=today)])
    df.to_csv(LOG,mode="a",header=not LOG.exists(),index=False)
    print(f"X200-G observation: {len(hits)} signal(s) tonight")
    for h in hits: print(f"  {h['ticker']} gap {h['gap']}% close ${h['close']}")
    # telegram removed 2026-09-30: X200-G now appears in the main evening message

if __name__=="__main__":
    main()
