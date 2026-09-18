#!/usr/bin/env python3
"""Diagnose why the observe scanner gets 0 five-minute bars.
Run:  cd ~/Documents/STS/15min && python3.12 diag_fetch.py
"""
import sys
from datetime import datetime, timedelta
sys.path.insert(0, '.')
sys.path.insert(0, '..')

import sts_15min_observe as obs

print("=" * 60)
print("  FETCH DIAGNOSTIC — ADP")
print("=" * 60)

ok = obs.init_schwab()
print(f"Schwab init: {ok}")
if not ok:
    sys.exit(1)

# ── 1. raw 5-minute call, WITH the start_datetime arg ────────────────
print("\n[1] 5-min call WITH start_datetime (what the scanner does now):")
start = datetime.now() - timedelta(days=12)
try:
    resp = obs.schwab_client.get_price_history_every_five_minutes(
        'ADP', start_datetime=start,
        need_extended_hours_data=False, need_previous_close=False)
    print(f"    HTTP status : {resp.status_code}")
    j = resp.json()
    print(f"    json keys   : {list(j.keys())}")
    print(f"    candles     : {len(j.get('candles', []))}")
    print(f"    empty flag  : {j.get('empty')}")
except Exception as e:
    print(f"    EXCEPTION: {type(e).__name__}: {e}")

# ── 2. raw 5-minute call, NO start_datetime (bare, like the downloader) ─
print("\n[2] 5-min call with NO start_datetime (bare — like download_market_data):")
try:
    resp2 = obs.schwab_client.get_price_history_every_five_minutes('ADP')
    print(f"    HTTP status : {resp2.status_code}")
    j2 = resp2.json()
    print(f"    json keys   : {list(j2.keys())}")
    print(f"    candles     : {len(j2.get('candles', []))}")
    print(f"    empty flag  : {j2.get('empty')}")
    if j2.get('candles'):
        c = j2['candles'][0]
        last = j2['candles'][-1]
        print(f"    first candle: {c}")
        print(f"    last  candle: {last}")
except Exception as e:
    print(f"    EXCEPTION: {type(e).__name__}: {e}")

# ── 3. daily call, for comparison ────────────────────────────────────
print("\n[3] daily call (for comparison):")
try:
    start_d = datetime.now() - timedelta(days=180)
    respd = obs.schwab_client.get_price_history_every_day(
        'ADP', start_datetime=start_d,
        need_extended_hours_data=False, need_previous_close=False)
    print(f"    HTTP status : {respd.status_code}")
    print(f"    candles     : {len(respd.json().get('candles', []))}")
except Exception as e:
    print(f"    EXCEPTION: {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print("  READING IT:")
print("  - If [1] gives 0 candles but [2] gives many -> the start_datetime")
print("    argument is the bug. Fix: drop it, fetch bare like the downloader.")
print("  - If both [1] and [2] are empty but [3] works -> 5-min endpoint")
print("    issue specifically.")
print("  - If all fail -> token / auth / connectivity.")
print("=" * 60)
