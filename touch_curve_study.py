#!/usr/bin/env python3.12
"""
touch_curve_study.py — data for the TOUCH CURVE chart:
"% of signals that have reached +5% / +10% / +20% (intraday high vs entry)
by week N", N = 0..12, on the PUBLISHED universe (PASS/WATCH gate + $50 floor,
DLB + D200G + B2 signals, same mechanics as cone_study_both.py).

Also computes the honest BASELINE: current S&P 500 names (sp500_tickers.txt),
every 5th trading day as a start date over the last 3 years, % that touched
+5% / +10% within N weeks of that arbitrary start.

Run:  python3.12 ~/STS/15min/touch_curve_study.py
Output: touch_curve_data.json + printed table.
"""
import glob, os, json
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_ENTRY_PRICE = 50.0
REFRACTORY = 20
WEEKS = list(range(13))
LEVELS = [5, 10, 20]

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

def touch_week(H, entry, e, level):
    """first week (0..12) by which running max high >= entry*(1+level%), else None."""
    lim = entry * (1 + level / 100.0)
    hi = H[e:e + 61]
    hit = np.where(hi >= lim)[0]
    if len(hit) == 0: return None
    return int(np.ceil(hit[0] / 5))          # td 0 -> wk0, td 1-5 -> wk1, ...

def main():
    qg = pd.read_csv(os.path.join(HERE, "qualgate_cache.csv"))
    keep = {str(r.ticker).upper() for r in qg.itertuples()
            if str(r.gate).upper() in ("PASS", "WATCH")}

    # ---- signals (published universe) ----
    counts = {lv: np.zeros(13) for lv in LEVELS}   # touched by week N (cumulative)
    n_sig = 0
    files = sorted(glob.glob(os.path.join(HERE, "daily_data_v2", "*.csv")))
    for fp in files:
        t = os.path.splitext(os.path.basename(fp))[0].upper()
        if t in {"SPY", "QQQ", "RSP"} or t not in keep: continue
        try:
            d = pd.read_csv(fp, index_col=0, parse_dates=True).sort_index()
        except Exception:
            continue
        if len(d) < 320: continue
        sig = signal_series(d)
        O, Hv = d["Open"].values, d["High"].values
        idx = np.where(sig.fillna(False).values)[0]
        last = -10**9
        for i in idx:
            if i - last < REFRACTORY: continue
            if i + 1 >= len(d) - 61: continue      # need full 12wk window
            e = i + 1
            entry = O[e]
            if not np.isfinite(entry) or entry <= 0: continue
            last = i
            if entry < MIN_ENTRY_PRICE: continue
            n_sig += 1
            for lv in LEVELS:
                wk = touch_week(Hv, entry, e, lv)
                if wk is not None:
                    counts[lv][min(wk, 12):] += 0   # no-op guard
                    for k in range(min(wk, 12), 13):
                        counts[lv][k] += 1
    sig_curves = {f"t{lv}": [round(100 * c / n_sig, 1) for c in counts[lv]] for lv in LEVELS}

    # ---- baseline: S&P 500, every 5th day start, last 3 years ----
    syms = open(os.path.join(HERE, "sp500_tickers.txt")).read().split()
    bcounts = {lv: np.zeros(13) for lv in [5, 10, 20]}
    n_base = 0
    for t in syms:
        fp = os.path.join(HERE, "daily_data_v2", t.replace(".", "-") + ".csv")
        if not os.path.exists(fp):
            fp = os.path.join(HERE, "daily_data_slow_ext", t.replace(".", "-") + ".csv")
            if not os.path.exists(fp): continue
        try:
            d = pd.read_csv(fp, index_col=0, parse_dates=True).sort_index()
        except Exception:
            continue
        d = d[d.index >= "2023-10-01"]
        O, Hv = d["Open"].values, d["High"].values
        for e in range(0, len(d) - 61, 5):
            entry = O[e]
            if not np.isfinite(entry) or entry <= 0: continue
            n_base += 1
            for lv in [5, 10, 20]:
                wk = touch_week(Hv, entry, e, lv)
                if wk is not None:
                    for k in range(min(wk, 12), 13):
                        bcounts[lv][k] += 1
    base_curves = {f"b{lv}": [round(100 * c / n_base, 1) for c in bcounts[lv]] for lv in [5, 10, 20]}

    out = {"n_signals": n_sig, "n_baseline_starts": n_base,
           "universe": "PASS/WATCH + $50 floor, DLB+D200G+B2, full 12wk windows only",
           "baseline": "current S&P 500, every 5th day start, Oct 2023 - present",
           "weeks": WEEKS, **sig_curves, **base_curves}
    print(f"signals: {n_sig} | baseline starts: {n_base}\n")
    print("wk   sig+5%  sig+10%  sig+20%   spx+5%  spx+10%  spx+20%")
    for k in WEEKS:
        print(f"{k:>2}  {sig_curves['t5'][k]:>6.1f}  {sig_curves['t10'][k]:>6.1f}"
              f"  {sig_curves['t20'][k]:>6.1f}   {base_curves['b5'][k]:>6.1f}"
              f"  {base_curves['b10'][k]:>6.1f}  {base_curves['b20'][k]:>6.1f}")
    with open(os.path.join(HERE, "touch_curve_data.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nwrote touch_curve_data.json")

if __name__ == "__main__":
    main()
