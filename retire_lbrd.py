#!/usr/bin/env python3
"""Retire LBRDA / LBRDK — merged into Charter (CHTR) on 2026-08-21.

Why by hand: Yahoo drops a ticker's recent history once it stops trading, so
daily_data_10y/LBRD?.csv jumps from 2026-07-17 straight to a lone zero-volume
bar on 2026-08-21. The tracker counts bars since entry (2026-07-20), sees one,
and calls the position "Active" forever — while the board drops it nightly as
stale. Two things fix that for good:

  1. fill the missing 2026-07-20 .. 2026-08-21 bars from Marketstack (2 requests)
     so the tracker sees the real 4+ weeks and retires it at the true last price;
  2. set close_date=2026-08-21 in sts_ml_paper_trades.csv so it is CLOSED, with
     a note saying why.

Idempotent. Backs up both CSVs before touching them.
    cd ~/STS/15min && /usr/local/bin/python3.12 retire_lbrd.py
"""
import sys, shutil, datetime as dt
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eod_adapter import get_provider

TICKERS = ["LBRDA", "LBRDK"]
CLOSE = "2026-08-21"
NOTE = "merged into CHTR 2026-08-21 (retired at last close)"
STAMP = dt.datetime.now().strftime("%Y%m%d_%H%M")

prov = get_provider()
for t in TICKERS:
    p = HERE / "daily_data_10y" / f"{t}.csv"
    old = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
    bars = prov.get_history(t, "2026-07-01", CLOSE)
    fresh = pd.DataFrame([{"Date": pd.Timestamp(b.date), "Open": b.open, "High": b.high,
                           "Low": b.low, "Close": b.close, "Volume": b.volume or 0}
                          for b in bars]).set_index("Date").sort_index()
    have = set(old.index)
    add = fresh[~fresh.index.isin(have)]
    # the lone zero-volume 08-21 bar is a Yahoo placeholder; prefer the vendor's real one
    if pd.Timestamp(CLOSE) in old.index and pd.Timestamp(CLOSE) in fresh.index and float(old.loc[CLOSE, "Volume"]) == 0:
        old = old.drop(pd.Timestamp(CLOSE)); add = fresh[~fresh.index.isin(set(old.index))]
    if len(add) == 0:
        print(f"{t}: nothing to add (already {len(old)} rows through {old.index.max().date()})")
        continue
    shutil.copy(p, p.with_suffix(f".csv.bak_{STAMP}"))
    merged = pd.concat([old, add]).sort_index()
    merged = merged[~merged.index.duplicated(keep="first")]
    merged.index.name = "Date"
    merged.to_csv(p)
    print(f"{t}: added {len(add)} bars {add.index.min().date()}..{add.index.max().date()}; "
          f"last close {float(merged['Close'].iloc[-1]):.2f} on {merged.index.max().date()}")

tp = HERE / "sts_ml_paper_trades.csv"
tr = pd.read_csv(tp, dtype=str, keep_default_na=False)
if "close_date" not in tr.columns:
    tr["close_date"] = ""
changed = 0
for i, r in tr.iterrows():
    if r["ticker"] in TICKERS and not r["close_date"]:
        tr.at[i, "close_date"] = CLOSE
        tr.at[i, "notes"] = (r["notes"] + "; " if r["notes"] else "") + NOTE
        changed += 1
if changed:
    shutil.copy(tp, tp.with_suffix(f".csv.bak_{STAMP}"))
    tr.to_csv(tp, index=False)
print(f"trades csv: {changed} row(s) closed on {CLOSE}" + (" (already done)" if not changed else ""))
print("\nNext: tonight's run (or  zsh run_evening.sh  now) rebuilds the tracker, workbook and board.")
