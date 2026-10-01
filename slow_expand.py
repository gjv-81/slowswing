#!/usr/bin/env python3.12
"""
slow_expand.py — find HIGH-QUALITY mid/large-cap candidates for the SLOW-LANE
universe (the site spec: price >= $50, mid/large cap), from the daily_data_ext
pool (US common stocks, already ETF-free), excluding names already in v2.

SCREEN (pre-committed):
  1. last close >= $50
  2. market cap >= $2B          (mid-cap floor; Yahoo fast_info)
  3. >= 750 daily bars (~3 yrs listed — matches the model's training rule)
  4. avg daily dollar volume (60d) >= $10M   (tradeable)
Survivors: slow_candidates.txt + 10 years of daily bars -> daily_data_slow_ext/
(SEPARATE folder — these names join the scan only via the dated Oct-15
universe decision; until then they exist for backtesting, e.g. X200.)

RUN:  cd ~/STS/15min && caffeinate -i python3.12 slow_expand.py
Resumable; cap lookups are throttled for Yahoo (expect ~20-30 min first run).
"""
import glob, os, time, sys
from pathlib import Path
import pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE=Path(__file__).resolve().parent
EXT=HERE/"daily_data_ext"
OUT=HERE/"daily_data_slow_ext"
LIST=HERE/"slow_candidates.txt"
CAPCACHE=HERE/"uw_archive"/"_cap_cache.csv"
MIN_PRICE=50.0; MIN_CAP=2e9; MIN_BARS=750; MIN_DVOL=10e6

def main():
    import yfinance as yf
    v2={os.path.splitext(os.path.basename(f))[0] for f in glob.glob(str(HERE/"daily_data_v2"/"*.csv"))}
    caps={}
    if CAPCACHE.exists():
        for _,r in pd.read_csv(CAPCACHE).iterrows(): caps[r["ticker"]]=r["cap"]
    # stage 1: local screens (price, bars, dollar volume) — no network
    stage1=[]
    for fp in sorted(glob.glob(str(EXT/"*.csv"))):
        t=os.path.splitext(os.path.basename(fp))[0]
        if t in v2: continue
        try:
            d=pd.read_csv(fp)
            if len(d)<MIN_BARS: continue
            close=float(d["Close"].iloc[-1])
            if close<MIN_PRICE: continue
            dvol=(d["Close"].tail(60)*d["Volume"].tail(60)).mean()
            if dvol<MIN_DVOL: continue
            stage1.append(t)
        except Exception: pass
    print(f"local screens (>= ${MIN_PRICE:.0f}, {MIN_BARS}+ bars, >= ${MIN_DVOL/1e6:.0f}M/day): {len(stage1)} candidates")
    # stage 2: market cap via Yahoo (cached, throttled)
    keep=[]
    for i,t in enumerate(stage1,1):
        if t in caps:
            cap=caps[t]
        else:
            cap=None
            for a in range(3):
                try:
                    cap=yf.Ticker(t).fast_info.get("market_cap") or yf.Ticker(t).fast_info.get("marketCap")
                    break
                except Exception: time.sleep(5*(a+1))
            caps[t]=cap if cap else -1
            time.sleep(0.8)
            if i%25==0:
                pd.DataFrame([{"ticker":k,"cap":v} for k,v in caps.items()]).to_csv(CAPCACHE,index=False)
                print(f"  [{i}/{len(stage1)}] kept so far {len(keep)}")
        if caps[t] and caps[t]>=MIN_CAP: keep.append(t)
    pd.DataFrame([{"ticker":k,"cap":v} for k,v in caps.items()]).to_csv(CAPCACHE,index=False)
    LIST.write_text("\n".join(sorted(keep))+"\n")
    print(f"\nQUALITY SURVIVORS (cap >= ${MIN_CAP/1e9:.0f}B): {len(keep)} -> {LIST.name}")
    # stage 3: 10y history download
    OUT.mkdir(exist_ok=True)
    todo=[t for t in keep if not (OUT/f"{t}.csv").exists()]
    print(f"downloading 10y bars for {len(todo)} names ...")
    CH=80
    ok=len(keep)-len(todo)
    for i in range(0,len(todo),CH):
        chunk=todo[i:i+CH]
        try:
            raw=yf.download(chunk,period="10y",interval="1d",auto_adjust=True,
                            group_by="ticker",progress=False,threads=True)
        except Exception as e:
            print(f"  batch failed: {e}"); continue
        for t in chunk:
            try:
                d=(raw[t] if len(chunk)>1 else raw).dropna()
                if len(d)<MIN_BARS: continue
                d=d[["Open","High","Low","Close","Volume"]]
                d.index.name="Date"
                d.reset_index().to_csv(OUT/f"{t}.csv",index=False)
                ok+=1
            except Exception: pass
        print(f"  {min(i+CH,len(todo))}/{len(todo)} | saved {ok}")
        time.sleep(2)
    print(f"\nDONE: {ok} quality mid/large-cap names in daily_data_slow_ext/")
    print("They join the live scan only via the dated Oct-15 universe decision;")
    print("available immediately for backtests (x200_backtest.py uses them).")

if __name__=="__main__":
    main()
