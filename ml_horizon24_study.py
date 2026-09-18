#!/usr/bin/env python3.12
# ============================================================================
# HORIZON STUDY — 12-week vs 24-week holds, same entries, same rules
# ============================================================================
# QUESTION: your UTS exit sweep showed profit factor still climbing at
# 12-week holds. Does holding 24 weeks keep paying, or does mean reversion
# set in? And is the extra return worth tying capital up twice as long?
#
# METHOD: one path pass over raw prices computes, for every entry bar,
# first-touch days for stops within 120 trading days AND the 12- and
# 24-week outcomes. Both horizons are then evaluated on the IDENTICAL set
# of entry bars (only bars with a full 24-week future are used), so the
# comparison is exact. Model scores (D10 etc.) are recomputed exactly as in
# v3 — trained on the 12-week stop-adjusted target, so "D10" means the same
# stocks as before.
#
# KEY METRIC: avg_R_per_week = average return / weeks held. Capital
# efficiency: a 24-week hold must roughly DOUBLE the 12-week return to be
# worth it, because the same capital could run two 12-week trades back to
# back. Also reported: a second model TRAINED on the 24-week target, to see
# whether the indicator weights change at the longer horizon.
#
# HOW TO RUN (needs ml_panel_cache_v2.parquet):
#   cd ~/Documents/STS/15min
#   caffeinate -i python3.12 ml_horizon24_study.py
# First run ~15-25 min (OHLC path pass), cached to ml_path_cache_24wk.parquet.
# OUTPUT: ONE file — ml_horizon24_study.xlsx
# ============================================================================

import os, sys, glob, json, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

CFG = dict(
    data_dir    = os.path.expanduser("~/Documents/STS/15min/daily_data_10y"),
    cap_file    = os.path.expanduser("~/Documents/STS/15min/cap_cache.json"),
    panel_cache = os.path.expanduser("~/Documents/STS/15min/ml_panel_cache_v2.parquet"),
    path_cache  = os.path.expanduser("~/Documents/STS/15min/ml_path_cache_24wk.parquet"),
    out_file    = os.path.expanduser("~/Documents/STS/15min/ml_horizon24_study.xlsx"),
    h12 = 60, h24 = 120,
    atr_mults   = [3.0, 5.0],
    mega_cap    = 200e9, stop_mega = -0.13, stop_other = -0.15,
    purge12     = 90,    # calendar days, for the 12wk-trained model (as v3)
    purge24     = 200,   # calendar days, for the 24wk-trained model
    ridge_alpha = 10.0, min_train_rows = 1000, min_train_years = 3,
    depth = -0.30, sma_len = 50, cross_within = 5, base_days = 30, base_frac = 0.60,
)

STS15 = ["fisher","vwap20","ichimoku","volstop","ema921","ea34","tmo","qqe",
         "laguerre_adx","vidya","hull","supertrend_fast","supertrend_slow",
         "tdfi","waddah"]
ADD7  = ["rs_8wk","rs_4wk","high52_prox","mom_6mo","dist_200dma",
         "rel_volume","spy_regime"]
MODEL_COLS = [f"c_{k}" for k in STS15] + ADD7

GLOSSARY = [
 ("Entry set", "Only bars with a complete 24-week future are used, so 12- and 24-week results describe the IDENTICAL trades."),
 ("R12 / R24", "Outcome at each horizon under a rule: stop value if the low touched the stop within 60 / 120 trading days, else the 12- / 24-week return."),
 ("avg_R_per_week", "Average return divided by weeks held (12 or 24). The capital-efficiency yardstick: two sequential 12-week trades occupy the same capital as one 24-week hold."),
 ("Rules", "NOSTOP = hold to horizon. FIXED = -13% MEGA / -15% others. ATR3/ATR5 = k x ATR20 below entry. Same-day ties: stop wins."),
 ("Weights_12wk_vs_24wk", "Walk-forward ridge weights when trained on the 12-week vs the 24-week stop-adjusted target (FIXED rule). Shows whether longer holds want different indicators."),
 ("Survivorship bias", "Still present, and it grows with horizon — a 24-week window gives dying stocks more time to die out of the dataset. 24-week numbers are MORE inflated than 12-week ones."),
]

def path_pass(df, h24, atr_mults, fixed_levels):
    n = len(df)
    C = df["Close"].values
    pc = np.concatenate([[np.nan], C[:-1]])
    tr = np.nanmax(np.vstack([df["High"].values - df["Low"].values,
                              np.abs(df["High"].values - pc),
                              np.abs(df["Low"].values - pc)]), axis=0)
    atr_pct = pd.Series(tr).ewm(span=20, adjust=False).mean().values / C
    lo = np.concatenate([df["Low"].values[1:], [np.nan]])
    cols = {f"dayx_fix_{int(abs(s)*100)}": np.full(n, np.nan) for s in fixed_levels}
    cols |= {f"dayx_atr{int(k*10)}": np.full(n, np.nan) for k in atr_mults}
    cols["atr_pct"] = atr_pct
    for i in range(n - 1):
        end = min(i + h24, n - 1)
        w_lo = lo[i:end]
        if len(w_lo) < h24: continue
        for s in fixed_levels:
            idx = np.nonzero(w_lo <= C[i] * (1 + s))[0]
            if len(idx): cols[f"dayx_fix_{int(abs(s)*100)}"][i] = idx[0] + 1
        for k in atr_mults:
            idx = np.nonzero(w_lo <= C[i] * (1 - k * atr_pct[i]))[0]
            if len(idx): cols[f"dayx_atr{int(k*10)}"][i] = idx[0] + 1
    out = pd.DataFrame(cols, index=df.index)
    cs = pd.Series(C, index=df.index)
    out["fwd12"] = (cs.shift(-CFG["h12"]) / cs - 1) * 100
    out["fwd24"] = (cs.shift(-CFG["h24"]) / cs - 1) * 100
    sma = cs.rolling(CFG["sma_len"]).mean()
    below = (cs < sma).astype(float)
    crossed = (cs > sma) & (cs.shift(1) <= sma.shift(1))
    out["cross_recent"] = crossed.rolling(CFG["cross_within"]).max().fillna(0)
    out["base_ok"] = (below.shift(CFG["cross_within"])
                      .rolling(CFG["base_days"]).mean() >= CFG["base_frac"]).astype(float)
    return out

def load_ohlc(path):
    if path.endswith(".parquet"): df = pd.read_parquet(path)
    else:                          df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce", utc=True).tz_localize(None)
    df = df[df.index.notna()]
    cols = {c.lower().strip(): c for c in df.columns}
    if not all(k in cols for k in ["high","low","close"]): return None
    out = df[[cols[k] for k in ["high","low","close"]]].copy()
    out.columns = ["High","Low","Close"]
    return out.apply(pd.to_numeric, errors="coerce").dropna().sort_index()

def main():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    if not os.path.exists(CFG["panel_cache"]):
        sys.exit("ERROR: run ml_weight_study_v2.py first (needs its cache).")
    print("Loading v2 panel cache ...")
    panel = pd.read_parquet(CFG["panel_cache"])
    panel["date"] = pd.to_datetime(panel["date"])

    if os.path.exists(CFG["path_cache"]):
        print(f"Using cached 24wk paths {CFG['path_cache']} (delete to recompute)")
        paths = pd.read_parquet(CFG["path_cache"])
    else:
        files = {os.path.splitext(os.path.basename(f))[0].upper(): f
                 for f in sorted(glob.glob(os.path.join(CFG["data_dir"], "*.csv")) +
                                 glob.glob(os.path.join(CFG["data_dir"], "*.parquet")))}
        tickers = [t for t in panel["ticker"].unique() if t in files]
        print(f"Path pass (120-day horizon) for {len(tickers)} tickers ...")
        frames = []
        for n, t in enumerate(tickers, 1):
            df = load_ohlc(files[t])
            if df is None: continue
            p = path_pass(df, CFG["h24"], CFG["atr_mults"],
                          [CFG["stop_mega"], CFG["stop_other"]])
            p["ticker"] = t
            frames.append(p.reset_index(names="date"))
            if n % 25 == 0 or n == len(tickers): print(f"  {n}/{len(tickers)}")
        paths = pd.concat(frames, ignore_index=True)
        paths["date"] = pd.to_datetime(paths["date"])
        paths.to_parquet(CFG["path_cache"])
        print(f"Cached to {CFG['path_cache']}")
    panel = panel.merge(paths, on=["ticker","date"], how="left")
    panel = panel[panel["fwd24"].notna()].copy()   # identical entry set
    panel["year"] = panel["date"].dt.year
    print(f"Entry set with full 24-week future: {len(panel):,} bars "
          f"({panel['date'].min().date()} to {panel['date'].max().date()})")

    try:
        caps = json.load(open(CFG["cap_file"]))
        tiers = {t: ("MEGA" if (v or 0) >= CFG["mega_cap"] else "LARGE")
                 for t, v in caps.items()}
    except Exception:
        tiers = {}
    mega = panel["ticker"].map(tiers).fillna("LARGE").eq("MEGA")
    panel["day_fix"]  = np.where(mega, panel["dayx_fix_13"], panel["dayx_fix_15"])
    panel["fix_pct"]  = np.where(mega, CFG["stop_mega"], CFG["stop_other"]) * 100
    # training target (identical to v3): 12wk fixed-stop outcome
    stopped12 = panel["day_fix"] <= CFG["h12"]
    panel["R_fixed12_train"] = np.where(stopped12, panel["fix_pct"], panel["fwd12"])
    stopped24 = panel["day_fix"] <= CFG["h24"]
    panel["R_fixed24_train"] = np.where(stopped24, panel["fix_pct"], panel["fwd24"])

    # ── walk-forward scores + weights at both horizons ──────────────────────
    def walk_forward(target_col, purge_days):
        years = sorted(panel["year"].unique())
        test_years = [y for y in years if y >= years[0] + CFG["min_train_years"]]
        oos, coef_rows = [], []
        for y in test_years:
            cut = pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=purge_days)
            tr = panel[panel["date"] < cut]
            te = panel[panel["year"] == y].copy()
            if len(tr) < CFG["min_train_rows"] or len(te) < 100: continue
            sc = StandardScaler().fit(tr[MODEL_COLS].values)
            m = Ridge(alpha=CFG["ridge_alpha"]).fit(
                sc.transform(tr[MODEL_COLS].values), tr[target_col].values)
            te["score"] = m.predict(sc.transform(te[MODEL_COLS].values))
            te["decile"] = pd.qcut(te["score"].rank(method="first"), 10,
                                   labels=[f"D{i}" for i in range(1, 11)])
            oos.append(te)
            for c, w in zip(MODEL_COLS, m.coef_):
                coef_rows.append(dict(fold=y, feature=c.replace("c_",""), weight=w))
        return pd.concat(oos, ignore_index=True), pd.DataFrame(coef_rows)

    print("Walk-forward model (12wk target, as v3) ...")
    oos, coefs12 = walk_forward("R_fixed12_train", CFG["purge12"])
    print("Walk-forward model (24wk target) ...")
    _, coefs24 = walk_forward("R_fixed24_train", CFG["purge24"])

    def stab(coefs):
        s = coefs.groupby("feature")["weight"].agg(["mean"])
        s["sign_cons_%"] = coefs.groupby("feature")["weight"].apply(
            lambda x: 100*max((x>0).mean(), (x<0).mean()))
        return s
    w12, w24 = stab(coefs12), stab(coefs24)
    wcmp = (w12.rename(columns={"mean":"weight_12wk","sign_cons_%":"cons12_%"})
            .join(w24.rename(columns={"mean":"weight_24wk","sign_cons_%":"cons24_%"})))
    wcmp = wcmp.reindex(wcmp["weight_12wk"].abs().sort_values(ascending=False).index).reset_index()

    bb = oos[(oos["high52_prox"] <= CFG["depth"]) &
             (oos["cross_recent"] == 1) & (oos["base_ok"] == 1)]
    subsets = {"D10_model_top10pct": oos[oos["decile"] == "D10"],
               "Top_quintile_D9_D10": oos[oos["decile"].isin(["D9","D10"])],
               "Base_breakout": bb,
               "All_OOS_bars": oos}

    # ── evaluate rules at both horizons on identical trades ────────────────
    def rule_outcome(d, rule, h):
        fwd = d["fwd12"] if h == CFG["h12"] else d["fwd24"]
        if rule == "NOSTOP":
            return fwd, pd.Series(False, index=d.index)
        if rule == "FIXED":
            dayc, loss = d["day_fix"], d["fix_pct"]
        else:
            k = float(rule[3:])
            dayc, loss = d[f"dayx_atr{int(k*10)}"], -100 * k * d["atr_pct"]
        hit = dayc <= h
        return pd.Series(np.where(hit, loss, fwd), index=d.index), hit

    rows = []
    for name, sub in subsets.items():
        for rule in ["NOSTOP", "FIXED", "ATR3", "ATR5"]:
            for h, wks in [(CFG["h12"], 12), (CFG["h24"], 24)]:
                R, hit = rule_outcome(sub, rule, h)
                rows.append(dict(subset=name, rule=rule, horizon_wks=wks,
                    trades=len(R), win_rate_pct=100*(R > 0).mean(),
                    stopped_pct=100*pd.Series(hit).mean(),
                    avg_R_pct=R.mean(), median_R_pct=R.median(),
                    p10_R_pct=R.quantile(0.10),
                    avg_R_per_week=R.mean() / wks))
    tbl = pd.DataFrame(rows)

    # per-year, D10, NOSTOP only (the recommended rule)
    d10 = subsets["D10_model_top10pct"]
    yr = []
    for y, d in d10.groupby("year"):
        for h, wks in [(CFG["h12"], 12), (CFG["h24"], 24)]:
            R, _ = rule_outcome(d, "NOSTOP", h)
            yr.append(dict(year=y, horizon_wks=wks, trades=len(R),
                win_rate_pct=100*(R > 0).mean(), avg_R_pct=R.mean(),
                median_R_pct=R.median(), avg_R_per_week=R.mean() / wks))
    yr = pd.DataFrame(yr)

    gloss = pd.DataFrame(GLOSSARY, columns=["term","meaning"])
    with pd.ExcelWriter(CFG["out_file"], engine="openpyxl") as xw:
        gloss.to_excel(xw, sheet_name="README_Glossary", index=False)
        tbl.to_excel(xw, sheet_name="Horizon_Comparison", index=False)
        yr.to_excel(xw, sheet_name="ByYear_D10_NOSTOP", index=False)
        wcmp.to_excel(xw, sheet_name="Weights_12wk_vs_24wk", index=False)

    print("\n" + "="*78)
    print("12 vs 24 WEEKS — identical entries (avg_R_per_week = capital efficiency)")
    print("="*78)
    for name in subsets:
        print(f"\n{name}:")
        t = tbl[tbl["subset"] == name]
        for rule in ["NOSTOP", "FIXED", "ATR5"]:
            r12 = t[(t["rule"] == rule) & (t["horizon_wks"] == 12)].iloc[0]
            r24 = t[(t["rule"] == rule) & (t["horizon_wks"] == 24)].iloc[0]
            print(f"  {rule:<7} 12wk: win {r12['win_rate_pct']:5.1f}% avg {r12['avg_R_pct']:+6.2f}% "
                  f"med {r12['median_R_pct']:+6.2f}% perwk {r12['avg_R_per_week']:+.3f}   |   "
                  f"24wk: win {r24['win_rate_pct']:5.1f}% avg {r24['avg_R_pct']:+6.2f}% "
                  f"med {r24['median_R_pct']:+6.2f}% perwk {r24['avg_R_per_week']:+.3f}")
    print("\nRULE OF THUMB: hold 24 weeks only if its avg_R_per_week beats the 12-week")
    print("number — otherwise recycling capital into fresh 12-week signals pays more.")
    print("\nTOP WEIGHT CHANGES (12wk-trained vs 24wk-trained):")
    for _, r in wcmp.head(8).iterrows():
        print(f"  {r['feature']:<14} 12wk {r['weight_12wk']:+.2f} ({r['cons12_%']:.0f}%)"
              f"   24wk {r['weight_24wk']:+.2f} ({r['cons24_%']:.0f}%)")
    print(f"\nNote: survivorship bias grows with horizon — 24wk numbers are more")
    print(f"inflated than 12wk ones.\nOutput written to: {CFG['out_file']}")

if __name__ == "__main__":
    main()
