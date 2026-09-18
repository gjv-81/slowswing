#!/usr/bin/env python3.12
"""
backfill_book.py — reconstruct paper signals for the 20 trading days BEFORE the
live book started (2026-07-20), by honest walk-forward re-scoring.

For each historical trading day it computes the STS score using ONLY data up to
that day (no look-ahead) and records EVERY qualifier (score >= threshold, valid
setup) — winners and losers alike (no cherry-picking). Each ticker is captured
once, on the first day it qualified in the window, exactly as the live scanner
would have caught it. Rows are appended to sts_ml_paper_trades.csv tagged
source='backfilled'; your normal evening run then computes wk2/wk4/phase/gate
for them like any other position.

Reuses the EXACT score_ticker / classify from sts_ml_evening.py, so the signal
logic is identical to the live scanner.

RUN ONCE on the Mac (needs yfinance + network, like the evening script):
    cd ~/STS/15min && python3.12 backfill_book.py            # preview first:
    cd ~/STS/15min && python3.12 backfill_book.py --dry-run  # shows what it would add, writes nothing
Then run your normal pipeline to score them:
    python3.12 sts_ml_evening.py

Offline logic test (loads daily_data_10y CSVs instead of yfinance; limited to
their date coverage):  BACKFILL_OFFLINE=1 python3 backfill_book.py --dry-run
"""
import os
import sys
import glob
import numpy as np       # noqa (score_ticker relies on the same stack)
import pandas as pd

import sts_ml_evening as ev            # reuse the live scanner's scoring + classify

LIVE_START = pd.Timestamp("2026-07-20")   # first day the live paper book was tracked
N_TRADING_DAYS = 20                        # how many trading days before that to reconstruct
DRY = "--dry-run" in sys.argv


def load_history(tickers):
    """Fresh yfinance history (default), or local daily_data_10y CSVs for an offline test."""
    if os.environ.get("BACKFILL_OFFLINE") == "1":
        out = {}
        for t in tickers:
            for ext in ("csv", "parquet"):
                p = os.path.join(ev.UNIVERSE_DIR, f"{t}.{ext}")
                if os.path.exists(p):
                    df = (pd.read_csv(p, parse_dates=["Date"]).set_index("Date")
                          if ext == "csv" else pd.read_parquet(p))
                    out[t] = df
                    break
        return out
    return ev.fetch_batch(tickers)


def main():
    universe = sorted({os.path.splitext(os.path.basename(f))[0].upper()
                       for f in glob.glob(os.path.join(ev.UNIVERSE_DIR, "*.csv")) +
                                glob.glob(os.path.join(ev.UNIVERSE_DIR, "*.parquet"))})
    if not universe:
        sys.exit(f"ERROR: no universe files in {ev.UNIVERSE_DIR}")
    print(f"Universe: {len(universe)} tickers. Loading history ...")
    data = load_history(universe + ["SPY", "RSP"])
    if "SPY" not in data or "RSP" not in data:
        sys.exit("ERROR: SPY/RSP history missing — cannot compute regime / RS.")
    spy, rsp = data["SPY"], data["RSP"]

    # Entry dates = the last N trading days strictly BEFORE the live book started.
    spy_days = [d for d in spy.index if d < LIVE_START]
    entry_days = spy_days[-N_TRADING_DAYS:]
    if not entry_days:
        sys.exit("No trading days before the live-start date in the data.")
    print(f"Reconstructing entries {entry_days[0].date()} .. {entry_days[-1].date()} "
          f"({len(entry_days)} trading days before {LIVE_START.date()})")

    # Existing book — for idempotency, and to tag prior rows as live-tracked.
    csv = ev.TRADES_CSV
    trades = (pd.read_csv(csv) if os.path.exists(csv)
              else pd.DataFrame(columns=["entry_date", "ticker", "shares", "entry_price",
                                         "score_at_entry", "rs_at_entry", "notes"]))
    if "source" not in trades.columns:
        trades["source"] = "live"     # everything already in the book was tracked live
    existing_pairs = set(zip(trades["ticker"].astype(str), trades["entry_date"].astype(str)))

    seen = set()          # capture each ticker once — the first day it qualified in the window
    new_rows = []
    rsp_c = rsp["Close"]
    for E in entry_days:
        prior = [d for d in spy.index if d < E]      # signal day = the bar before entry (fills next open)
        if not prior:
            continue
        D = prior[-1]
        rsp_at = rsp_c[rsp_c.index <= D]
        if len(rsp_at) < 41:
            continue
        rsp_mom40 = float(rsp_at.iloc[-1] / rsp_at.iloc[-41] - 1)
        for t in universe:
            if t in ev.EXCLUDE or t in seen or t not in data:
                continue
            hist = data[t]
            hist = hist[hist.index <= D]              # <-- only data up to the signal day: no look-ahead
            if len(hist) < 260:
                continue
            if float(hist["Close"].iloc[-1]) < ev.MIN_PRICE:
                continue
            r = ev.score_ticker(hist)
            if r is None or r["score"] < ev.THRESHOLD:
                continue
            setup, wr = ev.classify(r["score"], r["off_high"], r["dist200_pct"], r["wash_min8w"])
            if setup == "-":
                continue
            ed = E.date().isoformat()
            if (t, ed) in existing_pairs:             # already present (idempotent re-run)
                seen.add(t)
                continue
            rs = round(100 * (r["mom40"] - rsp_mom40), 1)
            new_rows.append(dict(entry_date=ed, ticker=t, shares=1, entry_price="",
                                 score_at_entry=r["score"], rs_at_entry=rs,
                                 notes=f"backfill (signal {D.date().isoformat()})",
                                 source="backfilled"))
            seen.add(t)

    print(f"Reconstructed signals: {len(new_rows)} unique tickers")
    from collections import Counter
    by_day = Counter(r["entry_date"] for r in new_rows)
    for d in sorted(by_day):
        print(f"  {d}: {by_day[d]}")

    if DRY:
        print("\n(dry run — nothing written) sample:")
        for row in new_rows[:15]:
            print(f"  {row['entry_date']} {row['ticker']:6} score {row['score_at_entry']}  rs {row['rs_at_entry']}")
        return

    if new_rows:
        add = pd.DataFrame(new_rows)
        for col in trades.columns:
            if col not in add.columns:
                add[col] = ""
        trades = pd.concat([trades, add[trades.columns]], ignore_index=True)
        trades.to_csv(csv, index=False)
        print(f"\nWrote {len(new_rows)} backfilled rows to {os.path.basename(csv)} (source=backfilled).")
        print("Next: python3.12 sts_ml_evening.py   (scores them into the tracker + workbook)")
    else:
        print("Nothing to add.")


if __name__ == "__main__":
    main()
