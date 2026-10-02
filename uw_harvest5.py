#!/usr/bin/env python3.12
"""
uw_harvest5.py : literature driven gap fill (Oct 2026). Personal research only.

Jobs, in priority order (each resumable: a ticker whose file exists is skipped):
  1. earnings_hist/      earnings dates + expected move + pre/post moves   1 request per ticker
  2. vol_realized_3y/    daily implied vol and realized vol, 3 years        1 request per ticker
                         (stock level volatility risk premium; IV history beyond 1 year)
  3. option_sentiment/   AVAR (call vs put IV asymmetry, smirk proxy), VWKS, score
                         paged backwards by date, about 4 requests per ticker, back to Sep 2024
  4. borrow_daily/       daily borrow fee, rebate, shares available (borrow cost control)
                         paged backwards, up to 15 requests per ticker, collapsed to one row per day
  5. rr_skew_jan27/      25 delta risk reversal skew on the Jan 15 2027 expiry (expired expiries
                         return nothing, so a long dated live expiry is the only history)
Universe: every ticker with options_volume coverage (core + expansion, about 1,760).
Expected total: about 30,000 requests, one quota day.

RUN:  cd ~/STS/15min && caffeinate -i python3.12 uw_harvest5.py
Stops cleanly at the daily quota; rerun later and it resumes.
"""
import glob, os, sys, time
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
ARCH=HERE/"uw_archive"
BASE="https://api.unusualwhales.com"
PAUSE=0.30; NREQ=0
FLOOR="2024-09-01"

def token():
    for f in (".env_uw",".env_uw_live"):
        p=HERE/f
        if p.exists():
            for ln in p.read_text().splitlines():
                if "UW_TOKEN" in ln: return ln.split("=",1)[1].strip().strip('"').strip("'")
    sys.exit("UW_TOKEN missing (.env_uw)")
TOK=token()

class QuotaHit(Exception): pass
def get(path,params=None):
    """returns parsed json, {} for genuinely empty / not found, None on transient failure"""
    global NREQ
    import requests
    n429=0
    for a in range(6):
        try:
            NREQ+=1
            r=requests.get(BASE+path,params=params or {},timeout=60,
                headers={"Authorization":f"Bearer {TOK}","Accept":"application/json"})
            time.sleep(PAUSE)
            if r.status_code==200: return r.json()
            if r.status_code==429:
                n429+=1
                if n429>=4: raise QuotaHit(r.text[:200])
                time.sleep(30*n429); continue
            if r.status_code in (401,403): raise QuotaHit(f"{r.status_code} {r.text[:200]}")
            if r.status_code in (404,422): return {}
            time.sleep(5)
        except QuotaHit: raise
        except Exception: time.sleep(5*(a+1))
    return None

def as_list(b, key=None):
    if not b: return []
    d=b.get("data",b) if isinstance(b,dict) else b
    if isinstance(d,dict):
        if key and isinstance(d.get(key),list): return d[key]
        for v in d.values():
            if isinstance(v,list): return v
        return [d]
    return d if isinstance(d,list) else []

def tickers():
    s=set()
    for d in ("options_volume","options_volume_ext"):
        s|={os.path.splitext(os.path.basename(f))[0].upper() for f in glob.glob(str(ARCH/d/"*.csv"))}
    return sorted(s)

def save(job,t,rows):
    d=ARCH/job; d.mkdir(exist_ok=True)
    pd.DataFrame(rows if rows else [{"_empty":1}]).to_csv(d/f"{t}.csv",index=False)

# ---------------- jobs ----------------
def job_earnings(t):
    b=get(f"/api/earnings/{t}")
    return None if b is None else as_list(b)

def job_vol(t):
    b=get(f"/api/stock/{t}/volatility/realized",{"timeframe":"3Y"})
    return None if b is None else as_list(b)

def job_sentiment(t):
    rows=[]; date=None; seen=set()
    for _ in range(6):
        b=get(f"/api/stock/{t}/volatility/option-sentiment",{"date":date} if date else {})
        if b is None: return None
        lst=as_list(b,"history")
        new=[r for r in lst if isinstance(r,dict) and r.get("date") and r["date"] not in seen]
        if not new: break
        for r in new: seen.add(r["date"])
        rows+=new
        earliest=min(r["date"] for r in new)[:10]
        if earliest<=FLOOR: break
        date=(pd.Timestamp(earliest)-pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return rows

def job_borrow(t):
    rows=[]; older=None; last_earliest=None
    for _ in range(15):
        b=get(f"/api/shorts/{t}/data",{"older_than":older} if older else {})
        if b is None: return None
        lst=[r for r in as_list(b) if isinstance(r,dict) and r.get("timestamp")]
        if not lst: break
        rows+=lst
        earliest=min(str(r["timestamp"]) for r in lst)
        if earliest[:10]<=FLOOR or earliest==last_earliest: break
        last_earliest=earliest; older=earliest
    if not rows: return []
    df=pd.DataFrame(rows)
    df["date"]=df["timestamp"].astype(str).str[:10]
    df=df.sort_values("timestamp").groupby("date").last().reset_index()
    keep=[c for c in ["date","fee_rate","rebate_rate","short_shares_available"] if c in df.columns]
    return df[keep].to_dict("records")

def job_rr(t):
    b=get(f"/api/stock/{t}/historical-risk-reversal-skew",{"expiry":"2027-01-15","delta":"25","timeframe":"2Y"})
    return None if b is None else as_list(b)

JOBS=[("earnings_hist",job_earnings),("vol_realized_3y",job_vol),("option_sentiment",job_sentiment),
      ("borrow_daily",job_borrow),("rr_skew_jan27",job_rr)]

def main():
    tk=tickers(); t0=time.time()
    print(f"{len(tk)} tickers, {len(JOBS)} jobs")
    try:
        for job,fn in JOBS:
            done=empty=0
            for i,t in enumerate(tk,1):
                if (ARCH/job/f"{t}.csv").exists(): continue
                rows=fn(t)
                if rows is None: continue          # transient, retried next run
                save(job,t,rows); done+=1; empty+=(not rows)
                if i%100==0: print(f"  {job}: {i}/{len(tk)} saved {done} empty {empty} | requests {NREQ} | {int(time.time()-t0)}s",flush=True)
            print(f"== {job} finished: saved {done}, empty {empty}",flush=True)
    except QuotaHit as e:
        print(f"\n== QUOTA or auth stop ({e}). Rerun later; it resumes. ==")
    print(f"\nRequests this run: {NREQ}")
    for job,_ in JOBS:
        n=len(glob.glob(str(ARCH/job/'*.csv')))
        print(f"  {job}: {n} of {len(tk)} tickers saved")

if __name__=="__main__": main()
