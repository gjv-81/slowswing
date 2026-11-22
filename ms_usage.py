#!/usr/bin/env python3.12
"""
ms_usage.py — running count of Marketstack calls for the current billing cycle (added 2026-11-22).

Why: the Basic plan allows 10,000 calls per cycle (cycle starts on the 13th). Marketstack bills
per SYMBOL per call. With overage switched off the feed simply stops at the limit; with it on,
every extra call is charged (a bug cost $125 in Oct 2026). Normal use is ~622 calls a night.

record(n) adds tonight's calls and returns a one-line warning when the count crosses 75%, 90% or
100% of the quota for the first time this cycle (else ""). State: marketstack_usage.json (kept in
R2 by the nightly). The count is OUR estimate; the dashboard at marketstack.com is the truth.
Quota override: env MARKETSTACK_QUOTA. Cycle day override: env MARKETSTACK_CYCLE_DAY.
"""
import json, os, datetime as dt
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marketstack_usage.json"
QUOTA = int(os.environ.get("MARKETSTACK_QUOTA", "10000"))
CYCLE_DAY = int(os.environ.get("MARKETSTACK_CYCLE_DAY", "13"))

def _cycle_start(today):
    if today.day >= CYCLE_DAY: return today.replace(day=CYCLE_DAY)
    prev = (today.replace(day=1) - dt.timedelta(days=1))
    return prev.replace(day=CYCLE_DAY)

def _load(today):
    cs = _cycle_start(today).isoformat()
    try:
        st = json.loads(STATE.read_text())
    except Exception:
        st = {}
    if st.get("cycle_start") != cs:
        st = {"cycle_start": cs, "calls": 0, "by_date": {}, "warned": []}
    return st

def record(n, folder="", today=None):
    today = today or dt.date.today()
    st = _load(today)
    n = int(n or 0)
    if n > 0:
        st["calls"] += n
        key = today.isoformat()
        st["by_date"][key] = st["by_date"].get(key, 0) + n
    msg = ""
    pct = 100.0 * st["calls"] / QUOTA if QUOTA else 0
    for level in (100, 90, 75):
        if pct >= level and level not in st["warned"]:
            st["warned"] = sorted(set(st["warned"]) | {l for l in (75, 90, 100) if l <= level})
            nights = [v for v in st["by_date"].values() if v > 50]
            per = sum(nights) / len(nights) if nights else 0
            left = max(0, QUOTA - st["calls"])
            tail = (f" About {int(left // per)} more night(s) at this rate." if per and left else "")
            msg = (f"Marketstack: {st['calls']:,} of {QUOTA:,} calls used this cycle ({pct:.0f}%), "
                   f"since {st['cycle_start']}." + (" LIMIT REACHED." if level == 100 else tail))
            break
    try:
        STATE.write_text(json.dumps(st, indent=1))
    except Exception:
        pass
    return msg

def status(today=None):
    st = _load(today or dt.date.today())
    return f"{st['calls']:,} of {QUOTA:,} calls since {st['cycle_start']}"

if __name__ == "__main__":
    print(status())
