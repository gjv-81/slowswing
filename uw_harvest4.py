#!/usr/bin/env python3.12
"""
uw_harvest4.py : GREEK FLOW (directional vega and delta flow) daily history.
Personal research only, never redistributed.

What it is: UW's greek flow endpoint returns, per ticker per day, minute by
minute delta flow and vega flow, split into DIRECTIONAL (signed by trade side:
bought at ask = positive, sold at bid = negative) and TOTAL. Directional vega
flow is the "vega weighted institutional flow" behind a conviction Z score.

Cost: ONE request per ticker per day, so we pull a focused slice:
  the most liquid option names (median daily call+put premium, last year),
  plus SPY, QQQ, IWM and the 17 watchlist names, full history each.
Names are pulled in liquidity order with complete date ranges, so if quota
runs out we have fewer names but every name we have is complete.

Storage: the 390 minute rows are collapsed to ONE row per day:
  sums of every flow field, minutes count, and last 60 minutes of
  directional delta and vega flow (late day positioning).
Empty days are recorded (minutes = 0) so they are never requested twice.

Output: uw_archive/greek_flow_daily/<T>.csv

RUN:  cd ~/STS/15min && caffeinate -i python3.12 uw_harvest4.py
      optional: --top 250 (default)   --start 2025-01-02 (default)
Stops cleanly if the daily quota is hit (repeated 429). Rerun after the
8pm ET reset and it resumes exactly where it left off.
Speed: about 6,000 requests per hour; 250 names x ~430 days is ~107k
requests, so plan on roughly 3 quota days (tonight, Sep 29, Sep 30, Oct 1).
"""
import glob, os, sys, time, csv
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
ARCH=HERE/"uw_archive"; OUT=ARCH/"greek_flow_daily"; OUT.mkdir(exist_ok=True)
BASE="https://api.unusualwhales.com"
PAUSE=0.30; NREQ=0
TOP=int(sys.argv[sys.argv.index("--top")+1]) if "--top" in sys.argv else 250
START=sys.argv[sys.argv.index("--start")+1] if "--start" in sys.argv else "2025-01-02"
FORCE=["SPY","QQQ","IWM","VEEV","SNOW","TTD","ARM","ASML","SE","RKLB","CRWV","HOOD",
       "COIN","PLTR","NBIS","ALAB","SNDK","MU","MRVL","WDC"]
FIELDS=["dir_delta_flow","dir_vega_flow","otm_dir_delta_flow","otm_dir_vega_flow",
        "otm_total_delta_flow","otm_total_vega_flow","total_delta_flow","total_vega_flow",
        "transactions","volume"]
COLS=["date","minutes"]+FIELDS+["last60_dir_delta_flow","last60_dir_vega_flow"]

def token():
    for f in (".env_uw",".env_uw_live"):
        p=HERE/f
        if p.exists():
            for ln in p.read_text().splitlines():
                if "UW_TOKEN" in ln: return ln.split("=",1)[1].strip().strip('"').strip("'")
    sys.exit("UW_TOKEN missing (.env_uw)")
TOK=token()

class QuotaHit(Exception): pass
def get(path,params):
    """returns list of rows, [] for a genuinely empty day, None on a transient failure"""
    global NREQ
    import requests
    n429=0
    for a in range(6):
        try:
            NREQ+=1
            r=requests.get(BASE+path,params=params,timeout=60,
                headers={"Authorization":f"Bearer {TOK}","Accept":"application/json"})
            time.sleep(PAUSE)
            if r.status_code==200:
                b=r.json(); d=b.get("data",b) if isinstance(b,dict) else b
                return d if isinstance(d,list) else []
            if r.status_code==429:
                n429+=1
                if n429>=4: raise QuotaHit(r.text[:200])
                time.sleep(30*n429); continue
            if r.status_code in (401,403): raise QuotaHit(f"{r.status_code} {r.text[:200]}")
            if r.status_code in (404,422): return []
            time.sleep(5)
        except QuotaHit: raise
        except Exception: time.sleep(5*(a+1))
    return None

def f(x):
    try: return float(x)
    except Exception: return 0.0

def summarize(day,rs):
    row={"date":day,"minutes":len(rs)}
    for k in FIELDS: row[k]=round(sum(f(x.get(k)) for x in rs),2)
    rs=sorted(rs,key=lambda x:str(x.get("timestamp","")))[-60:]
    row["last60_dir_delta_flow"]=round(sum(f(x.get("dir_delta_flow")) for x in rs),2)
    row["last60_dir_vega_flow"]=round(sum(f(x.get("dir_vega_flow")) for x in rs),2)
    return row

def ranked_tickers():
    liq={}
    for d in ("options_volume","options_volume_ext"):
        for fp in glob.glob(str(ARCH/d/"*.csv")):
            t=os.path.splitext(os.path.basename(fp))[0].upper()
            try:
                o=pd.read_csv(fp,usecols=["date","call_premium","put_premium"]).sort_values("date").tail(250)
                if len(o)>=200: liq[t]=float((o.call_premium+o.put_premium).median())
            except Exception: pass
    top=[t for t,_ in sorted(liq.items(),key=lambda kv:-kv[1])][:TOP]
    return list(dict.fromkeys([t for t in FORCE if t in liq or t in ("SPY","QQQ","IWM")]+top))

def trading_days():
    px=pd.read_csv(HERE/"daily_data_v2"/"SPY.csv",usecols=[0])
    ds=pd.to_datetime(px.iloc[:,0]).dt.strftime("%Y-%m-%d")
    return [d for d in ds if d>=START]

def main():
    tk=ranked_tickers(); days=trading_days()
    print(f"greek flow: {len(tk)} tickers x {len(days)} days ({days[0]} to {days[-1]})")
    t0=time.time()
    try:
        for i,t in enumerate(tk,1):
            fp=OUT/f"{t}.csv"
            have=set(pd.read_csv(fp,usecols=["date"])["date"].astype(str)) if fp.exists() else set()
            todo=[d for d in days if d not in have]
            if not todo: continue
            new=0
            with open(fp,"a",newline="") as h:
                w=csv.DictWriter(h,fieldnames=COLS)
                if not have: w.writeheader()
                for d in todo:
                    rs=get(f"/api/stock/{t}/greek-flow",{"date":d})
                    if rs is None: continue            # transient: retry next run
                    w.writerow(summarize(d,rs)); new+=1
                    h.flush()
            print(f"  [{i}/{len(tk)}] {t}: +{new} days  | requests {NREQ} | {int(time.time()-t0)}s")
    except QuotaHit as e:
        print(f"\n== QUOTA or auth stop ({e}). Rerun after the 8pm ET reset; it resumes. ==")
    print(f"\nRequests this run: {NREQ}")
    done=[p for p in OUT.glob("*.csv")]
    full=sum(1 for p in done if len(pd.read_csv(p,usecols=["date"]))>=len(days))
    print(f"Tickers with complete history: {full} of {len(tk)} targeted")

if __name__=="__main__": main()
