#!/usr/bin/env python3
"""
sp500_touch_baseline.py — the "typical S&P 500 stock" comparison for the site.

Owner: the website chat (GJ, 2026-11-01: "you own the balloons and the S&P 500
month-to-month updates"). Reproduces, to the decimal, the one-off study that
produced sp500_monthly_touch_baseline.csv on 2026-10-12, and keeps it current.

For every current S&P 500 constituent (sp500_tickers.txt) with data in
daily_data_v2, for each calendar month:
  s1_5 / s1_10  = share whose HIGH in the month reached +5% / +10% above the
                  OPEN of the month's first session  ("M1" — what the site calls
                  "typical S&P 500 stock"; a real, achievable reference point)
  s2_5 / s2_10  = share whose highest high AFTER the month's lowest low was +5% /
                  +10% above that low  (the most generous reading; footnote only)
Months with fewer than MIN_SESSIONS sessions so far are skipped, so the current
month is only written once it is (nearly) complete.

Writes:
  sp500_monthly_touch_baseline.csv   (month,n,s1_5,s1_10,s2_5,s2_10) — the record
  site/stats_history.json["baseline"] — by_month (all months), p5/p10/low_p5/
      low_p10 = trailing-36-month averages, as_of, months, n_stocks, note.
      The site's balloons do NOT use p5/p10 any more: they compare against the
      SAME months as our setups (computed in the page from by_month). p5/p10 stay
      for the "three-year average" line in the track-record table.

SAME-WINDOWS comparison (GJ, 2026-11-01 — the one the site shows):
  For every snapshot in stats_history.json, and for every one of OUR published
  setups in that snapshot's cohort (same cohort rules as build_stats.load_positions:
  window completed by the snapshot date), measure every S&P 500 stock from the OPEN
  of our setup's entry date to its highest HIGH through the snapshot date — exactly
  how build_stats measures our own peak — and average across the cohort. Written as
  idx_p5 / idx_p10 / idx_p20 / idx_n on snap["month"] and snap["cumulative"]. Our
  own figures are never touched (never restated); only the comparison is added.

Run (monthly, after build_stats.py has written the month's snapshot):
  python3 sp500_touch_baseline.py            # last completed month + current if complete
  python3 sp500_touch_baseline.py 2026-10    # a specific month
  python3 sp500_touch_baseline.py --all      # rebuild 2023-10 onward
Current constituents only — survivorship makes the index read HIGH, which is the
conservative direction for a comparison that is meant to flatter the index.
"""
import sys, os, json, datetime as dt
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TICKERS = os.path.join(HERE, "sp500_tickers.txt")
DATA = os.path.join(HERE, "daily_data_v2")
CSV = os.path.join(HERE, "sp500_monthly_touch_baseline.csv")
HIST = os.path.join(HERE, "site", "stats_history.json")
FIRST_MONTH = "2023-10"
TRAILING = 36
MIN_SESSIONS = 10          # a month counts once it has this many sessions (≈ half a month)


def path_for(t):
    for f in (os.path.join(DATA, f"{t}.csv"), os.path.join(DATA, f"{t.replace('.', '-')}.csv")):
        if os.path.exists(f):
            return f
    return None


def load_all():
    frames = {}
    for t in open(TICKERS).read().split():
        f = path_for(t)
        if not f:
            continue
        try:
            d = pd.read_csv(f, index_col=0, parse_dates=True).sort_index()
            d = d[~d.index.duplicated()].dropna(subset=["Open", "High", "Low"])
            frames[t] = d[["Open", "High", "Low"]]
        except Exception:
            pass
    return frames


def month_stats(frames, ym):
    s = np.zeros(4); n = 0
    for t, d in frames.items():
        m = d[d.index.strftime("%Y-%m") == ym]
        if len(m) < MIN_SESSIONS:
            continue
        n += 1
        o = float(m["Open"].iloc[0]); h = float(m["High"].max())
        i = int(np.argmin(m["Low"].values)); lo = float(m["Low"].iloc[i]); hafter = float(m["High"].iloc[i:].max())
        s += [h >= o * 1.05, h >= o * 1.10, hafter >= lo * 1.05, hafter >= lo * 1.10]
    if n == 0:
        return None
    return dict(month=ym, n=n, s1_5=round(100 * s[0] / n, 1), s1_10=round(100 * s[1] / n, 1),
                s2_5=round(100 * s[2] / n, 1), s2_10=round(100 * s[3] / n, 1))


def month_complete(frames, ym):
    """True when SPY (or the bulk of names) has traded the month's last session."""
    spy = frames.get("SPY") or next(iter(frames.values()))
    last = spy.index.max()
    y, m = map(int, ym.split("-"))
    nxt = dt.date(y + (m == 12), (m % 12) + 1, 1)
    return last.date() >= pd.Timestamp(nxt).date() - pd.tseries.offsets.BDay(1)


def same_windows(frames, hist):
    """Add idx_p5/idx_p10/idx_p20/idx_n to every snapshot's month + cumulative blocks."""
    sys.path.insert(0, HERE)
    import build_stats                                   # same cohort rules as the published figures
    df = build_stats.load_positions()
    completed = df["entry_date"].dt.date + build_stats.WINDOW
    names = {t: d for t, d in frames.items() if t != "SPY"}
    cache = {}
    def idx_touch(entry, asof):
        key = (entry.date(), asof)
        if key not in cache:
            hits = np.zeros(3); n = 0
            for d in names.values():
                w = d[(d.index >= entry) & (d.index.date <= asof)]
                if len(w) < 5:
                    continue
                o = float(w["Open"].iloc[0]); h = float(w["High"].max()); n += 1
                hits += [h >= o * 1.05, h >= o * 1.10, h >= o * 1.20]
            cache[key] = (hits / n * 100) if n else None
        return cache[key]
    def fill(block, g, asof):
        if block is None or not len(g):
            return
        vals = [v for v in (idx_touch(e, asof) for e in g["entry_date"]) if v is not None]
        if not vals:
            return
        m = np.mean(vals, axis=0)
        block.update({"idx_p5": round(float(m[0]), 1), "idx_p10": round(float(m[1]), 1), "idx_p20": round(float(m[2]), 1), "idx_n": len(vals)})
    for snap in hist.get("snapshots", []):
        asof = dt.date.fromisoformat(snap["as_of"])
        cum = df[completed <= asof]
        month = df[(completed >= asof.replace(day=1)) & (completed <= asof)]
        fill(snap.get("cumulative"), cum, asof)
        fill(snap.get("month"), month, asof)
        c = snap.get("cumulative") or {}
        print(f"  {snap['label']}: S&P same windows -> month {snap['month'].get('idx_p5') if snap.get('month') else None}/{snap['month'].get('idx_p10') if snap.get('month') else None}  cumulative {c.get('idx_p5')}/{c.get('idx_p10')} (n={c.get('idx_n')})")


def main(argv):
    frames = load_all()
    spy_path = os.path.join(DATA, "SPY.csv")
    if os.path.exists(spy_path):
        frames["SPY"] = pd.read_csv(spy_path, index_col=0, parse_dates=True).sort_index()[["Open", "High", "Low"]]
    n_stocks = len([t for t in frames if t != "SPY"])
    old = pd.read_csv(CSV, dtype=str) if os.path.exists(CSV) else pd.DataFrame(columns=["month", "n", "s1_5", "s1_10", "s2_5", "s2_10"])
    rows = {r["month"]: r for r in old.to_dict("records")}

    today = dt.date.today()
    cur = today.strftime("%Y-%m")
    prev = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    if "--all" in argv:
        months = pd.period_range(FIRST_MONTH, cur, freq="M").strftime("%Y-%m").tolist()
    elif len(argv) > 1 and argv[1][:1].isdigit():
        months = [argv[1]]
    else:
        months = [prev] + ([cur] if month_complete(frames, cur) else [])

    for ym in months:
        if ym == cur and not month_complete(frames, ym) and "--force" not in argv:
            print(f"{ym}: month not complete yet — skipped"); continue
        st = month_stats({t: d for t, d in frames.items() if t != "SPY"}, ym)
        if not st:
            print(f"{ym}: no data"); continue
        rows[ym] = {k: str(v) for k, v in st.items()}
        print(f"{ym}: n={st['n']}  +5% {st['s1_5']}  +10% {st['s1_10']}   (generous {st['s2_5']} / {st['s2_10']})")

    out = pd.DataFrame([rows[k] for k in sorted(rows)])
    out.to_csv(CSV, index=False)

    # ---- site/stats_history.json["baseline"] ----
    hist = json.load(open(HIST)) if os.path.exists(HIST) else {"snapshots": []}
    base = hist.get("baseline") or {}
    by_month = {r["month"]: {"p5": float(r["s1_5"]), "p10": float(r["s1_10"])} for r in out.to_dict("records")}
    keys = sorted(by_month)[-TRAILING:]
    f = lambda col: round(float(np.mean([float(rows[k][col]) for k in keys])), 1)
    base.update({
        "source": os.path.basename(CSV),
        "as_of": keys[-1], "months": len(keys), "n_stocks": n_stocks,
        "note": "A typical S&P 500 stock, from the first session of each calendar month to its highest high in that month (M1). Current constituents, so it reads high. Hypothetical.",
        "p5": f("s1_5"), "p10": f("s1_10"), "low_p5": f("s2_5"), "low_p10": f("s2_10"),
        "by_month": by_month,
        "updated": today.isoformat(),
    })
    hist["baseline"] = base
    try:
        same_windows(frames, hist)
    except Exception as e:
        print(f"same-windows comparison failed (non-fatal): {e}")
    json.dump(hist, open(HIST, "w"), indent=1)
    print(f"baseline -> {os.path.relpath(HIST, HERE)}: {len(by_month)} months, trailing-{len(keys)} avg +5% {base['p5']} / +10% {base['p10']} (as of {base['as_of']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
