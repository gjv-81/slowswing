#!/usr/bin/env python3.12
# ============================================================================
# STOP DESIGN STUDY (v3) — fixed vs ATR-scaled vs breakeven stops
# ============================================================================
# WHY: both the model's top decile (D10) and the base-breakout setup showed
# the same disease — ~46-50% of trades hit the fixed -13/-15% stop because
# those stocks' normal 12-week noise is wider than the stop. This study asks:
# does sizing the stop to each stock's own volatility fix the economics?
#
# EXIT RULES TESTED (entry = close of signal bar, 60-trading-day horizon):
#   FIXED    : current tiered stop (-13% MEGA >= $200B, -15% others)
#   ATR2..5  : stop at k x ATR20 below entry (k = 2,3,4,5)
#   BE10_ATR3: ATR3 stop until +10% is touched, then stop moves to entry
#              (banks nothing, but kills the give-back; keeps the right tail)
#   NOSTOP   : hold the full 12 weeks (reference ceiling)
#
# FAIR COMPARISON — R-MULTIPLES: a wide stop risks more per share, so raw %
# returns flatter it. avg_R_multiple = trade return / initial stop distance
# = profit per dollar RISKED (what equal-dollar-risk position sizing earns).
#
# SUBSETS: D10 & top-quintile picks of the v2 model (recomputed walk-forward,
# out-of-sample), the base-breakout signals (>=30% off high + base + fresh
# 50-SMA cross), and all bars.
#
# HOW TO RUN (needs ml_panel_cache_v2.parquet):
#   cd ~/Documents/STS/15min
#   caffeinate -i python3.12 ml_stop_design_study.py
# First run computes price-path touches (~10-20 min), caches to
# ml_path_cache_v3.parquet; reruns take seconds.
# OUTPUT: ONE file — ml_stop_design_study.xlsx
# ============================================================================

import os, sys, glob, json, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

CFG = dict(
    data_dir    = os.path.expanduser("~/Documents/STS/15min/daily_data_10y"),
    cap_file    = os.path.expanduser("~/Documents/STS/15min/cap_cache.json"),
    panel_cache = os.path.expanduser("~/Documents/STS/15min/ml_panel_cache_v2.parquet"),
    path_cache  = os.path.expanduser("~/Documents/STS/15min/ml_path_cache_v3.parquet"),
    out_file    = os.path.expanduser("~/Documents/STS/15min/ml_stop_design_study.xlsx"),
    horizon     = 60,
    atr_mults   = [2.0, 3.0, 4.0, 5.0],
    be_target   = 0.10,          # breakeven rule arms after +10%
    be_atr_mult = 3.0,           # initial stop for the breakeven rule
    mega_cap    = 200e9, stop_mega = -0.13, stop_other = -0.15,
    purge_days  = 90, ridge_alpha = 10.0, min_train_rows = 1000,
    min_train_years = 3,
    # base-breakout definition (same as ml_base_breakout_study.py):
    depth = -0.30, sma_len = 50, cross_within = 5, base_days = 30, base_frac = 0.60,
)

STS15 = ["fisher","vwap20","ichimoku","volstop","ema921","ea34","tmo","qqe",
         "laguerre_adx","vidya","hull","supertrend_fast","supertrend_slow",
         "tdfi","waddah"]
ADD7  = ["rs_8wk","rs_4wk","high52_prox","mom_6mo","dist_200dma",
         "rel_volume","spy_regime"]
MODEL_COLS = [f"c_{k}" for k in STS15] + ADD7

GLOSSARY = [
 ("FIXED", "Current stop: -13% (MEGA, cap >= $200B) / -15% (others). Fill assumed at the stop level (gaps fill worse in reality — true for every rule)."),
 ("ATRk", "Stop placed k x ATR(20) below entry. Volatile stock -> wider stop; quiet stock -> tighter. Median ATR20 is ~2%/day, so ATR3 is roughly -6% on a quiet stock and -15%+ on a volatile one."),
 ("BE10_ATR3", "Start with an ATR3 stop. The first day the HIGH touches +10%, the stop moves to the entry price. Outcome: ATR3 loss, or 0% (round-trip back to entry), or the full 12-week return."),
 ("NOSTOP", "Hold to 12 weeks no matter what. Reference ceiling, not a recommendation."),
 ("avg_R_multiple", "Average (trade return / initial stop distance) = profit per dollar risked. THE fair metric: with equal-dollar-risk sizing, a +1R trade pays the same whether the stop was 6% or 15% away. NOSTOP shown per 15% notional risk."),
 ("stopped_%", "Share of trades that hit the initial stop (for BE10: initial ATR3 stop only; breakeven exits are counted in be_exit_%)."),
 ("Subsets", "D10 / top-quintile = out-of-sample model favorites (v2 walk-forward, recomputed identically). Base_breakout = >=30% off 52-wk high + base + fresh 50-SMA cross. All_bars = everything."),
 ("Same-day ties", "If stop and target are touched the same day, the stop wins (conservative)."),
]

# ─── path pass: per-bar touch days for ATR stops, +10%, and breakeven ───────
def path_pass(df, horizon, atr_mults, be_target):
    n = len(df)
    C = df["Close"].values
    pc = np.concatenate([[np.nan], C[:-1]])
    tr = np.nanmax(np.vstack([df["High"].values - df["Low"].values,
                              np.abs(df["High"].values - pc),
                              np.abs(df["Low"].values - pc)]), axis=0)
    atr = pd.Series(tr).ewm(span=20, adjust=False).mean().values
    atr_pct = atr / C
    lo = np.concatenate([df["Low"].values[1:],  [np.nan]])
    hi = np.concatenate([df["High"].values[1:], [np.nan]])
    cols = {f"day_atr{int(k*10)}": np.full(n, np.nan) for k in atr_mults}
    cols["day_tgt_be"] = np.full(n, np.nan)
    cols["day_be_back"] = np.full(n, np.nan)   # low<=entry AFTER +10% touch
    cols["atr_pct"] = atr_pct
    for i in range(n - 1):
        end = min(i + horizon, n - 1)
        w_lo = lo[i:end]; w_hi = hi[i:end]
        if len(w_lo) < horizon: continue
        for k in atr_mults:
            lvl = C[i] * (1 - k * atr_pct[i])
            idx = np.nonzero(w_lo <= lvl)[0]
            if len(idx): cols[f"day_atr{int(k*10)}"][i] = idx[0] + 1
        idx_t = np.nonzero(w_hi >= C[i] * (1 + be_target))[0]
        if len(idx_t):
            t = idx_t[0]
            cols["day_tgt_be"][i] = t + 1
            idx_b = np.nonzero(w_lo[t+1:] <= C[i])[0]
            if len(idx_b): cols["day_be_back"][i] = t + 1 + idx_b[0] + 1
    return pd.DataFrame(cols, index=df.index)

def load_ohlc(path):
    if path.endswith(".parquet"): df = pd.read_parquet(path)
    else:                          df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce", utc=True).tz_localize(None)
    df = df[df.index.notna()]
    cols = {c.lower().strip(): c for c in df.columns}
    if not all(k in cols for k in ["open","high","low","close"]): return None
    out = df[[cols[k] for k in ["open","high","low","close"]]].copy()
    out.columns = ["Open","High","Low","Close"]
    return out.apply(pd.to_numeric, errors="coerce").dropna().sort_index()

def breakout_flags(close):
    sma = close.rolling(CFG["sma_len"]).mean()
    below = (close < sma).astype(float)
    crossed = (close > sma) & (close.shift(1) <= sma.shift(1))
    f = pd.DataFrame(index=close.index)
    f["cross_recent"] = crossed.rolling(CFG["cross_within"]).max().fillna(0)
    f["base_ok"] = (below.shift(CFG["cross_within"])
                    .rolling(CFG["base_days"]).mean() >= CFG["base_frac"]).astype(float)
    return f

def main():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    if not os.path.exists(CFG["panel_cache"]):
        sys.exit("ERROR: run ml_weight_study_v2.py first (needs its cache).")
    print("Loading v2 panel cache ...")
    panel = pd.read_parquet(CFG["panel_cache"])
    panel["date"] = pd.to_datetime(panel["date"])

    # ── path cache (ATR stops / breakeven) + breakout flags ────────────────
    if os.path.exists(CFG["path_cache"]):
        print(f"Using cached paths {CFG['path_cache']} (delete to recompute)")
        paths = pd.read_parquet(CFG["path_cache"])
    else:
        files = {os.path.splitext(os.path.basename(f))[0].upper(): f
                 for f in sorted(glob.glob(os.path.join(CFG["data_dir"], "*.csv")) +
                                 glob.glob(os.path.join(CFG["data_dir"], "*.parquet")))}
        tickers = [t for t in panel["ticker"].unique() if t in files]
        print(f"Computing ATR-stop/breakeven touch days for {len(tickers)} tickers ...")
        frames = []
        for n, t in enumerate(tickers, 1):
            df = load_ohlc(files[t])
            if df is None: continue
            p = path_pass(df, CFG["horizon"], CFG["atr_mults"], CFG["be_target"])
            p = pd.concat([p, breakout_flags(df["Close"])], axis=1)
            p["ticker"] = t
            frames.append(p.reset_index(names="date"))
            if n % 25 == 0 or n == len(tickers): print(f"  {n}/{len(tickers)}")
        paths = pd.concat(frames, ignore_index=True)
        paths["date"] = pd.to_datetime(paths["date"])
        paths.to_parquet(CFG["path_cache"])
        print(f"Path cache written to {CFG['path_cache']}")
    panel = panel.merge(paths, on=["ticker","date"], how="left")

    # ── tiers / fixed-stop outcome ──────────────────────────────────────────
    try:
        caps = json.load(open(CFG["cap_file"]))
        tiers = {t: ("MEGA" if (v or 0) >= CFG["mega_cap"] else "LARGE")
                 for t, v in caps.items()}
    except Exception:
        tiers = {}
    panel["tier"] = panel["ticker"].map(tiers).fillna("LARGE")
    mega = panel["tier"].eq("MEGA")
    panel["day_stop_fixed"] = np.where(mega, panel["day_stop_13"], panel["day_stop_15"])
    panel["fixed_pct"] = np.where(mega, CFG["stop_mega"], CFG["stop_other"]) * 100
    panel["R_fixed"] = np.where(panel["day_stop_fixed"].notna(),
                                panel["fixed_pct"], panel["fwd_12wk"])
    panel["year"] = panel["date"].dt.year

    # ── recompute v2 walk-forward scores (identical setup) ─────────────────
    print("Recomputing v2 walk-forward model scores (out-of-sample) ...")
    years = sorted(panel["date"].dt.year.unique())
    test_years = [y for y in years if y >= years[0] + CFG["min_train_years"]]
    oos = []
    for y in test_years:
        cut = pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=CFG["purge_days"])
        tr = panel[panel["date"] < cut]
        te = panel[panel["year"] == y].copy()
        if len(tr) < CFG["min_train_rows"] or len(te) < 100: continue
        sc = StandardScaler().fit(tr[MODEL_COLS].values)
        m = Ridge(alpha=CFG["ridge_alpha"]).fit(sc.transform(tr[MODEL_COLS].values),
                                                tr["R_fixed"].values)
        te["score"] = m.predict(sc.transform(te[MODEL_COLS].values))
        te["decile"] = pd.qcut(te["score"].rank(method="first"), 10,
                               labels=[f"D{i}" for i in range(1, 11)])
        oos.append(te)
    oos = pd.concat(oos, ignore_index=True)

    bb = oos[(oos["high52_prox"] <= CFG["depth"]) &
             (oos["cross_recent"] == 1) & (oos["base_ok"] == 1)]
    subsets = {
        "D10_model_top10pct":  oos[oos["decile"] == "D10"],
        "Top_quintile_D9_D10": oos[oos["decile"].isin(["D9","D10"])],
        "Base_breakout":       bb,
        "All_OOS_bars":        oos,
    }

    # ── evaluate exit rules ─────────────────────────────────────────────────
    def eval_rules(d):
        rows = []
        fwd = d["fwd_12wk"]
        # FIXED
        risk = -d["fixed_pct"]
        R = d["R_fixed"]
        rows.append(("FIXED_13_15", R, d["day_stop_fixed"].notna(), risk, None))
        # ATR k
        for k in CFG["atr_mults"]:
            dayc = d[f"day_atr{int(k*10)}"]
            risk = 100 * k * d["atr_pct"]
            R = pd.Series(np.where(dayc.notna(), -risk, fwd), index=d.index)
            rows.append((f"ATR{int(k)}", R, dayc.notna(), risk, None))
        # BE10_ATR3
        k = CFG["be_atr_mult"]
        day_s = d[f"day_atr{int(k*10)}"]; day_t = d["day_tgt_be"]; day_b = d["day_be_back"]
        risk = 100 * k * d["atr_pct"]
        stop_first = day_s.notna() & (day_t.isna() | (day_s <= day_t))
        be_exit = ~stop_first & day_t.notna() & day_b.notna()
        R = pd.Series(np.where(stop_first, -risk,
                      np.where(be_exit, 0.0, fwd)), index=d.index)
        rows.append(("BE10_ATR3", R, stop_first, risk, be_exit))
        # NOSTOP
        rows.append(("NOSTOP", fwd, pd.Series(False, index=d.index),
                     pd.Series(15.0, index=d.index), None))
        out = []
        for name, R, stopped, risk, be in rows:
            rm = R / risk.replace(0, np.nan)
            out.append(dict(rule=name, trades=len(R),
                win_rate_pct=100*(R > 0).mean(),
                stopped_pct=100*pd.Series(stopped).mean(),
                be_exit_pct=(100*pd.Series(be).mean() if be is not None else np.nan),
                avg_R_pct=R.mean(), median_R_pct=R.median(),
                avg_R_multiple=rm.mean(), median_R_multiple=rm.median(),
                avg_risk_pct=risk.mean()))
        return pd.DataFrame(out)

    main_rows = []
    for name, sub in subsets.items():
        t = eval_rules(sub); t.insert(0, "subset", name)
        main_rows.append(t)
        print(f"  evaluated {name} ({len(sub):,} trades)")
    main_tbl = pd.concat(main_rows, ignore_index=True)

    # per-year: FIXED vs ATR3 vs BE10 on D10 and Base_breakout
    def per_year(sub):
        rows = []
        for y, d in sub.groupby("year"):
            for r in ["FIXED_13_15", "ATR3", "BE10_ATR3", "NOSTOP"]:
                e = eval_rules(d)
                e = e[e["rule"] == r].iloc[0]
                rows.append(dict(year=y, rule=r, trades=e["trades"],
                    win_rate_pct=e["win_rate_pct"], avg_R_pct=e["avg_R_pct"],
                    median_R_pct=e["median_R_pct"],
                    avg_R_multiple=e["avg_R_multiple"]))
        return pd.DataFrame(rows)
    yr_d10 = per_year(subsets["D10_model_top10pct"])
    yr_bb  = per_year(subsets["Base_breakout"]) if len(bb) > 200 else pd.DataFrame()

    gloss = pd.DataFrame(GLOSSARY, columns=["term","meaning"])
    with pd.ExcelWriter(CFG["out_file"], engine="openpyxl") as xw:
        gloss.to_excel(xw, sheet_name="README_Glossary", index=False)
        main_tbl.to_excel(xw, sheet_name="Exit_Rules_All_Subsets", index=False)
        yr_d10.to_excel(xw, sheet_name="ByYear_D10", index=False)
        if len(yr_bb): yr_bb.to_excel(xw, sheet_name="ByYear_BaseBreakout", index=False)

    print("\n" + "="*78)
    print("STOP DESIGN RESULTS (avg_R_multiple = profit per dollar risked — fair metric)")
    print("="*78)
    for name in subsets:
        print(f"\n{name}:")
        t = main_tbl[main_tbl["subset"] == name]
        for _, r in t.iterrows():
            be = f" be_exit {r['be_exit_pct']:4.1f}%" if pd.notna(r["be_exit_pct"]) else ""
            print(f"  {r['rule']:<12} win {r['win_rate_pct']:5.1f}%  stopped {r['stopped_pct']:5.1f}%{be}"
                  f"  avgR {r['avg_R_pct']:+6.2f}%  medR {r['median_R_pct']:+6.2f}%"
                  f"  R-mult avg {r['avg_R_multiple']:+.3f}")
    print("\nHOW TO READ: R-mult avg +0.20 means every $1 risked returned $0.20 on")
    print("average. Compare rules WITHIN a subset. NOSTOP R-mult uses 15% notional")
    print("risk. Stops assumed to fill at the level (gaps fill worse). Survivorship")
    print(f"bias still inflates everything.\nOutput written to: {CFG['out_file']}")

if __name__ == "__main__":
    main()
