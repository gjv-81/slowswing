#!/usr/bin/env python3.12
"""
uw_harvest3.py : GAP FILL before the UW trial ends (~Oct 2). Personal research only.

Why: the audit on 2026-09-28 found
  iv_rank/        only 5 days of history (default call returned 1 week)
  greek_exposure/ only 1 year (Sep 2025 onward), half the options_volume window
This script pulls the deepest history the API will give, for every ticker that
has options_volume coverage (core + expansion, about 1,760 names).

Output (new folders, the old ones are left untouched):
  uw_archive/iv_rank_hist/<T>.csv      daily close, implied volatility, iv_rank_1y
  uw_archive/greek_exposure_2y/<T>.csv daily call/put gamma, delta, charm, vanna

Step 1 (PROBE): on NVDA it tries several parameter variants per endpoint and
keeps whichever returns the earliest start date. It prints what it found, so
you can see how deep the history really goes before the bulk run.
Step 2 (BULK): every ticker, resumable (a ticker whose file already exists is
skipped), capped at 35,000 requests; rerun to continue.

RUN:  cd ~/STS/15min && caffeinate -i python3.12 uw_harvest3.py
      (add --probe to run only step 1)
Expected: about 3,500 requests, roughly 25 to 40 minutes.
"""
import glob, os, sys, time, json
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
ARCH=HERE/"uw_archive"
BASE="https://api.unusualwhales.com"
BUDGET=35000; PAUSE=0.30; NREQ=0

def token():
    for f in (".env_uw",".env_uw_live"):
        p=HERE/f
        if p.exists():
            for ln in p.read_text().splitlines():
                if "UW_TOKEN" in ln: return ln.split("=",1)[1].strip().strip('"').strip("'")
    sys.exit("UW_TOKEN missing (.env_uw)")
TOK=token()

def get(path,params=None):
    global NREQ
    import requests
    if NREQ>=BUDGET:
        print(f"\n== budget {BUDGET} reached, rerun tomorrow and it resumes =="); sys.exit(0)
    NREQ+=1
    for a in range(3):
        try:
            r=requests.get(BASE+path,params=params or {},timeout=60,
                headers={"Authorization":f"Bearer {TOK}","Accept":"application/json"})
            time.sleep(PAUSE)
            if r.status_code==200: return r.json()
            if r.status_code==429: time.sleep(30); continue
            if r.status_code in (401,403): print(f"   {r.status_code} on {path} {params}: {r.text[:150]}")
            return None
        except Exception: time.sleep(5*(a+1))
    return None
def rows(b):
    if b is None: return []
    d=b.get("data",b) if isinstance(b,dict) else b
    return d if isinstance(d,list) else ([d] if isinstance(d,dict) else [])
def span(rs):
    ds=sorted(str(r.get("date") or r.get("market_date") or "")[:10] for r in rs)
    ds=[d for d in ds if d]
    return (ds[0],ds[-1],len(ds)) if ds else (None,None,0)

JOBS={
 "iv_rank_hist":("/api/stock/{t}/iv-rank",
    [{"timespan":"2y"},{"timespan":"2024-09-01"},{"timespan":"1y"},{"timespan":"2y","limit":600}]),
 "greek_exposure_2y":("/api/stock/{t}/greek-exposure",
    [{"timeframe":"2Y"},{"timeframe":"3Y"},{"timeframe":"1Y"}]),
}

def probe():
    best={}
    for job,(path,variants) in JOBS.items():
        print(f"\n== PROBE {job} on NVDA")
        top=None
        for v in variants:
            s=span(rows(get(path.format(t="NVDA"),v)))
            print(f"   {json.dumps(v):32s} -> start {s[0]}  end {s[1]}  rows {s[2]}")
            if s[0] and (top is None or s[0]<top[1][0] or (s[0]==top[1][0] and s[2]>top[1][2])): top=(v,s)
        if top: print(f"   BEST: {top[0]}  ({top[1][2]} rows from {top[1][0]})"); best[job]=top[0]
        else: print("   no variant returned data; this job will be skipped")
    (ARCH/"_harvest3_params.json").write_text(json.dumps(best,indent=1))
    return best

def tickers():
    s=set()
    for d in ("options_volume","options_volume_ext"):
        s|={os.path.splitext(os.path.basename(f))[0].upper() for f in glob.glob(str(ARCH/d/"*.csv"))}
    return sorted(s)

def bulk(best):
    tk=tickers(); print(f"\n== BULK: {len(tk)} tickers x {len(best)} jobs")
    for job,params in best.items():
        path=JOBS[job][0]; out=ARCH/job; out.mkdir(exist_ok=True)
        done=miss=0; t0=time.time()
        for i,t in enumerate(tk,1):
            f=out/f"{t}.csv"
            if f.exists(): continue
            rs=rows(get(path.format(t=t),params))
            if rs: pd.DataFrame(rs).to_csv(f,index=False); done+=1
            else: miss+=1
            if i%100==0: print(f"   {job}: {i}/{len(tk)}  saved {done}  empty {miss}  req {NREQ}  {int(time.time()-t0)}s")
        print(f"   {job} finished: saved {done}, empty {miss}")

def audit():
    print("\n== AUDIT (median ticker)")
    for job in JOBS:
        st=[];n=[]
        for f in glob.glob(str(ARCH/job/"*.csv")):
            try:
                d=pd.read_csv(f,usecols=["date"])["date"].astype(str).str[:10]
                st.append(d.min()); n.append(len(d))
            except Exception: pass
        if n: print(f"   {job}: {len(n)} files | median start {sorted(st)[len(st)//2]} | median rows {int(pd.Series(n).median())}")

if __name__=="__main__":
    best=probe()
    if "--probe" in sys.argv or not best: sys.exit(0)
    bulk(best); audit()
    print(f"\nDone. Requests used this run: {NREQ}")
