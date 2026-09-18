#!/usr/bin/env python3.12
# ============================================================================
# RS ZERO-CROSS STUDY — "RS crosses up through 0 while the score is high"
# ============================================================================
# HYPOTHESIS (from UNH, CRWD, DDOG observations): a stock whose 8-week RS
# crosses from negative to positive WHILE the ML score is elevated marks
# the start of the recovery leg — a better-timed entry than merely being
# in the top score bucket.
#
# FIXED RULE, NO FITTING: nothing is trained here, so the full 10-year
# panel is a fair test. The comparison that matters (pre-committed):
#   B (cross + score >= 2)  vs  D (score >= 2 anytime)  at 12 weeks.
# If B does not beat D, the cross adds no timing value.
#
# RULES TESTED (all evaluated on no-stop 12-week forward returns):
#   A: RS crosses 0 upward (any score)
#   B: cross + score >= 2          <- the hypothesis
#   C: cross + score >= 3
#   E: cross + score >= 2 + stock >= 25% below its 52-wk high (the
#      UNH/CRWD/DDOG shape made explicit)
#   D: score >= 2, no cross requirement (the current scan bucket, baseline)
#   F: all bars (market baseline)
#
# HOW TO RUN (needs ml_panel_cache_v2.parquet):
#   cd ~/Documents/STS/15min && python3.12 ml_rscross_study.py
# OUTPUT: ONE file — ml_rscross_study.xlsx
# ============================================================================

import os, sys
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

CACHE = os.path.expanduser("~/Documents/STS/15min/ml_panel_cache_v2.parquet")
OUT   = os.path.expanduser("~/Documents/STS/15min/ml_rscross_study.xlsx")

ZC = {"high52_prox": (-0.149772, 0.156737), "dist_200dma": (1.681650, 6.240695),
      "mom_6mo": (0.086250, 0.361377), "c_qqe": (0.044473, 0.194268),
      "c_hull": (0.027496, 0.303103), "rs_8wk": (0.004520, 0.155298)}
W  = {"high52_prox": -2.20, "dist_200dma": 1.35, "mom_6mo": 1.08,
      "c_qqe": -0.99, "rs_8wk": 0.63, "c_hull": 0.60}

GLOSSARY = [
 ("Score", "The 6-term TOS-equivalent score (clipped z-weights); the RS leg uses rs_8wk (vs SPY). Levels comparable to your TOS column (~0.9 rank correlation with the full model)."),
 ("Cross", "rs_8wk was negative at the prior weekly sample and >= 0 at this one (samples ~5 trading days apart, gap capped at 12 calendar days)."),
 ("Rule B vs D", "THE pre-committed comparison: does requiring the cross beat simply being in the score >= 2 bucket? Timing value = B minus D."),
 ("Outcomes", "No-stop 12-week forward return (the exit design the stop study validated). Win = return > 0. Excess = minus SPY same period."),
 ("By-year table", "Regime robustness: a rule that only wins in 2020 is a bull-recovery artifact, not an edge."),
 ("Multiple comparisons", "This is the program's 8th study on the same data. One pre-committed comparison (B vs D) keeps it honest; treat everything else as descriptive."),
]

def main():
    if not os.path.exists(CACHE):
        sys.exit("ERROR: run ml_weight_study_v2.py first (needs its cache).")
    print("Loading panel ...")
    p = pd.read_parquet(CACHE, columns=["ticker","date","high52_prox","dist_200dma",
        "mom_6mo","c_qqe","c_hull","rs_8wk","fwd_12wk","fwd_12wk_excess"])
    p["date"] = pd.to_datetime(p["date"])
    p = p.dropna().sort_values(["ticker","date"]).reset_index(drop=True)

    z = lambda c: np.clip((p[c] - ZC[c][0]) / ZC[c][1], -3, 3)
    p["score"] = sum(W[c] * z(c) for c in W)

    g = p.groupby("ticker")
    prev_rs   = g["rs_8wk"].shift(1)
    prev_date = g["date"].shift(1)
    gap_ok    = (p["date"] - prev_date).dt.days <= 12
    p["cross"] = (prev_rs < 0) & (p["rs_8wk"] >= 0) & gap_ok

    rules = {
        "A_cross_any":        p["cross"],
        "B_cross_score2":     p["cross"] & (p["score"] >= 2),
        "C_cross_score3":     p["cross"] & (p["score"] >= 3),
        "E_cross_s2_deep25":  p["cross"] & (p["score"] >= 2) & (p["high52_prox"] <= -0.25),
        "D_score2_anytime":   (p["score"] >= 2),
        "F_all_bars":         pd.Series(True, index=p.index),
    }

    def stats(mask):
        d = p[mask]
        return dict(n=len(d), win_pct=100*(d["fwd_12wk"]>0).mean(),
            avg_pct=d["fwd_12wk"].mean(), median_pct=d["fwd_12wk"].median(),
            avg_excess_pct=d["fwd_12wk_excess"].mean(),
            p10_pct=d["fwd_12wk"].quantile(0.10),
            p90_pct=d["fwd_12wk"].quantile(0.90))
    summary = pd.DataFrame([{**{"rule": k}, **stats(m)} for k, m in rules.items()]).round(2)

    yr_rows = []
    for k in ["B_cross_score2", "D_score2_anytime", "E_cross_s2_deep25"]:
        d = p[rules[k]]
        for y, dd in d.groupby(d["date"].dt.year):
            yr_rows.append(dict(rule=k, year=y, n=len(dd),
                win_pct=round(100*(dd["fwd_12wk"]>0).mean(),1),
                avg_pct=round(dd["fwd_12wk"].mean(),2),
                avg_excess_pct=round(dd["fwd_12wk_excess"].mean(),2)))
    byyear = pd.DataFrame(yr_rows)

    gloss = pd.DataFrame(GLOSSARY, columns=["term","meaning"])
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        byyear.to_excel(xw, sheet_name="ByYear", index=False)
        gloss.to_excel(xw, sheet_name="Glossary", index=False)

    print("\n" + "="*76)
    print("RS ZERO-CROSS STUDY — no-stop 12-week outcomes")
    print("="*76)
    for _, r in summary.iterrows():
        print(f"  {r['rule']:<20} n={int(r['n']):>6}  win {r['win_pct']:5.1f}%"
              f"  avg {r['avg_pct']:+6.2f}%  med {r['median_pct']:+6.2f}%"
              f"  excess {r['avg_excess_pct']:+6.2f}%  [p10 {r['p10_pct']:+.1f} / p90 {r['p90_pct']:+.1f}]")
    b = summary[summary["rule"]=="B_cross_score2"].iloc[0]
    d = summary[summary["rule"]=="D_score2_anytime"].iloc[0]
    print("\nPRE-COMMITTED VERDICT (B vs D):")
    print(f"  timing value = avg {b['avg_pct']-d['avg_pct']:+.2f}% | "
          f"excess {b['avg_excess_pct']-d['avg_excess_pct']:+.2f}% | "
          f"win rate {b['win_pct']-d['win_pct']:+.1f} pts")
    print("  -> If these are ~zero or negative, the cross adds no timing value")
    print("     and remains a nice chart narrative, not a rule.")
    print(f"\nCaveats: weekly sampling can miss crosses by a few days; survivorship")
    print(f"bias inflates all rules equally.\nOutput written to: {OUT}")

if __name__ == "__main__":
    main()
