#!/usr/bin/env python3
"""
uts_daily_scan.py — end-of-day UTS daily swing scanner
=======================================================
Runs the whole universe through the UTS Aggressive daily BUY engine and
prints two lists:

  SIGNAL  — all six UTS BUY conditions met on the latest daily bar AND
            a fresh breakout today (close above the prior bar's high).
            The stock qualified AND broke out today.

  PRIMED  — all six UTS BUY conditions met on the latest bar, but no
            breakout today (close did not clear the prior bar's high).
            Coiled and qualified — the "about to break" watch list.

This reads the LOCAL daily CSVs saved by download_daily_data.py — it does
NOT hit Schwab. So re-run download_daily_data.py whenever you want fresh
data (e.g. after the close each day), then run this.

BUY-ONLY by design — the daily model does not trade SELL.

Run:
  cd ~/Documents/STS/15min && python3.12 uts_daily_scan.py

Optional — scan just a few tickers:
  python3.12 uts_daily_scan.py NVDA AMD MU GOOGL
"""

import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
STS_DIR    = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(STS_DIR))

from download_daily_data import load_daily_csv, OUT_DIR
from uts_daily_engine import evaluate_daily, MIN_BARS_DAILY

# ─── UNIVERSE ────────────────────────────────────────────────────────────────

def get_tickers():
    """Tickers to scan: CLI args if given, else every CSV in daily_data/."""
    if len(sys.argv) > 1:
        return [t.upper() for t in sys.argv[1:]]
    if not OUT_DIR.exists():
        print(f"ERROR: {OUT_DIR} not found. Run download_daily_data.py first.")
        sys.exit(1)
    tickers = sorted(p.stem for p in OUT_DIR.glob('*.csv'))
    if not tickers:
        print(f"ERROR: no CSVs in {OUT_DIR}. Run download_daily_data.py first.")
        sys.exit(1)
    return tickers

# ─── SCAN ────────────────────────────────────────────────────────────────────

def main():
    tickers = get_tickers()
    print("=" * 64)
    print("  UTS DAILY SCAN — end-of-day swing watch list")
    print(f"  Universe : {len(tickers)} tickers (from {OUT_DIR.name}/)")
    print(f"  Run at   : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 64)

    signaled, primed = [], []
    no_data, errors = 0, 0
    latest_date = None

    for ticker in tickers:
        df = load_daily_csv(ticker)
        if df is None or len(df) < MIN_BARS_DAILY:
            no_data += 1
            continue
        try:
            r = evaluate_daily(ticker, df)
        except Exception as e:
            errors += 1
            continue
        if latest_date is None or (r['date'] and r['date'] > latest_date):
            latest_date = r['date']
        if r['status'] == 'SIGNAL':
            signaled.append(r)
        elif r['status'] == 'PRIMED':
            primed.append(r)

    # sort each list by price (just a stable, readable order)
    signaled.sort(key=lambda r: r['ticker'])
    primed.sort(key=lambda r: r['ticker'])

    print(f"\n  Most recent daily bar in data: {latest_date}")
    print(f"  Scanned OK: {len(tickers) - no_data - errors}   "
          f"no-data/thin: {no_data}   errors: {errors}")

    # ── SIGNAL ──
    print("\n" + "─" * 64)
    print(f"  🟢 SIGNAL — conditions met + breakout today  ({len(signaled)})")
    print("─" * 64)
    if signaled:
        print(f"  {'TICKER':<8}{'PRICE':>10}   {'CONDITIONS':<40}")
        for r in signaled:
            print(f"  {r['ticker']:<8}{r['price']:>10.2f}   {r['reason']:<40}")
    else:
        print("  (none today)")

    # ── PRIMED ──
    print("\n" + "─" * 64)
    print(f"  🟡 PRIMED — conditions met, no breakout yet  "
          f"({len(primed)})")
    print(f"     ^ tomorrow's watch list — coiled, waiting to break")
    print("─" * 64)
    if primed:
        print(f"  {'TICKER':<8}{'PRICE':>10}   {'CONDITIONS':<40}")
        for r in primed:
            print(f"  {r['ticker']:<8}{r['price']:>10.2f}   {r['reason']:<40}")
    else:
        print("  (none today)")

    # ── save to CSV for record-keeping ──
    out_path = SCRIPT_DIR / f"uts_daily_scan_{latest_date}.csv"
    try:
        import csv
        with open(out_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['status', 'ticker', 'price', 'date', 'conditions'])
            for r in signaled + primed:
                w.writerow([r['status'], r['ticker'], r['price'],
                            r['date'], r['reason']])
        print(f"\n  Saved: {out_path.name}  "
              f"({len(signaled) + len(primed)} rows)")
    except Exception as e:
        print(f"\n  (could not save CSV: {e})")

    # ── reading guide ──
    print("\n" + "=" * 64)
    print("  CONDITIONS legend (each + means met, - means not met):")
    print("    cloud  price above the Ichimoku cloud")
    print("    macd   MACD line above signal")
    print("    vstop  Volatility Stop bullish")
    print("    wad    Williams A/D rising")
    print("    emas   price above the 8/34/55/89 EMAs")
    print("    sqz    squeeze OFF (volatility expanded)")
    print()
    print("  NOTE: this is a SCREEN, not a trade list. It tells you where")
    print("  the UTS daily conditions line up — apply your own judgment,")
    print("  and remember the strategy has NOT yet been backtested on")
    print("  daily data. backtest_uts_daily.py is the next build.")
    print("=" * 64)

if __name__ == '__main__':
    main()
