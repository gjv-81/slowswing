#!/usr/bin/env python3.12
# ============================================================================
# LANE B STUDY — deep-drawdown (UNH-type) bars only
# ============================================================================
# QUESTION: when a stock is CRASHED (6-month momentum >= 2 standard deviations
# WORSE than the market cross-section that day, AND below its 200-day MA),
# what happens over the next 12 weeks — and does ANY indicator separate the
# recoveries (UNH) from the value traps?
#
# Uses the cached feature panel from ml_weight_study.py — runs in seconds.
# HOW TO RUN:
#   cd ~/Documents/STS/15min
#   python3.12 ml_laneB_study.py
#
# OUTPUT: ml_laneB_study.xlsx (one file)
#   - Baseline:      Lane B bars vs all bars — win rate & returns by year
#   - Feature_IC:    per-feature rank correlation with 12-wk return, per year
#                    (univariate — robust with the smaller Lane B sample)
#   - Ridge_Weights: walk-forward learned weights inside Lane B
#   - Score_Quintiles: learned-score quintiles -> win rate (the threshold table)
#   - README_Glossary
#
# HONEST CAVEATS (also printed at the end):
#   1. SURVIVORSHIP BIAS IS WORST EXACTLY HERE. The 604 tickers are today's
#      survivors. Crashed stocks that never recovered (delisted/acquired/faded)
#      are missing, so Lane B win rates are INFLATED. Treat absolute win rates
#      as upper bounds; relative comparisons (which features separate winners)
#      are more trustworthy.
#   2. No stop-loss in the label: a bar that dips -20% then recovers counts
#      as a win here, but your -13/-15% stop would have exited it.
# ============================================================================

import os, sys
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

CFG = dict(
    panel_cache = os.path.expanduser("~/Documents/STS/15min/ml_panel_cache.parquet"),
    out_file    = os.path.expanduser("~/Documents/STS/15min/ml_laneB_study.xlsx"),
    z_thresh    = -2.0,   # mom_6mo must be >= 2 std WORSE than that day's cross-section
    min_xsec    = 30,     # need >= this many stocks on a date to compute the z-score
    purge_days  = 90,
    ridge_alpha = 10.0,
    min_train   = 300,    # Lane B sample is small — relaxed fold minimums
    min_test    = 50,
)

STS16 = ["fisher","vwap20","ichimoku","volstop","macd","ema921","ea34","tmo",
         "qqe","laguerre_adx","vidya","hull","supertrend_fast","supertrend_slow",
         "tdfi","waddah"]
ADD5  = ["rs_8wk","rs_4wk","high52_prox","rel_volume","spy_regime"]
# mom_6mo and dist_200dma are EXCLUDED as predictors here — they define the
# Lane B filter itself, so inside the lane they are restricted-range by design.

GLOSSARY = [
 ("Lane B bar", "A stock-day where 6-mo momentum is >=2 std worse than the market cross-section AND price is below the 200-DMA. The UNH/VEEV situation."),
 ("Win", "12-week forward return > 0 (no stop-loss applied — see caveats)."),
 ("Feature IC", "Spearman rank correlation between one feature's value on Lane B bars and the 12-wk forward return, computed per year. Positive & consistent = that feature helps pick recoveries."),
 ("Sign consistency", "% of years where the feature's IC kept the same sign. >=75% = worth attention; ~50% = noise."),
 ("Score quintile", "Lane B bars ranked by the walk-forward model score, split into 5 buckets per year (out-of-sample). Q5 = model's favorites. If Q5 win rate >> Q1, the model separates UNHs from value traps."),
 ("Survivorship bias", "Dead/delisted stocks are missing from the data. Lane B win rates are inflated — read them as upper bounds."),
]

def spearman(a, b):
    a, b = pd.Series(a), pd.Series(b)
    if a.nunique() < 3 or len(a) < 30: return np.nan
    return a.corr(b, method="spearman")

def main():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    if not os.path.exists(CFG["panel_cache"]):
        sys.exit(f"ERROR: {CFG['panel_cache']} not found.\n"
                 "Run ml_weight_study.py first — it creates the cached panel.")
    print("Loading cached panel ...")
    panel = pd.read_parquet(CFG["panel_cache"])
    panel["date"] = pd.to_datetime(panel["date"])
    print(f"  {len(panel):,} bars, {panel['ticker'].nunique()} tickers")

    # ── define Lane B: crashed vs cross-section + below 200-DMA ────────────
    g = panel.groupby("date")["mom_6mo"]
    mu, sd, n = g.transform("mean"), g.transform("std"), g.transform("count")
    panel["mom_z"] = np.where((n >= CFG["min_xsec"]) & (sd > 0),
                              (panel["mom_6mo"] - mu) / sd, np.nan)
    laneB = panel[(panel["mom_z"] <= CFG["z_thresh"]) &
                  (panel["dist_200dma"] < 0)].copy()
    print(f"\nLane B bars: {len(laneB):,} "
          f"({100*len(laneB)/len(panel):.1f}% of all bars), "
          f"{laneB['ticker'].nunique()} tickers ever qualified")
    if len(laneB) < 500:
        sys.exit("ERROR: too few Lane B bars to analyze. "
                 "Loosen z_thresh in CFG (e.g. -1.5) and rerun.")

    laneB["year"] = laneB["date"].dt.year
    panel["year"] = panel["date"].dt.year
    laneB["win"] = (laneB["fwd_12wk"] > 0).astype(int)
    panel["win"] = (panel["fwd_12wk"] > 0).astype(int)

    # ── 1. BASELINE: how do crashed stocks perform vs everything? ──────────
    def perf(df):
        return pd.Series({"bars": len(df), "win_rate_%": 100*df["win"].mean(),
                          "avg_ret_%": df["fwd_12wk"].mean(),
                          "median_ret_%": df["fwd_12wk"].median(),
                          "avg_excess_vs_SPY_%": df["fwd_12wk_excess"].mean(),
                          "p10_ret_%": df["fwd_12wk"].quantile(0.10),
                          "p90_ret_%": df["fwd_12wk"].quantile(0.90)})
    base = pd.concat([
        laneB.groupby("year").apply(perf, include_groups=False).assign(group="LaneB_crashed"),
        panel.groupby("year").apply(perf, include_groups=False).assign(group="All_bars"),
    ]).reset_index().sort_values(["year", "group"])
    tot = pd.DataFrame([perf(laneB).to_dict() | {"year": "ALL", "group": "LaneB_crashed"},
                        perf(panel).to_dict() | {"year": "ALL", "group": "All_bars"}])
    base = pd.concat([base, tot], ignore_index=True)

    # ── 2. UNIVARIATE: which single features separate winners? ─────────────
    feats = [f"c_{k}" for k in STS16] + [f"v_{k}" for k in STS16] + ADD5 + ["hand_score"]
    ic_rows = []
    for f in feats:
        ics = laneB.groupby("year").apply(
            lambda d: spearman(d[f], d["fwd_12wk"]), include_groups=False).dropna()
        if not len(ics): continue
        ic_rows.append(dict(feature=f, mean_IC=ics.mean(), years=len(ics),
            sign_consistency_pct=100*max((ics > 0).mean(), (ics < 0).mean())))
    ic = (pd.DataFrame(ic_rows).assign(a=lambda d: d["mean_IC"].abs())
          .sort_values("a", ascending=False).drop(columns="a"))

    # ── 3. WALK-FORWARD RIDGE inside Lane B ─────────────────────────────────
    model_cols = [f"c_{k}" for k in STS16] + ADD5
    years = sorted(laneB["year"].unique())
    coef_rows, fold_rows, quint_frames = [], [], []
    for y in years[2:]:
        cut = pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=CFG["purge_days"])
        tr = laneB[laneB["date"] < cut]; te = laneB[laneB["year"] == y].copy()
        if len(tr) < CFG["min_train"] or len(te) < CFG["min_test"]: continue
        sc = StandardScaler().fit(tr[model_cols].values)
        m = Ridge(alpha=CFG["ridge_alpha"]).fit(sc.transform(tr[model_cols].values),
                                                tr["fwd_12wk"].values)
        te["score"] = m.predict(sc.transform(te[model_cols].values))
        fold_rows.append(dict(fold=y, train=len(tr), test=len(te),
                              IC_model=spearman(te["score"], te["fwd_12wk"]),
                              IC_hand_score=spearman(te["hand_score"], te["fwd_12wk"])))
        for c, w in zip(model_cols, m.coef_):
            coef_rows.append(dict(fold=y, feature=c.replace("c_", ""), weight=w))
        te["quintile"] = pd.qcut(te["score"].rank(method="first"), 5,
                                 labels=["Q1_worst","Q2","Q3","Q4","Q5_best"])
        quint_frames.append(te)
    if not fold_rows:
        sys.exit("ERROR: not enough Lane B history for walk-forward folds.")
    folds = pd.DataFrame(fold_rows)
    coefs = pd.DataFrame(coef_rows)
    stab = coefs.groupby("feature")["weight"].agg(["mean", "std"])
    stab["sign_consistency_pct"] = coefs.groupby("feature")["weight"].apply(
        lambda s: 100*max((s > 0).mean(), (s < 0).mean()))
    stab = stab.reindex(stab["mean"].abs().sort_values(ascending=False).index).reset_index()

    allq = pd.concat(quint_frames)
    quint = allq.groupby("quintile", observed=True).agg(
        bars=("win","size"), win_rate_pct=("win", lambda s: 100*s.mean()),
        avg_ret_pct=("fwd_12wk","mean"), median_ret_pct=("fwd_12wk","median"),
        avg_excess_pct=("fwd_12wk_excess","mean")).reset_index()

    gloss = pd.DataFrame(GLOSSARY, columns=["term","meaning"])
    with pd.ExcelWriter(CFG["out_file"], engine="openpyxl") as xw:
        gloss.to_excel(xw, sheet_name="README_Glossary", index=False)
        base.to_excel(xw, sheet_name="Baseline", index=False)
        ic.to_excel(xw, sheet_name="Feature_IC", index=False)
        stab.to_excel(xw, sheet_name="Ridge_Weights", index=False)
        folds.to_excel(xw, sheet_name="Fold_Performance", index=False)
        quint.to_excel(xw, sheet_name="Score_Quintiles", index=False)

    # ── console report ──────────────────────────────────────────────────────
    lb, ab = perf(laneB), perf(panel)
    print("\n" + "="*72)
    print("LANE B (crashed >=2 std + below 200-DMA) vs ALL BARS — 12-wk forward")
    print("="*72)
    print(f"  Win rate:      LaneB {lb['win_rate_%']:.1f}%   vs  all bars {ab['win_rate_%']:.1f}%")
    print(f"  Avg return:    LaneB {lb['avg_ret_%']:+.2f}%  vs  all bars {ab['avg_ret_%']:+.2f}%")
    print(f"  Median return: LaneB {lb['median_ret_%']:+.2f}%  vs  all bars {ab['median_ret_%']:+.2f}%")
    print(f"  Excess vs SPY: LaneB {lb['avg_excess_vs_SPY_%']:+.2f}%  vs  all bars {ab['avg_excess_vs_SPY_%']:+.2f}%")
    print(f"  Tails: 10th pct {lb['p10_ret_%']:+.1f}%  /  90th pct {lb['p90_ret_%']:+.1f}%  (LaneB)")
    print("\nTOP 10 FEATURES for separating recoveries from value traps (univariate):")
    for _, r in ic.head(10).iterrows():
        flag = "STABLE" if r["sign_consistency_pct"] >= 75 else "unstable"
        print(f"  {r['feature']:<20} IC={r['mean_IC']:+.3f}  "
              f"consistent {r['sign_consistency_pct']:.0f}% [{flag}]")
    print(f"\nHand score (current 18-pt) inside Lane B: "
          f"mean IC {folds['IC_hand_score'].mean():+.3f} | "
          f"ML model: mean IC {folds['IC_model'].mean():+.3f}")
    print("\nSCORE QUINTILES (out-of-sample — the 'can we pick the UNHs?' test):")
    for _, r in quint.iterrows():
        print(f"  {r['quintile']:<9} win {r['win_rate_pct']:.1f}%  "
              f"avg {r['avg_ret_pct']:+.2f}%  median {r['median_ret_pct']:+.2f}%")
    print("\nCAVEATS: (1) survivorship bias inflates ALL Lane B numbers — dead")
    print("stocks are missing, so treat win rates as upper bounds; (2) no stop")
    print("loss in the label; (3) sample is small — trust sign consistency,")
    print(f"not point estimates.\nOutput written to: {CFG['out_file']}")

if __name__ == "__main__":
    main()
