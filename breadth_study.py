#!/usr/bin/env python3.12
"""
breadth_study.py — does market BREADTH at entry predict how our setups do?

Question (GJ, 2026-10-19): a reader suggested tracking RSP/SPY (equal- vs
cap-weight) and the % of S&P 500 stocks above their 200-day; "index at a record
but only 40% above the average = divergence". Before putting either on the
board, test whether they carry information about OUR signals' forward returns.

Signals: same generator as touch_curve_study.py / cone_study_both.py —
score >= 2.0 and >= 10% below the 52-week high, PASS/WATCH gate, $50 floor,
20-day refractory, entry = next day's open, daily_data_v2 universe.
Phoenix-like = >= 25% below the 52-week high at signal; Cruise-like = 10-25%.

Breadth measures (all computed from the same CSVs, nothing new downloaded):
  B200   = % of S&P 500 names (sp500_tickers.txt, CURRENT constituents) with
           close > 200-day SMA on the day before entry.  (Survivorship: today's
           members were, on average, yesterday's winners, so early-years breadth
           reads high. Reported alongside the same measure on the whole
           ~1,000-name v2 universe, U200, which has less of that bias.)
  dB20   = change in B200 over the prior 20 sessions (rising / falling breadth)
  RS60   = RSP/SPY ratio, % change over prior 60 sessions (narrowing < 0)
  DIVERG = SPY within 2% of its 52-week high AND B200 < 50%
  SPY200 = SPY above its 200-day (the existing dial's red/not-red line)

Outcomes per signal: 4-wk and 12-wk close return, 12-wk excess over SPY,
touched +5% / +10% within 12 wks (intraday high), max 4-wk dip.

Reading rules (pre-committed): a bucket matters only if (a) n >= 150,
(b) the 12-wk median return differs from the pooled median by >= 2 points,
AND (c) the ordering survives inside BOTH SPY200 states (otherwise it is the
regime dial wearing a different hat).

Run:   cd ~/STS/15min && nohup python3.12 breadth_study.py > breadth_study.log 2>&1 &
Output: breadth_study.log (tables), breadth_study_signals.csv (one row per signal),
        breadth_series.csv (daily B200 / U200 / RS ratio for charting).
"""
import glob, os, sys
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.join(HERE, "daily_data_v2")
SLOW = os.path.join(HERE, "daily_data_slow_ext")
MIN_ENTRY_PRICE = 50.0
REFRACTORY = 20
START = "2018-06-01"          # need 252 bars before first signal; data begins ~2016

ZC = {"high52": (-0.149772, 0.156737), "dist200": (1.681650, 6.240695),
      "mom6": (0.086250, 0.361377), "qqe": (0.044473, 0.194268),
      "hull": (0.027496, 0.303103), "mom40": (0.020000, 0.155298)}
W  = {"high52": -2.20, "dist200": 1.35, "mom6": 1.08,
      "qqe": -0.99, "mom40": 0.63, "hull": 0.60}

def zclip(s, key):
    m, sd = ZC[key]; return ((s - m) / sd).clip(-3, 3)
def wilders(s, n): return s.ewm(alpha=1/n, adjust=False).mean()
def rsi_wilder(s, n=20):
    d = s.diff(); up, dn = d.clip(lower=0), -d.clip(upper=0)
    rs = wilders(up, n) / wilders(dn, n).replace(0, 1e-10)
    return 100 - 100 / (1 + rs)
def wma(s, n):
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

def load(fp):
    d = pd.read_csv(fp, index_col=0, parse_dates=True).sort_index()
    d.index = pd.to_datetime(d.index).tz_localize(None)
    d = d[~d.index.duplicated(keep="last")]
    d = d[d["Close"].notna() & (d["Close"] > 0)]
    return d

def signal_frame(d):
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
    return pd.DataFrame({"sig": (score >= 2.0) & (high52 <= -0.10), "high52": high52})

def find_csv(t):
    for base in (V2, SLOW):
        fp = os.path.join(base, t.replace(".", "-") + ".csv")
        if os.path.exists(fp): return fp
    return None

# --------------------------------------------------------------------------- breadth series
def breadth_series():
    spx = open(os.path.join(HERE, "sp500_tickers.txt")).read().split()
    above = {}        # ticker -> Series(bool) close > sma200
    for fp in sorted(glob.glob(os.path.join(V2, "*.csv"))):
        t = os.path.splitext(os.path.basename(fp))[0].upper()
        if t in {"SPY", "QQQ", "RSP"}: continue
        try: d = load(fp)
        except Exception: continue
        if len(d) < 220: continue
        c = d["Close"]
        above[t] = (c > c.rolling(200).mean()).where(c.rolling(200).mean().notna())
    A = pd.DataFrame(above).sort_index()
    A = A[A.index >= "2017-01-01"]
    u200 = A.mean(axis=1, skipna=True) * 100
    spx_cols = [c for c in A.columns if c in {s.replace(".", "-") for s in spx} or c in spx]
    b200 = A[spx_cols].mean(axis=1, skipna=True) * 100
    nspx = A[spx_cols].notna().sum(axis=1)
    spy = load(os.path.join(V2, "SPY.csv"))["Close"]; rsp = load(os.path.join(V2, "RSP.csv"))["Close"]
    ratio = (rsp / spy).dropna()
    ser = pd.DataFrame({"B200": b200, "U200": u200, "n_spx": nspx, "ratio": ratio,
                        "SPY": spy}).dropna(subset=["B200", "SPY"])
    ser["dB20"] = ser["B200"] - ser["B200"].shift(20)
    ser["RS60"] = (ser["ratio"] / ser["ratio"].shift(60) - 1) * 100
    ser["SPY200"] = ser["SPY"] > ser["SPY"].rolling(200).mean()
    ser["SPYnearHigh"] = ser["SPY"] / ser["SPY"].rolling(252).max() - 1 >= -0.02
    ser["DIVERG"] = ser["SPYnearHigh"] & (ser["B200"] < 50)
    return ser, spy

# --------------------------------------------------------------------------- signals
def signals(ser, spy):
    qg = pd.read_csv(os.path.join(HERE, "qualgate_cache.csv"))
    keep = {str(r.ticker).upper() for r in qg.itertuples() if str(r.gate).upper() in ("PASS", "WATCH")}
    spyv = spy.reindex(ser.index).ffill()
    rows = []
    for fp in sorted(glob.glob(os.path.join(V2, "*.csv"))):
        t = os.path.splitext(os.path.basename(fp))[0].upper()
        if t in {"SPY", "QQQ", "RSP"} or t not in keep: continue
        try: d = load(fp)
        except Exception: continue
        if len(d) < 320: continue
        sf = signal_frame(d)
        O, Hv, Lv, Cv = d["Open"].values, d["High"].values, d["Low"].values, d["Close"].values
        idx = np.where(sf["sig"].fillna(False).values)[0]
        last = -10**9
        for i in idx:
            if i - last < REFRACTORY: continue
            if i + 1 >= len(d) - 61: continue
            if d.index[i] < pd.Timestamp(START): continue
            e = i + 1; entry = O[e]
            if not np.isfinite(entry) or entry <= 0: continue
            last = i
            if entry < MIN_ENTRY_PRICE: continue
            sday = d.index[i]
            if sday not in ser.index: continue
            b = ser.loc[sday]
            if not np.isfinite(b["B200"]) or not np.isfinite(b["RS60"]) or not np.isfinite(b["dB20"]): continue
            hi = Hv[e:e + 61]; lo20 = Lv[e:e + 21]
            edate, d4, d12 = d.index[e], d.index[min(e + 20, len(d) - 1)], d.index[e + 60]
            s0 = spyv.get(edate, np.nan); s12 = spyv.get(d12, np.nan)
            rows.append(dict(
                ticker=t, date=sday.date(), entry=entry,
                setup=("phoenix" if sf["high52"].iloc[i] <= -0.25 else "cruise"),
                B200=b["B200"], U200=b["U200"], dB20=b["dB20"], RS60=b["RS60"],
                SPY200=bool(b["SPY200"]), DIVERG=bool(b["DIVERG"]),
                r4=(Cv[e + 20] / entry - 1) * 100, r12=(Cv[e + 60] / entry - 1) * 100,
                x12=((Cv[e + 60] / entry) - (s12 / s0)) * 100 if np.isfinite(s0) and np.isfinite(s12) else np.nan,
                t5=bool((hi >= entry * 1.05).any()), t10=bool((hi >= entry * 1.10).any()),
                md4=(lo20.min() / entry - 1) * 100,
            ))
    return pd.DataFrame(rows)

# --------------------------------------------------------------------------- tables
def table(df, by, title, order=None):
    g = df.groupby(by, observed=True)
    out = pd.DataFrame({
        "n": g.size(),
        "med r12": g["r12"].median().round(1), "avg r12": g["r12"].mean().round(1),
        "med r4": g["r4"].median().round(1),
        "excess12": g["x12"].median().round(1),
        "win12 %": (g["r12"].apply(lambda s: (s > 0).mean()) * 100).round(0),
        "t5 %": (g["t5"].mean() * 100).round(0), "t10 %": (g["t10"].mean() * 100).round(0),
        "avg md4": g["md4"].mean().round(1),
    })
    if order is not None: out = out.reindex([o for o in order if o in out.index])
    print(f"\n### {title}\n{out.to_string()}")
    return out

def main():
    print("Building breadth series ...", flush=True)
    ser, spy = breadth_series()
    ser.to_csv(os.path.join(HERE, "breadth_series.csv"))
    print(f"  {len(ser)} sessions, S&P names covered today: {int(ser['n_spx'].iloc[-1])}, "
          f"latest B200 {ser['B200'].iloc[-1]:.0f}%  U200 {ser['U200'].iloc[-1]:.0f}%  "
          f"RS60 {ser['RS60'].iloc[-1]:+.1f}%  dB20 {ser['dB20'].iloc[-1]:+.0f}  "
          f"SPY>200 {bool(ser['SPY200'].iloc[-1])}  diverg {bool(ser['DIVERG'].iloc[-1])}", flush=True)
    print(f"  B200 distribution: " + ", ".join(f"p{p}={np.nanpercentile(ser['B200'], p):.0f}" for p in (10, 25, 50, 75, 90)))

    print("Generating signals ...", flush=True)
    df = signals(ser, spy)
    df.to_csv(os.path.join(HERE, "breadth_study_signals.csv"), index=False)
    print(f"  {len(df)} signals {df['date'].min()} .. {df['date'].max()}  "
          f"(phoenix {int((df['setup']=='phoenix').sum())}, cruise {int((df['setup']=='cruise').sum())})")
    pooled_med = df["r12"].median()
    print(f"\nPOOLED: n={len(df)} med r12 {pooled_med:+.1f}%  avg {df['r12'].mean():+.1f}%  "
          f"excess12 med {df['x12'].median():+.1f}  win12 {100*(df['r12']>0).mean():.0f}%  t5 {100*df['t5'].mean():.0f}%  t10 {100*df['t10'].mean():.0f}%")

    bins = [0, 40, 50, 60, 70, 101]; labels = ["<40", "40-50", "50-60", "60-70", "70+"]
    df["Bbkt"] = pd.cut(df["B200"], bins=bins, labels=labels, right=False)
    df["Ubkt"] = pd.cut(df["U200"], bins=bins, labels=labels, right=False)
    df["trend"] = np.where(df["dB20"] >= 5, "breadth rising (+5)", np.where(df["dB20"] <= -5, "breadth falling (-5)", "flat"))
    df["rs"] = np.where(df["RS60"] <= -2, "narrowing (RS60<=-2)", np.where(df["RS60"] >= 2, "broadening (RS60>=+2)", "neutral"))
    df["regime"] = np.where(df["SPY200"], "SPY above 200d", "SPY below 200d")

    table(df, "Bbkt", "% of S&P 500 above 200-day at entry (B200)", labels)
    table(df, "Ubkt", "% of whole v2 universe above 200-day at entry (U200)", labels)
    table(df, "trend", "Breadth trend over prior 20 sessions (dB20)", ["breadth falling (-5)", "flat", "breadth rising (+5)"])
    table(df, "rs", "RSP/SPY 60-session change (RS60)", ["narrowing (RS60<=-2)", "neutral", "broadening (RS60>=+2)"])
    table(df, "DIVERG", "Divergence flag: SPY within 2% of 52wk high AND B200 < 50%")
    table(df, "regime", "Existing dial line: SPY vs its 200-day")

    print("\n\n===== CONTROL FOR REGIME (rule c): breadth bucket WITHIN each SPY state =====")
    for reg, sub in df.groupby("regime"):
        table(sub, "Bbkt", f"B200 bucket | {reg}", labels)
        table(sub, "rs", f"RS60 | {reg}", ["narrowing (RS60<=-2)", "neutral", "broadening (RS60>=+2)"])
        table(sub, "trend", f"dB20 | {reg}", ["breadth falling (-5)", "flat", "breadth rising (+5)"])

    print("\n\n===== BY SETUP =====")
    for st, sub in df.groupby("setup"):
        table(sub, "Bbkt", f"B200 bucket | {st}", labels)
        table(sub, "DIVERG", f"Divergence | {st}")

    print("\n\n===== BY YEAR (sanity: is any effect just one episode?) =====")
    df["year"] = pd.to_datetime(df["date"]).dt.year
    yr = df.groupby("year").agg(n=("r12", "size"), B200_med=("B200", "median"), med_r12=("r12", "median"),
                                 excess12=("x12", "median")).round(1)
    print(yr.to_string())

    print("\n\n===== CORRELATIONS (Spearman, 12-wk return) =====")
    for c in ("B200", "U200", "dB20", "RS60"):
        print(f"  {c:6s} rho = {df[[c, 'r12']].corr(method='spearman').iloc[0, 1]:+.3f}")
    print("\nDone.")

if __name__ == "__main__":
    main()
