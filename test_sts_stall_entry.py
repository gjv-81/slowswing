#!/usr/bin/env python3
"""
test_sts_stall_entry.py
Pre registered test: BUY INSIDE THE MOVING AVERAGE STALL, with an On Balance Volume split.
Written 2026-10-13 BEFORE any run on the out of sample universe.

WHY
  Two earlier tests (range/pullback context control, stall breakout ctrl_stall) found that
  random days inside an MA confluence stall beat the breakout and beat random days. That
  was seen only in control groups, i.e. post hoc. This tests it as a signal on stocks
  never used in those studies.

UNIVERSES
  PRIMARY (verdict): daily_data_ext, the 1,246 expansion names (3 years, Sep 2023 to now),
           minus any ticker also in daily_data_v2. Never touched by tonight's studies.
  REFERENCE: daily_data_v2 (10 years, in sample for the idea) reported for comparison only.
  Both: price >= $25 and 20 day average dollar volume >= $20M on the signal day.

STALL (identical to test_sts_stall_breakout.py)
  Bunched bar: EMA 9/14/21 and SMA 50 within 1 ATR(14). Episode starts on a bunched bar
  after 3+ non bunched bars; live while the last bunched bar is <= 5 bars ago and <= 40
  bars old. Shape judged at the episode's first bar with the prior 60 bars:
    PEAK   60 bar high after 60 bar low, high >= 2 ATR above the stall close.
    BOTTOM 60 bar low after 60 bar high, stall close >= 2 ATR above the low.

SIGNAL (one per episode)
  The day the episode reaches its 3rd bunched bar, provided it has not already closed
  above first stall candle high + 1 ATR (i.e. still a stall, not yet a breakout).
  Entry = next day's open. No stops or targets: MFE, MAE and close return at 5/10/20 bars,
  0.05% slip per side on close returns.

OBV SPLIT
  OBV slope over the stall = (OBV on signal day - OBV the day before the stall began)
  divided by (20 day average volume x bars in the stall). Positive = net buying volume
  while price stalled. Signals are split into terciles (cutoffs from the primary universe):
  OBV_low, OBV_mid, OBV_high.

CONTROLS (same ticker, same calendar year, entry next open)
  ctrl_any     random eligible day.
  ctrl_shape   random day NOT in a stall whose 60 bar shape matches (PEAK: 60 bar high came
               after the low and is >= 2 ATR above close; BOTTOM: the mirror). Tests whether
               the STALL adds anything beyond the run up / pullback shape itself.

PRE COMMITTED PASS RULES (primary universe, per shape)
  Stall entry passes if:
    A1. 20 day mean close return beats ctrl_any by >= 1.0 point AND beats ctrl_shape by >= 0.5.
    A2. Beats ctrl_any in at least 2 of the 3 calendar years 2024, 2025, 2026.
    A3. 20 day median return of signals > 0.
  OBV passes if:
    B1. OBV_high beats OBV_low by >= 1.0 point on 20 day mean return,
    B2. in at least 2 of the 3 years, and
    B3. the reference universe (v2) shows the same direction.
  Anything that fails is dropped, not re tuned.

CAVEATS
  Three years is one market regime (mostly a bull run). Both folders hold today's listed
  names (survivorship bias). The expansion universe includes some smaller caps; the
  dollar volume floor is the liquidity guard.

Run on the Mac:
  cd ~/STS/15min && python3.12 test_sts_stall_entry.py
Output: STS_stall_entry_test.xlsx (Verdict, Notes, ByShape, ByYear, OBV, Watch) and
        STS_stall_entry_signals.csv
"""
import os
import glob
import random
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PRIMARY = os.path.join(HERE, "daily_data_ext")
REFERENCE = os.path.join(HERE, "daily_data_v2")
OUT = os.path.join(HERE, "STS_stall_entry_test.xlsx")
OUT_CSV = os.path.join(HERE, "STS_stall_entry_signals.csv")

MIN_PRICE, MIN_DV, WARMUP = 25.0, 20e6, 80
SLIP = 0.0005
HORIZONS = (5, 10, 20)
N_CTRL = 3
SEED = 31
YEARS = [2024, 2025, 2026]
ETFS = {"SPY", "QQQ", "IWM", "DIA", "XLC", "XLP", "XLK", "XLF", "XLE", "XLV",
        "XLI", "XLY", "XLU", "XLB", "XLRE", "SMH", "GLD", "TLT"}

ZC = {"high52": (-0.149772, 0.156737), "dist200": (1.681650, 6.240695),
      "mom6": (0.086250, 0.361377), "qqe": (0.044473, 0.194268),
      "hull": (0.027496, 0.303103), "mom40": (0.020000, 0.155298)}
W = {"high52": -2.20, "dist200": 1.35, "mom6": 1.08,
     "qqe": -0.99, "mom40": 0.63, "hull": 0.60}


def wilders(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def wma_fast(x, n):
    x = np.asarray(x, float)
    w = np.arange(1, n + 1, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = np.convolve(x, w[::-1], mode="valid") / w.sum()
    return out


def bucket_codes(C, H, atr):
    high52 = C / H.rolling(252).max() - 1
    sma200 = C.rolling(200).mean()
    dist200 = (C - sma200) / atr
    mom6 = C.shift(10) / C.shift(126) - 1
    d = C.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    rsi = 100 - 100 / (1 + wilders(up, 20) / wilders(dn, 20).replace(0, 1e-10))
    qqe = (rsi.fillna(50).ewm(span=5, adjust=False).mean() - 50) / 50
    hma = pd.Series(wma_fast(2 * wma_fast(C, 10) - wma_fast(C, 20), 4), index=C.index)
    hull = (hma - hma.shift(1)) / atr
    mom40 = C / C.shift(40) - 1
    vals = dict(high52=high52, dist200=dist200, mom6=mom6, qqe=qqe, hull=hull, mom40=mom40)
    score = sum(W[k] * np.clip((vals[k] - ZC[k][0]) / ZC[k][1], -3, 3) for k in W)
    sc = np.round(score.values, 1)
    off = high52.values * 100
    above = (C > sma200).values
    code = np.full(len(C), "-", dtype=object)
    deep, mid, s2 = off <= -25, (off > -25) & (off <= -10), off > -10
    g2 = sc >= 2
    code[deep & above & g2] = "D200G"
    code[deep & above & ~g2] = "D200"
    code[~(deep & above) & g2 & mid] = "B2"
    code[~(deep & above) & g2 & s2] = "S2"
    code[~(deep & above) & g2 & deep] = "DLB"
    code[np.isnan(sc)] = "na"
    return code, sc


def shape_at(h, l, c, atr, i):
    if i < 60:
        return "other"
    win_h, win_l = h[i - 60:i], l[i - 60:i]
    ih, il = int(np.argmax(win_h)), int(np.argmin(win_l))
    if ih > il and win_h[ih] >= c[i] + 2 * atr[i]:
        return "PEAK"
    if il > ih and c[i] >= win_l[il] + 2 * atr[i]:
        return "BOTTOM"
    return "other"


def analyze(df):
    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    v = df["Volume"].values.astype(float)
    n = len(c)
    C, H, L = df["Close"].astype(float), df["High"].astype(float), df["Low"].astype(float)
    cp = C.shift(1)
    tr = pd.concat([H - L, (H - cp).abs(), (L - cp).abs()], axis=1).max(axis=1)
    atr_s = wilders(tr, 14)
    atr = atr_s.values
    code, score = bucket_codes(C, H, atr_s)
    mas = np.vstack([ema(c, 9), ema(c, 14), ema(c, 21), C.rolling(50).mean().values])
    with np.errstate(invalid="ignore"):
        bunched = (mas.max(axis=0) - mas.min(axis=0)) <= 1.0 * atr
    vol20 = pd.Series(v).rolling(20).mean().values
    dv20 = pd.Series(c * v).rolling(20).mean().values
    elig = (c >= MIN_PRICE) & (dv20 >= MIN_DV) & (np.arange(n) >= WARMUP)
    obv = np.concatenate([[0.0], np.cumsum(np.sign(np.diff(c)) * v[1:])])

    sig = np.zeros(n, bool)
    sig_shape = np.full(n, "", dtype=object)
    obv_slope = np.full(n, np.nan)
    in_stall = np.zeros(n, bool)
    ep_start = -1; last_b = -10; count = 0; fired = False; ep_shape = ""
    live = None
    for i in range(n):
        if bunched[i]:
            if ep_start < 0 or i - last_b > 3:
                ep_start, count, fired = i, 0, False
                ep_shape = shape_at(h, l, c, atr, i)
            count += 1
            last_b = i
        alive = ep_start >= 0 and (i - last_b) <= 5 and (i - ep_start) <= 40
        if not alive:
            continue
        if not fired and count >= 3 and c[i] > h[ep_start] + atr[i]:
            fired = True
        if fired:
            continue
        if count >= 3:
            in_stall[i] = True
        if count == 3 and bunched[i] and ep_shape in ("PEAK", "BOTTOM"):
            sig[i] = True
            sig_shape[i] = ep_shape
            base = obv[ep_start - 1] if ep_start >= 1 else 0.0
            bars = i - ep_start + 1
            if np.isfinite(vol20[i]) and vol20[i] > 0:
                obv_slope[i] = (obv[i] - base) / (vol20[i] * bars)
        if i == n - 1 and count >= 3 and ep_shape in ("PEAK", "BOTTOM"):
            base = obv[ep_start - 1] if ep_start >= 1 else 0.0
            bars = i - ep_start + 1
            live = dict(shape=ep_shape, bucket=code[i],
                        ml_score=float(score[i]) if np.isfinite(score[i]) else np.nan,
                        close=round(c[i], 2), stall_start=df.index[ep_start].date(),
                        bunched_bars=count,
                        obv_slope=round((obv[i] - base) / (vol20[i] * bars), 3)
                        if vol20[i] > 0 else np.nan,
                        stall_low=round(l[ep_start:i + 1].min(), 2),
                        breakout_close_above=round(h[ep_start] + atr[i], 2),
                        eligible=bool(elig[i]))
    shape_now = np.array([shape_at(h, l, c, atr, i) for i in range(n)], dtype=object)
    return dict(o=o, h=h, l=l, c=c, n=n, code=code, elig=elig, sig=sig, sig_shape=sig_shape,
                obv_slope=obv_slope, in_stall=in_stall, shape_now=shape_now), live


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


def run_ticker(tk, df, rng, universe):
    d, live = analyze(df)
    dates = df.index
    last_ok = d["n"] - 1 - max(HORIZONS)
    rows = []
    pool_any, pool_shape = {}, {}
    for r in range(last_ok + 1):
        if not d["elig"][r]:
            continue
        y = dates[r].year
        pool_any.setdefault(y, []).append(r)
        sh = d["shape_now"][r]
        if sh in ("PEAK", "BOTTOM") and not d["in_stall"][r]:
            pool_shape.setdefault((y, sh), []).append(r)

    def add(t, kind, shape, obv=np.nan):
        m = measure(d, t)
        if m is None:
            return
        P, row = m
        rows.append(dict(universe=universe, ticker=tk, shape=shape, kind=kind,
                         signal_date=dates[t], year=dates[t].year, entry=round(P, 2),
                         bucket=d["code"][t], obv_slope=obv, **row))

    for t in np.where(d["sig"][: last_ok + 1] & d["elig"][: last_ok + 1])[0]:
        shape = d["sig_shape"][t]
        add(t, "signal", shape, d["obv_slope"][t])
        y = dates[t].year
        for kind, pool in (("ctrl_any", pool_any.get(y)), ("ctrl_shape", pool_shape.get((y, shape)))):
            if pool:
                for _ in range(N_CTRL):
                    add(rng.choice(pool), kind, shape)
    if live:
        live.update(ticker=tk, universe=universe)
    return rows, live


def collect(folder, universe, exclude=(), seed=SEED, files=None):
    rng = random.Random(seed)
    rows, lives = [], []
    files = files if files is not None else sorted(glob.glob(os.path.join(folder, "*.csv")))
    for k, f in enumerate(files):
        tk = os.path.basename(f)[:-4]
        if tk in ETFS or tk in exclude:
            continue
        try:
            df = pd.read_csv(f, parse_dates=["Date"], index_col="Date")
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
            if len(df) < WARMUP + 40:
                continue
            r, live = run_ticker(tk, df, rng, universe)
            rows.extend(r)
            if live:
                lives.append(live)
        except Exception as ex:
            print(f"skip {tk}: {ex}")
        if (k + 1) % 200 == 0:
            print(f"{universe}: {k + 1}/{len(files)} tickers")
    return pd.DataFrame(rows), pd.DataFrame(lives)


def summarize(g):
    out = {"n": len(g)}
    for k in HORIZONS:
        out[f"ret{k}_mean"] = 100 * g[f"ret{k}"].mean()
        out[f"ret{k}_median"] = 100 * g[f"ret{k}"].median()
        out[f"win{k}_pct"] = 100 * (g[f"ret{k}"] > 0).mean()
        out[f"mfe{k}_median"] = 100 * g[f"mfe{k}"].median()
        out[f"mae{k}_mean"] = 100 * g[f"mae{k}"].mean()
    return pd.Series(out)


def report(T, L):
    cols = [f"{m}{k}" for m in ("mfe", "mae", "ret") for k in HORIZONS]
    by_shape = T.groupby(["universe", "shape", "kind"])[cols].apply(summarize).reset_index()
    by_year = T.groupby(["universe", "shape", "year", "kind"])[cols].apply(summarize).reset_index()

    S = T[T.kind == "signal"].copy()
    prim = S[(S.universe == "primary") & S.obv_slope.notna()]
    q1, q2 = prim.obv_slope.quantile([1 / 3, 2 / 3]).values
    S["obv_group"] = np.where(S.obv_slope.isna(), "na",
                     np.where(S.obv_slope <= q1, "OBV_low",
                     np.where(S.obv_slope <= q2, "OBV_mid", "OBV_high")))
    by_obv = S.groupby(["universe", "shape", "obv_group"])[cols].apply(summarize).reset_index()
    by_obv_year = S.groupby(["universe", "shape", "year", "obv_group"])[cols].apply(summarize).reset_index()

    def g(df, **kw):
        q = df
        for kk, vv in kw.items():
            q = q[q[kk] == vv]
        return q.iloc[0] if len(q) else None

    V = []
    for shape in ("PEAK", "BOTTOM"):
        s = g(by_shape, universe="primary", shape=shape, kind="signal")
        ca = g(by_shape, universe="primary", shape=shape, kind="ctrl_any")
        cs = g(by_shape, universe="primary", shape=shape, kind="ctrl_shape")
        rs = g(by_shape, universe="reference", shape=shape, kind="signal")
        ra = g(by_shape, universe="reference", shape=shape, kind="ctrl_any")
        if s is None or ca is None:
            continue
        a1 = (s.ret20_mean - ca.ret20_mean >= 1.0) and cs is not None and (s.ret20_mean - cs.ret20_mean >= 0.5)
        yrs = 0
        for y in YEARS:
            sy = g(by_year, universe="primary", shape=shape, year=y, kind="signal")
            cy = g(by_year, universe="primary", shape=shape, year=y, kind="ctrl_any")
            if sy is not None and cy is not None and sy.ret20_mean > cy.ret20_mean:
                yrs += 1
        a3 = s.ret20_median > 0
        hi = g(by_obv, universe="primary", shape=shape, obv_group="OBV_high")
        lo = g(by_obv, universe="primary", shape=shape, obv_group="OBV_low")
        rhi = g(by_obv, universe="reference", shape=shape, obv_group="OBV_high")
        rlo = g(by_obv, universe="reference", shape=shape, obv_group="OBV_low")
        b1 = hi is not None and lo is not None and hi.ret20_mean - lo.ret20_mean >= 1.0
        oy = 0
        for y in YEARS:
            hy = g(by_obv_year, universe="primary", shape=shape, year=y, obv_group="OBV_high")
            ly = g(by_obv_year, universe="primary", shape=shape, year=y, obv_group="OBV_low")
            if hy is not None and ly is not None and hy.ret20_mean > ly.ret20_mean:
                oy += 1
        b3 = rhi is not None and rlo is not None and rhi.ret20_mean > rlo.ret20_mean
        V.append(dict(
            shape=shape, signals=int(s.n),
            sig_ret20=round(s.ret20_mean, 2), sig_ret20_median=round(s.ret20_median, 2),
            any_ret20=round(ca.ret20_mean, 2), shape_ctrl_ret20=round(cs.ret20_mean, 2) if cs is not None else np.nan,
            sig_win20=round(s.win20_pct, 1), any_win20=round(ca.win20_pct, 1),
            sig_mfe5_med=round(s.mfe5_median, 2), sig_mfe10_med=round(s.mfe10_median, 2),
            sig_mfe20_med=round(s.mfe20_median, 2), sig_mae20_mean=round(s.mae20_mean, 2),
            ref_sig_ret20=round(rs.ret20_mean, 2) if rs is not None else np.nan,
            ref_any_ret20=round(ra.ret20_mean, 2) if ra is not None else np.nan,
            A1_edge=a1, A2_years_beating_any=yrs, A3_median_pos=bool(a3),
            STALL_PASS=bool(a1 and yrs >= 2 and a3),
            obv_high_ret20=round(hi.ret20_mean, 2) if hi is not None else np.nan,
            obv_low_ret20=round(lo.ret20_mean, 2) if lo is not None else np.nan,
            ref_obv_high_ret20=round(rhi.ret20_mean, 2) if rhi is not None else np.nan,
            ref_obv_low_ret20=round(rlo.ret20_mean, 2) if rlo is not None else np.nan,
            B1_obv_edge=b1, B2_obv_years=oy, B3_ref_agrees=b3,
            OBV_PASS=bool(b1 and oy >= 2 and b3)))
    V = pd.DataFrame(V)

    for col in cols:
        S[col] = (100 * S[col]).round(2)
    if len(L):
        L = L[L.eligible].copy()
        L["obv_group"] = np.where(L.obv_slope <= q1, "OBV_low",
                         np.where(L.obv_slope <= q2, "OBV_mid", "OBV_high"))
        front = ["ticker", "universe", "shape", "bucket", "ml_score", "obv_group", "obv_slope",
                 "close", "stall_low", "breakout_close_above", "stall_start", "bunched_bars"]
        L = L[front].sort_values(["shape", "obv_slope"], ascending=[True, False])

    notes = pd.DataFrame({"note": [
        "Pre registered stall entry test with OBV split. Research only, not advice.",
        f"Primary universe: daily_data_ext minus v2 overlap (out of sample). Reference: daily_data_v2. Price >= $25, 20d dollar volume >= $20M.",
        "Signal: the day a live MA stall (EMA 9/14/21 + SMA 50 within 1 ATR) reaches its 3rd bunched bar, before any breakout, shape PEAK or BOTTOM. Entry next open. One per episode.",
        f"OBV slope = OBV change since the stall began / (20d avg volume x stall bars). Tercile cutoffs from primary: {q1:.3f} and {q2:.3f}.",
        "Controls: ctrl_any random eligible day; ctrl_shape random non stall day with the same 60 bar shape. Same ticker and year.",
        "Stall pass: 20d mean beats ctrl_any by 1.0 and ctrl_shape by 0.5; beats ctrl_any in 2 of 3 years (2024 to 2026); median 20d return > 0.",
        "OBV pass: OBV_high beats OBV_low by 1.0 on 20d mean; in 2 of 3 years; reference universe same direction.",
        "Caveats: 3 years = mostly one bull regime; survivorship bias; no stops or position sizing modeled.",
    ]})

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        V.to_excel(xw, sheet_name="Verdict", index=False)
        notes.to_excel(xw, sheet_name="Notes", index=False)
        by_shape.round(2).to_excel(xw, sheet_name="ByShape", index=False)
        by_year.round(2).to_excel(xw, sheet_name="ByYear", index=False)
        by_obv.round(2).to_excel(xw, sheet_name="OBV", index=False)
        by_obv_year.round(2).to_excel(xw, sheet_name="OBV_ByYear", index=False)
        (L if len(L) else pd.DataFrame()).to_excel(xw, sheet_name="Watch", index=False)
    S.to_csv(OUT_CSV, index=False)

    pd.set_option("display.width", 250)
    print("\nVERDICT")
    print(V.T.to_string())
    print(f"\nSaved {OUT}\nSaved {OUT_CSV}")


def main():
    v2 = {os.path.basename(f)[:-4] for f in glob.glob(os.path.join(REFERENCE, "*.csv"))}
    Tp, Lp = collect(PRIMARY, "primary", exclude=v2)
    Tr, Lr = collect(REFERENCE, "reference")
    report(pd.concat([Tp, Tr], ignore_index=True), pd.concat([Lp, Lr], ignore_index=True))


if __name__ == "__main__":
    main()
