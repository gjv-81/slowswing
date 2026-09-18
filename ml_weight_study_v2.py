#!/usr/bin/env python3.12
# ============================================================================
# ML WEIGHT STUDY v2 — stop-adjusted target, exit rules, threshold table
# ============================================================================
# Changes vs v1:
#   1. COLLINEARITY FIX: MACD dropped from the model (near-duplicate of
#      EMA 9/21 — their v1 weights were a meaningless +4/-4 spread).
#      MACD still computed and still part of the 16-vote hand score baseline.
#   2. STOP-ADJUSTED TARGET: each bar is replayed forward day by day.
#      If the LOW breaches the stop (-13% MEGA >=$200B, -15% otherwise)
#      before day 60, the outcome is the stop loss. Otherwise it is the
#      12-week return. The model learns the trade you actually place.
#   3. THRESHOLD TABLE: out-of-sample score deciles -> win rate & avg return.
#      Pick your entry cutoff with measured odds, like >=14/18 today.
#   4. EXIT RULES: hold-to-12wk (stop only) vs profit targets +5/10/15/20%
#      (first touch wins; same-day tie goes to the stop — conservative).
#      Answers: are we giving back profits by holding 12 weeks?
#   5. GAVE-BACK ANALYSIS: of trades that ended flat/negative, how many had
#      +10% on the table at some point during the 12 weeks?
#
# HOW TO RUN (exact commands):
#   cd ~/Documents/STS/15min
#   caffeinate -i python3.12 ml_weight_study_v2.py
# First run recomputes features + price paths (~40-60 min), then caches to
# ml_panel_cache_v2.parquet — later reruns take seconds.
#
# OUTPUT: ONE file — ml_weight_study_v2.xlsx
# ============================================================================

import os, sys, glob, math, json, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

CFG = dict(
    data_dir       = os.path.expanduser("~/Documents/STS/15min/daily_data_10y"),
    cap_file       = os.path.expanduser("~/Documents/STS/15min/cap_cache.json"),
    out_file       = os.path.expanduser("~/Documents/STS/15min/ml_weight_study_v2.xlsx"),
    panel_cache    = os.path.expanduser("~/Documents/STS/15min/ml_panel_cache_v2.parquet"),
    horizon        = 60,
    sample_every   = 5,
    purge_days     = 90,
    min_train_years= 3,
    min_train_rows = 1000,
    ridge_alpha    = 10.0,
    min_bars       = 750,
    warmup         = 280,
    mega_cap       = 200e9,   # >= this market cap -> MEGA, stop -13%
    stop_mega      = -0.13,
    stop_other     = -0.15,
    targets        = [0.05, 0.10, 0.15, 0.20],
)

HAND_WEIGHTS = {"fisher": 3, "vwap20": 2, "ichimoku": 1, "volstop": 1,
    "macd": 1, "ema921": 1, "ea34": 1, "tmo": 1, "qqe": 1, "laguerre_adx": 1,
    "vidya": 1, "hull": 1, "supertrend_fast": 1, "supertrend_slow": 1,
    "tdfi": 1, "waddah": 1}
STS16 = list(HAND_WEIGHTS.keys())
STS15 = [k for k in STS16 if k != "macd"]          # collinearity fix
ADD7  = ["rs_8wk", "rs_4wk", "high52_prox", "mom_6mo", "dist_200dma",
         "rel_volume", "spy_regime"]
MODEL_COLS = [f"c_{k}" for k in STS15] + ADD7      # 22 features

GLOSSARY = [
 ("R (stop-adj return)", "The trade's outcome under your real rules: if the low breaches the stop (-13% MEGA / -15% others) within 60 trading days, R = the stop loss. Otherwise R = the 12-week return. All win rates use R > 0."),
 ("Tier", "MEGA = market cap >= $200B (stop -13%). LARGE/other = everything else (stop -15%). Caps from cap_cache.json; missing tickers treated as LARGE."),
 ("Threshold table", "All out-of-sample test bars ranked by model score and split into deciles (D10 = model's favorite 10%). Shows win rate and avg R per decile. Pick your entry cutoff from this — it replaces the hand-picked >=14/18."),
 ("Exit rule HOLD", "Enter, apply stop, otherwise hold the full 12 weeks. The baseline your exit-sweep work supported."),
 ("Exit rule T10 (etc.)", "Same, but bank the profit the first day the HIGH touches +10% (+5/15/20 similarly). Same-day stop-and-target tie counts as the stop (conservative)."),
 ("Gave-back", "Of trades that finished flat or negative under HOLD, the share that had +10% (or +5%) available at some point during the 12 weeks. High = holding is leaving profits on the table; low = losers never gave you an out."),
 ("MFE / MAE", "Max favorable / adverse excursion: the highest high and lowest low (vs entry) during the 60 days, in %."),
 ("Spearman IC", "Rank correlation between model score and realized R on unseen test years. 0 = coin flip; +0.05 tradeable; +0.10 strong."),
 ("Sign consistency", "% of test folds where a weight kept its sign. >=80% = trustworthy."),
 ("Suggested weight", "Mean learned weight rescaled so the largest = 3.0, rounded to 0.5. Negative = the indicator's bullish reading predicted worse outcomes."),
 ("Survivorship bias", "Universe = today's survivors; absolute win rates are upper bounds. Relative comparisons (deciles, exit rules) are more robust."),
]

# ─── helpers + indicators (identical formulas to v1 / live scanner) ─────────
def ema(s, n):  return s.ewm(span=n, adjust=False).mean()

def wma(s, n):
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

def true_range(df):
    pc = df["Close"].shift(1)
    return pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(),
                      (df["Low"] - pc).abs()], axis=1).max(axis=1)

def rsi_wilder(s, n=14):
    d = s.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / dn.ewm(alpha=1/n, adjust=False).mean().replace(0, 1e-10)
    return 100 - 100 / (1 + rs)

def fisher_series(df, period=10):
    mid = (df["High"] + df["Low"]) / 2
    hi, lo = mid.rolling(period).max(), mid.rolling(period).min()
    raw = (2 * ((mid - lo) / (hi - lo).replace(0, np.nan) - 0.5)).fillna(0).values
    val = np.zeros(len(raw)); fish = np.zeros(len(raw))
    for i in range(1, len(raw)):
        val[i]  = np.clip(0.33 * raw[i] + 0.67 * val[i-1], -0.999, 0.999)
        fish[i] = 0.5 * math.log((1 + val[i]) / (1 - val[i])) + 0.5 * fish[i-1]
    return pd.Series(fish, index=df.index)

def volstop_series(df, mult=3.0, length=10):
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

def laguerre_series(df, n=8):
    H, L, C = df["High"].values, df["Low"].values, df["Close"].values
    L0 = L1 = L2 = L3 = float(C[0])
    rv = np.full(len(C), 0.5); gm = np.full(len(C), 0.5)
    for i in range(len(C)):
        s = max(0, i - n + 1)
        rng = H[s:i+1].max() - L[s:i+1].min()
        if rng < 1e-10 or i < n - 1: continue
        tot = sum(max(H[j], C[j-1] if j > 0 else C[j]) -
                  min(L[j], C[j-1] if j > 0 else C[j]) for j in range(s, i+1))
        g = float(np.clip(math.log(tot / rng) / math.log(n) if tot > 0 else 0.5, 0, 1))
        l0 = (1-g)*C[i] + g*L0; l1 = -g*l0 + L0 + g*L1
        l2 = -g*l1 + L1 + g*L2; l3 = -g*l2 + L2 + g*L3
        L0, L1, L2, L3 = l0, l1, l2, l3
        CU = max(L0-L1, 0) + max(L1-L2, 0) + max(L2-L3, 0)
        CD = max(L1-L0, 0) + max(L2-L1, 0) + max(L3-L2, 0)
        rv[i] = CU / (CU + CD) if (CU + CD) else 0.5
        gm[i] = g
    return pd.Series(rv, index=df.index), pd.Series(gm, index=df.index)

def vidya_series(df, length=5):
    k = 1.0 / length
    src = df["Close"].values
    out = np.zeros(len(src)); out[0] = src[0]
    for i in range(1, len(src)):
        pdm = max(src[i] - src[i-1], 0); mdm = max(src[i-1] - src[i], 0)
        vI = abs(pdm - mdm) / (pdm + mdm + 1e-10)
        out[i] = (1 - k * vI) * out[i-1] + k * vI * src[i]
    return pd.Series(out, index=df.index)

# ─── path analysis: first-touch days for stops & targets ────────────────────
def path_columns(df, horizon, levels_dn, levels_up):
    """For each bar: MFE/MAE over next `horizon` bars and first-touch day
    (1-based) for each stop (on lows) and target (on highs). NaN = never."""
    n = len(df)
    C = df["Close"].values
    lo = np.concatenate([df["Low"].values[1:],  np.full(1, np.nan)])
    hi = np.concatenate([df["High"].values[1:], np.full(1, np.nan)])
    res = {f"day_stop_{int(abs(s)*100)}": np.full(n, np.nan) for s in levels_dn}
    res |= {f"day_tgt_{int(g*100)}": np.full(n, np.nan) for g in levels_up}
    res["mfe60"] = np.full(n, np.nan); res["mae60"] = np.full(n, np.nan)
    for i in range(n - 1):
        end = min(i + horizon, n - 1)
        w_lo = lo[i:end]; w_hi = hi[i:end]
        if len(w_lo) < horizon:  # incomplete window -> leave NaN (dropped later)
            continue
        res["mae60"][i] = np.nanmin(w_lo) / C[i] - 1
        res["mfe60"][i] = np.nanmax(w_hi) / C[i] - 1
        for s in levels_dn:
            idx = np.nonzero(w_lo <= C[i] * (1 + s))[0]
            if len(idx): res[f"day_stop_{int(abs(s)*100)}"][i] = idx[0] + 1
        for g in levels_up:
            idx = np.nonzero(w_hi >= C[i] * (1 + g))[0]
            if len(idx): res[f"day_tgt_{int(g*100)}"][i] = idx[0] + 1
    return pd.DataFrame(res, index=df.index)

# ─── features (same as v1) + paths + target ────────────────────────────────
def build_features(df, spy):
    out = pd.DataFrame(index=df.index)
    C, H, L, V = df["Close"], df["High"], df["Low"], df["Volume"]
    atr = true_range(df).ewm(span=14, adjust=False).mean().replace(0, np.nan)

    ft = fisher_series(df)
    out["c_fisher"] = ft - ft.shift(1)
    out["v_fisher"] = np.sign(out["c_fisher"]).replace(0, -1)

    tp = (H + L + C) / 3
    vwap20 = (tp * V).rolling(20).sum() / V.rolling(20).sum().replace(0, np.nan)
    out["c_vwap20"] = (C - vwap20) / atr
    out["v_vwap20"] = np.sign(out["c_vwap20"]).replace(0, -1)

    tenkan = (H.rolling(9).max() + L.rolling(9).min()) / 2
    kijun  = (H.rolling(26).max() + L.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((H.rolling(52).max() + L.rolling(52).min()) / 2).shift(26)
    upper = pd.concat([span_a, span_b], axis=1).max(axis=1)
    lower = pd.concat([span_a, span_b], axis=1).min(axis=1)
    out["c_ichimoku"] = (C - (upper + lower) / 2) / atr
    out["v_ichimoku"] = np.where(C > upper, 1, np.where(C < lower, -1, 0))

    vs = volstop_series(df)
    out["c_volstop"] = vs.astype(float); out["v_volstop"] = vs

    macd = ema(C, 12) - ema(C, 26)          # kept for hand score only
    out["v_macd"] = np.where(macd > 0, 1, -1)

    d921 = ema(C, 9) - ema(C, 21)
    out["c_ema921"] = d921 / atr
    out["v_ema921"] = np.where(d921 > 0, 1, -1)

    hi34, lo34 = ema(H, 34), ema(L, 34)
    out["c_ea34"] = (C - (hi34 + lo34) / 2) / atr
    out["v_ea34"] = np.where(C > hi34, 1, np.where(C < lo34, -1, 0))

    O = df["Open"]
    sig_sum = sum(np.sign(C - O.shift(j)).fillna(0) for j in range(14))
    main = ema(ema(pd.Series(sig_sum, index=df.index), 5), 3)
    tsig = ema(main, 3)
    out["c_tmo"] = (main - tsig) / 14.0
    out["v_tmo"] = np.where(main > tsig, 1, -1)

    rsi_s = rsi_wilder(C, 20).fillna(50)
    rsi_ma = ema(rsi_s, 5)
    dar = ema(ema(rsi_ma.diff().abs(), 39), 39) * 4.236
    out["c_qqe"] = (rsi_ma - 50) / 50
    out["v_qqe"] = np.where((rsi_ma >= 50) & (rsi_ma > rsi_ma - dar), 1,
                    np.where((rsi_ma <= 50) & (rsi_ma < rsi_ma + dar), -1, 0))

    lrsi, lgam = laguerre_series(df)
    atr9 = true_range(df).ewm(span=9, adjust=False).mean().replace(0, 1e-10)
    pdm = H.diff().clip(lower=0); mdm = (-L.diff()).clip(lower=0)
    pdi = 100 * pdm.ewm(span=9, adjust=False).mean() / atr9
    mdi = 100 * mdm.ewm(span=9, adjust=False).mean() / atr9
    adx = (((pdi - mdi).abs() / (pdi + mdi + 1e-10)) * 100).ewm(span=9, adjust=False).mean()
    bull = (pdi > mdi) & (adx > 35); bear = (mdi > pdi) & (adx > 35)
    out["c_laguerre_adx"] = lrsi - 0.5
    out["v_laguerre_adx"] = np.where((lrsi > lgam) | bull, 1,
                             np.where((lrsi < lgam) | bear, -1, 0))

    vid = vidya_series(df)
    out["c_vidya"] = (C - vid) / atr
    out["v_vidya"] = np.where(C > vid, 1, -1)

    hull = wma(2 * wma(C, 10) - wma(C, 20), 4)
    out["c_hull"] = (hull - hull.shift(1)) / atr
    out["v_hull"] = np.where(hull > hull.shift(1), 1, -1)

    st_f = supertrend_series(df, 1.5, 3)
    st_s = supertrend_series(df, 3.0, 5)
    out["c_supertrend_fast"] = st_f.astype(float); out["v_supertrend_fast"] = st_f
    out["c_supertrend_slow"] = st_s.astype(float); out["v_supertrend_slow"] = st_s

    src = C * 1000
    mma = ema(src, 13); smma = ema(mma, 13)
    avg = ((mma - mma.shift(1)) + (smma - smma.shift(1))) / 2
    tdf = (mma - smma).abs() * (avg.abs() ** 3) * np.sign(avg)
    peak = tdf.abs().rolling(39).max().replace(0, np.nan)
    tdfi = (tdf / peak).clip(-1, 1)
    out["c_tdfi"] = tdfi
    out["v_tdfi"] = np.where(tdfi > 0.05, 1, np.where(tdfi < -0.05, -1, 0))

    m = (ema(C, 20) - ema(C, 40)) * 150
    t1 = m - m.shift(1)
    bbm = C.rolling(20).mean(); bbs = C.rolling(20).std()
    e1 = ((bbm + 2*bbs) - (bbm - 2*bbs)).replace(0, np.nan)
    wv = (t1 / e1).clip(-2, 2)
    out["c_waddah"] = wv
    out["v_waddah"] = np.where(wv > 0.05, 1, np.where(wv < -0.05, -1, 0))

    spy_c = spy["Close"].reindex(df.index).ffill()
    out["rs_8wk"]      = C.pct_change(40) - spy_c.pct_change(40)
    out["rs_4wk"]      = C.pct_change(20) - spy_c.pct_change(20)
    out["high52_prox"] = C / C.rolling(252).max() - 1
    out["mom_6mo"]     = C.shift(10) / C.shift(126) - 1
    out["dist_200dma"] = (C - C.rolling(200).mean()) / atr
    out["rel_volume"]  = (V / V.rolling(20).mean().replace(0, np.nan)).clip(0, 10)
    spy_atr = true_range(spy).ewm(span=14, adjust=False).mean().replace(0, np.nan)
    spy_reg = (spy["Close"] - spy["Close"].rolling(200).mean()) / spy_atr
    out["spy_regime"]  = spy_reg.reindex(df.index).ffill()

    out["fwd_12wk"] = (C.shift(-CFG["horizon"]) / C - 1) * 100
    spy_fwd         = (spy_c.shift(-CFG["horizon"]) / spy_c - 1) * 100
    out["fwd_12wk_excess"] = out["fwd_12wk"] - spy_fwd
    out["hand_score"] = sum(HAND_WEIGHTS[k] * out[f"v_{k}"] for k in STS16)

    paths = path_columns(df, CFG["horizon"],
                         [CFG["stop_mega"], CFG["stop_other"]], CFG["targets"])
    return pd.concat([out, paths], axis=1)

def load_ticker(path):
    if path.endswith(".parquet"): df = pd.read_parquet(path)
    else:                          df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce", utc=True).tz_localize(None)
    df = df[df.index.notna()]
    cols = {c.lower().strip(): c for c in df.columns}
    need = ["open", "high", "low", "close", "volume"]
    if not all(k in cols for k in need): return None
    df = df[[cols[k] for k in need]]
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    df = df.apply(pd.to_numeric, errors="coerce").dropna()
    return df.sort_index() if len(df) else None

def load_universe():
    files = sorted(glob.glob(os.path.join(CFG["data_dir"], "*.parquet")) +
                   glob.glob(os.path.join(CFG["data_dir"], "*.csv")))
    if not files: sys.exit(f"ERROR: no data files in {CFG['data_dir']}")
    data = {}
    for f in files:
        t = os.path.splitext(os.path.basename(f))[0].upper()
        if t in data: continue
        df = load_ticker(f)
        if df is None: print(f"  skip {t}: bad columns"); continue
        if t != "SPY" and len(df) < CFG["min_bars"]:
            print(f"  skip {t}: {len(df)} bars"); continue
        data[t] = df
    if "SPY" not in data: sys.exit("ERROR: SPY missing from data folder.")
    return data

def load_tiers():
    try:
        caps = json.load(open(CFG["cap_file"]))
        return {t: ("MEGA" if v >= CFG["mega_cap"] else "LARGE")
                for t, v in caps.items()}
    except Exception as e:
        print(f"  (cap_cache.json not usable: {e} — all tickers treated as LARGE)")
        return {}

def spearman_ic(pred, actual):
    if len(pred) < 30: return np.nan
    return pd.Series(pred).corr(pd.Series(actual), method="spearman")

def main():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    print("=" * 76)
    print("ML WEIGHT STUDY v2 — stop-adjusted 12-week target")
    print("=" * 76)
    if os.path.exists(CFG["panel_cache"]):
        print(f"\nUsing cached panel {CFG['panel_cache']} (delete to recompute)")
        panel = pd.read_parquet(CFG["panel_cache"])
    else:
        data = load_universe()
        spy = data["SPY"]
        tickers = [t for t in data if t != "SPY"]
        print(f"Loaded {len(tickers)} tickers + SPY. Computing features + paths ...")
        frames = []
        for n, t in enumerate(tickers, 1):
            try:
                f = build_features(data[t], spy)
                f = f.iloc[CFG["warmup"]:].iloc[::CFG["sample_every"]]
                f = f.replace([np.inf, -np.inf], np.nan)
                # path day_* columns are legitimately NaN (= never touched):
                core = [c for c in f.columns if not c.startswith("day_")]
                f = f.dropna(subset=core)
                if len(f):
                    f.insert(0, "ticker", t)
                    frames.append(f.reset_index(names="date"))
            except Exception as e:
                print(f"  {t}: FAILED ({e})")
            if n % 10 == 0 or n == len(tickers):
                print(f"  {n}/{len(tickers)} tickers done")
        panel = pd.concat(frames, ignore_index=True)
        panel.to_parquet(CFG["panel_cache"])
        print(f"Panel cached to {CFG['panel_cache']}")
    panel["date"] = pd.to_datetime(panel["date"])

    # ── tiered stop-adjusted outcome R ──────────────────────────────────────
    tiers = load_tiers()
    panel["tier"] = panel["ticker"].map(tiers).fillna("LARGE")
    is_mega = panel["tier"].eq("MEGA")
    panel["day_stop"] = np.where(is_mega, panel["day_stop_13"], panel["day_stop_15"])
    panel["stop_pct"] = np.where(is_mega, CFG["stop_mega"], CFG["stop_other"]) * 100
    stopped = panel["day_stop"].notna()
    panel["R"] = np.where(stopped, panel["stop_pct"], panel["fwd_12wk"])
    panel["win"] = (panel["R"] > 0).astype(int)
    print(f"\nPanel: {len(panel):,} rows | stopped out: {100*stopped.mean():.1f}% "
          f"| win rate (R>0): {100*panel['win'].mean():.1f}%")

    # ── walk-forward ────────────────────────────────────────────────────────
    years = sorted(panel["date"].dt.year.unique())
    test_years = [y for y in years if y >= years[0] + CFG["min_train_years"]]
    perf_rows, coef_rows, oos_frames = [], [], []
    for y in test_years:
        cut = pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=CFG["purge_days"])
        tr = panel[panel["date"] < cut]
        te = panel[panel["date"].dt.year == y].copy()
        if len(tr) < CFG["min_train_rows"] or len(te) < 100: continue
        sc = StandardScaler().fit(tr[MODEL_COLS].values)
        model = Ridge(alpha=CFG["ridge_alpha"]).fit(
            sc.transform(tr[MODEL_COLS].values), tr["R"].values)
        te["score"] = model.predict(sc.transform(te[MODEL_COLS].values))
        te["decile"] = pd.qcut(te["score"].rank(method="first"), 10,
                               labels=[f"D{i}" for i in range(1, 11)])
        oos_frames.append(te)
        perf_rows.append(dict(fold=y, train_rows=len(tr), test_rows=len(te),
            IC_model=spearman_ic(te["score"], te["R"]),
            IC_hand_score=spearman_ic(te["hand_score"], te["R"])))
        for c, w in zip(MODEL_COLS, model.coef_):
            coef_rows.append(dict(fold=y, feature=c.replace("c_", ""), weight=w))
        print(f"  {y}: IC model {perf_rows[-1]['IC_model']:+.3f} | "
              f"hand {perf_rows[-1]['IC_hand_score']:+.3f}")
    if not perf_rows: sys.exit("ERROR: no valid folds.")
    perf = pd.DataFrame(perf_rows)
    coefs = pd.DataFrame(coef_rows)
    oos = pd.concat(oos_frames, ignore_index=True)   # pooled out-of-sample bars

    # ── weight stability ────────────────────────────────────────────────────
    stab = coefs.groupby("feature")["weight"].agg(["mean", "std"])
    stab["sign_consistency_%"] = coefs.groupby("feature")["weight"].apply(
        lambda s: 100 * max((s > 0).mean(), (s < 0).mean()))
    stab["abs"] = stab["mean"].abs()
    stab = stab.sort_values("abs", ascending=False)
    stab["suggested_weight"] = (stab["mean"] * (3.0 / stab["abs"].max()) * 2).round() / 2
    stab["current_weight"] = [HAND_WEIGHTS.get(f, 0) for f in stab.index]
    stab = stab.drop(columns="abs").reset_index()

    # ── threshold table (pooled OOS deciles) ────────────────────────────────
    thr = oos.groupby("decile", observed=True).agg(
        bars=("win", "size"), win_rate_pct=("win", lambda s: 100 * s.mean()),
        stopped_pct=("day_stop", lambda s: 100 * s.notna().mean()),
        avg_R_pct=("R", "mean"), median_R_pct=("R", "median"),
        avg_excess_pct=("fwd_12wk_excess", "mean")).reset_index()

    # ── exit rules on the model's top decile & top quintile ────────────────
    def exit_rule_returns(df, tgt=None):
        """R under: stop / optional profit target / else hold to 12wk."""
        if tgt is None:
            return df["R"]
        dt = df[f"day_tgt_{int(tgt*100)}"]
        hit_t = dt.notna(); hit_s = df["day_stop"].notna()
        tgt_first = hit_t & (~hit_s | (dt < df["day_stop"]))   # tie -> stop
        return pd.Series(np.where(tgt_first, tgt * 100,
                          np.where(hit_s, df["stop_pct"], df["fwd_12wk"])),
                         index=df.index)
    exit_rows = []
    subsets = {"Top_decile_D10": oos[oos["decile"] == "D10"],
               "Top_quintile_D9_D10": oos[oos["decile"].isin(["D9", "D10"])],
               "All_OOS_bars": oos}
    for name, sub in subsets.items():
        for rule, tgt in [("HOLD_12wk", None)] + [
                (f"T{int(g*100)}", g) for g in CFG["targets"]]:
            r = exit_rule_returns(sub, tgt)
            exit_rows.append(dict(subset=name, rule=rule, trades=len(r),
                win_rate_pct=100 * (r > 0).mean(), avg_ret_pct=r.mean(),
                median_ret_pct=r.median()))
    exits = pd.DataFrame(exit_rows)

    # ── gave-back analysis (top quintile) ───────────────────────────────────
    tq = subsets["Top_quintile_D9_D10"]
    gb_rows = []
    for g in CFG["targets"]:
        touched = tq[f"day_tgt_{int(g*100)}"].notna()
        losers = tq["R"] <= 0
        gb_rows.append(dict(target=f"+{int(g*100)}%",
            pct_of_all_trades_touched=100 * touched.mean(),
            pct_of_losers_that_touched=100 * (touched & losers).sum() / max(losers.sum(), 1),
            pct_touched_but_finished_below=100 * (touched & (tq["fwd_12wk"] < g*100)).sum() / max(touched.sum(), 1)))
    gaveback = pd.DataFrame(gb_rows)

    # ── by-tier check ───────────────────────────────────────────────────────
    bytier = (oos[oos["decile"].isin(["D9", "D10"])]
              .groupby("tier").agg(trades=("win", "size"),
                  win_rate_pct=("win", lambda s: 100 * s.mean()),
                  avg_R_pct=("R", "mean"), median_R_pct=("R", "median"))
              .reset_index())

    means = perf[["IC_model", "IC_hand_score"]].mean()
    gloss = pd.DataFrame(GLOSSARY, columns=["term", "meaning"])
    with pd.ExcelWriter(CFG["out_file"], engine="openpyxl") as xw:
        gloss.to_excel(xw, sheet_name="README_Glossary", index=False)
        perf.to_excel(xw, sheet_name="Fold_Performance", index=False)
        stab.to_excel(xw, sheet_name="Weight_Stability", index=False)
        thr.to_excel(xw, sheet_name="Threshold_Table", index=False)
        exits.to_excel(xw, sheet_name="Exit_Rules", index=False)
        gaveback.to_excel(xw, sheet_name="GaveBack", index=False)
        bytier.to_excel(xw, sheet_name="By_Tier", index=False)

    print("\n" + "=" * 76)
    print("RESULTS — stop-adjusted 12-week outcome (R)")
    print("=" * 76)
    print(f"Model mean IC {means['IC_model']:+.4f}  |  hand score {means['IC_hand_score']:+.4f}"
          f"  |  model beats hand in "
          f"{int((perf['IC_model'] > perf['IC_hand_score']).sum())}/{len(perf)} folds")
    print("\nTHRESHOLD TABLE (out-of-sample deciles, D10 = best):")
    for _, r in thr.iterrows():
        print(f"  {r['decile']:<4} win {r['win_rate_pct']:5.1f}%  stopped {r['stopped_pct']:5.1f}%"
              f"  avgR {r['avg_R_pct']:+6.2f}%  medianR {r['median_R_pct']:+6.2f}%")
    print("\nEXIT RULES (top quintile of model score):")
    for _, r in exits[exits["subset"] == "Top_quintile_D9_D10"].iterrows():
        print(f"  {r['rule']:<10} win {r['win_rate_pct']:5.1f}%  "
              f"avg {r['avg_ret_pct']:+6.2f}%  median {r['median_ret_pct']:+6.2f}%")
    print("\nGAVE-BACK (top quintile):")
    for _, r in gaveback.iterrows():
        print(f"  {r['target']:<5} touched in {r['pct_of_all_trades_touched']:.1f}% of trades | "
              f"{r['pct_of_losers_that_touched']:.1f}% of LOSERS had it available | "
              f"{r['pct_touched_but_finished_below']:.1f}% of touchers finished below it")
    print("\nTOP 10 WEIGHTS:")
    for _, r in stab.head(10).iterrows():
        flag = "STABLE" if r["sign_consistency_%"] >= 80 else "unstable"
        print(f"  {r['feature']:<16} {r['mean']:+.3f}  [{flag} {r['sign_consistency_%']:.0f}%]"
              f"  suggested {r['suggested_weight']:+.1f} (current x{r['current_weight']})")
    print(f"\nCaveats: survivorship bias inflates absolute win rates; stop fills")
    print(f"assumed at the stop level (gaps through the stop fill worse).")
    print(f"Output written to: {CFG['out_file']}")

if __name__ == "__main__":
    main()
