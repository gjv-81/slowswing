#!/usr/bin/env python3.12
# ============================================================================
# SLOW STS STUDY — the 16 STS indicators re-tuned to the 12-week horizon
# ============================================================================
# HYPOTHESIS TEST: earlier studies zeroed out the STS indicators — but their
# settings (Fisher 10, EMA 9/21, SuperTrend 3-5 bars...) carry 3-day-to-
# 2-month memory, mismatched to a 12-week horizon. Here every indicator is
# rebuilt with ~5x lookbacks (the "weekly edition" on daily bars):
#
#   Fisher 50 | rollVWAP 100d | Ichimoku 45/130/260 | VolStop len50
#   EMA 45/105 | EA34 -> EMA170 | TMO 70/25/15 | QQE RSI100
#   Laguerre 40 + ADX 45 | VIDYA 25 | Hull 100 | ST(1.5,15) ST(3.0,25)
#   TDFI 65/65 | Waddah 100/200 BB100          (MACD dropped, as in v2)
#
# FOUR MODELS, identical walk-forward, identical 12-week stop-adjusted
# target (from the v2 cache):
#   A. ADD7        — the 7 additions only (mom_6mo, high52_prox, ...)
#   B. FAST15+ADD7 — original STS settings + additions (the v2 model)
#   C. SLOW15+ADD7 — re-tuned STS + additions   <- the test
#   D. SLOW15      — re-tuned STS alone
# If C beats A and the slow indicators earn stable weights, the STS toolkit
# adds something beyond the simple features. If C == A, the additions
# already cover the slow scale and the indicator set is settled.
#
# HOW TO RUN (needs ml_panel_cache_v2.parquet):
#   cd ~/Documents/STS/15min
#   caffeinate -i python3.12 ml_slow_sts_study.py     (~40 min first run)
# OUTPUT: ONE file — ml_slow_sts_study.xlsx
# ============================================================================

import os, sys, glob, math, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

CFG = dict(
    data_dir    = os.path.expanduser("~/Documents/STS/15min/daily_data_10y"),
    panel_cache = os.path.expanduser("~/Documents/STS/15min/ml_panel_cache_v2.parquet"),
    slow_cache  = os.path.expanduser("~/Documents/STS/15min/ml_slow_feats_cache.parquet"),
    out_file    = os.path.expanduser("~/Documents/STS/15min/ml_slow_sts_study.xlsx"),
    mega_cap = 200e9, stop_mega = -0.13, stop_other = -0.15,
    cap_file = os.path.expanduser("~/Documents/STS/15min/cap_cache.json"),
    purge_days = 90, ridge_alpha = 10.0,
    min_train_rows = 1000, min_train_years = 3,
)

SLOW15 = ["s_fisher","s_vwap","s_ichimoku","s_volstop","s_ema","s_ea","s_tmo",
          "s_qqe","s_laguerre_adx","s_vidya","s_hull","s_st_fast","s_st_slow",
          "s_tdfi","s_waddah"]
FAST15 = ["c_fisher","c_vwap20","c_ichimoku","c_volstop","c_ema921","c_ea34",
          "c_tmo","c_qqe","c_laguerre_adx","c_vidya","c_hull",
          "c_supertrend_fast","c_supertrend_slow","c_tdfi","c_waddah"]
ADD7   = ["rs_8wk","rs_4wk","high52_prox","mom_6mo","dist_200dma",
          "rel_volume","spy_regime"]

GLOSSARY = [
 ("Slow settings", "Every STS indicator's lookback multiplied ~5x so its memory matches a 12-week horizon (e.g., Fisher 10->50 = 10 weeks of memory instead of 2)."),
 ("Model A (ADD7)", "Only the 7 additions. The bar the slow STS must clear."),
 ("Model B (FAST15+ADD7)", "Original STS settings + additions = the v2 model."),
 ("Model C (SLOW15+ADD7)", "Re-tuned STS + additions. THE TEST: does C beat A?"),
 ("Model D (SLOW15)", "Re-tuned STS alone — can the toolkit stand by itself?"),
 ("Target", "12-week stop-adjusted return R (fixed -13/-15% tiered stops), identical to v2."),
 ("Spearman IC", "Rank correlation of model score vs realized R on unseen test years."),
 ("Sign consistency", ">=80% across folds = a weight you can trust."),
]

def ema(s, n):  return s.ewm(span=n, adjust=False).mean()
def wma(s, n):
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)
def true_range(df):
    pc = df["Close"].shift(1)
    return pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(),
                      (df["Low"] - pc).abs()], axis=1).max(axis=1)
def rsi_wilder(s, n):
    d = s.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / dn.ewm(alpha=1/n, adjust=False).mean().replace(0, 1e-10)
    return 100 - 100 / (1 + rs)

def fisher_series(df, period):
    mid = (df["High"] + df["Low"]) / 2
    hi, lo = mid.rolling(period).max(), mid.rolling(period).min()
    raw = (2 * ((mid - lo) / (hi - lo).replace(0, np.nan) - 0.5)).fillna(0).values
    val = np.zeros(len(raw)); fish = np.zeros(len(raw))
    for i in range(1, len(raw)):
        val[i]  = np.clip(0.33 * raw[i] + 0.67 * val[i-1], -0.999, 0.999)
        fish[i] = 0.5 * math.log((1 + val[i]) / (1 - val[i])) + 0.5 * fish[i-1]
    return pd.Series(fish, index=df.index)

def volstop_series(df, mult, length):
    a = (df["High"] - df["Low"]).ewm(span=length, adjust=False).mean()
    svs = (df["Low"] + mult * a).values; lvs = (df["High"] - mult * a).values
    c = df["Close"].values
    dirs = np.zeros(len(df), dtype=int)
    for i in range(1, len(df)):
        if dirs[i-1] <= 0: dirs[i] = 1 if c[i] >= svs[i-1] else -1
        else:              dirs[i] = -1 if c[i] <= lvs[i-1] else 1
    return pd.Series(dirs, index=df.index)

def supertrend_series(df, mult, period):
    a = true_range(df).ewm(span=period, adjust=False).mean()
    hl2 = (df["High"] + df["Low"]) / 2
    up = (hl2 + mult * a).values; dn = (hl2 - mult * a).values
    c = df["Close"].values
    ub = up.copy(); db = dn.copy()
    tr = np.ones(len(df), dtype=int)
    for i in range(1, len(df)):
        ub[i] = min(up[i], ub[i-1]) if c[i-1] > ub[i-1] else up[i]
        db[i] = max(dn[i], db[i-1]) if c[i-1] < db[i-1] else dn[i]
        if   tr[i-1] == -1 and c[i] > ub[i-1]: tr[i] = 1
        elif tr[i-1] ==  1 and c[i] < db[i-1]: tr[i] = -1
        else:                                   tr[i] = tr[i-1]
    return pd.Series(tr, index=df.index)

def laguerre_series(df, n):
    """Adaptive-gamma Laguerre RSI (vectorized range/total, recursive filter)."""
    H, L, C = df["High"], df["Low"], df["Close"]
    pc = C.shift(1)
    trng = pd.concat([H, pc], axis=1).max(axis=1) - pd.concat([L, pc], axis=1).min(axis=1)
    tot = trng.rolling(n).sum().values
    rng = (H.rolling(n).max() - L.rolling(n).min()).values
    Cv = C.values
    L0 = L1 = L2 = L3 = float(Cv[0])
    rv = np.full(len(Cv), 0.5)
    for i in range(len(Cv)):
        if i < n - 1 or rng[i] < 1e-10 or not np.isfinite(tot[i]): continue
        g = float(np.clip(math.log(tot[i] / rng[i]) / math.log(n)
                          if tot[i] > 0 else 0.5, 0, 1))
        l0 = (1-g)*Cv[i] + g*L0; l1 = -g*l0 + L0 + g*L1
        l2 = -g*l1 + L1 + g*L2; l3 = -g*l2 + L2 + g*L3
        L0, L1, L2, L3 = l0, l1, l2, l3
        CU = max(L0-L1, 0) + max(L1-L2, 0) + max(L2-L3, 0)
        CD = max(L1-L0, 0) + max(L2-L1, 0) + max(L3-L2, 0)
        rv[i] = CU / (CU + CD) if (CU + CD) else 0.5
    return pd.Series(rv, index=df.index)

def vidya_series(df, length):
    k = 1.0 / length
    src = df["Close"].values
    out = np.zeros(len(src)); out[0] = src[0]
    for i in range(1, len(src)):
        pdm = max(src[i] - src[i-1], 0); mdm = max(src[i-1] - src[i], 0)
        vI = abs(pdm - mdm) / (pdm + mdm + 1e-10)
        out[i] = (1 - k * vI) * out[i-1] + k * vI * src[i]
    return pd.Series(out, index=df.index)

def build_slow(df):
    out = pd.DataFrame(index=df.index)
    C, H, L, V, O = df["Close"], df["High"], df["Low"], df["Volume"], df["Open"]
    atr = true_range(df).ewm(span=70, adjust=False).mean().replace(0, np.nan)

    ft = fisher_series(df, 50)
    out["s_fisher"] = ft - ft.shift(5)                       # weekly-scale slope

    tp = (H + L + C) / 3
    vwap = (tp * V).rolling(100).sum() / V.rolling(100).sum().replace(0, np.nan)
    out["s_vwap"] = (C - vwap) / atr

    tenkan = (H.rolling(45).max() + L.rolling(45).min()) / 2
    kijun  = (H.rolling(130).max() + L.rolling(130).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(130)
    span_b = ((H.rolling(260).max() + L.rolling(260).min()) / 2).shift(130)
    upper = pd.concat([span_a, span_b], axis=1).max(axis=1)
    lower = pd.concat([span_a, span_b], axis=1).min(axis=1)
    out["s_ichimoku"] = (C - (upper + lower) / 2) / atr

    out["s_volstop"] = volstop_series(df, 3.0, 50).astype(float)

    out["s_ema"] = (ema(C, 45) - ema(C, 105)) / atr

    hi, lo = ema(H, 170), ema(L, 170)
    out["s_ea"] = (C - (hi + lo) / 2) / atr

    sig_sum = sum(np.sign(C - O.shift(j)).fillna(0) for j in range(70))
    main = ema(ema(pd.Series(sig_sum, index=df.index), 25), 15)
    tsig = ema(main, 15)
    out["s_tmo"] = (main - tsig) / 70.0

    rsi_ma = ema(rsi_wilder(C, 100).fillna(50), 25)
    out["s_qqe"] = (rsi_ma - 50) / 50

    out["s_laguerre_adx"] = laguerre_series(df, 40) - 0.5

    out["s_vidya"] = (C - vidya_series(df, 25)) / atr

    hull = wma(2 * wma(C, 50) - wma(C, 100), 10)
    out["s_hull"] = (hull - hull.shift(5)) / atr

    out["s_st_fast"] = supertrend_series(df, 1.5, 15).astype(float)
    out["s_st_slow"] = supertrend_series(df, 3.0, 25).astype(float)

    src = C * 1000
    mma = ema(src, 65); smma = ema(mma, 65)
    avg = ((mma - mma.shift(1)) + (smma - smma.shift(1))) / 2
    tdf = (mma - smma).abs() * (avg.abs() ** 3) * np.sign(avg)
    peak = tdf.abs().rolling(195).max().replace(0, np.nan)
    out["s_tdfi"] = (tdf / peak).clip(-1, 1)

    m = (ema(C, 100) - ema(C, 200)) * 150
    t1 = m - m.shift(5)
    bbm = C.rolling(100).mean(); bbs = C.rolling(100).std()
    e1 = ((bbm + 2*bbs) - (bbm - 2*bbs)).replace(0, np.nan)
    out["s_waddah"] = (t1 / e1).clip(-2, 2)
    return out

def load_ohlcv(path):
    if path.endswith(".parquet"): df = pd.read_parquet(path)
    else:                          df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce", utc=True).tz_localize(None)
    df = df[df.index.notna()]
    cols = {c.lower().strip(): c for c in df.columns}
    need = ["open","high","low","close","volume"]
    if not all(k in cols for k in need): return None
    out = df[[cols[k] for k in need]].copy()
    out.columns = ["Open","High","Low","Close","Volume"]
    return out.apply(pd.to_numeric, errors="coerce").dropna().sort_index()

def spearman(a, b):
    return pd.Series(a).reset_index(drop=True).corr(
        pd.Series(b).reset_index(drop=True), method="spearman")

def main():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    import json

    if not os.path.exists(CFG["panel_cache"]):
        sys.exit("ERROR: run ml_weight_study_v2.py first (needs its cache).")
    print("Loading v2 panel cache ...")
    panel = pd.read_parquet(CFG["panel_cache"])
    panel["date"] = pd.to_datetime(panel["date"])

    if os.path.exists(CFG["slow_cache"]):
        print(f"Using cached slow features {CFG['slow_cache']} (delete to recompute)")
        slow = pd.read_parquet(CFG["slow_cache"])
    else:
        files = {os.path.splitext(os.path.basename(f))[0].upper(): f
                 for f in sorted(glob.glob(os.path.join(CFG["data_dir"], "*.csv")) +
                                 glob.glob(os.path.join(CFG["data_dir"], "*.parquet")))}
        tickers = [t for t in panel["ticker"].unique() if t in files]
        wanted = {t: set(g) for t, g in panel.groupby("ticker")["date"]}
        print(f"Computing slow STS features for {len(tickers)} tickers ...")
        frames = []
        for n, t in enumerate(tickers, 1):
            df = load_ohlcv(files[t])
            if df is None: continue
            s = build_slow(df)
            s = s[s.index.isin(wanted[t])]          # keep only panel dates
            s["ticker"] = t
            frames.append(s.reset_index(names="date"))
            if n % 10 == 0 or n == len(tickers): print(f"  {n}/{len(tickers)}")
        slow = pd.concat(frames, ignore_index=True)
        slow["date"] = pd.to_datetime(slow["date"])
        slow.to_parquet(CFG["slow_cache"])
        print(f"Cached to {CFG['slow_cache']}")
    panel = panel.merge(slow, on=["ticker","date"], how="inner")
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=SLOW15 + FAST15 + ADD7 + ["fwd_12wk"])
    panel["year"] = panel["date"].dt.year
    print(f"Merged panel: {len(panel):,} rows")

    try:
        caps = json.load(open(CFG["cap_file"]))
        mega = panel["ticker"].map(
            lambda t: (caps.get(t) or 0) >= CFG["mega_cap"])
    except Exception:
        mega = pd.Series(False, index=panel.index)
    day_stop = np.where(mega, panel["day_stop_13"], panel["day_stop_15"])
    stop_pct = np.where(mega, CFG["stop_mega"], CFG["stop_other"]) * 100
    panel["R"] = np.where(pd.notna(day_stop), stop_pct, panel["fwd_12wk"])

    MODELS = {"A_ADD7_only": ADD7,
              "B_FAST15_ADD7": FAST15 + ADD7,
              "C_SLOW15_ADD7": SLOW15 + ADD7,
              "D_SLOW15_only": SLOW15}

    years = sorted(panel["year"].unique())
    test_years = [y for y in years if y >= years[0] + CFG["min_train_years"]]
    perf_rows, coef_rows = [], []
    for y in test_years:
        cut = pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=CFG["purge_days"])
        tr = panel[panel["date"] < cut]
        te = panel[panel["year"] == y]
        if len(tr) < CFG["min_train_rows"] or len(te) < 100: continue
        row = dict(fold=y, train_rows=len(tr), test_rows=len(te))
        for name, cols in MODELS.items():
            sc = StandardScaler().fit(tr[cols].values)
            m = Ridge(alpha=CFG["ridge_alpha"]).fit(
                sc.transform(tr[cols].values), tr["R"].values)
            pred = m.predict(sc.transform(te[cols].values))
            row[f"IC_{name}"] = spearman(pred, te["R"].values)
            if name == "C_SLOW15_ADD7":
                for c, w in zip(cols, m.coef_):
                    coef_rows.append(dict(fold=y, feature=c, weight=w))
        perf_rows.append(row)
        print(f"  {y}: " + "  ".join(f"{k[3:]}={v:+.3f}" for k, v in row.items()
                                     if k.startswith("IC_")))
    if not perf_rows: sys.exit("ERROR: no valid folds.")
    perf = pd.DataFrame(perf_rows)
    coefs = pd.DataFrame(coef_rows)
    stab = coefs.groupby("feature")["weight"].agg(["mean","std"])
    stab["sign_consistency_%"] = coefs.groupby("feature")["weight"].apply(
        lambda s: 100*max((s>0).mean(), (s<0).mean()))
    stab["group"] = ["SLOW_STS" if f in SLOW15 else "ADDITION" for f in stab.index]
    stab = stab.reindex(stab["mean"].abs().sort_values(ascending=False).index).reset_index()

    means = perf[[c for c in perf.columns if c.startswith("IC_")]].mean()
    summary = pd.DataFrame({
        "model": list(MODELS.keys()),
        "mean_IC": [means[f"IC_{k}"] for k in MODELS],
        "folds_beating_A": ["-" if k == "A_ADD7_only" else
            int((perf[f"IC_{k}"] > perf["IC_A_ADD7_only"]).sum()) for k in MODELS]})

    gloss = pd.DataFrame(GLOSSARY, columns=["term","meaning"])
    with pd.ExcelWriter(CFG["out_file"], engine="openpyxl") as xw:
        gloss.to_excel(xw, sheet_name="README_Glossary", index=False)
        summary.to_excel(xw, sheet_name="Model_Comparison", index=False)
        perf.to_excel(xw, sheet_name="Fold_Performance", index=False)
        stab.to_excel(xw, sheet_name="Weights_C_SLOW15_ADD7", index=False)

    print("\n" + "="*72)
    print("SLOW STS TEST — out-of-sample mean IC (12-week stop-adjusted target)")
    print("="*72)
    for _, r in summary.iterrows():
        extra = ("(baseline)" if r["folds_beating_A"] == "-" else
                 f"beats ADD7-only in {r['folds_beating_A']}/{len(perf)} folds")
        print(f"  {r['model']:<16} IC = {r['mean_IC']:+.4f}   {extra}")
    print("\nTOP 12 WEIGHTS in model C (slow STS + additions):")
    for _, r in stab.head(12).iterrows():
        flag = "STABLE" if r["sign_consistency_%"] >= 80 else "unstable"
        print(f"  {r['feature']:<16} [{r['group']:<8}] {r['mean']:+.3f} "
              f"[{flag} {r['sign_consistency_%']:.0f}%]")
    print("\nREADING: if C > A and slow STS features hold STABLE weights, the")
    print("re-tuned toolkit adds real signal. If C == A, the additions already")
    print(f"cover the slow scale.\nOutput written to: {CFG['out_file']}")

if __name__ == "__main__":
    main()
