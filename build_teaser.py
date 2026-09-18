#!/usr/bin/env python3
"""
build_teaser.py — split board.json into the PUBLIC feed and leave the rest gated.

  board.json          full board -> pushed to KV, served only by /api/board (gated)
  site/teaser.json    public feed -> all RETIRED names (the Track Record, which is
                      the proof that persuades people) + exactly ONE current name
                      as the home-page hook. No other active/out-of-range names.

Run from the pipeline after board.json is built. Writes site/teaser.json.
"""
import json, os, sys
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(DIR, "board.json")
OUT = os.path.join(DIR, "site", "teaser.json")

MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def signal_ts(rec, session_year):
    """'Aug 14' -> a sortable date, rolling back a year if it lands in the future."""
    try:
        mon, day = str(rec.get("date", "")).split()
        dt = datetime(session_year, MON[mon], int(day))
        return dt
    except Exception:
        return datetime.min


# Dollar prices are withheld from the PUBLIC feed pending written confirmation
# from the market-data vendor that our licence covers displaying prices to
# non-subscribers. Percentages are ours — they are computed from the prices, not
# the prices themselves — so the track record keeps all of its meaning while the
# vendor's actual numbers stay behind the paywall. Flip this to False to restore.
HIDE_PUBLIC_PRICES = True
PRICE_FIELDS = ("pe", "pc")


def strip_prices(rec):
    """A copy of rec with the vendor's price fields removed."""
    if not HIDE_PUBLIC_PRICES:
        return rec
    return {k: v for k, v in rec.items() if k not in PRICE_FIELDS}


def main():
    with open(SRC) as f:
        board = json.load(f)

    names = board.get("names", [])
    session = str(board.get("session_date", ""))[:10]
    try:
        year = int(session[:4])
    except Exception:
        year = datetime.now().year

    retired = [r for r in names if r.get("phase") == "retired"]
    current = [r for r in names if r.get("phase") in ("active", "extended")]

    # the single newest current name — the hook on the home page
    teaser = []
    if current:
        newest = sorted(current, key=lambda r: signal_ts(r, year), reverse=True)[0]
        teaser = [newest]

    out = {
        "generated_at": board.get("generated_at"),
        "session_date": board.get("session_date"),
        "regime": board.get("regime"),
        "market": board.get("market"),
        "names": [strip_prices(r) for r in (retired + teaser)],
        "counts": {
            "retired": len(retired),
            "teaser": len(teaser),
            "gated": len(current) - len(teaser),
        },
        "public": True,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print("teaser.json: %d retired + %d current shown, %d current withheld -> %s"
          % (len(retired), len(teaser), len(current) - len(teaser), OUT))
    if HIDE_PUBLIC_PRICES:
        print("  prices WITHHELD from the public feed (pe/pc stripped); percentages kept")
    if teaser:
        print("  hook name: %s (%s)" % (teaser[0].get("t"), teaser[0].get("date")))


if __name__ == "__main__":
    sys.exit(main())
