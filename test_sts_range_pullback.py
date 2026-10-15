#!/usr/bin/env python3
"""
test_sts_range_pullback.py
Short term STS research: RANGE REVERSION and PULLBACK IN UPTREND (daily bars, long only).

SETUPS (evaluated at the close of signal day t, rules frozen before running)
  R     Range bottom. Last 30 bars form a range: (30d high - 30d low) <= 6 ATR and the
        20 SMA moved <= 1 ATR over the last 10 bars (flat). Close sits in the bottom
        25% of that range.
  R200  Same as R, plus close above the 200 SMA (range inside a long term uptrend).
  P1    Short pullback in uptrend: close > 200 SMA, 50 SMA > 200 SMA, 2 period RSI < 10.
  P2    Pullback to the 20 EMA: close > 200 SMA, 50 SMA > 200 SMA and rising (vs 10 bars
        ago), today's low touched the 20 EMA, close above the 50 SMA, and the highest
        close of the prior 10 bars was >= 20 EMA + 1.5 ATR (it was extended, then pulled in).
  C     Moving average confluence breakout: on at least 5 of the prior 10 bars the
        EMA 9/14/21 and SMA 50 were bunched within 1 ATR (the stall), and today the
        close is > 0.5 ATR above the highest of them AND above the prior 10 day high.
  All: price >= $25, 20 day avg dollar volume >= $20M, 220 bars of history.

ENTRIES
  open  buy at next day's open (first move).
  stop  buy stop at signal high + $0.01 next day only (waits for the turn, the
        "second move"). If not filled, the setup can retrigger the next day.

EXITS (protective stop 1.5 ATR, volatility scaled target, time limit)
  X5   2 ATR target, close of day 5
  X10  3 ATR target, close of day 10
  Same bar stop and target counts as stop. Gaps fill at the open. 0.05% slip per side.

20 variants = 5 setups x 2 entries x 2 exits, one position at a time per ticker.

CONTROLS (same ticker, same calendar year, same entry mechanic, same exits)
  ctrl_any      random eligible day.
  ctrl_context  random day in the same SITUATION but not the trigger:
                R = in a range (any position), R200 = in a range above the 200,
                P1/P2 = in the uptrend, C = inside a stall that did not break out today. Tells us if the entry POINT adds edge
                beyond just being in that situation. PRIMARY control.

PRE COMMITTED PASS RULE (per variant)
  1. Test years 2022 to 2026: mean net return > 0, and beats BOTH controls by >= 0.30
     points per trade.
  2. Beats ctrl_context in at least 3 of the 5 test years.
  3. Design years 2016 to 2021: also beats ctrl_context (same direction).
  With 20 variants, about 1 could pass by luck; a real edge should show up in
  several related variants, not one.

CAVEAT: daily_data_v2 = today's index members (survivorship bias, flatters longs).

Run on the Mac:
  cd ~/STS/15min && python3.12 test_sts_range_pullback.py
Output: STS_range_pullback_test.xlsx (Verdict, Notes, ByPeriod, ByYear, Today,
        Spotlight) plus STS_range_pullback_trades.csv (every signal trade).
"""
import os
import glob
import random
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "daily_data_v2")
OUT = os.path.join(HERE, "STS_range_pullback_test.xlsx")
OUT_CSV = os.path.join(HERE, "STS_range_pullback_trades.csv")

MIN_PRICE, MIN_DV, WARMUP = 25.0, 20e6, 220
SLIP, TICK = 0.0005, 0.01
STOP_ATR = 1.5
EXITS = {"X5": (2.0, 5), "X10": (3.0, 10)}
SETUPS = ["R", "R200", "P1", "P2", "C"]
ENTRIES = ["open", "stop"]
N_CTRL = 2
SEED = 11
DESIGN = list(range(2016, 2022))
TEST = list(range(2022, 2027))
EDGE_MIN = 0.30
ETFS = {"SPY", "QQQ", "IWM", "DIA", "XLC", "XLP", "XLK", "XLF", "XLE", "XLV",
        "XLI", "XLY", "XLU", "XLB", "XLRE", "SMH", "GLD", "TLT"}
SPOTLIGHT = ["RKLB", "LRCX", "META", "CRM"]
VARIANTS = [(s, e, x) for s in SETUPS for e in ENTRIES for x in EXITS]


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def wilder_rsi(c, n):
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().values
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = up / dn
    return np.where(dn == 0, 100.0, 100 - 100 / (1 + rs))


def features(df):
    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    v = df["Volume"].values.astype(float)
    n = len(c)
    cs = pd.Series(c)
    cp = cs.shift(1).values
    tr = np.fmax(h, cp) - np.fmin(l, cp)
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().values
    sma20 = cs.rolling(20).mean().values
    sma50 = cs.rolling(50).mean().values
    sma200 = cs.rolling(200).mean().values
    e20 = ema(c, 20)
    dv20 = pd.Series(c * v).rolling(20).mean().values
    hh30 = pd.Series(h).rolling(30).max().values
    ll30 = pd.Series(l).rolling(30).min().values
    width = hh30 - ll30
    with np.errstate(divide="ignore", invalid="ignore"):
        pos = (c - ll30) / width
    sma20_10 = pd.Series(sma20).shift(10).values
    sma50_10 = pd.Series(sma50).shift(10).values
    rsi2 = wilder_rsi(c, 2)
    prior_max_close10 = cs.shift(1).rolling(10).max().values
    mas = np.vstack([ema(c, 9), ema(c, 14), ema(c, 21), sma50])
    ma_top = mas.max(axis=0)
    with np.errstate(invalid="ignore"):
        bunched = ((ma_top - mas.min(axis=0)) <= 1.0 * atr).astype(float)
    stall = pd.Series(bunched).shift(1).rolling(10).sum().values >= 5
    prior_hh10 = pd.Series(h).shift(1).rolling(10).max().values

    idx = np.arange(n)
    elig = (c >= MIN_PRICE) & (dv20 >= MIN_DV) & (idx >= WARMUP) & np.isfinite(sma200)

    in_range = (width <= 6 * atr) & (np.abs(sma20 - sma20_10) <= 1.0 * atr)
    uptrend = (c > sma200) & (sma50 > sma200)

    trig = {
        "R": in_range & (pos <= 0.25),
        "R200": in_range & (pos <= 0.25) & (c > sma200),
        "P1": uptrend & (rsi2 < 10),
        "P2": uptrend & (sma50 > sma50_10) & (l <= e20) & (c > sma50) &
              (prior_max_close10 >= e20 + 1.5 * atr),
        "C": stall & (c > ma_top + 0.5 * atr) & (c > prior_hh10),
    }
    ctx = {"R": in_range, "R200": in_range & (c > sma200), "P1": uptrend,
           "P2": uptrend & (sma50 > sma50_10), "C": stall}
    trig = {k: v_ & elig for k, v_ in trig.items()}
    ctx = {k: v_ & elig for k, v_ in ctx.items()}

    status = dict(close=c[-1], atr=atr[-1], atr_pct=100 * atr[-1] / c[-1],
                  range_low_30d=ll30[-1], range_high_30d=hh30[-1],
                  range_width_atr=width[-1] / atr[-1], pos_in_range_pct=100 * pos[-1],
                  sma20_drift_atr=(sma20[-1] - sma20_10[-1]) / atr[-1],
                  above_200=c[-1] > sma200[-1], sma50_gt_200=sma50[-1] > sma200[-1],
                  rsi2=rsi2[-1], ema20=e20[-1], buy_stop_tomorrow=h[-1] + TICK,
                  eligible=bool(elig[-1]),
                  **{f"setup_{k}": bool(trig[k][-1]) for k in SETUPS})
    return dict(o=o, h=h, l=l, c=c, atr=atr, n=n, elig=elig, trig=trig, ctx=ctx), status


def fill_for(d, t, entry):
    e = t + 1
    if e >= d["n"]:
        return None
    if entry == "open":
        return d["o"][e]
    stop_px = d["h"][t] + TICK
    if d["h"][e] < stop_px:
        return None
    return max(d["o"][e], stop_px)


def simulate(d, e, P, A, exit_key):
    o, h, l, c, n = d["o"], d["h"], d["l"], d["c"], d["n"]
    tgt_atr, hold = EXITS[exit_key]
    stop, tgt = P - STOP_ATR * A, P + tgt_atr * A
    last = min(n - 1, e + hold - 1)
    for i in range(e, last + 1):
        first = i == e
        if not first and o[i] <= stop:
            return i, o[i], "stop_gap"
        if l[i] <= stop:
            return i, stop, "stop"
        if not first and o[i] >= tgt:
            return i, o[i], "target_gap"
        if h[i] >= tgt:
            return i, tgt, "target"
    return last, c[last], ("time" if last == e + hold - 1 else "open_at_end")


def trade_row(tk, dates, d, t, e, P, A, setup, entry, exit_key, kind):
    xb, xp, why = simulate(d, e, P, A, exit_key)
    j5 = min(d["n"], e + 5)
    mfe5 = d["h"][e:j5].max() / P - 1
    ret = (xp * (1 - SLIP)) / (P * (1 + SLIP)) - 1
    return (tk, setup, entry, exit_key, kind, dates[t], dates[t].year, dates[e],
            round(P, 2), dates[xb], round(xp, 2), why, xb - e + 1, ret,
            mfe5 >= 0.06, why in ("target", "target_gap"))


COLS = ["ticker", "setup", "entry", "exit", "kind", "signal_date", "year", "fill_date",
        "fill", "exit_date", "exit_px", "reason", "hold_days", "ret", "hit6_5d", "hit_target"]


def run_ticker(tk, df, rng):
    d, status = features(df)
    dates = df.index
    n = d["n"]
    rows = []
    ctx_pool, any_pool = {}, {}
    elig_idx = np.where(d["elig"][: n - 1])[0]
    for r in elig_idx:
        any_pool.setdefault(dates[r].year, []).append(r)
    for s in SETUPS:
        pool = {}
        for r in np.where(d["ctx"][s][: n - 1] & ~d["trig"][s][: n - 1])[0]:
            pool.setdefault(dates[r].year, []).append(r)
        ctx_pool[s] = pool
    for setup, entry, exit_key in VARIANTS:
        cands = np.where(d["trig"][setup][: n - 1])[0]
        free_from = 0
        for t in cands:
            if t < free_from:
                continue
            P = fill_for(d, t, entry)
            if P is None:
                continue
            e = t + 1
            row = trade_row(tk, dates, d, t, e, P, d["atr"][t], setup, entry, exit_key, "signal")
            rows.append(row)
            free_from = dates.get_loc(row[9])
            y = dates[t].year
            for kind, pools in (("ctrl_any", any_pool), ("ctrl_context", ctx_pool[setup])):
                cand = pools.get(y)
                if not cand:
                    continue
                got, tries = 0, 0
                while got < N_CTRL and tries < 20:
                    tries += 1
                    r = rng.choice(cand)
                    Pr = fill_for(d, r, entry)
                    if Pr is None:
                        continue
                    rows.append(trade_row(tk, dates, d, r, r + 1, Pr, d["atr"][r],
                                          setup, entry, exit_key, kind))
                    got += 1
    out = pd.DataFrame(rows, columns=COLS)
    if len(out):
        for col in ("setup", "entry", "exit", "kind", "reason", "ticker"):
            out[col] = out[col].astype("category")
        out["ret"] = out["ret"].astype("float32")
    status["ticker"] = tk
    status["last_date"] = dates[-1].date()
    return out, status


def collect(files, seed=SEED):
    rng = random.Random(seed)
    parts, stats = [], []
    for k, f in enumerate(files):
        tk = os.path.basename(f)[:-4]
        if tk in ETFS:
            continue
        try:
            df = pd.read_csv(f, parse_dates=["Date"], index_col="Date")
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
            if len(df) < WARMUP + 20:
                continue
            p, s = run_ticker(tk, df, rng)
            if len(p):
                parts.append(p)
            stats.append(s)
        except Exception as ex:
            print(f"skip {tk}: {ex}")
        if (k + 1) % 100 == 0:
            print(f"{k + 1}/{len(files)} tickers")
    T = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)
    return T, pd.DataFrame(stats)


def summarize(g):
    r = g["ret"].astype(float)
    w, lo = r[r > 0], r[r <= 0]
    return pd.Series({
        "trades": len(g),
        "win_pct": 100 * (r > 0).mean(),
        "mean_ret_pct": 100 * r.mean(),
        "median_ret_pct": 100 * r.median(),
        "avg_win_pct": 100 * w.mean() if len(w) else np.nan,
        "avg_loss_pct": 100 * lo.mean() if len(lo) else np.nan,
        "target_hit_pct": 100 * g["hit_target"].mean(),
        "hit6_5d_pct": 100 * g["hit6_5d"].mean(),
        "avg_hold_days": g["hold_days"].mean(),
    })


def report(T, S):
    for col in ("setup", "entry", "exit", "kind", "reason", "ticker"):
        T[col] = T[col].astype(str)
    T["period"] = np.where(T["year"].isin(TEST), "test_2022_2026",
                   np.where(T["year"].isin(DESIGN), "design_2016_2021", "other"))
    keys = ["setup", "entry", "exit"]
    cols = ["ret", "hit_target", "hit6_5d", "hold_days"]
    by_period = T.groupby(keys + ["period", "kind"])[cols].apply(summarize).reset_index()
    by_year = T.groupby(keys + ["year", "kind"])[cols].apply(summarize).reset_index()

    def m(df, setup, entry, ex, kind, **kw):
        q = df[(df.setup == setup) & (df.entry == entry) & (df.exit == ex) & (df.kind == kind)]
        for kk, vv in kw.items():
            q = q[q[kk] == vv]
        return q.iloc[0] if len(q) else None

    V = []
    for setup, entry, ex in VARIANTS:
        s = m(by_period, setup, entry, ex, "signal", period="test_2022_2026")
        ca = m(by_period, setup, entry, ex, "ctrl_any", period="test_2022_2026")
        cc = m(by_period, setup, entry, ex, "ctrl_context", period="test_2022_2026")
        sd = m(by_period, setup, entry, ex, "signal", period="design_2016_2021")
        cd = m(by_period, setup, entry, ex, "ctrl_context", period="design_2016_2021")
        if s is None or ca is None or cc is None:
            continue
        r1 = (s.mean_ret_pct > 0 and s.mean_ret_pct - ca.mean_ret_pct >= EDGE_MIN
              and s.mean_ret_pct - cc.mean_ret_pct >= EDGE_MIN)
        yrs = 0
        for y in TEST:
            sy = m(by_year, setup, entry, ex, "signal", year=y)
            cy = m(by_year, setup, entry, ex, "ctrl_context", year=y)
            if sy is not None and cy is not None and sy.mean_ret_pct > cy.mean_ret_pct:
                yrs += 1
        r3 = sd is not None and cd is not None and sd.mean_ret_pct > cd.mean_ret_pct
        V.append(dict(
            setup=setup, entry=entry, exit=ex, test_trades=int(s.trades),
            sig_mean_pct=round(s.mean_ret_pct, 2),
            ctx_mean_pct=round(cc.mean_ret_pct, 2), any_mean_pct=round(ca.mean_ret_pct, 2),
            edge_vs_ctx=round(s.mean_ret_pct - cc.mean_ret_pct, 2),
            edge_vs_any=round(s.mean_ret_pct - ca.mean_ret_pct, 2),
            sig_win_pct=round(s.win_pct, 1), sig_target_hit_pct=round(s.target_hit_pct, 1),
            ctx_target_hit_pct=round(cc.target_hit_pct, 1),
            sig_avg_win=round(s.avg_win_pct, 2), sig_avg_loss=round(s.avg_loss_pct, 2),
            design_sig_mean=round(sd.mean_ret_pct, 2) if sd is not None else np.nan,
            design_ctx_mean=round(cd.mean_ret_pct, 2) if cd is not None else np.nan,
            rule1_test_edge=r1, test_years_beating_ctx=yrs, rule2_3of5=yrs >= 3,
            rule3_design_agrees=r3, PASS=bool(r1 and yrs >= 3 and r3)))
    V = pd.DataFrame(V)

    sig = T[T.kind == "signal"].copy()
    sig["ret_pct"] = (100 * sig["ret"].astype(float)).round(2)
    spot = sig[sig.ticker.isin(SPOTLIGHT) & (sig.year >= 2025)].drop(columns=["ret"])
    spot = spot.sort_values(["ticker", "setup", "entry", "exit", "signal_date"])

    S = S.copy()
    flag_cols = [f"setup_{k}" for k in SETUPS]
    today = S[S[flag_cols].any(axis=1) | S.ticker.isin(SPOTLIGHT)].copy()
    today["spotlight"] = today.ticker.isin(SPOTLIGHT)
    today = today.sort_values(["spotlight", "ticker"], ascending=[False, True])
    num = today.select_dtypes("number").columns
    today[num] = today[num].round(2)
    front = ["ticker", "last_date", "spotlight"] + flag_cols
    today = today[front + [c for c in today.columns if c not in front]]

    notes = pd.DataFrame({"note": [
        "Range reversion and pullback in uptrend, daily bars, long only. Research only, not advice.",
        "R = bottom 25% of a flat 30 day range (width <= 6 ATR, 20 SMA drift <= 1 ATR over 10 bars). R200 = same, above the 200 SMA.",
        "P1 = uptrend (close > 200 SMA, 50 > 200) and 2 period RSI < 10. P2 = uptrend with rising 50, low touches 20 EMA after being 1.5 ATR above it, close above the 50.",
        "Entry open = next open. Entry stop = buy stop at signal high + 1 cent next day (waits for the turn).",
        "Exits: 1.5 ATR stop always. X5 = 2 ATR target or close of day 5. X10 = 3 ATR target or close of day 10. 0.05% slip per side.",
        "ctrl_any = random eligible day, same ticker and year. ctrl_context = random day in the same situation (in range / in uptrend) that is NOT a trigger day. Same entry and exits.",
        "Pass rule: test years mean > 0 and beats both controls by 0.30 pts; beats ctrl_context in 3 of 5 test years; design years agree.",
        "C = moving average confluence breakout: EMA 9/14/21 and SMA 50 within 1 ATR on 5 of the prior 10 bars, then a close > 0.5 ATR above the top average and above the prior 10 day high.",
        "20 variants were tested, so one lucky pass is expected. Trust a pattern across related variants, not one row.",
        "Survivorship bias: today's index members only. 2026 is a partial year. Today sheet = setups on the latest bar (research flags, not trade instructions).",
    ]})

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        V.to_excel(xw, sheet_name="Verdict", index=False)
        notes.to_excel(xw, sheet_name="Notes", index=False)
        by_period.round(2).to_excel(xw, sheet_name="ByPeriod", index=False)
        by_year.round(2).to_excel(xw, sheet_name="ByYear", index=False)
        today.to_excel(xw, sheet_name="Today", index=False)
        spot.to_excel(xw, sheet_name="Spotlight", index=False)
    sig.drop(columns=["ret"]).to_csv(OUT_CSV, index=False)

    pd.set_option("display.width", 250)
    print("\nVERDICT (test years 2022 to 2026)")
    print(V.to_string(index=False))
    print(f"\nSaved {OUT}\nSaved {OUT_CSV}")


def main():
    files = sorted(glob.glob(os.path.join(DATA, "*.csv")))
    T, S = collect(files)
    report(T, S)


if __name__ == "__main__":
    main()
