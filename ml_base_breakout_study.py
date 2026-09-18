#!/usr/bin/env python3.12
# ============================================================================
# BASE BREAKOUT STUDY — beaten-down stocks reclaiming the 50-day SMA
# ============================================================================
# THE SETUP BEING TESTED (Weinstein Stage-2 style recovery entry):
#   1. DEPTH:   stock is >= 30% below its 52-week high
#   2. BASE:    over the 30 days before the cross it closed below its 50-SMA
#               at least 60% of the time (a real base under the line)
#   3. TRIGGER: it crossed above the 50-day SMA within the last 5 days
#
# QUESTIONS ANSWERED:
#   - How do these entries perform over the next 12 weeks, with your real
#     tiered stops (-13% MEGA / -15% others) applied?
#   - Which of the 22 indicators separate the winners from the losers
#     INSIDE this setup (univariate ICs + walk-forward ridge weights)?
#   - Can the model rank them (out-of-sample score quintiles)?
#   - How much profit was available along the way (MFE / target touches)?
#
# HOW TO RUN (needs ml_panel_cache_v2.parquet from ml_weight_study_v2.py):
#   cd ~/Documents/STS/15min
#   python3.12 ml_base_breakout_study.py        # runs in ~2-3 minutes
#
# OUTPUT: ONE file — ml_base_breakout_study.xlsx
# ============================================================================

import os, sys, glob, json, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

CFG = dict(
    data_dir    = os.path.expanduser("~/Documents/STS/15min/daily_data_10y"),
    cap_file    = os.path.expanduser("~/Documents/STS/15min/cap_cache.json"),
    panel_cache = os.path.expanduser("~/Documents/STS/15min/ml_panel_cache_v2.parquet"),
    out_file    = os.path.expanduser("~/Documents/STS/15min/ml_base_breakout_study.xlsx"),
    depth       = -0.30,  # close must be >= 30% below 52-wk high
    sma_len     = 50,     # the moving average being reclaimed
    cross_within= 5,      # cross must have happened in the last N trading days
    base_days   = 30,     # look-back window for the base test
    base_frac   = 0.60,   # fraction of base_days spent below the SMA
    mega_cap    = 200e9, stop_mega = -0.13, stop_other = -0.15,
    purge_days  = 90, ridge_alpha = 10.0, min_train = 300, min_test = 40,
)

STS15 = ["fisher","vwap20","ichimoku","volstop","ema921","ea34","tmo","qqe",
         "laguerre_adx","vidya","hull","supertrend_fast","supertrend_slow",
         "tdfi","waddah"]
ADD7  = ["rs_8wk","rs_4wk","high52_prox","mom_6mo","dist_200dma",
         "rel_volume","spy_regime"]
MODEL_COLS = [f"c_{k}" for k in STS15] + ADD7

GLOSSARY = [
 ("Signal bar", "A stock-day meeting all 3 conditions: >=30% below 52-wk high, based below the 50-SMA (>=60% of prior 30 days), crossed above the 50-SMA within the last 5 days."),
 ("R", "Stop-adjusted 12-week outcome: stop loss (-13% MEGA / -15% others) if the low breached it first, else the 12-week return. Win = R > 0."),
 ("Feature IC", "Per-year Spearman rank correlation between an indicator's value AT the signal and R. Positive & consistent = that indicator picks the recoveries."),
 ("Score quintile", "Signal bars ranked by walk-forward model score (out-of-sample), split in 5. Q5 = model favorites."),
 ("MFE / target touch", "Max favorable excursion and %% of signals that touched +5/10/15/20%% within the 12 weeks — the exit-design context."),
 ("Survivorship bias", "Crashed stocks that never recovered are missing from the universe. All absolute win rates here are UPPER bounds — this setup is affected more than most."),
]

def load_close_flags(path):
    """50-SMA cross + base flags from raw daily closes."""
    if path.endswith(".parquet"): df = pd.read_parquet(path)
    else:                          df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce", utc=True).tz_localize(None)
    df = df[df.index.notna()]
    cols = {c.lower().strip(): c for c in df.columns}
    if "close" not in cols: return None
    c = pd.to_numeric(df[cols["close"]], errors="coerce").dropna().sort_index()
    sma = c.rolling(CFG["sma_len"]).mean()
    below = (c < sma).astype(float)
    crossed = (c > sma) & (c.shift(1) <= sma.shift(1))
    out = pd.DataFrame(index=c.index)
    out["cross_recent"] = crossed.rolling(CFG["cross_within"]).max().fillna(0)
    # base measured over the window ENDING the day before the cross window
    out["base_ok"] = (below.shift(CFG["cross_within"])
                      .rolling(CFG["base_days"]).mean() >= CFG["base_frac"]).astype(float)
    return out

def spearman(a, b):
    a, b = pd.Series(a).reset_index(drop=True), pd.Series(b).reset_index(drop=True)
    if a.nunique() < 3 or len(a) < 25: return np.nan
    return a.corr(b, method="spearman")

def main():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    if not os.path.exists(CFG["panel_cache"]):
        sys.exit("ERROR: ml_panel_cache_v2.parquet not found — run ml_weight_study_v2.py first.")
    print("Loading cached panel ...")
    panel = pd.read_parquet(CFG["panel_cache"])
    panel["date"] = pd.to_datetime(panel["date"])
    print(f"  {len(panel):,} bars, {panel['ticker'].nunique()} tickers")

    # ── stop-adjusted outcome (same as v2) ─────────────────────────────────
    try:
        caps = json.load(open(CFG["cap_file"]))
        tiers = {t: ("MEGA" if (v or 0) >= CFG["mega_cap"] else "LARGE")
                 for t, v in caps.items()}
    except Exception:
        tiers = {}
    panel["tier"] = panel["ticker"].map(tiers).fillna("LARGE")
    mega = panel["tier"].eq("MEGA")
    panel["day_stop"] = np.where(mega, panel["day_stop_13"], panel["day_stop_15"])
    panel["stop_pct"] = np.where(mega, CFG["stop_mega"], CFG["stop_other"]) * 100
    panel["R"] = np.where(panel["day_stop"].notna(), panel["stop_pct"], panel["fwd_12wk"])
    panel["win"] = (panel["R"] > 0).astype(int)
    panel["year"] = panel["date"].dt.year

    # ── compute cross/base flags from raw closes and merge ─────────────────
    print("Computing 50-SMA cross + base flags from daily closes ...")
    files = {os.path.splitext(os.path.basename(f))[0].upper(): f
             for f in sorted(glob.glob(os.path.join(CFG["data_dir"], "*.csv")) +
                             glob.glob(os.path.join(CFG["data_dir"], "*.parquet")))}
    flag_frames = []
    tickers = [t for t in panel["ticker"].unique() if t in files]
    for n, t in enumerate(tickers, 1):
        fl = load_close_flags(files[t])
        if fl is None: continue
        fl["ticker"] = t
        flag_frames.append(fl.reset_index(names="date"))
        if n % 100 == 0: print(f"  {n}/{len(tickers)}")
    flags = pd.concat(flag_frames, ignore_index=True)
    flags["date"] = pd.to_datetime(flags["date"])
    panel = panel.merge(flags, on=["ticker", "date"], how="left")

    # ── the signal filter ───────────────────────────────────────────────────
    sig = panel[(panel["high52_prox"] <= CFG["depth"]) &
                (panel["cross_recent"] == 1) & (panel["base_ok"] == 1)].copy()
    print(f"\nSIGNAL BARS: {len(sig):,} ({100*len(sig)/len(panel):.2f}% of all bars), "
          f"{sig['ticker'].nunique()} tickers, "
          f"~{len(sig)/max(sig['year'].nunique(),1):.0f} signals/year across the universe")
    if len(sig) < 300:
        sys.exit("ERROR: too few signals — loosen depth/base_frac in CFG and rerun.")

    # ── 1. baseline performance ─────────────────────────────────────────────
    def perf(d):
        return pd.Series({"signals": len(d), "win_rate_%": 100*d["win"].mean(),
            "stopped_%": 100*d["day_stop"].notna().mean(),
            "avg_R_%": d["R"].mean(), "median_R_%": d["R"].median(),
            "avg_raw_12wk_%": d["fwd_12wk"].mean(),
            "avg_excess_vs_SPY_%": d["fwd_12wk_excess"].mean(),
            "avg_MFE_%": 100*d["mfe60"].mean(), "avg_MAE_%": 100*d["mae60"].mean()})
    base = sig.groupby("year").apply(perf, include_groups=False).reset_index()
    allrow = perf(sig).to_frame().T.assign(year="ALL_SIGNALS")
    allbars = perf(panel).to_frame().T.assign(year="ALL_BARS_baseline")
    base = pd.concat([base, allrow, allbars], ignore_index=True)

    # ── 2. univariate feature ICs inside the setup ──────────────────────────
    feats = MODEL_COLS + ["hand_score"]
    ic_rows = []
    for f in feats:
        ics = sig.groupby("year").apply(lambda d: spearman(d[f], d["R"]),
                                        include_groups=False).dropna()
        if len(ics) < 4: continue
        ic_rows.append(dict(feature=f.replace("c_",""), mean_IC=ics.mean(),
            years=len(ics),
            sign_consistency_pct=100*max((ics>0).mean(), (ics<0).mean())))
    if ic_rows:
        ic = (pd.DataFrame(ic_rows).assign(a=lambda d: d["mean_IC"].abs())
              .sort_values("a", ascending=False).drop(columns="a"))
    else:
        ic = pd.DataFrame([{"feature": "(too few signals per year for ICs)",
                            "mean_IC": np.nan, "years": 0,
                            "sign_consistency_pct": np.nan}])

    # ── 3. walk-forward ridge within the setup ──────────────────────────────
    years = sorted(sig["year"].unique())
    coef_rows, fold_rows, oos_frames = [], [], []
    for y in years[2:]:
        cut = pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=CFG["purge_days"])
        tr = sig[sig["date"] < cut]; te = sig[sig["year"] == y].copy()
        if len(tr) < CFG["min_train"] or len(te) < CFG["min_test"]: continue
        sc = StandardScaler().fit(tr[MODEL_COLS].values)
        m = Ridge(alpha=CFG["ridge_alpha"]).fit(sc.transform(tr[MODEL_COLS].values),
                                                tr["R"].values)
        te["score"] = m.predict(sc.transform(te[MODEL_COLS].values))
        te["quintile"] = pd.qcut(te["score"].rank(method="first"), 5,
                                 labels=["Q1","Q2","Q3","Q4","Q5"])
        oos_frames.append(te)
        fold_rows.append(dict(fold=y, train=len(tr), test=len(te),
            IC_model=spearman(te["score"], te["R"]),
            IC_hand=spearman(te["hand_score"], te["R"])))
        for c, w in zip(MODEL_COLS, m.coef_):
            coef_rows.append(dict(fold=y, feature=c.replace("c_",""), weight=w))
    stab = quint = folds = None
    if fold_rows:
        folds = pd.DataFrame(fold_rows)
        coefs = pd.DataFrame(coef_rows)
        stab = coefs.groupby("feature")["weight"].agg(["mean","std"])
        stab["sign_consistency_pct"] = coefs.groupby("feature")["weight"].apply(
            lambda s: 100*max((s>0).mean(), (s<0).mean()))
        stab = stab.reindex(stab["mean"].abs().sort_values(ascending=False).index).reset_index()
        allq = pd.concat(oos_frames)
        quint = allq.groupby("quintile", observed=True).agg(
            signals=("win","size"), win_rate_pct=("win", lambda s: 100*s.mean()),
            stopped_pct=("day_stop", lambda s: 100*s.notna().mean()),
            avg_R_pct=("R","mean"), median_R_pct=("R","median")).reset_index()

    # ── 4. profit availability (exit context) ───────────────────────────────
    touch_rows = []
    for g in [5, 10, 15, 20]:
        col = f"day_tgt_{g}"
        touched = sig[col].notna()
        losers = sig["R"] <= 0
        touch_rows.append(dict(target=f"+{g}%",
            pct_signals_touched=100*touched.mean(),
            pct_losers_touched=100*(touched & losers).sum()/max(losers.sum(),1)))
    touch = pd.DataFrame(touch_rows)

    gloss = pd.DataFrame(GLOSSARY, columns=["term","meaning"])
    with pd.ExcelWriter(CFG["out_file"], engine="openpyxl") as xw:
        gloss.to_excel(xw, sheet_name="README_Glossary", index=False)
        base.to_excel(xw, sheet_name="Performance", index=False)
        ic.to_excel(xw, sheet_name="Feature_IC", index=False)
        if stab is not None:
            stab.to_excel(xw, sheet_name="Ridge_Weights", index=False)
            folds.to_excel(xw, sheet_name="Fold_Performance", index=False)
            quint.to_excel(xw, sheet_name="Score_Quintiles", index=False)
        touch.to_excel(xw, sheet_name="Profit_Touches", index=False)

    # ── console report ──────────────────────────────────────────────────────
    s, a = perf(sig), perf(panel)
    print("\n" + "="*72)
    print("BASE BREAKOUT (>=30% off high + base + fresh 50-SMA reclaim), 12-wk R")
    print("="*72)
    print(f"  Signals:  {int(s['signals']):,}   vs baseline = all {int(a['signals']):,} bars")
    print(f"  Win rate: {s['win_rate_%']:.1f}%   (all bars {a['win_rate_%']:.1f}%)")
    print(f"  Stopped:  {s['stopped_%']:.1f}%   (all bars {a['stopped_%']:.1f}%)")
    print(f"  Avg R:    {s['avg_R_%']:+.2f}%  (all bars {a['avg_R_%']:+.2f}%)")
    print(f"  Median R: {s['median_R_%']:+.2f}%  (all bars {a['median_R_%']:+.2f}%)")
    print(f"  Excess vs SPY: {s['avg_excess_vs_SPY_%']:+.2f}%  (all bars {a['avg_excess_vs_SPY_%']:+.2f}%)")
    print(f"  Avg MFE {s['avg_MFE_%']:+.1f}%  avg MAE {s['avg_MAE_%']:+.1f}%")
    print("\nTOP 10 FEATURES inside the setup (univariate IC vs R):")
    for _, r in ic.head(10).iterrows():
        flag = "STABLE" if r["sign_consistency_pct"] >= 75 else "unstable"
        print(f"  {r['feature']:<16} IC={r['mean_IC']:+.3f} [{flag} {r['sign_consistency_pct']:.0f}%]")
    if folds is not None:
        print(f"\nWalk-forward model IC {folds['IC_model'].mean():+.3f} | "
              f"hand score {folds['IC_hand'].mean():+.3f}")
        print("SCORE QUINTILES (out-of-sample):")
        for _, r in quint.iterrows():
            print(f"  {r['quintile']}  win {r['win_rate_pct']:5.1f}%  stopped {r['stopped_pct']:5.1f}%"
                  f"  avgR {r['avg_R_pct']:+6.2f}%  medianR {r['median_R_pct']:+6.2f}%")
    else:
        print("\n(too few signals for walk-forward model — univariate ICs only)")
    print("\nPROFIT AVAILABILITY:")
    for _, r in touch.iterrows():
        print(f"  {r['target']:<5} touched in {r['pct_signals_touched']:.1f}% of signals | "
              f"available in {r['pct_losers_touched']:.1f}% of losers")
    print("\nCaveat: survivorship bias hits this setup hardest — crashed stocks that")
    print("never recovered are missing. Win rates are upper bounds.")
    print(f"Output written to: {CFG['out_file']}")

if __name__ == "__main__":
    main()
