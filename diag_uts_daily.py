#!/usr/bin/env python3
"""
diag_uts_daily.py — per-bar trace of the UTS daily engine for one ticker
=========================================================================
The daily scan classified a stock as PRIMED, but your TOS chart shows the
UTS "Long" label already on. This tool settles whether that is a real
disagreement or just a definition gap.

It prints the last N daily bars for one ticker, showing EVERY condition's
value on each bar, plus the FIRED / PRIMED / none classification — so you
can see EXACTLY which bar the engine's conditions first lined up, and
compare it to where the UTS arrow sits on your chart.

  - If the engine's first all-conditions-met bar lines up with the UTS
    arrow on your chart -> the engine is CORRECT. "PRIMED today" just
    means today is not a NEW signal; the existing one is days old, and
    UTS's "Long" label is the still-open-position state, not a fresh
    arrow.
  - If they do NOT line up -> a real computation bug, and the per-bar
    values show which condition is wrong.

Run:
  cd ~/Documents/STS/15min && python3.12 diag_uts_daily.py CRWD
  python3.12 diag_uts_daily.py AAPL 20      (trace 20 bars instead of 10)
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from download_daily_data import load_daily_csv
from uts_daily_engine import compute_uts_daily_buy, MIN_BARS_DAILY

if len(sys.argv) < 2:
    print("usage: python3.12 diag_uts_daily.py TICKER [n_bars]")
    sys.exit(1)

TICKER = sys.argv[1].upper()
N_BARS = int(sys.argv[2]) if len(sys.argv) > 2 else 10

print("=" * 78)
print(f"  UTS DAILY TRACE — {TICKER}  (last {N_BARS} daily bars)")
print("=" * 78)

df = load_daily_csv(TICKER)
if df is None:
    print(f"  No daily CSV for {TICKER}. Run download_daily_data.py first.")
    sys.exit(1)
if len(df) < MIN_BARS_DAILY:
    print(f"  Only {len(df)} daily bars (<{MIN_BARS_DAILY}) — cannot evaluate.")
    sys.exit(1)

states = compute_uts_daily_buy(df)

# join price + states for the last N bars
tail = states.iloc[-N_BARS:].copy()
tail['Close'] = df['Close'].iloc[-N_BARS:]
tail['High'] = df['High'].iloc[-N_BARS:]

print(f"  {len(df)} daily bars loaded. Most recent: {df.index[-1].date()}")
print()

# header
print(f"  {'DATE':<12}{'CLOSE':>9}  "
      f"{'cloud':>6}{'macd':>6}{'vstop':>7}{'wad':>6}{'emas':>7}{'sqz':>6}"
      f"   {'CORE':>5} {'BREAK':>6}   {'VERDICT':<8}")
print("  " + "-" * 74)

for ts, row in tail.iterrows():
    date = ts.strftime('%Y-%m-%d')
    close = row['Close']

    def mk(v, true='  +', false='  -'):
        return true if v else false

    cloud = '  +' if row['ichi'] == 1 else ('  -' if row['ichi'] == -1 else '  0')
    macd  = '  +' if row['macd'] == 1 else ('  -' if row['macd'] == -1 else '  0')
    vstop = mk(row['vstop'])
    wad   = mk(row['wad_rising'])
    emas  = mk(row['above_emas'])
    sqz   = mk(row['squeeze_off'])
    core  = mk(row['core_ok'], '  Y', '  .')
    brk   = mk(row['broke_out'], '  Y', '  .')

    if row['signal']:
        verdict = 'SIGNAL'
    elif row['primed']:
        verdict = 'PRIMED'
    else:
        verdict = '-'

    print(f"  {date:<12}{close:>9.2f}  "
          f"{cloud:>6}{macd:>6}{vstop:>7}{wad:>6}{emas:>7}{sqz:>6}"
          f"   {core:>5} {brk:>6}   {verdict:<8}")

print("  " + "-" * 74)

# summary — find the first bar in the visible window where core_ok turned on
core_bars = tail[tail['core_ok']]
if len(core_bars):
    first_core = core_bars.index[0]
    print(f"\n  First bar (in this window) where ALL conditions aligned: "
          f"{first_core.strftime('%Y-%m-%d')}")
    print(f"  >> Compare this date to where the UTS arrow sits on your")
    print(f"     {TICKER} daily chart.")
    print(f"     - If they MATCH: the engine is correct. The scan saying")
    print(f"       'PRIMED' just means today is not a NEW signal — UTS's")
    print(f"       'Long' label is the still-open position, not a fresh arrow.")
    print(f"     - If they DON'T match: a real bug — the per-bar condition")
    print(f"       columns above show which one is wrong.")
else:
    print(f"\n  No bar in the last {N_BARS} had all conditions aligned.")
    print(f"  If your chart shows UTS 'Long' on {TICKER}, either the signal")
    print(f"  is older than {N_BARS} bars (re-run with a bigger n_bars), or")
    print(f"  a condition disagrees — widen the window to investigate.")

# also report how the most recent bar classified
last = tail.iloc[-1]
print(f"\n  Most recent bar ({tail.index[-1].strftime('%Y-%m-%d')}): "
      f"{'SIGNAL' if last['signal'] else 'PRIMED' if last['primed'] else 'no signal'}")
if last['core_ok']:
    if last['signal']:
        print(f"  (all six conditions met AND a fresh breakout today.)")
    else:
        print(f"  (all six conditions met, but today's close did not clear")
        print(f"   the prior bar's high — PRIMED, coiled, not yet broken out.)")
print("=" * 78)
