#!/usr/bin/env python3
"""
test_sts_stall_breakout.py
Moving average confluence STALL then BREAKOUT, two shapes, tagged by STS bucket.

STALL EPISODE
  "Bunched" bar: EMA 9, EMA 14, EMA 21 and SMA 50 all within 1 ATR(14) of each other.
  An episode starts on a bunched bar after 3+ non bunched bars. It stays live while
  the last bunched bar is <= 5 bars ago and the episode is <= 40 bars old.
  First stall candle = the episode's first bar.

TRIGGER (once per episode)
  Episode has >= 3 bunched bars, and today's close > first stall candle's HIGH + 1 ATR.
  Entry = next day's open (actable at 10:15).

SHAPES (judged at the first stall candle, using the prior 60 bars)
  PEAK   (scenario 1, CRM style): the 60 bar high came AFTER the 60 bar low, and that
         high is >= 2 ATR above the stall close. Price ran up, peaked, came back to the
         averages and stalled.
  BOTTOM (scenario 2): the 60 bar low came AFTER the 60 bar high, and the stall close is
         >= 2 ATR above that low. Price came up off a bottom and stalled at the averages.

BUCKET TAG (STS ML score, same weights and z constants as sts_ml_evening.py, on the
  trigger day): D200G, D200, B2, S2, DLB, or "-" (not a setup). Answers "is this B2/DLB?"

MEASURES (no stops, no targets: pure path measurement from the entry open)
  For 1, 2 and 4 weeks (5, 10, 20 bars): MFE (best high), MAE (worst low), and the
  close return at the horizon. 0.05% slip per side on close returns.

CONTROLS (same ticker, same calendar year, entry next open)
  ctrl_any     random eligible day.
  ctrl_stall   random day INSIDE a live stall episode of the same shape (>= 3 bunched
               bars) that is not a trigger day. Tests "buy the clearance" vs "buy the stall".
  ctrl_bucket  random day with the SAME bucket tag. Tests whether the trigger adds
               anything beyond simply being a B2 / DLB / etc. day.

PRE COMMITTED PASS RULE (per shape)
  1. Test years 2022 to 2026: mean 20 day close return beats BOTH ctrl_stall and
     ctrl_bucket by >= 1.0 point.
  2. Beats ctrl_bucket on that measure in >= 3 of the 5 test years.
  3. Design years 2016 to 2021 agree (beats ctrl_bucket).
  MFE is reported because it was asked for, but MFE is the best case, not capturable,
  so it is NOT used to pass or fail.

CAVEAT: daily_data_v2 = today's index members (survivorship bias, flatters longs).

Run on the Mac:
  cd ~/STS/15min && python3.12 test_sts_stall_breakout.py
Output: STS_stall_breakout_test.xlsx (Verdict, Notes, ByPeriod, ByBucket, ByYear,
        Watch, Spotlight) and STS_stall_breakout_signals.csv
"""
import os
import glob
import random
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "daily_data_v2")
OUT = os.path.join(HERE, "STS_stall_breakout_test.xlsx")
OUT_CSV = os.path.join(HERE, "STS_stall_breakout_signals.csv")

MIN_PRICE, MIN_DV, WARMUP = 25.0, 20e6, 260
SLIP = 0.0005
HORIZONS = (5, 10, 20)
N_CTRL = 3
SEED = 23
DESIGN = list(range(2016, 2022))
TEST = list(range(2022, 2027))
EDGE_MIN = 1.0
ETFS = {"SPY", "QQQ", "IWM", "DIA", "XLC", "XLP", "XLK", "XLF", "XLE", "XLV",
        "XLI", "XLY", "XLU", "XLB", "XLRE", "SMH", "GLD", "TLT"}
SPOTLIGHT = ["CRM", "RKLB", "LRCX", "META"]

# STS ML score (copied from sts_ml_evening.py, must match)
ZC = {"high52": (-0.149772, 0.156737), "dist200": (1.681650, 6.240695),
      "mom6": (0.086250, 0.361377), "qqe": (0.044473, 0.194268),
      "hull": (0.027496, 0.303103), "mom40": (0.020000, 0.155298)}
W = {"high52": -2.20, "dist200": 1.35, "mom6": 1.08,
     "qqe": -0.99, "mom40": 0.63, "hull": 0.60}


def wilders(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def wma_fast(x, n):
    x = np.asarray(x, float)
    w = np.arange(1, n + 1, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = np.convolve(x, w[::-1], mode="valid") / w.sum()
    return out


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def bucket_codes(C, H, atr):
    pc = C.shift(1)
    high52 = C / H.rolling(252).max() - 1
    sma200 = C.rolling(200).mean()
    dist200 = (C - sma200) / atr
    mom6 = C.shift(10) / C.shift(126) - 1
    d = C.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    rsi = 100 - 100 / (1 + wilders(up, 20) / wilders(dn, 20).replace(0, 1e-10))
    qqe = (rsi.fillna(50).ewm(span=5, adjust=False).mean() - 50) / 50
    w10, w20 = wma_fast(C, 10), wma_fast(C, 20)
    hma = pd.Series(wma_fast(2 * w10 - w20, 4), index=C.index)
    hull = (hma - hma.shift(1)) / atr
    mom40 = C / C.shift(40) - 1
    vals = dict(high52=high52, dist200=dist200, mom6=mom6, qqe=qqe, hull=hull, mom40=mom40)
    score = sum(W[k] * np.clip((vals[k] - ZC[k][0]) / ZC[k][1], -3, 3) for k in W)
    off = high52.values * 100
    above = (C > sma200).values
    sc = np.round(score.values, 1)  # scanner rounds to 1 decimal before the >= 2 test
    code = np.full(len(C), "-", dtype=object)
    deep, mid, s2 = off <= -25, (off > -25) & (off <= -10), off > -10
    g2 = sc >= 2
    code[deep & above & g2] = "D200G"
    code[deep & above & ~g2] = "D200"
    code[~(deep & above) & g2 & mid] = "B2"
    code[~(deep & above) & g2 & s2] = "S2"
    code[~(deep & above) & g2 & deep] = "DLB"
    code[np.isnan(sc)] = "na"
    return code, sc, off


def analyze(df):
    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    v = df["Volume"].values.astype(float)
    n = len(c)
    C, H = df["Close"].astype(float), df["High"].astype(float)
    cp = C.shift(1)
    tr = pd.concat([H - df["Low"], (H - cp).abs(), (df["Low"] - cp).abs()], axis=1).max(axis=1)
    atr_s = wilders(tr, 14)
    atr = atr_s.values
    code, score, off = bucket_codes(C, H, atr_s)

    mas = np.vstack([ema(c, 9), ema(c, 14), ema(c, 21), C.rolling(50).mean().values])
    with np.errstate(invalid="ignore"):
        bunched = (mas.max(axis=0) - mas.min(axis=0)) <= 1.0 * atr
    dv20 = pd.Series(c * v).rolling(20).mean().values
    elig = (c >= MIN_PRICE) & (dv20 >= MIN_DV) & (np.arange(n) >= WARMUP) & (code != "na")

    trig = np.zeros(n, bool)
    shape = np.full(n, "", dtype=object)       # shape of the live episode on each bar
    in_stall = np.zeros(n, bool)               # live episode with >= 3 bunched bars
    ep_start = -1; last_b = -10; count = 0; fired = False; ep_shape = ""
    live_info = None
    for i in range(n):
        if bunched[i]:
            if ep_start < 0 or i - last_b > 3:
                ep_start, count, fired = i, 0, False
                ep_shape = "other"
                if i >= 60:
                    win_h, win_l = h[i - 60:i], l[i - 60:i]
                    ih, il = int(np.argmax(win_h)), int(np.argmin(win_l))
                    if ih > il and win_h[ih] >= c[i] + 2 * atr[i]:
                        ep_shape = "PEAK"
                    elif il > ih and c[i] >= win_l[il] + 2 * atr[i]:
                        ep_shape = "BOTTOM"
            count += 1
            last_b = i
        alive = ep_start >= 0 and (i - last_b) <= 5 and (i - ep_start) <= 40
        if alive:
            shape[i] = ep_shape
            if count >= 3:
                level = h[ep_start] + atr[i]
                if not fired and c[i] > level:
                    trig[i] = True
                    fired = True
                elif not fired:
                    in_stall[i] = True
            if i == n - 1 and not fired and ep_shape in ("PEAK", "BOTTOM"):
                live_info = dict(shape=ep_shape, stall_start=df.index[ep_start].date(),
                                 first_stall_high=round(h[ep_start], 2),
                                 trigger_close_above=round(h[ep_start] + atr[i], 2),
                                 bunched_bars=count, close=round(c[i], 2),
                                 atr=round(atr[i], 2), bucket=code[i],
                                 ml_score=round(float(score[i]), 2),
                                 off_52wk_high_pct=round(float(off[i]), 1),
                                 needs_pct=round(100 * ((h[ep_start] + atr[i]) / c[i] - 1), 1))
    return dict(o=o, h=h, l=l, c=c, n=n, atr=atr, code=code, elig=elig, trig=trig,
                shape=shape, in_stall=in_stall), live_info


def measure(d, t):
    e = t + 1
    P = d["o"][e]
    row = {}
    for k in HORIZONS:
        j = e + k
        if j > d["n"]:
            return None
        row[f"mfe{k}"] = d["h"][e:j].max() / P - 1
        row[f"mae{k}"] = d["l"][e:j].min() / P - 1
        row[f"ret{k}"] = d["c"][j - 1] * (1 - SLIP) / (P * (1 + SLIP)) - 1
    return P, row


def run_ticker(tk, df, rng):
    d, live = analyze(df)
    dates = df.index
    n = d["n"]
    last_ok = n - 1 - max(HORIZONS)
    rows = []
    pool_any, pool_stall, pool_bucket = {}, {}, {}
    for r in range(last_ok + 1):
        if not d["elig"][r]:
            continue
        y = dates[r].year
        pool_any.setdefault(y, []).append(r)
        pool_bucket.setdefault((y, d["code"][r]), []).append(r)
        if d["in_stall"][r] and d["shape"][r] in ("PEAK", "BOTTOM"):
            pool_stall.setdefault((y, d["shape"][r]), []).append(r)

    def add(t, kind, scen):
        m = measure(d, t)
        if m is None:
            return
        P, row = m
        rows.append(dict(ticker=tk, scenario=scen, kind=kind, signal_date=dates[t],
                         year=dates[t].year, entry_date=dates[t + 1], entry=round(P, 2),
                         bucket=d["code"][t], **row))

    for t in np.where(d["trig"][: last_ok + 1] & d["elig"][: last_ok + 1])[0]:
        scen = d["shape"][t]
        if scen not in ("PEAK", "BOTTOM"):
            continue
        add(t, "signal", scen)
        y = dates[t].year
        for kind, pool in (("ctrl_any", pool_any.get(y)),
                           ("ctrl_stall", pool_stall.get((y, scen))),
                           ("ctrl_bucket", pool_bucket.get((y, d["code"][t])))):
            if pool:
                for _ in range(N_CTRL):
                    add(rng.choice(pool), kind, scen)
    if live:
        live["ticker"] = tk
    return rows, live


def collect(files, seed=SEED):
    rng = random.Random(seed)
    rows, lives = [], []
    for k, f in enumerate(files):
        tk = os.path.basename(f)[:-4]
        if tk in ETFS:
            continue
        try:
            df = pd.read_csv(f, parse_dates=["Date"], index_col="Date")
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
            if len(df) < WARMUP + 40:
                continue
            r, live = run_ticker(tk, df, rng)
            rows.extend(r)
            if live:
                lives.append(live)
        except Exception as ex:
            print(f"skip {tk}: {ex}")
        if (k + 1) % 100 == 0:
            print(f"{k + 1}/{len(files)} tickers")
    return pd.DataFrame(rows), pd.DataFrame(lives)


def summarize(g):
    out = {"trades": len(g)}
    for k in HORIZONS:
        out[f"mfe{k}_mean"] = 100 * g[f"mfe{k}"].mean()
        out[f"mfe{k}_median"] = 100 * g[f"mfe{k}"].median()
        out[f"mae{k}_mean"] = 100 * g[f"mae{k}"].mean()
        out[f"ret{k}_mean"] = 100 * g[f"ret{k}"].mean()
        out[f"ret{k}_median"] = 100 * g[f"ret{k}"].median()
        out[f"win{k}_pct"] = 100 * (g[f"ret{k}"] > 0).mean()
    out["mfe20_ge10_pct"] = 100 * (g["mfe20"] >= 0.10).mean()
    out["mfe10_ge6_pct"] = 100 * (g["mfe10"] >= 0.06).mean()
    return pd.Series(out)


def report(T, L):
    T["period"] = np.where(T["year"].isin(TEST), "test_2022_2026",
                   np.where(T["year"].isin(DESIGN), "design_2016_2021", "other"))
    cols = [f"{m}{k}" for m in ("mfe", "mae", "ret") for k in HORIZONS]
    by_period = T.groupby(["scenario", "period", "kind"])[cols].apply(summarize).reset_index()
    by_year = T.groupby(["scenario", "year", "kind"])[cols].apply(summarize).reset_index()
    tb = T[T.kind.isin(["signal", "ctrl_bucket"]) & (T.period == "test_2022_2026")]
    by_bucket = tb.groupby(["scenario", "bucket", "kind"])[cols].apply(summarize).reset_index()
    cnt = T[T.kind == "signal"].groupby(["scenario", "bucket"]).size()
    mix = (100 * cnt / cnt.groupby(level=0).transform("sum")).round(1)

    def g(df, scen, kind, **kw):
        q = df[(df.scenario == scen) & (df.kind == kind)]
        for kk, vv in kw.items():
            q = q[q[kk] == vv]
        return q.iloc[0] if len(q) else None

    V = []
    for scen in ("PEAK", "BOTTOM"):
        s = g(by_period, scen, "signal", period="test_2022_2026")
        cs = g(by_period, scen, "ctrl_stall", period="test_2022_2026")
        cb = g(by_period, scen, "ctrl_bucket", period="test_2022_2026")
        ca = g(by_period, scen, "ctrl_any", period="test_2022_2026")
        sd = g(by_period, scen, "signal", period="design_2016_2021")
        cbd = g(by_period, scen, "ctrl_bucket", period="design_2016_2021")
        if s is None or cs is None or cb is None:
            continue
        r1 = (s.ret20_mean - cs.ret20_mean >= EDGE_MIN) and (s.ret20_mean - cb.ret20_mean >= EDGE_MIN)
        yrs = 0
        for y in TEST:
            sy, cy = g(by_year, scen, "signal", year=y), g(by_year, scen, "ctrl_bucket", year=y)
            if sy is not None and cy is not None and sy.ret20_mean > cy.ret20_mean:
                yrs += 1
        r3 = sd is not None and cbd is not None and sd.ret20_mean > cbd.ret20_mean
        row = dict(scenario=scen, test_signals=int(s.trades))
        for lab, x in (("sig", s), ("stall", cs), ("bucket", cb), ("any", ca)):
            row[f"{lab}_ret20"] = round(x.ret20_mean, 2) if x is not None else np.nan
        for lab, x in (("sig", s), ("stall", cs), ("bucket", cb)):
            row[f"{lab}_mfe5_med"] = round(x.mfe5_median, 2)
            row[f"{lab}_mfe10_med"] = round(x.mfe10_median, 2)
            row[f"{lab}_mfe20_med"] = round(x.mfe20_median, 2)
        row.update(sig_win20=round(s.win20_pct, 1), sig_mfe20_ge10=round(s.mfe20_ge10_pct, 1),
                   bucket_mfe20_ge10=round(cb.mfe20_ge10_pct, 1),
                   design_sig_ret20=round(sd.ret20_mean, 2) if sd is not None else np.nan,
                   design_bucket_ret20=round(cbd.ret20_mean, 2) if cbd is not None else np.nan,
                   rule1_edge_1pt=r1, test_years_beating_bucket=yrs, rule2_3of5=yrs >= 3,
                   rule3_design_agrees=r3, PASS=bool(r1 and yrs >= 3 and r3))
        V.append(row)
    V = pd.DataFrame(V)

    sig = T[T.kind == "signal"].copy()
    for col in cols:
        sig[col] = (100 * sig[col]).round(2)
    spot = sig[sig.ticker.isin(SPOTLIGHT) & (sig.year >= 2024)].sort_values(["ticker", "signal_date"])
    if len(L):
        L = L[["ticker", "shape", "bucket", "ml_score", "close", "trigger_close_above", "needs_pct",
               "first_stall_high", "atr", "stall_start", "bunched_bars", "off_52wk_high_pct"]]
        L = L.sort_values(["shape", "needs_pct"])

    notes = pd.DataFrame({"note": [
        "Moving average confluence stall then breakout. Research only, not advice.",
        "Bunched = EMA 9/14/21 and SMA 50 within 1 ATR. Episode starts on a bunched bar after 3+ non bunched bars; live while last bunched bar <= 5 bars ago and <= 40 bars old.",
        "Trigger: >= 3 bunched bars in the episode, close > first stall candle high + 1 ATR, once per episode. Entry next open.",
        "PEAK = 60 bar high came after the 60 bar low and is >= 2 ATR above the stall close (CRM style). BOTTOM = 60 bar low came after the high and the stall close is >= 2 ATR above it.",
        "Bucket = STS ML setup code on the trigger day (D200G, D200, B2, S2, DLB, '-').",
        "MFE/MAE/close return at 5, 10, 20 bars from the entry open. No stops or targets. 0.05% slip per side on close returns.",
        "Controls: ctrl_any random day; ctrl_stall random non trigger day inside a live stall of the same shape; ctrl_bucket random day with the same bucket code. Same ticker and year.",
        "Pass: test years 20 day mean close return beats ctrl_stall and ctrl_bucket by 1.0 pt; beats ctrl_bucket in 3 of 5 test years; design years agree. MFE is reported, not judged.",
        "Watch sheet: live stalls tonight with the close needed to trigger (research flag, not an instruction). Survivorship bias: today's index members only.",
    ]})
    mix_df = mix.rename("pct_of_signals").reset_index()

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        V.to_excel(xw, sheet_name="Verdict", index=False)
        notes.to_excel(xw, sheet_name="Notes", index=False)
        by_period.round(2).to_excel(xw, sheet_name="ByPeriod", index=False)
        by_bucket.round(2).to_excel(xw, sheet_name="ByBucket", index=False)
        mix_df.to_excel(xw, sheet_name="BucketMix", index=False)
        by_year.round(2).to_excel(xw, sheet_name="ByYear", index=False)
        (L if len(L) else pd.DataFrame()).to_excel(xw, sheet_name="Watch", index=False)
        spot.to_excel(xw, sheet_name="Spotlight", index=False)
    sig.to_csv(OUT_CSV, index=False)

    pd.set_option("display.width", 250)
    print("\nVERDICT")
    print(V.T.to_string())
    print("\nBUCKET MIX (% of signals)")
    print(mix.to_string())
    print(f"\nSaved {OUT}\nSaved {OUT_CSV}")


def main():
    files = sorted(glob.glob(os.path.join(DATA, "*.csv")))
    T, L = collect(files)
    report(T, L)


if __name__ == "__main__":
    main()
