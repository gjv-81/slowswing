#!/usr/bin/env python3.12
"""
uw_harvest.py — bulk-archive Unusual Whales data during the API trial.
PERSONAL RESEARCH USE ONLY (UW terms: no redistribution — never feeds the website).

PHASE 1 (this script, ~5-6k requests for ~1,026 tickers):
  uw_archive/options_volume/<T>.csv   daily side-classified call/put volume+premium (~2yr)
  uw_archive/greek_exposure/<T>.csv   daily GEX/DEX/charm/vanna history (~1yr)
  uw_archive/iv_rank/<T>.csv          daily IV + IV-rank history
  uw_archive/flow_alerts/<T>.csv      recent UW-classified unusual alerts
  uw_archive/market/*.csv             market tide, total options volume
Resumable: skips tickers already saved. Budget-capped at 35k requests/run.

RUN:  cd ~/STS/15min && caffeinate -i python3.12 uw_harvest.py
"""
import os, sys, time, json, glob
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
ARCH=HERE/"uw_archive"
BASE="https://api.unusualwhales.com"
BUDGET=35000
PAUSE=0.30                     # polite pacing; ~3/sec max

def token():
    env=HERE/".env_uw"
    for ln in env.read_text().splitlines():
        if "UW_TOKEN" in ln: return ln.split("=",1)[1].strip().strip('"').strip("'")
    sys.exit("UW_TOKEN missing")

TOK=token(); NREQ=0
def get(path, params=None):
    global NREQ
    import requests
    if NREQ>=BUDGET: sys.exit(f"request budget {BUDGET} reached — rerun tomorrow (resumable)")
    NREQ+=1
    for attempt in range(3):
        try:
            r=requests.get(BASE+path, params=params or {},
                headers={"Authorization":f"Bearer {TOK}","Accept":"application/json"},timeout=60)
            time.sleep(PAUSE)
            if r.status_code==200: return r.json()
            if r.status_code in (404,422): return None
            if r.status_code==429: time.sleep(30); continue
            return None
        except Exception:
            time.sleep(5*(attempt+1))
    return None

def rows(body):
    if body is None: return []
    d=body.get("data",body) if isinstance(body,dict) else body
    return d if isinstance(d,list) else ([d] if isinstance(d,dict) else [])

def save(sub, t, recs):
    if not recs: return False
    d=ARCH/sub; d.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(recs).to_csv(d/f"{t}.csv",index=False)
    return True

def paged(path, limit=500, max_pages=4, params=None):
    """options-volume style pagination: try page=0..n until short/empty page."""
    out=[]; seen=set()
    for pg in range(max_pages):
        p=dict(params or {}); p.update(limit=limit, page=pg)
        rs=rows(get(path,p))
        if not rs: break
        key=json.dumps(rs[0],sort_keys=True,default=str)
        if key in seen: break                      # page param ignored -> stop
        seen.add(key); out.extend(rs)
        if len(rs)<limit: break
    return out

def main():
    ARCH.mkdir(exist_ok=True)
    tickers=[t.strip() for t in open(HERE/"universe_v2_tickers.txt") if t.strip()]
    print(f"harvesting {len(tickers)} tickers (budget {BUDGET} requests)")
    # market-wide first (cheap)
    for name,path,params in [("market_tide","/api/market/market-tide",{}),
                             ("total_options_volume","/api/market/total-options-volume",{"limit":500}),
                             ("oi_change_market","/api/market/oi-change",{"limit":500})]:
        rs=rows(get(path,params))
        if rs:
            (ARCH/"market").mkdir(parents=True,exist_ok=True)
            pd.DataFrame(rs).to_csv(ARCH/"market"/f"{name}.csv",index=False)
            print(f"  market/{name}: {len(rs)} rows")
    done=0
    for i,t in enumerate(tickers,1):
        if (ARCH/"options_volume"/f"{t}.csv").exists(): done+=1; continue
        ok=save("options_volume",t,paged(f"/api/stock/{t}/options-volume"))
        save("greek_exposure",t,rows(get(f"/api/stock/{t}/greek-exposure")))
        save("iv_rank",t,rows(get(f"/api/stock/{t}/iv-rank",{"limit":500})))
        save("flow_alerts",t,rows(get(f"/api/stock/{t}/flow-alerts",{"limit":200})))
        if ok: done+=1
        if i%25==0: print(f"  [{i}/{len(tickers)}] saved {done} | requests used {NREQ}")
    print(f"\nDONE phase 1: {done} tickers archived | total requests {NREQ}")
    print("Next: python3.12 uw_backtest.py   (pre-registered flame stage-2)")

if __name__=="__main__":
    main()
