#!/usr/bin/env python3
"""
test_sts_strategy.py
Short term STS trend continuation test (daily bars, long only).

What it tests
  The "Aggressive" daily entry from the TOS chart strategy, rebuilt so it can
  be traded live (no look ahead):
    Signal day t (evaluated at the close):
      close above the Ichimoku cloud, MACD histogram > 0, not in a TTM squeeze,
      volatility stop direction up, Williams A/D above its 57 EMA,
      close above EMA 8/34/55/89, price >= $25, 20d avg dollar volume >= $20M.
    Order for day t+1: buy stop at high[t] + $0.01.
      Fill = max(open[t+1], stop) if high[t+1] reaches the stop, else no trade.
  The chart version used high[-1] > high and open[-1] (tomorrow's bar); the
  buy stop is the honest equivalent. The repainting ZigZag exit (U1) is dropped.

Exit variants (each runs its own one-position-at-a-time state machine)
  A_script        chart exits only (cloud+vol stop break, 3 bar pattern breaks,
                  Laguerre/MACD weakness), executed next open. No stop.
  B_script_stop   A plus a 1.5 ATR protective stop.
  C_atr_5d        1.5 ATR stop, 2 ATR target, exit at close of day 5.  (main)
  D_6pct_5d       1.5 ATR stop, +6% fixed target, exit at close of day 5.
  Same day stop and target: stop is assumed first (conservative).

Controls (the key test)
  ctrl_open : random day in the same ticker and same calendar year, enter next open.
  ctrl_stop : random day in the same ticker and year whose next day breaks the
              prior high, filled with the same buy stop. Isolates the indicator
              filter from the breakout fill mechanics. PRIMARY control.
  Both controls must also pass the price and liquidity filter.

Pre committed pass rule (judged on 2022 to 2026 only, per variant)
  1. +6% within 5 days hit rate beats ctrl_stop by >= 10 points
  2. mean net return per trade > 0 and > ctrl_stop mean
  3. both 1 and 2 hold in at least 3 of the 5 test years
Design years 2016 to 2021 are for reading only; rules were frozen before running.

Caveat: daily_data_v2 holds TODAY's index members, so names that were dropped
or went bankrupt are missing (survivorship bias, flatters long strategies).

Run (on the Mac):
  cd ~/STS/15min && python3.12 test_sts_strategy.py
Output: STS_short_term_test.xlsx in the same folder.
"""
import os
import glob
import math
import random
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "daily_data_v2")
OUT = os.path.join(HERE, "STS_short_term_test.xlsx")

MIN_PRICE = 25.0
MIN_DV = 20e6
WARMUP = 130
SLIP = 0.0005            # per side
TICK = 0.01
STOP_ATR = 1.5
TGT_ATR = 2.0
FIXED_TGT = 0.06
MAX_HOLD = 5             # trading days incl. fill day
SCRIPT_CAP = 120         # safety cap for script exit variants
N_CTRL = 3
SEED = 7
DESIGN = list(range(2016, 2022))
TEST = list(range(2022, 2027))
ETFS = {"SPY", "QQQ", "IWM", "DIA", "XLC", "XLP", "XLK", "XLF", "XLE", "XLV",
        "XLI", "XLY", "XLU", "XLB", "XLRE", "SMH", "GLD", "TLT"}
VARIANTS = ["A_script", "B_script_stop", "C_atr_5d", "D_6pct_5d"]
SPOTLIGHT = ["RKLB", "META"]


# ----------------------------------------------------------------- indicators
def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def indicators(df):
    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    v = df["Volume"].values.astype(float)
    n = len(c)
    hs, ls, cs = pd.Series(h), pd.Series(l), pd.Series(c)
    cp = cs.shift(1).values

    # Ichimoku (cloud under today's bar)
    tenkan = (hs.rolling(9).max() + ls.rolling(9).min()) / 2
    kijun = (hs.rolling(26).max() + ls.rolling(26).min()) / 2
    spanA = ((tenkan + kijun) / 2).shift(26).values
    spanB = ((hs.rolling(52).max() + ls.rolling(52).min()) / 2).shift(26).values
    up_cloud = np.fmax(spanA, spanB)
    lo_cloud = np.fmin(spanA, spanB)
    ichi_up = c > up_cloud
    ichi_dn = c < lo_cloud

    # MACD 12/26/9 histogram
    e12, e26 = ema(c, 12), ema(c, 26)
    macd = e12 - e26
    hist = macd - ema(macd, 9)

    # Predicted MACD (PMACDeq vs PMACDsignal, EMA case)
    fc, sc = 2 / 13, 2 / 27
    pf = pd.Series(e12).shift(1).values
    ps = pd.Series(e26).shift(1).values
    cross = pf * fc - ps * sc
    den = fc - sc
    peq = cross / den
    prev_diff = pf - ps
    pd_ema = pd.Series(prev_diff).ewm(span=9, adjust=False, ignore_na=True).mean().values
    psig = (pd_ema - prev_diff + cross) / den

    # 9 EMA close vs 9 EMA open
    hist8 = (ema(c, 9) - ema(o, 9)) > 0

    # Volatility stop (close style, 3 x EMA10 of range)
    rng_atr = ema(h - l, 10)
    off = np.ceil(3.0 * rng_atr / TICK) * TICK
    svs, lvs = l + off, h - off
    shortvs = np.empty(n); longvs = np.empty(n); direc = np.zeros(n)
    shortvs[0], longvs[0] = svs[0], lvs[0]
    for i in range(1, n):
        shortvs[i] = svs[i] if c[i] > shortvs[i - 1] else min(svs[i], shortvs[i - 1])
        longvs[i] = lvs[i] if c[i] < longvs[i - 1] else max(lvs[i], longvs[i - 1])
        ls_ = c[i] >= shortvs[i - 1] and c[i - 1] < shortvs[i - 1]
        ss_ = c[i] <= longvs[i - 1] and c[i - 1] > longvs[i - 1]
        d = direc[i - 1]
        direc[i] = 1 if (d <= 0 and ls_) else (-1 if (d >= 0 and ss_) else d)

    # Williams A/D vs its 57 EMA
    trh = np.fmax(h, cp); trl = np.fmin(l, cp)
    ad = np.where(c > cp, c - trl, np.where(c < cp, c - trh, 0.0))
    ad[0] = 0.0
    wad = np.cumsum(ad)
    wad_ok = wad > ema(wad, 57)

    # EMA stack
    e8, e34, e55, e89 = ema(c, 8), ema(c, 34), ema(c, 55), ema(c, 89)

    # TTM squeeze off: BB(20,2) upper >= KC(20,1.5 ATR) upper
    sma20 = cs.rolling(20).mean().values
    sd20 = cs.rolling(20).std(ddof=0).values
    tr = np.fmax(h, cp) - np.fmin(l, cp)
    tr[0] = h[0] - l[0]
    atr20 = pd.Series(tr).rolling(20).mean().values
    sq_off = (sma20 + 2.0 * sd20) >= (sma20 + 1.5 * atr20)

    # Laguerre RSI with fractal energy gamma
    nfe = 13
    s13 = pd.Series(tr).rolling(nfe).sum().values
    span13 = hs.rolling(nfe).max().values - ls.rolling(nfe).min().values
    with np.errstate(divide="ignore", invalid="ignore"):
        gamma = np.log(s13 / span13) / math.log(nfe)
    o_m = (o + cp) / 2
    c_m = (o_m + trh + trl + c) / 4
    rsi = np.full(n, np.nan)
    L0 = L1 = L2 = L3 = None
    for i in range(1, n):
        g = gamma[i]
        if not np.isfinite(g) or not np.isfinite(c_m[i]):
            continue
        if L0 is None:
            L0 = L1 = L2 = L3 = c_m[i]
            continue
        n0 = (1 - g) * c_m[i] + g * L0
        n1 = -g * n0 + L0 + g * L1
        n2 = -g * n1 + L1 + g * L2
        n3 = -g * n2 + L2 + g * L3
        L0, L1, L2, L3 = n0, n1, n2, n3
        cu = max(L0 - L1, 0) + max(L1 - L2, 0) + max(L2 - L3, 0)
        cd = max(L1 - L0, 0) + max(L2 - L1, 0) + max(L3 - L2, 0)
        rsi[i] = cu / (cu + cd) if (cu + cd) != 0 else 0.0
    rsi_weak = rsi < gamma

    # ATR14 Wilder for stops and targets
    atr14 = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().values
    dv20 = pd.Series(c * v).rolling(20).mean().values

    idx = np.arange(n)
    eligible = (c >= MIN_PRICE) & (dv20 >= MIN_DV) & (idx >= WARMUP)

    entry = (ichi_up & (hist > 0) & sq_off & (direc > 0) & wad_ok &
             (c > e8) & (c > e34) & (c > e55) & (c > e89) & eligible)

    # Script exits (no U1)
    h1, h2, h3, h4 = (pd.Series(h).shift(k).values for k in (1, 2, 3, 4))
    l1, l2 = pd.Series(l).shift(1).values, pd.Series(l).shift(2).values
    pat1 = (h1 > h2) & (h2 > h3) & (h3 > h4) & (c < l1)
    pat2 = (h1 <= h2) & (l1 >= l2) & (c < l1)
    pat3 = (h > h1) & (l < l1) & (c < l1)
    weak = (~hist8) & rsi_weak
    exA = ichi_dn & (direc < 0)
    exB = (pat1 | pat2 | pat3) & weak
    exC = weak & (peq < psig)
    exit_sig = exA | exB | exC

    return dict(o=o, h=h, l=l, c=c, atr=atr14, entry=entry, exit_sig=exit_sig,
                eligible=eligible, n=n)


# ---------------------------------------------------------------- simulation
def simulate(d, e, P, A, variant):
    """Trade filled on bar e at price P; A = ATR14 of signal bar. Returns
    (exit_bar, exit_price, reason)."""
    o, h, l, c, n = d["o"], d["h"], d["l"], d["c"], d["n"]
    use_stop = variant != "A_script"
    stop = P - STOP_ATR * A
    if variant == "C_atr_5d":
        tgt = P + TGT_ATR * A
    elif variant == "D_6pct_5d":
        tgt = P * (1 + FIXED_TGT)
    else:
        tgt = None
    script = variant in ("A_script", "B_script_stop")
    last = min(n - 1, e + (SCRIPT_CAP if script else MAX_HOLD) - 1)
    pending_open_exit = False
    for i in range(e, last + 1):
        if pending_open_exit:
            return i, o[i], "script_exit"
        first = i == e
        if use_stop:
            if not first and o[i] <= stop:
                return i, o[i], "stop_gap"
            if l[i] <= stop:
                return i, stop, "stop"
        if tgt is not None:
            if not first and o[i] >= tgt:
                return i, o[i], "target_gap"
            if h[i] >= tgt:
                return i, tgt, "target"
        if script and d["exit_sig"][i]:
            pending_open_exit = True
    if pending_open_exit and last + 1 < n:
        return last + 1, o[last + 1], "script_exit"
    if last == n - 1 and (script or last < e + MAX_HOLD - 1):
        return last, c[last], "open_at_end"
    return last, c[last], "time" if not script else "cap"


def entry_stats(d, e, P, A):
    h, l = d["h"], d["l"]
    j = min(d["n"], e + MAX_HOLD)
    mfe = h[e:j].max() / P - 1
    mae = l[e:j].min() / P - 1
    return mfe, mae, mfe >= FIXED_TGT, h[e:j].max() >= P + TGT_ATR * A


def record(tk, dates, d, t, e, P, A, variant, kind):
    xb, xp, why = simulate(d, e, P, A, variant)
    mfe, mae, hit6, hit2 = entry_stats(d, e, P, A)
    ret = (xp * (1 - SLIP)) / (P * (1 + SLIP)) - 1
    return dict(ticker=tk, kind=kind, variant=variant, signal_date=dates[t],
                year=dates[t].year, fill_date=dates[e], fill=round(P, 2),
                exit_date=dates[xb], exit=round(xp, 2), reason=why,
                hold_days=xb - e + 1, ret=ret, mfe5=mfe, mae5=mae,
                hit6_5d=hit6, hit2atr_5d=hit2, atr_pct=A / P)


def run_ticker(tk, df, rng):
    d = indicators(df)
    dates = df.index
    n = d["n"]
    o, h = d["o"], d["h"]
    out = []
    # control pools per year
    elig = np.where(d["eligible"][: n - 1])[0]
    pool_open, pool_stop = {}, {}
    for r in elig:
        if r + 1 >= n:
            continue
        y = dates[r].year
        pool_open.setdefault(y, []).append(r)
        if h[r + 1] >= h[r] + TICK:
            pool_stop.setdefault(y, []).append(r)
    cands = np.where(d["entry"][: n - 1])[0]
    for variant in VARIANTS:
        free_from = 0
        for t in cands:
            if t < free_from:
                continue
            e = t + 1
            stop_px = h[t] + TICK
            if h[e] < stop_px:
                continue
            P = max(o[e], stop_px)
            A = d["atr"][t]
            rec = record(tk, dates, d, t, e, P, A, variant, "signal")
            out.append(rec)
            xb = dates.get_loc(rec["exit_date"])
            free_from = xb  # flat by the close of the exit bar; can signal again that evening
            y = dates[t].year
            for _ in range(N_CTRL):
                if pool_open.get(y):
                    r = rng.choice(pool_open[y])
                    out.append(record(tk, dates, d, r, r + 1, o[r + 1], d["atr"][r], variant, "ctrl_open"))
                if pool_stop.get(y):
                    r = rng.choice(pool_stop[y])
                    Pr = max(o[r + 1], h[r] + TICK)
                    out.append(record(tk, dates, d, r, r + 1, Pr, d["atr"][r], variant, "ctrl_stop"))
    return out


# ------------------------------------------------------------------ summaries
def summarize(g):
    r = g["ret"]
    w, lo = r[r > 0], r[r <= 0]
    return pd.Series({
        "trades": len(g),
        "win_pct": 100 * (r > 0).mean(),
        "mean_ret_pct": 100 * r.mean(),
        "median_ret_pct": 100 * r.median(),
        "avg_win_pct": 100 * w.mean() if len(w) else np.nan,
        "avg_loss_pct": 100 * lo.mean() if len(lo) else np.nan,
        "win_loss_ratio": (w.mean() / -lo.mean()) if len(w) and len(lo) and lo.mean() < 0 else np.nan,
        "avg_hold_days": g["hold_days"].mean(),
        "hit6_5d_pct": 100 * g["hit6_5d"].mean(),
        "hit2atr_5d_pct": 100 * g["hit2atr_5d"].mean(),
        "mfe5_mean_pct": 100 * g["mfe5"].mean(),
        "mae5_mean_pct": 100 * g["mae5"].mean(),
    })


def collect(files, seed=SEED):
    rng = random.Random(seed)
    rows = []
    for k, f in enumerate(files):
        tk = os.path.basename(f)[:-4]
        if tk in ETFS:
            continue
        try:
            df = pd.read_csv(f, parse_dates=["Date"], index_col="Date")
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df = df[(df["High"] > 0) & (df["Low"] > 0)]
            if len(df) < WARMUP + 20:
                continue
            rows.extend(run_ticker(tk, df, rng))
        except Exception as ex:  # keep going on a bad file
            print(f"skip {tk}: {ex}")
        if (k + 1) % 100 == 0:
            print(f"{k + 1}/{len(files)} tickers")
    return rows


def report(T):
    T["period"] = np.where(T["year"].isin(TEST), "test_2022_2026",
                   np.where(T["year"].isin(DESIGN), "design_2016_2021", "other"))

    cols = ["ret", "hold_days", "hit6_5d", "hit2atr_5d", "mfe5", "mae5"]
    by_period = T.groupby(["variant", "period", "kind"])[cols].apply(summarize).reset_index()
    by_year = T.groupby(["variant", "year", "kind"])[cols].apply(summarize).reset_index()
    reasons = (T[T.kind == "signal"].groupby(["variant", "reason"]).size()
               .rename("count").reset_index())

    # verdict
    verdict = []
    for v in VARIANTS:
        def get(df, kind, **kw):
            q = df[(df.variant == v) & (df.kind == kind)]
            for kk, vv in kw.items():
                q = q[q[kk] == vv]
            return q.iloc[0] if len(q) else None
        s = get(by_period, "signal", period="test_2022_2026")
        cs = get(by_period, "ctrl_stop", period="test_2022_2026")
        co = get(by_period, "ctrl_open", period="test_2022_2026")
        if s is None or cs is None:
            continue
        c1 = s.hit6_5d_pct - cs.hit6_5d_pct >= 10
        c2 = s.mean_ret_pct > 0 and s.mean_ret_pct > cs.mean_ret_pct
        yrs_ok = 0
        for y in TEST:
            sy = get(by_year, "signal", year=y)
            cy = get(by_year, "ctrl_stop", year=y)
            if sy is not None and cy is not None:
                if (sy.hit6_5d_pct - cy.hit6_5d_pct >= 10) and sy.mean_ret_pct > 0 and sy.mean_ret_pct > cy.mean_ret_pct:
                    yrs_ok += 1
        verdict.append(dict(
            variant=v, test_trades=int(s.trades),
            sig_hit6_pct=round(s.hit6_5d_pct, 1), ctrl_stop_hit6_pct=round(cs.hit6_5d_pct, 1),
            ctrl_open_hit6_pct=round(co.hit6_5d_pct, 1) if co is not None else np.nan,
            hit6_edge_pts=round(s.hit6_5d_pct - cs.hit6_5d_pct, 1),
            sig_mean_ret_pct=round(s.mean_ret_pct, 2), ctrl_stop_mean_ret_pct=round(cs.mean_ret_pct, 2),
            ctrl_open_mean_ret_pct=round(co.mean_ret_pct, 2) if co is not None else np.nan,
            sig_win_pct=round(s.win_pct, 1), sig_win_loss_ratio=round(s.win_loss_ratio, 2),
            rule1_hit_edge_10pts=c1, rule2_expectancy=c2, test_years_passing=yrs_ok,
            rule3_3of5_years=yrs_ok >= 3, PASS=bool(c1 and c2 and yrs_ok >= 3)))
    V = pd.DataFrame(verdict)

    trades = T[T.kind == "signal"].copy()
    spot = trades[trades.ticker.isin(SPOTLIGHT) & (trades.year >= 2025)].sort_values(["ticker", "variant", "signal_date"])
    for df_ in (trades, spot):
        for col in ("ret", "mfe5", "mae5", "atr_pct"):
            df_[col] = (100 * df_[col]).round(2)

    notes = pd.DataFrame({"note": [
        "Short term STS trend continuation test, daily bars, long only.",
        "Universe: daily_data_v2 (S&P 500 + S&P 400 + watchlist), ETFs removed, price >= $25 and 20 day dollar volume >= $20M on the signal day.",
        "Entry: chart Aggressive conditions at the close, then a buy stop at the signal day high + 1 cent for the next day. No look ahead.",
        "Exits: A = chart exits (no ZigZag U1), B = A plus 1.5 ATR stop, C = 1.5 ATR stop / 2 ATR target / 5 days, D = 1.5 ATR stop / +6% / 5 days.",
        "Costs: 0.05% slippage per side. Same bar stop and target counted as a stop.",
        "Controls: ctrl_open = random day same ticker same year, buy next open. ctrl_stop = random day same ticker same year whose next day breaks the high, same buy stop fill (primary).",
        "Pass rule (test years 2022 to 2026): hit +6% in 5 days beats ctrl_stop by 10+ points, mean net return > 0 and above ctrl_stop, both true in 3 of 5 test years.",
        "Survivorship bias: the folder holds today's index members, so dropped and bankrupt names are missing. Results for long strategies are flattered.",
        "2026 is a partial year. Returns are per trade, not compounded, and ignore position sizing.",
    ]})

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        V.to_excel(xw, sheet_name="Verdict", index=False)
        notes.to_excel(xw, sheet_name="Notes", index=False)
        by_period.round(2).to_excel(xw, sheet_name="ByPeriod", index=False)
        by_year.round(2).to_excel(xw, sheet_name="ByYear", index=False)
        reasons.to_excel(xw, sheet_name="ExitReasons", index=False)
        spot.to_excel(xw, sheet_name="RKLB_META_2025_26", index=False)
        trades.sort_values("signal_date").to_excel(xw, sheet_name="Trades", index=False)

    pd.set_option("display.width", 200)
    print("\nVERDICT (test years 2022 to 2026)")
    print(V.to_string(index=False))
    print(f"\nSaved {OUT}")


def main():
    files = sorted(glob.glob(os.path.join(DATA, "*.csv")))
    report(pd.DataFrame(collect(files)))


if __name__ == "__main__":
    main()
