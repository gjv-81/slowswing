#!/usr/bin/env python3.12
"""
cone_study_both.py — signal-journey cones for the FULL published setup family
(DLB + D200G + B2: score >= 2.0 and at least 10% below the 52-week high),
computed TWO ways in one run:

  A) RAW        — every ticker in daily_data_v2, no gate, no price floor
  B) PUBLISHED  — QualGate PASS/WATCH only (qualgate_cache.csv) + entry >= $50
                  (same filters the website board enforces)

Same mechanics as before: next-session-open entry, 20td per-ticker refractory,
weekly closes td 0..60. Writes cone_data_both.json, prints both tables.

Run:  python3.12 ~/STS/15min/cone_study_both.py
"""
import glob, os, json
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_ENTRY_PRICE = 50.0
REFRACTORY = 20
WEEKS = list(range(13))

ZC = {"high52": (-0.149772, 0.156737), "dist200": (1.681650, 6.240695),
      "mom6": (0.086250, 0.361377), "qqe": (0.044473, 0.194268),
      "hull": (0.027496, 0.303103), "mom40": (0.020000, 0.155298)}
W  = {"high52": -2.20, "dist200": 1.35, "mom6": 1.08,
      "qqe": -0.99, "mom40": 0.63, "hull": 0.60}

def zclip(s, key):
    m, sd = ZC[key]
    return ((s - m) / sd).clip(-3, 3)

def wilders(s, n): return s.ewm(alpha=1/n, adjust=False).mean()

def rsi_wilder(s, n=20):
    d = s.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    rs = wilders(up, n) / wilders(dn, n).replace(0, 1e-10)
    return 100 - 100 / (1 + rs)

def wma(s, n):
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

def signal_series(d):
    """score >= 2 and at least 10% below the 52wk high -> DLB / D200G / B2."""
    C, H, L = d["Close"], d["High"], d["Low"]
    pc = C.shift(1)
    tr = pd.concat([H - L, (H - pc).abs(), (L - pc).abs()], axis=1).max(axis=1)
    atr = wilders(tr, 14)
    high52 = C / H.rolling(252).max() - 1
    dist200 = (C - C.rolling(200).mean()) / atr
    mom6 = C.shift(10) / C.shift(126) - 1
    qqe = (rsi_wilder(C, 20).fillna(50).ewm(span=5, adjust=False).mean() - 50) / 50
    hma = wma(2 * wma(C, 10) - wma(C, 20), 4)
    hull = (hma - hma.shift(1)) / atr
    mom40 = C / C.shift(40) - 1
    score = (W["high52"]*zclip(high52,"high52") + W["dist200"]*zclip(dist200,"dist200")
             + W["mom6"]*zclip(mom6,"mom6") + W["qqe"]*zclip(qqe,"qqe")
             + W["hull"]*zclip(hull,"hull") + W["mom40"]*zclip(mom40,"mom40"))
    return (score >= 2.0) & (high52 <= -0.10)

def collect(files, keep=None, price_floor=None):
    paths = {wk: [] for wk in WEEKS}
    n_sig = 0; dmin = dmax = None
    for fp in files:
        t = os.path.splitext(os.path.basename(fp))[0].upper()
        if t in {"SPY", "QQQ", "RSP"}: continue
        if keep is not None and t not in keep: continue
        try:
            d = pd.read_csv(fp, index_col=0, parse_dates=True).sort_index()
        except Exception:
            continue
        if len(d) < 320: continue
        sig = signal_series(d)
        O, C = d["Open"].values, d["Close"].values
        idx = np.where(sig.fillna(False).values)[0]
        last = -10**9
        for i in idx:
            if i - last < REFRACTORY: continue
            if i + 1 >= len(d): continue
            e = i + 1
            entry = O[e]
            if not np.isfinite(entry) or entry <= 0: continue
            last = i
            if price_floor is not None and entry < price_floor: continue
            n_sig += 1
            dt = d.index[e]
            dmin = dt if dmin is None or dt < dmin else dmin
            dmax = dt if dmax is None or dt > dmax else dmax
            for wk in WEEKS:
                j = e + wk * 5
                if j < len(d):
                    paths[wk].append((C[j] / entry - 1) * 100)
    return paths, n_sig, dmin, dmax

def summarize(label, paths, n_sig, dmin, dmax):
    print(f"\n=== {label} ===  signals: {n_sig}  ({dmin.date()} -> {dmax.date()})")
    print("wk    n     p10    p25    p50    p75    p90   win%")
    out = {"n_signals": n_sig, "date_range": [str(dmin.date()), str(dmax.date())],
           "weeks": WEEKS, "p10": [], "p25": [], "p50": [], "p75": [], "p90": [],
           "n_per_week": [], "win_pct": []}
    for wk in WEEKS:
        a = np.array(paths[wk])
        p = np.percentile(a, [10, 25, 50, 75, 90])
        for q, v in zip(["p10","p25","p50","p75","p90"], p):
            out[q].append(round(float(v), 2))
        out["n_per_week"].append(int(len(a)))
        out["win_pct"].append(round(float((a > 0).mean() * 100), 1))
        print(f"{wk:>2} {len(a):>6} " + " ".join(f"{v:>6.2f}" for v in p)
              + f"  {(a>0).mean()*100:>5.1f}")
    return out

def main():
    files = sorted(glob.glob(os.path.join(HERE, "daily_data_v2", "*.csv")))
    print(f"{len(files)} tickers in daily_data_v2")
    qg = pd.read_csv(os.path.join(HERE, "qualgate_cache.csv"))
    keep = {str(r.ticker).upper() for r in qg.itertuples()
            if str(r.gate).upper() in ("PASS", "WATCH")}
    print(f"PASS/WATCH tickers with gate data: {len(keep)}")

    a = collect(files)                                   # raw
    b = collect(files, keep=keep, price_floor=MIN_ENTRY_PRICE)  # published
    out = {"setups": "DLB + D200G + B2 (score>=2, >=10% below 52wk high)",
           "caveats": "gate = current fundamentals applied retroactively; "
                      "current constituents only (survivorship)",
           "raw": summarize("A) RAW — all tickers, no gate, no floor", *a),
           "published": summarize("B) PUBLISHED — PASS/WATCH + $50 floor", *b)}
    with open(os.path.join(HERE, "cone_data_both.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nwrote cone_data_both.json")

if __name__ == "__main__":
    main()
