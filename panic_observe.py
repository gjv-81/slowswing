#!/usr/bin/env python3.12
"""
panic_observe.py — nightly OBSERVATION tag for "panic entry" conditions.
(Pre-registered study: STS_T5_MKTGAP_PREREG.md, 2026-10-30. Logged tag only —
changes nothing about what qualifies.)

Conditions (both must be true for the tag to be ON for the next 3 sessions):
  1. HEAVY GAP-DOWN DAY: >= HEAVY_THRESHOLD stocks in daily_data_v2 gapped down
     today (today's high < yesterday's low AND open <= 0.98 x yesterday's close).
     Threshold = top 2% of days over 2017-2026 (91 names in the study).
  2. MARKET ALREADY FALLING: SPY close is down >= 3% over the last 10 sessions.

Writes panic_log.csv (one row per date: count, spy_10d, heavy, falling, tag_on,
tag_until) and prints a one-line summary the evening message picks up.
Study result (10y): signals in the tag window touched +5/+10/+20% within 4 wk
84/60/31% (ex-2020) vs 71/47/19% normally; dips deeper (-12.5% avg). n=287, clustered.
"""
import glob, os, datetime
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
LOG = HERE / "panic_log.csv"
HEAVY_THRESHOLD = 91      # from the study (top 2% of days, 2017-2026)
SPY_DROP = -3.0           # % over 10 sessions
WINDOW = 3                # sessions the tag stays on after a qualifying day

def main():
    spy = pd.read_csv(HERE / "daily_data_v2" / "SPY.csv", index_col=0, parse_dates=True).sort_index()["Close"]
    asof = spy.index.max()
    spy10 = (float(spy.iloc[-1]) / float(spy.iloc[-11]) - 1) * 100 if len(spy) > 11 else np.nan
    count = 0; n_checked = 0
    for fp in glob.glob(str(HERE / "daily_data_v2" / "*.csv")):
        t = os.path.basename(fp)[:-4].upper()
        if t in {"SPY", "QQQ", "RSP"}: continue
        try:
            d = pd.read_csv(fp, index_col=0, parse_dates=True).sort_index()
        except Exception:
            continue
        if len(d) < 2 or d.index[-1] != asof: continue
        n_checked += 1
        h, l, o = float(d["High"].iloc[-1]), float(d["Low"].iloc[-2]), float(d["Open"].iloc[-1])
        pc = float(d["Close"].iloc[-2])
        if h < l and o <= pc * 0.98: count += 1
    heavy = count >= HEAVY_THRESHOLD
    falling = bool(np.isfinite(spy10) and spy10 <= SPY_DROP)
    today = asof.date().isoformat()
    # tag_until: carry a prior qualifying day forward WINDOW sessions
    tag_until = ""
    if LOG.exists():
        prev = pd.read_csv(LOG, dtype=str)
        prev = prev[prev["date"] < today]
        if len(prev):
            last = prev[prev["heavy"].astype(str) == "True"]
            last = last[last["falling"].astype(str) == "True"]
            if len(last):
                qday = pd.Timestamp(last["date"].iloc[-1])
                k = spy.index.searchsorted(qday)
                if k + WINDOW < len(spy):
                    tag_until = spy.index[k + WINDOW].date().isoformat()
    if heavy and falling:
        k = spy.index.searchsorted(asof)
        tag_until = spy.index[min(k + WINDOW, len(spy) - 1)].date().isoformat()
        if k + WINDOW >= len(spy):   # future sessions unknown — approximate with calendar days
            tag_until = (asof + pd.Timedelta(days=5)).date().isoformat()
    tag_on = bool((heavy and falling) or (tag_until and tag_until >= today))
    row = dict(date=today, gapdown_count=count, checked=n_checked, spy_10d=round(spy10, 2) if np.isfinite(spy10) else "",
               heavy=heavy, falling=falling, tag_on=tag_on, tag_until=tag_until)
    df = pd.DataFrame([row])
    if LOG.exists():
        old = pd.read_csv(LOG, dtype=str)
        old = old[old["date"] != today]
        df = pd.concat([old, df.astype(str)], ignore_index=True)
    df.to_csv(LOG, index=False)
    status = "ON" if tag_on else "off"
    print(f"PANIC-ENTRY check {today}: {count} gap-downs (of {n_checked}), SPY 10d {spy10:+.1f}% -> "
          f"heavy={heavy} falling={falling} tag={status}" + (f" (until {tag_until})" if tag_on and tag_until else ""))

if __name__ == "__main__":
    main()
