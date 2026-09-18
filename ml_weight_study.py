#!/usr/bin/env python3.12
# ============================================================================
# ML WEIGHT STUDY — learn indicator weights from data (STS daily system)
# ============================================================================
# WHAT THIS DOES (plain language):
#   1. Loads 10-year daily OHLCV files from daily_data_10y/
#   2. Computes 23 features on every bar of every ticker:
#        - the 16 STS indicators (VWAP replaced with 20-day rolling VWAP),
#          each in TWO forms: the binary vote (+1/0/-1, same as the scanner)
#          and a CONTINUOUS strength value (how bullish, not just whether)
#        - 7 additions: RS 8-week, RS 4-week, 52-week-high proximity,
#          6-month momentum, distance from 200-DMA, relative volume,
#          SPY regime (all continuous)
#   3. Target (label): 12-week (60 trading-day) forward return
#   4. WALK-FORWARD validation: train on early years, test on the next
#      unseen year, slide forward, retrain. A 60-day purge gap between
#      train and test prevents label leakage. Bars are sampled every 5th
#      day so overlapping 60-day labels don't inflate confidence.
#   5. Four models compared on every test year:
#        A. HAND SCORE   — your current 18-point weighted vote score (baseline)
#        B. VOTES-16     — ridge regression on the 16 binary votes
#        C. CONT-16      — ridge regression on the 16 continuous values
#        D. FULL-23      — ridge on 16 continuous + 7 additions
#   6. Output: ONE file — ml_weight_study.xlsx (learned weights, stability,
#      per-fold performance, suggested integer weights, glossary)
#
# HOW TO RUN (exact commands):
#   pip3.12 install pandas numpy scikit-learn openpyxl pyarrow --break-system-packages
#   cd ~/Documents/STS/15min
#   python3.12 ml_weight_study.py
#
# REQUIREMENTS: daily_data_10y/ must contain one file per ticker
# (TICKER.csv or TICKER.parquet) INCLUDING SPY (needed for RS + regime).
# ============================================================================

import os, sys, glob, math, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─── CONFIG ─────────────────────────────────────────────────────────────────
CFG = dict(
    data_dir       = os.path.expanduser("~/Documents/STS/15min/daily_data_10y"),
    out_file       = os.path.expanduser("~/Documents/STS/15min/ml_weight_study.xlsx"),
    horizon        = 60,      # forward-return horizon in trading days (12 weeks)
    sample_every   = 5,       # keep every 5th bar (weekly) to de-overlap labels
    purge_days     = 90,      # calendar-day gap between train end and test start
    min_train_years= 3,       # first test fold needs >= this many training years
    min_train_rows = 1000,    # skip fold if training panel smaller than this
    ridge_alpha    = 10.0,    # ridge regularization strength
    min_bars       = 750,     # ticker must have >= this many daily bars
    warmup         = 280,     # bars dropped from start (252 rolling max + slack)
    panel_cache    = os.path.expanduser("~/Documents/STS/15min/ml_panel_cache.parquet"),
    # feature panel is cached after the slow computation — delete the cache
    # file (or change features) to force a full recompute
)

HAND_WEIGHTS = {  # current model: Fisher x3, VWAP x2, all others x1 (max 18)
    "fisher": 3, "vwap20": 2, "ichimoku": 1, "volstop": 1, "macd": 1,
    "ema921": 1, "ea34": 1, "tmo": 1, "qqe": 1, "laguerre_adx": 1,
    "vidya": 1, "hull": 1, "supertrend_fast": 1, "supertrend_slow": 1,
    "tdfi": 1, "waddah": 1,
}
STS16 = list(HAND_WEIGHTS.keys())
ADD7  = ["rs_8wk", "rs_4wk", "high52_prox", "mom_6mo", "dist_200dma",
         "rel_volume", "spy_regime"]

GLOSSARY = [
 ("fisher",          "Fisher Transform (10): today's FT minus yesterday's. Rising = bullish. Vote weight x3 in current model."),
 ("vwap20",          "REPLACED: 20-day rolling VWAP (volume-weighted avg price of last month). Feature = (close - VWAP20)/ATR. Old intraday VWAP is meaningless on daily bars."),
 ("ichimoku",        "Ichimoku 9/26/52: (close - cloud midpoint)/ATR. Vote: above cloud +1, below -1."),
 ("volstop",         "Volatility Stop (10, x3): trailing stop direction, inherently +1/-1 (state, no continuous form)."),
 ("macd",            "MACD 12/26: (EMA12 - EMA26)/ATR. Vote: line above zero."),
 ("ema921",          "EMA 9/21: (EMA9 - EMA21)/ATR. Vote: fast above slow."),
 ("ea34",            "EA34: (close - midpoint of EMA34(High)/EMA34(Low))/ATR. Vote: close above/below the band."),
 ("tmo",             "True Momentum Oscillator (14/5/3): main minus signal line, scaled by 14."),
 ("qqe",             "QQE (RSI 20, slow 5): smoothed RSI distance from 50, scaled to -1..+1."),
 ("laguerre_adx",    "Laguerre RSI (8) + ADX (9): Laguerre RSI minus 0.5. Vote uses the scanner's rsi>gamma / ADX>35 rule."),
 ("vidya",           "VIDYA (5): (close - VIDYA)/ATR. Adaptive MA that slows in chop."),
 ("hull",            "Hull MA (20): one-bar slope of the HMA divided by ATR. Vote: HMA rising."),
 ("supertrend_fast", "SuperTrend (x1.5, 3): trend state, +1/-1 (no continuous form)."),
 ("supertrend_slow", "SuperTrend (x3.0, 5): trend state, +1/-1 (no continuous form)."),
 ("tdfi",            "Trend Direction Force Index (13/13/3): normalized force value, -1..+1. Vote at +/-0.05."),
 ("waddah",          "Waddah Attar (150,20/40,BB20): MACD momentum burst / Bollinger width, clipped -1..+1. Vote at +/-0.05."),
 ("rs_8wk",          "ADDITION: stock 40-day return minus SPY 40-day return. Your strongest backtest variable (PF ~2.6 cell)."),
 ("rs_4wk",          "ADDITION: stock 20-day return minus SPY 20-day return. Soft 4-week RS = pullback-in-uptrend when 8-week is strong."),
 ("high52_prox",     "ADDITION: close / 252-day high, minus 1 (0 = at the high). George & Hwang 2004 momentum effect."),
 ("mom_6mo",         "ADDITION: return from 126 days ago to 10 days ago (skips last 2 weeks). Jegadeesh & Titman momentum."),
 ("dist_200dma",     "ADDITION: (close - 200-day SMA)/ATR. Continuous trend health (Faber-style, ranking not gate)."),
 ("rel_volume",      "ADDITION: volume / 20-day average volume. Institutional participation, continuous."),
 ("spy_regime",      "ADDITION: (SPY - SPY 200-DMA)/SPY ATR. Market health as a graded input, not a veto."),
 ("TARGET fwd_12wk", "12-week (60 trading-day) forward return of the stock, in %. What every model tries to predict."),
 ("Spearman IC",     "Rank correlation between model prediction and realized forward return on UNSEEN test data. >0.05 is meaningful for a single-horizon equity signal; higher is better."),
 ("Walk-forward",    "Train on early years -> test next unseen year -> slide forward and retrain. 90-calendar-day purge gap stops the model peeking at test-period outcomes."),
 ("Sign consistency","% of test folds where a feature's learned weight kept the same sign. >=80% = stable/trustworthy; ~50% = noise."),
 ("Suggested weight","Mean learned weight rescaled so the largest = 3.0 (matching your Fisher x3 convention), rounded to 0.5. NEGATIVE = indicator predicted the OPPOSITE of its vote direction."),
]

# ─── BASIC HELPERS ──────────────────────────────────────────────────────────
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

# ─── FULL-SERIES INDICATOR IMPLEMENTATIONS (match scanner formulas) ─────────
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

# ─── FEATURE MATRIX FOR ONE TICKER ──────────────────────────────────────────
def build_features(df, spy):
    """Returns DataFrame: 16 votes (v_*), 16 continuous (c_*), 7 additions, target."""
    out = pd.DataFrame(index=df.index)
    C, H, L, V = df["Close"], df["High"], df["Low"], df["Volume"]
    atr = true_range(df).ewm(span=14, adjust=False).mean().replace(0, np.nan)

    # 1. Fisher (x3 in current model)
    ft = fisher_series(df)
    out["c_fisher"] = ft - ft.shift(1)
    out["v_fisher"] = np.sign(out["c_fisher"]).replace(0, -1)

    # 2. VWAP -> 20-day rolling VWAP (x2 in current model)
    tp = (H + L + C) / 3
    vwap20 = (tp * V).rolling(20).sum() / V.rolling(20).sum().replace(0, np.nan)
    out["c_vwap20"] = (C - vwap20) / atr
    out["v_vwap20"] = np.sign(out["c_vwap20"]).replace(0, -1)

    # 3. Ichimoku 9/26/52
    tenkan = (H.rolling(9).max() + L.rolling(9).min()) / 2
    kijun  = (H.rolling(26).max() + L.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((H.rolling(52).max() + L.rolling(52).min()) / 2).shift(26)
    upper = pd.concat([span_a, span_b], axis=1).max(axis=1)
    lower = pd.concat([span_a, span_b], axis=1).min(axis=1)
    out["c_ichimoku"] = (C - (upper + lower) / 2) / atr
    out["v_ichimoku"] = np.where(C > upper, 1, np.where(C < lower, -1, 0))

    # 4. Volatility Stop (state variable — vote only)
    vs = volstop_series(df)
    out["c_volstop"] = vs.astype(float)
    out["v_volstop"] = vs

    # 5. MACD 12/26
    macd = ema(C, 12) - ema(C, 26)
    out["c_macd"] = macd / atr
    out["v_macd"] = np.where(macd > 0, 1, -1)

    # 6. EMA 9/21
    d921 = ema(C, 9) - ema(C, 21)
    out["c_ema921"] = d921 / atr
    out["v_ema921"] = np.where(d921 > 0, 1, -1)

    # 7. EA34
    hi34, lo34 = ema(H, 34), ema(L, 34)
    out["c_ea34"] = (C - (hi34 + lo34) / 2) / atr
    out["v_ea34"] = np.where(C > hi34, 1, np.where(C < lo34, -1, 0))

    # 8. TMO 14/5/3  (vectorized: sum of sign(C - O.shift(j)), j=0..13)
    O = df["Open"]
    sig_sum = sum(np.sign(C - O.shift(j)).fillna(0) for j in range(14))
    main = ema(ema(pd.Series(sig_sum, index=df.index), 5), 3)
    tsig = ema(main, 3)
    out["c_tmo"] = (main - tsig) / 14.0
    out["v_tmo"] = np.where(main > tsig, 1, -1)

    # 9. QQE (RSI 20, slow 5, factor 4.236)
    rsi_s = rsi_wilder(C, 20).fillna(50)
    rsi_ma = ema(rsi_s, 5)
    dar = ema(ema(rsi_ma.diff().abs(), 39), 39) * 4.236
    out["c_qqe"] = (rsi_ma - 50) / 50
    out["v_qqe"] = np.where((rsi_ma >= 50) & (rsi_ma > rsi_ma - dar), 1,
                    np.where((rsi_ma <= 50) & (rsi_ma < rsi_ma + dar), -1, 0))

    # 10. Laguerre RSI (8) + ADX (9)
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

    # 11. VIDYA (5)
    vid = vidya_series(df)
    out["c_vidya"] = (C - vid) / atr
    out["v_vidya"] = np.where(C > vid, 1, -1)

    # 12. Hull MA (20)
    hull = wma(2 * wma(C, 10) - wma(C, 20), 4)
    out["c_hull"] = (hull - hull.shift(1)) / atr
    out["v_hull"] = np.where(hull > hull.shift(1), 1, -1)

    # 13/14. SuperTrends (state variables — vote only)
    st_f = supertrend_series(df, 1.5, 3)
    st_s = supertrend_series(df, 3.0, 5)
    out["c_supertrend_fast"] = st_f.astype(float); out["v_supertrend_fast"] = st_f
    out["c_supertrend_slow"] = st_s.astype(float); out["v_supertrend_slow"] = st_s

    # 15. TDFI 13/13/3
    src = C * 1000
    mma = ema(src, 13); smma = ema(mma, 13)
    avg = ((mma - mma.shift(1)) + (smma - smma.shift(1))) / 2
    tdf = (mma - smma).abs() * (avg.abs() ** 3) * np.sign(avg)
    peak = tdf.abs().rolling(39).max().replace(0, np.nan)
    tdfi = (tdf / peak).clip(-1, 1)
    out["c_tdfi"] = tdfi
    out["v_tdfi"] = np.where(tdfi > 0.05, 1, np.where(tdfi < -0.05, -1, 0))

    # 16. Waddah Attar (150, 20/40, BB 20)
    m = (ema(C, 20) - ema(C, 40)) * 150
    t1 = m - m.shift(1)
    bbm = C.rolling(20).mean(); bbs = C.rolling(20).std()
    e1 = ((bbm + 2*bbs) - (bbm - 2*bbs)).replace(0, np.nan)
    wv = (t1 / e1).clip(-2, 2)
    out["c_waddah"] = wv
    out["v_waddah"] = np.where(wv > 0.05, 1, np.where(wv < -0.05, -1, 0))

    # ── 7 ADDITIONS (continuous) ────────────────────────────────────────────
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

    # ── TARGET ──────────────────────────────────────────────────────────────
    out["fwd_12wk"]        = (C.shift(-CFG["horizon"]) / C - 1) * 100
    spy_fwd                = (spy_c.shift(-CFG["horizon"]) / spy_c - 1) * 100
    out["fwd_12wk_excess"] = out["fwd_12wk"] - spy_fwd

    # hand score = current live model (Fisher x3, VWAP x2, rest x1)
    out["hand_score"] = sum(HAND_WEIGHTS[k] * out[f"v_{k}"] for k in STS16)
    return out

# ─── DATA LOADING ───────────────────────────────────────────────────────────
def load_ticker(path):
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce", utc=True).tz_localize(None)
    df = df[df.index.notna()]
    cols = {c.lower().strip(): c for c in df.columns}
    need = ["open", "high", "low", "close", "volume"]
    if not all(k in cols for k in need):
        return None
    df = df[[cols[k] for k in need]]
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    df = df.apply(pd.to_numeric, errors="coerce").dropna()
    return df.sort_index() if len(df) else None

def load_universe():
    files = sorted(glob.glob(os.path.join(CFG["data_dir"], "*.parquet")) +
                   glob.glob(os.path.join(CFG["data_dir"], "*.csv")))
    if not files:
        sys.exit(f"ERROR: no .csv/.parquet files found in {CFG['data_dir']}\n"
                 f"Run download_daily_yf.py first.")
    data = {}
    for f in files:
        t = os.path.splitext(os.path.basename(f))[0].upper()
        if t in data: continue
        df = load_ticker(f)
        if df is None:
            print(f"  skip {t}: missing OHLCV columns"); continue
        if t != "SPY" and len(df) < CFG["min_bars"]:
            print(f"  skip {t}: only {len(df)} bars (<{CFG['min_bars']})"); continue
        data[t] = df
    if "SPY" not in data:
        sys.exit("ERROR: SPY not found in data folder — required for RS features, "
                 "SPY regime, and excess returns. Add SPY to daily_data_10y/ and rerun.")
    return data

# ─── MAIN ───────────────────────────────────────────────────────────────────
def spearman_ic(pred, actual):
    if len(pred) < 30: return np.nan
    return pd.Series(pred).corr(pd.Series(actual), method="spearman")

def main():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    print("=" * 76)
    print("ML WEIGHT STUDY — STS daily system, 12-week forward return")
    print("=" * 76)
    if os.path.exists(CFG["panel_cache"]):
        print(f"\nFound cached feature panel: {CFG['panel_cache']}")
        print("Loading it (delete this file to force full recompute) ...")
        panel = pd.read_parquet(CFG["panel_cache"])
    else:
        print(f"\nLoading data from {CFG['data_dir']} ...")
        data = load_universe()
        spy = data["SPY"]
        tickers = [t for t in data if t != "SPY"]
        print(f"Loaded {len(tickers)} tickers + SPY "
              f"({spy.index[0].date()} to {spy.index[-1].date()})")

        print("\nComputing 23 features per ticker (loops for Fisher/VolStop/"
              "SuperTrend/Laguerre/VIDYA — this is the slow part) ...")
        frames = []
        for n, t in enumerate(tickers, 1):
            try:
                feats = build_features(data[t], spy)
                feats = feats.iloc[CFG["warmup"]:]                # drop warm-up bars
                feats = feats.iloc[::CFG["sample_every"]]         # weekly sampling
                feats = feats.replace([np.inf, -np.inf], np.nan).dropna()
                if len(feats):
                    feats.insert(0, "ticker", t)
                    frames.append(feats.reset_index(names="date"))
            except Exception as e:
                print(f"  {t}: FAILED ({e})")
            if n % 10 == 0 or n == len(tickers):
                print(f"  {n}/{len(tickers)} tickers done")
        panel = pd.concat(frames, ignore_index=True)
        panel.to_parquet(CFG["panel_cache"])
        print(f"Feature panel cached to {CFG['panel_cache']}")
    panel["date"] = pd.to_datetime(panel["date"])
    print(f"\nPanel: {len(panel):,} rows "
          f"({panel['date'].min().date()} to {panel['date'].max().date()})")

    vote_cols = [f"v_{k}" for k in STS16]
    cont_cols = [f"c_{k}" for k in STS16]
    full_cols = cont_cols + ADD7

    # ── walk-forward folds by calendar year ─────────────────────────────────
    years = sorted(panel["date"].dt.year.unique())
    first_test = years[0] + CFG["min_train_years"]
    test_years = [y for y in years if y >= first_test]
    print(f"Walk-forward test years: {test_years}\n")

    perf_rows, coef_rows = [], []
    for y in test_years:
        cut = pd.Timestamp(f"{y}-01-01") - pd.Timedelta(days=CFG["purge_days"])
        tr = panel[panel["date"] < cut]
        te = panel[panel["date"].dt.year == y]
        if len(tr) < CFG["min_train_rows"] or len(te) < 100:
            print(f"  {y}: skipped (train={len(tr)}, test={len(te)})"); continue
        ytr, yte = tr["fwd_12wk"].values, te["fwd_12wk"].values
        row = dict(fold=y, train_rows=len(tr), test_rows=len(te))

        # baseline A: hand score (no fitting)
        row["IC_hand_score"] = spearman_ic(te["hand_score"].values, yte)

        # models B, C, D
        for name, cols in [("votes16", vote_cols), ("cont16", cont_cols),
                           ("full23", full_cols)]:
            sc = StandardScaler().fit(tr[cols].values)
            model = Ridge(alpha=CFG["ridge_alpha"]).fit(sc.transform(tr[cols].values), ytr)
            pred = model.predict(sc.transform(te[cols].values))
            row[f"IC_{name}"] = spearman_ic(pred, yte)
            if name == "full23":
                row["R2_full23"] = model.score(sc.transform(te[cols].values), yte)
                for c, coef in zip(cols, model.coef_):
                    coef_rows.append(dict(fold=y, feature=c.replace("c_", ""),
                                          weight=coef))
        perf_rows.append(row)
        print(f"  {y}:  hand={row['IC_hand_score']:+.3f}  votes16={row['IC_votes16']:+.3f}"
              f"  cont16={row['IC_cont16']:+.3f}  full23={row['IC_full23']:+.3f}")

    if not perf_rows:
        sys.exit("\nERROR: no valid folds — not enough history. Need >= "
                 f"{CFG['min_train_years']+1} years of data.")

    perf = pd.DataFrame(perf_rows)
    coefs = pd.DataFrame(coef_rows)

    # ── weight stability + suggested integer weights ────────────────────────
    stab = coefs.groupby("feature")["weight"].agg(["mean", "std"])
    sign_cons = coefs.groupby("feature")["weight"].apply(
        lambda s: 100 * max((s > 0).mean(), (s < 0).mean()))
    stab["sign_consistency_%"] = sign_cons
    stab["abs_mean"] = stab["mean"].abs()
    stab = stab.sort_values("abs_mean", ascending=False)
    scale = 3.0 / stab["abs_mean"].max()
    stab["suggested_weight"] = (stab["mean"] * scale * 2).round() / 2
    stab["current_weight"] = [HAND_WEIGHTS.get(f, 0) for f in stab.index]
    stab = stab.drop(columns="abs_mean").reset_index()

    wide = coefs.pivot(index="feature", columns="fold", values="weight")
    wide["mean"] = wide.mean(axis=1)
    wide = wide.reindex(stab["feature"]).reset_index()

    # ── write ONE output file ───────────────────────────────────────────────
    means = perf[[c for c in perf.columns if c.startswith("IC_")]].mean()
    summary = pd.DataFrame({
        "model": ["A. Hand score (current 18-pt)", "B. Votes-16 (ML on binary votes)",
                  "C. Cont-16 (ML on continuous)", "D. Full-23 (continuous + additions)"],
        "mean_IC_out_of_sample": [means["IC_hand_score"], means["IC_votes16"],
                                  means["IC_cont16"], means["IC_full23"]],
        "folds_beating_hand_score": [
            "-",
            int((perf["IC_votes16"] > perf["IC_hand_score"]).sum()),
            int((perf["IC_cont16"]  > perf["IC_hand_score"]).sum()),
            int((perf["IC_full23"]  > perf["IC_hand_score"]).sum())],
    })
    gloss = pd.DataFrame(GLOSSARY, columns=["term", "meaning"])
    with pd.ExcelWriter(CFG["out_file"], engine="openpyxl") as xw:
        gloss.to_excel(xw, sheet_name="README_Glossary", index=False)
        summary.to_excel(xw, sheet_name="Model_Comparison", index=False)
        perf.to_excel(xw, sheet_name="Fold_Performance", index=False)
        stab.to_excel(xw, sheet_name="Weight_Stability", index=False)
        wide.to_excel(xw, sheet_name="Weights_By_Fold", index=False)

    # ── plain-language verdict ──────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("RESULTS (out-of-sample mean Spearman IC — higher = better predictor)")
    print("=" * 76)
    for _, r in summary.iterrows():
        print(f"  {r['model']:<42} IC = {r['mean_IC_out_of_sample']:+.4f}"
              f"   beats hand score in {r['folds_beating_hand_score']}/"
              f"{len(perf)} folds" if r["folds_beating_hand_score"] != "-" else
              f"  {r['model']:<42} IC = {r['mean_IC_out_of_sample']:+.4f}   (baseline)")
    print("\nTOP 10 FEATURES by learned weight (full-23 model, mean across folds):")
    for _, r in stab.head(10).iterrows():
        flag = "STABLE" if r["sign_consistency_%"] >= 80 else "unstable"
        print(f"  {r['feature']:<18} weight={r['mean']:+.3f}  "
              f"sign-consistent {r['sign_consistency_%']:.0f}% [{flag}]  "
              f"suggested={r['suggested_weight']:+.1f}  (current x{r['current_weight']})")
    print(f"\nHOW TO READ THIS (also in README_Glossary sheet):")
    print("  - IC = rank correlation between prediction and realized 12-wk return")
    print("    on data the model NEVER saw. 0.00 = coin flip, 0.05+ = real edge.")
    print("  - If cont16 > votes16: continuous values carry more info than votes")
    print("    (your gates-vs-ranking finding, confirmed at the indicator level).")
    print("  - If full23 > cont16: the 7 additions (RS, momentum, 52wk-high...)")
    print("    add signal beyond the 16 STS indicators.")
    print("  - Trust a weight only if sign-consistent >= 80% across folds.")
    print("  - NEGATIVE suggested weight = indicator predicted the OPPOSITE of")
    print("    its bullish vote at 12-week horizon (common for fast oscillators).")
    print(f"\nOutput written to: {CFG['out_file']}")

if __name__ == "__main__":
    main()
