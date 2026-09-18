#!/usr/bin/env python3
"""
fetch_names.py — build names.json { "TICKER": "Company Name", ... } for the board.

The workbook has no company names, but the site shows them (e.g. "NVIDIA", not
"NVDA"). This fills that gap using yfinance (already installed for your pipeline).

RUN ONCE on the Mac (it has yfinance + internet):
    cd ~/STS/15min && python3 fetch_names.py
Re-run whenever new tickers appear on the board. It's incremental (skips names
it already has) and checkpoints as it goes, so it's safe to interrupt.
"""
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
XLSX = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "STS_holy_grail.xlsx"
OUT = HERE / "names.json"
TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,5}$")

import pandas as pd

tr = pd.read_excel(XLSX, sheet_name="Tracker")
tickers = sorted({str(t).upper() for t in tr["ticker"] if TICKER_RE.match(str(t))})

names = {}
if OUT.is_file():
    try:
        names = {k.upper(): v for k, v in json.loads(OUT.read_text()).items()}
    except Exception:
        names = {}

try:
    import yfinance as yf
except ImportError:
    sys.exit("This needs yfinance:  python3 -m pip install yfinance")

todo = [t for t in tickers if t not in names]
print(f"{len(tickers)} tickers total, {len(todo)} to fetch ...")
for i, t in enumerate(todo, 1):
    try:
        info = yf.Ticker(t).get_info()
        names[t] = info.get("shortName") or info.get("longName") or t
    except Exception as e:
        names[t] = t
        print(f"  {t}: failed ({e}) — leaving as ticker")
    print(f"  {i}/{len(todo)}  {t} -> {names[t]}")
    if i % 10 == 0:
        OUT.write_text(json.dumps(names, indent=2, ensure_ascii=False))   # checkpoint
    time.sleep(0.3)

OUT.write_text(json.dumps(names, indent=2, ensure_ascii=False))
print(f"\nwrote {OUT}  ({len(names)} names)")
