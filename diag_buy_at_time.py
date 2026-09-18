#!/usr/bin/env python3
"""
diag_buy_at_time.py — evaluate the BUY gates AS OF a specific time today.

The normal trace (diag_buy_path.py) only sees the latest bar. This one
rebuilds the data as it existed at a chosen time and runs the full BUY gate
sequence with ONLY data up to that bar — so you can ask "would this have
triggered at 9:45?" honestly, without hindsight.

It can also STEP through the morning: pass 'step' and it walks every 15-min
bar from the open and prints the gate verdict at each, so you see the exact
bar the engine first qualifies (and what blocked it before that).

Run:
  cd ~/Documents/STS/15min && python3.12 diag_buy_at_time.py SPOT 09:45
  cd ~/Documents/STS/15min && python3.12 diag_buy_at_time.py SPOT step
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, '..')

import pandas as pd
import sts_15min_observe as obs
import sts_signal_engine_15m as eng

if len(sys.argv) < 3:
    print("usage: python3.12 diag_buy_at_time.py TICKER HH:MM")
    print("   or: python3.12 diag_buy_at_time.py TICKER step")
    sys.exit(1)

TICKER = sys.argv[1].upper()
MODE   = sys.argv[2].lower()

print("=" * 64)
print(f"  BUY TRACE AS-OF TIME — {TICKER}")
print("=" * 64)

if not obs.init_schwab():
    sys.exit(1)

ticker, df_d, df_15 = obs.fetch_ticker_bundle(TICKER)
if df_d is None or df_15 is None:
    print("  fetch failed")
    sys.exit(1)

# today's 15-min bars
today = df_15[df_15.index.date == df_15.index[-1].date()]
if len(today) == 0:
    print("  no bars for today yet")
    sys.exit(1)

print(f"  daily bars: {len(df_d)}   total 15-min bars: {len(df_15)}")
print(f"  today's bars: {today.index[0].strftime('%H:%M')} "
      f"-> {today.index[-1].strftime('%H:%M')}  ({len(today)} bars)")


def eval_buy_asof(cutoff_ts):
    """Run the BUY gate sequence using only data at-or-before cutoff_ts.
    Returns (first_failing_gate, detail) or ('PASS ALL', '')."""
    upto = df_15[df_15.index <= cutoff_ts]
    if len(upto) < eng.MIN_BARS_BASE:
        return 'insufficient bars', f'{len(upto)} < {eng.MIN_BARS_BASE}'
    price = float(upto['Close'].iloc[-1])
    t2 = eng.resample_tf(upto, '30min')
    t3 = eng.resample_tf(upto, '60min')

    ok, reason, info = eng.daily_check(df_d, price, 'BUY')
    if not ok:
        return 'daily', reason
    for label, tf in [('15m trend', upto), ('30m trend', t2), ('60m trend', t3)]:
        okx, rx = eng.trend_check(tf, 'BUY')
        if not okx:
            return label, rx
    oke, re = eng.five_min_extras(upto, 'BUY')
    if not oke:
        return 'extras', re
    okm, rm = eng.five_min_momentum(upto, 'BUY')
    if not okm:
        return 'momentum', rm
    return 'PASS ALL', f'price {price:.2f}'


if MODE == 'step':
    print(f"\n  Stepping every 15-min bar of today (BUY side):\n")
    print(f"  {'bar':<8}{'verdict':<16}{'detail'}")
    print(f"  {'-'*60}")
    first_pass = None
    for ts in today.index:
        gate, detail = eval_buy_asof(ts)
        mark = '  <-- would FIRE' if gate == 'PASS ALL' else ''
        print(f"  {ts.strftime('%H:%M'):<8}{gate:<16}{detail}{mark}")
        if gate == 'PASS ALL' and first_pass is None:
            first_pass = ts
    print()
    if first_pass:
        print(f"  >> Engine would FIRST fire BUY on {TICKER} at "
              f"{first_pass.strftime('%H:%M')}.")
    else:
        print(f"  >> Engine never qualifies a BUY on {TICKER} today "
              f"(through {today.index[-1].strftime('%H:%M')}).")
else:
    # specific time
    hh, mm = MODE.split(':')
    target = today.index[0].replace(hour=int(hh), minute=int(mm))
    # find the bar at or just after that time
    cands = today[today.index >= target]
    if len(cands) == 0:
        print(f"  no bar at/after {MODE} today")
        sys.exit(1)
    ts = cands.index[0]
    gate, detail = eval_buy_asof(ts)
    print(f"\n  As of bar {ts.strftime('%H:%M')}:")
    if gate == 'PASS ALL':
        print(f"  >> BUY WOULD FIRE — all gates passed ({detail})")
    else:
        print(f"  >> BUY blocked at [{gate}] gate: {detail}")

print("=" * 64)
