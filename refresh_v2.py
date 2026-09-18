#!/usr/bin/env python3.12
"""
refresh_v2.py — nightly data refresh for the SEPARATE v2 universe (daily_data_v2/).
Batch-downloads the last 2 years for every ticker already in daily_data_v2/
(plus SPY/RSP) and MERGES the fresh bars into each CSV: deep history preserved,
fresh (re-adjusted) values win on overlapping dates. Same merge logic as the
live pipeline's write_back. Fast: chunked/threaded yfinance (~1000 names in a
few minutes). Run by run_v2_evening.sh before eval_universe_v2.py.
"""
import os, glob
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
OUTDIR = HERE / "daily_data_v2"
COLS = ["Open", "High", "Low", "Close", "Volume"]

def main():
    tickers = sorted({os.path.splitext(os.path.basename(f))[0].upper()
                      for f in glob.glob(str(OUTDIR / "*.csv"))} | {"SPY", "RSP"})
    if not tickers:
        raise SystemExit("daily_data_v2/ is empty — run build_universe.py first")
    import yfinance as yf
    print(f"Refreshing {len(tickers)} v2 tickers (2y batch) ...")
    updated = failed = 0
    CH = 100
    for i in range(0, len(tickers), CH):
        chunk = tickers[i:i+CH]
        try:
            raw = yf.download(chunk, period="2y", progress=False,
                              auto_adjust=True, group_by="ticker", threads=True)
        except Exception as e:
            print(f"  batch {i//CH+1} failed: {e}"); failed += len(chunk); continue
        for t in chunk:
            try:
                f = (raw[t] if len(chunk) > 1 else raw).dropna()
                f = f[[c for c in COLS if c in f.columns]]
                if len(f) == 0: failed += 1; continue
                f.index = pd.to_datetime(f.index); f.index.name = "Date"
                path = OUTDIR / f"{t}.csv"
                if path.exists():
                    old = pd.read_csv(path, index_col=0, parse_dates=True)
                    old = old[[c for c in COLS if c in old.columns]]
                    merged = pd.concat([old[old.index < f.index.min()], f]).sort_index()
                    merged = merged[~merged.index.duplicated(keep="last")]
                else:
                    merged = f
                merged.reset_index().to_csv(path, index=False)
                updated += 1
            except Exception:
                failed += 1
        print(f"  {min(i+CH, len(tickers))}/{len(tickers)} done")
    print(f"v2 refresh: {updated} updated, {failed} failed")

if __name__ == "__main__":
    main()
