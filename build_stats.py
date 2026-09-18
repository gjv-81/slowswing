#!/usr/bin/env python3
"""
build_stats.py — month-end snapshots of the track record, for the website.

The home-page headline ("N% reached +5% at peak") is a HEADLINE, not a ticker.
It is restated once a month from a snapshot taken on the last trading day of
the month, and the snapshot is what the site displays — nothing is recomputed
in the browser, so the number is literally "as of <month end>" and cannot creep.

What a snapshot holds (site/stats_history.json, one entry per month):
  * month cohort  = setups whose 4-week window COMPLETED in that month
                    (entry_date + 28 days falls inside the month), measured as
                    of the snapshot date
  * cumulative    = every setup that had completed its window by the snapshot
                    date — this is what the balloons show
  * for each: n, touched +5/+10/+20% at peak, avg peak, median days to peak,
    avg 4-week return, share positive at 4 weeks, avg max dip in first 4 weeks

Peaks are measured from the daily bars in daily_data_10y/ up to the snapshot
date, so a backfilled snapshot (--asof 2026-08-31) is the number the site
WOULD have shown on that day, not today's peaks relabelled.

Runs from run_evening.sh every night; writes only on the last trading day of
the month (or with --asof / --force). Idempotent per month.

  /usr/local/bin/python3.12 build_stats.py                    # nightly (no-op unless month end)
  /usr/local/bin/python3.12 build_stats.py --asof 2026-08-31  # backfill one month
  /usr/local/bin/python3.12 build_stats.py --force            # snapshot today, whatever the date
"""
import argparse, json, sys, datetime as dt
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
XLSX = HERE / "STS_holy_grail.xlsx"
BARS = HERE / "daily_data_10y"
OUT = HERE / "site" / "stats_history.json"
PUBLISHED = {"D200G", "DLB", "B2"}          # same gate as build_board.py: Phoenix + Cruise only
WINDOW = dt.timedelta(days=28)              # the 4-week tracking window, calendar days


def last_trading_day_of_month(d: dt.date) -> bool:
    n = d + dt.timedelta(days=1)
    while n.weekday() >= 5:
        n += dt.timedelta(days=1)
    return n.month != d.month


def load_positions():
    df = pd.read_excel(XLSX, sheet_name="Tracker")
    df["entry_date"] = pd.to_datetime(df["entry_date"], errors="coerce")
    df = df[df["entry_date"].notna() & df["setup"].isin(PUBLISHED)].copy()
    for c in ("entry", "wk4_ret_pct", "maxdip_4wk_pct", "mfe_pct", "dtp"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.upper()
    return df[df["entry"].notna()]


_bars_cache = {}
def bars(t: str):
    if t not in _bars_cache:
        p = BARS / f"{t}.csv"
        if p.exists():
            b = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
            _bars_cache[t] = b[["High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce")
        else:
            _bars_cache[t] = None
    return _bars_cache[t]


def peak_asof(row, asof: dt.date):
    """(peak % , trading days to peak) from entry through `asof`, from daily bars.
    Falls back to the workbook's own peak-to-date if the bars are missing."""
    b = bars(row.ticker)
    e = row.entry_date.date()
    if b is not None:
        w = b[(b.index.date >= e) & (b.index.date <= asof)].dropna(subset=["High"])
        if len(w):
            hi = w["High"].values
            i = int(hi.argmax())
            return (float(hi[i]) / row.entry - 1) * 100, i
    return (row.mfe_pct if pd.notna(row.mfe_pct) else 0.0), (int(row.dtp) if pd.notna(row.dtp) else None)


def stats(df, asof: dt.date):
    if not len(df):
        return None
    pk, dtp = zip(*(peak_asof(r, asof) for r in df.itertuples()))
    pk = pd.Series(pk); dtp = pd.Series([d for d in dtp if d is not None])
    w4 = df["wk4_ret_pct"].dropna(); md = df["maxdip_4wk_pct"].dropna()
    r = lambda x, k=1: (round(float(x), k) if pd.notna(x) else None)
    return {
        "n": int(len(df)),
        "p5": r((pk >= 5).mean() * 100), "p10": r((pk >= 10).mean() * 100), "p20": r((pk >= 20).mean() * 100),
        "avg_peak": r(pk.mean()), "med_dtp": (int(dtp.median()) if len(dtp) else None),
        "avg_wk4": r(w4.mean()) if len(w4) else None,
        "pos4": r((w4 > 0).mean() * 100) if len(w4) else None,
        "avg_md4": r(md.mean()) if len(md) else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", help="snapshot date YYYY-MM-DD (backfill)")
    ap.add_argument("--force", action="store_true", help="snapshot today even if not month end")
    a = ap.parse_args()

    today = dt.date.today()
    asof = dt.date.fromisoformat(a.asof) if a.asof else today
    if not a.asof and not a.force and not last_trading_day_of_month(asof):
        print(f"build_stats: {asof} is not the last trading day of the month — nothing to do")
        return 0

    df = load_positions()
    completed = df["entry_date"].dt.date + WINDOW
    cum = df[completed <= asof]
    month_start = asof.replace(day=1)
    month = df[(completed >= month_start) & (completed <= asof)]

    entry = {
        "as_of": asof.isoformat(),
        "label": asof.strftime("%b %Y"),
        "month": stats(month, asof),
        "cumulative": stats(cum, asof),
        "by_setup": {k: stats(cum[cum["setup"].isin(v)], asof)
                     for k, v in (("phoenix", {"D200G", "DLB"}), ("cruise", {"B2"}))},
    }

    hist = {"snapshots": []}
    if OUT.exists():
        try:
            hist = json.loads(OUT.read_text())
        except Exception:
            pass
    key = asof.strftime("%Y-%m")
    hist["snapshots"] = [s for s in hist.get("snapshots", []) if s["as_of"][:7] != key] + [entry]
    hist["snapshots"].sort(key=lambda s: s["as_of"])
    hist["updated"] = today.isoformat()
    OUT.write_text(json.dumps(hist, indent=1))
    c, m = entry["cumulative"], entry["month"]
    print(f"build_stats: snapshot {entry['label']} (as of {asof}) -> {OUT.name}")
    print(f"  cumulative n={c['n']}  +5% {c['p5']}%  +10% {c['p10']}%  avg peak {c['avg_peak']}%  median dtp {c['med_dtp']}")
    if m: print(f"  this month n={m['n']}  +5% {m['p5']}%  +10% {m['p10']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
