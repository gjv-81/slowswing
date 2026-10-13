#!/usr/bin/env python3.12
"""
cone_study_gated.py — the signal-journey cone restricted to the WEBSITE universe:
QualGate PASS or WATCH only (per qualgate_cache.csv), entry price >= $50 —
the same filters build_board.py / build_stats.py enforce on the site.

Same signal definition as cone_study.py (deep >=25% off 52wk high, score >= 2.0,
next-open entry, 20td refractory). Tickers absent from qualgate_cache.csv are
EXCLUDED (gate unknown).

HONESTY CAVEAT (printed into the json): the gate is computed from CURRENT
fundamentals and applied to 10 years of history — a company that is PASS today
may not have been PASS in 2019. This is unavoidable (no historical gate data);
label any published use accordingly.

Run:  python3.12 ~/STS/15min/cone_study_gated.py
Output: cone_data_gated.json + summary table.
"""
import glob, os, json
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_ENTRY_PRICE = 50.0

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

REFRACTORY = 20
WEEKS = list(range(13))

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
    return (score >= 2.0) & (high52 <= -0.25)

def main():
    qg = pd.read_csv(os.path.join(HERE, "qualgate_cache.csv"))
    gate = {str(r.ticker).upper(): str(r.gate).upper() for r in qg.itertuples()}
    keep = {t for t, g in gate.items() if g in ("PASS", "WATCH")}
    print(f"qualgate cache: {len(gate)} tickers, PASS/WATCH: {len(keep)}")

    paths = {wk: [] for wk in WEEKS}
    n_sig = 0; n_price_skip = 0; n_nogate = 0; dmin = dmax = None
    files = sorted(glob.glob(os.path.join(HERE, "daily_data_v2", "*.csv")))
    for k, fp in enumerate(files):
        t = os.path.splitext(os.path.basename(fp))[0].upper()
        if t in {"SPY", "QQQ", "RSP"}: continue
        if t not in gate: n_nogate += 1; continue
        if t not in keep: continue
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
            if entry < MIN_ENTRY_PRICE:
                last = i; n_price_skip += 1; continue
            last = i
            n_sig += 1
            dt = d.index[e]
            dmin = dt if dmin is None or dt < dmin else dmin
            dmax = dt if dmax is None or dt > dmax else dmax
            for wk in WEEKS:
                j = e + wk * 5
                if j < len(d):
                    paths[wk].append((C[j] / entry - 1) * 100)
        if (k + 1) % 200 == 0: print(f"  {k+1}/{len(files)}, signals: {n_sig}")

    out = {"n_signals": n_sig,
           "universe": "QualGate PASS/WATCH (current snapshot) + entry >= $50",
           "skipped_under_50": n_price_skip,
           "tickers_without_gate": n_nogate,
           "date_range": [str(dmin.date()), str(dmax.date())],
           "caveat": "gate is TODAY'S fundamentals applied retroactively; no historical gate data exists",
           "weeks": WEEKS}
    print(f"\nsignals: {n_sig}  ({dmin.date()} -> {dmax.date()})  | skipped <$50: {n_price_skip} | no gate data: {n_nogate} tickers\n")
    print("wk    n     p10    p25    p50    p75    p90   win%")
    for q in ["p10","p25","p50","p75","p90"]: out[q] = []
    out["n_per_week"] = []; out["win_pct"] = []
    for wk in WEEKS:
        a = np.array(paths[wk])
        p = np.percentile(a, [10, 25, 50, 75, 90])
        for q, v in zip(["p10","p25","p50","p75","p90"], p):
            out[q].append(round(float(v), 2))
        out["n_per_week"].append(int(len(a)))
        out["win_pct"].append(round(float((a > 0).mean() * 100), 1))
        print(f"{wk:>2} {len(a):>6} " + " ".join(f"{v:>6.2f}" for v in p)
              + f"  {(a>0).mean()*100:>5.1f}")
    with open(os.path.join(HERE, "cone_data_gated.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\nwrote cone_data_gated.json")

if __name__ == "__main__":
    main()
