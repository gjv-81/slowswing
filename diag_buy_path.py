#!/usr/bin/env python3
"""
diag_buy_path.py — trace the BUY evaluation gate-by-gate for a ticker.

The engine checks BUY then SELL and only reports ONE reason (the last
direction tried), which hides WHY a BUY failed. This re-runs the engine's
OWN gate functions in the BUY direction and prints each gate's verdict, so
you can see exactly where a setup is rejected and compare it to your chart.

It does NOT reimplement the strategy — it calls the same functions the
engine calls (daily_check, trend_check, five_min_extras, five_min_momentum),
in the same order. Pure transparency.

Run:  cd ~/Documents/STS/15min && python3.12 diag_buy_path.py ADP
"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, '..')

import sts_15min_observe as obs
import sts_signal_engine_15m as eng

TICKER = sys.argv[1].upper() if len(sys.argv) > 1 else 'ADP'

print("=" * 64)
print(f"  BUY-PATH TRACE — {TICKER}")
print("=" * 64)

if not obs.init_schwab():
    sys.exit(1)

ticker, df_d, df_15 = obs.fetch_ticker_bundle(TICKER)
if df_d is None or df_15 is None:
    print(f"  fetch failed — df_d={df_d is not None}, df_15={df_15 is not None}")
    sys.exit(1)

print(f"  daily bars : {len(df_d)}")
print(f"  15-min bars: {len(df_15)}")

if len(df_15) < eng.MIN_BARS_BASE:
    print(f"  STOP: only {len(df_15)} 15-min bars (<{eng.MIN_BARS_BASE})")
    sys.exit(1)

current_price = float(df_15['Close'].iloc[-1])
print(f"  current px : {current_price:.2f}")
print(f"  last bar   : {df_15.index[-1]}")

# the engine builds these two rungs
df_t2 = eng.resample_tf(df_15, '30min')
df_t3 = eng.resample_tf(df_15, '60min')
print(f"  30-min bars: {len(df_t2)}   60-min bars: {len(df_t3)}")
print()

D = 'BUY'
print(f"  ── BUY gate sequence (in engine order) ──")

# Gate 1: daily check
ok, reason, info = eng.daily_check(df_d, current_price, D)
print(f"  [1] daily_check        : {'PASS' if ok else 'FAIL'}  {('' if ok else '— '+reason)}")
if info:
    print(f"        prev_high={info.get('prev_high')}  prev_low={info.get('prev_low')}  "
          f"atr={info.get('atr')}  avg_vol={info.get('avg_vol')}")
if not ok:
    print(f"\n  >> BUY rejected at the DAILY gate. price {current_price:.2f} vs "
          f"prev_high {info.get('prev_high')}.")
    print(f"     For a BUY the strategy needs price ABOVE yesterday's high.")
    sys.exit(0)

# Gate 2-4: trend on 15m / 30m / 60m
for label, df_tf in [('15m base', df_15), ('30m rung', df_t2), ('60m rung', df_t3)]:
    okx, rx = eng.trend_check(df_tf, D)
    print(f"  [.] trend {label:9s}  : {'PASS' if okx else 'FAIL'}  {('' if okx else '— '+rx)}")
    if not okx:
        print(f"\n  >> BUY rejected at the {label} TREND gate: {rx}")
        print(f"     (BUY needs close above the Ichimoku cloud AND 9EMA>21EMA "
              f"on this timeframe.)")
        sys.exit(0)

# Gate 5: extras
oke, re = eng.five_min_extras(df_15, D)
print(f"  [5] extras (EMA34/55..) : {'PASS' if oke else 'FAIL'}  {('' if oke else '— '+re)}")
if not oke:
    print(f"\n  >> BUY rejected at the EXTRAS gate: {re}")
    sys.exit(0)

# Gate 6: momentum (MACD + RSI Laguerre crosses + Fisher)
okm, rm = eng.five_min_momentum(df_15, D)
print(f"  [6] momentum (cross/FT) : {'PASS' if okm else 'FAIL'}  {('' if okm else '— '+rm)}")
if not okm:
    print(f"\n  >> BUY rejected at the MOMENTUM gate: {rm}")
    print(f"     This gate wants a CLEAN MACD cross within {eng.MACD_CROSS_WINDOW} "
          f"closed bars, an RSI-Laguerre cross within {eng.RSI_CROSS_WINDOW}, "
          f"and Fisher rising.")
    print(f"     A breakout that's already extended (cross happened many bars "
          f"ago) fails here even though the chart looks strongly up.")
    sys.exit(0)

print(f"\n  >> ALL BUY GATES PASSED — engine would fire BUY on {TICKER}.")
print("=" * 64)
