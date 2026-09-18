#!/usr/bin/env python3
"""Verify the fetch fix — confirms the scanner's own functions now return
enough data and the engine actually evaluates instead of bailing.
Run:  cd ~/Documents/STS/15min && python3.12 verify_fetch_fix.py
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, '..')

import sts_15min_observe as obs
from sts_signal_engine_15m import evaluate_ticker, MIN_BARS_BASE, MIN_BARS_DAILY

print("=" * 60)
print("  VERIFY FETCH FIX")
print("=" * 60)
print(f"  MIN_BARS_BASE  = {MIN_BARS_BASE}  (15-min bars the engine needs)")
print(f"  MIN_BARS_DAILY = {MIN_BARS_DAILY}")

if not obs.init_schwab():
    sys.exit(1)

# test a spread of tickers — big, mid, and a couple thinner names
for tk in ['ADP', 'NVDA', 'AMD', 'MU', 'CME', 'PGR']:
    print(f"\n  {tk}:")
    ticker, df_d, df_15 = obs.fetch_ticker_bundle(tk)
    d_ok  = df_d  is not None and len(df_d)  >= MIN_BARS_DAILY
    f_ok  = df_15 is not None and len(df_15) >= MIN_BARS_BASE
    print(f"    daily bars : {0 if df_d  is None else len(df_d):>5}   {'OK' if d_ok else 'TOO FEW'}")
    print(f"    15-min bars: {0 if df_15 is None else len(df_15):>5}   {'OK' if f_ok else 'TOO FEW'}")
    if d_ok and f_ok:
        r = evaluate_ticker(tk, df_d, df_15)
        print(f"    engine     : signal={r['signal']}  reason={r['reason']}")
        if 'insufficient' in (r['reason'] or ''):
            print(f"    *** STILL INSUFFICIENT — fix did not work ***")
    else:
        print(f"    engine     : SKIPPED — not enough data")

print("\n" + "=" * 60)
print("  If every ticker shows 'OK' for both bar counts and the engine")
print("  reason is a real strategy reason (not 'insufficient ... data'),")
print("  the fetch fix worked — restart the observe scanner.")
print("=" * 60)
