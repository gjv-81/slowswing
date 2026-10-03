#!/usr/bin/env python3.12
"""
uw_harvest6.py : re-pull implied volatility history as deep as UW goes (from about Jul 17 2023).
Personal research only.

Why: STS_VOL_SETUP_PREREG.md Model 1 uses a 6 month IV rank, which needs IV history
from mid 2023 to start in Jan 2024. The earlier pull (vol_realized_3y) began Oct 2023.

Output: uw_archive/vol_realized_5y/<T>.csv   (one request per ticker, about 1,760 requests)
Reminder: the realized_volatility column in these files looks FORWARD; it is never used.

RUN:  cd ~/STS/15min && caffeinate -i python3.12 uw_harvest6.py
Resumable: tickers already saved are skipped. Stops cleanly at the daily quota.
"""
import glob, time
import uw_harvest5 as h

def main():
    tk=h.tickers(); t0=time.time(); done=empty=0
    job="vol_realized_5y"
    print(f"{len(tk)} tickers")
    try:
        for i,t in enumerate(tk,1):
            if (h.ARCH/job/f"{t}.csv").exists(): continue
            b=h.get(f"/api/stock/{t}/volatility/realized",{"timeframe":"5Y"})
            if b is None: continue
            rows=h.as_list(b)
            h.save(job,t,rows); done+=1; empty+=(not rows)
            if i%100==0: print(f"  {i}/{len(tk)} saved {done} empty {empty} | requests {h.NREQ} | {int(time.time()-t0)}s",flush=True)
    except h.QuotaHit as e:
        print(f"\n== QUOTA or auth stop ({e}). Rerun later; it resumes. ==")
    n=len(glob.glob(str(h.ARCH/job/'*.csv')))
    print(f"\nRequests this run: {h.NREQ} | {job}: {n} of {len(tk)} tickers saved")

if __name__=="__main__": main()
