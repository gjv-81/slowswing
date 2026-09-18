"""
STS Indicators — v3.2
=====================
Standalone, tested indicator functions used by the STS Universe Scanner.

Kept separate from the scanner so the math can be unit-tested in isolation.
Every function here is exercised by test_indicators.py — run that before
trusting any change to this file.

Indicators:
  • ema, sma, true_range, atr        — basics
  • ichimoku_cloud_top               — Ichimoku upper boundary
  • macd_lines                       — MACD line + signal line (12,26,9 EXP)
  • williams_ad                      — Williams Accumulation/Distribution
  • fisher_transform                 — Ehlers Fisher Transform (H+L)/2, period 10
  • rsi_laguerre                     — Mobius RSI-in-Laguerre-Time w/ Fractal Energy

Cross / state helpers:
  • most_recent_cross_held           — clean cross of fast above slow, closed bars
  • most_recent_cross_below_held     — mirror: clean cross below
  • falling_sustained                — fast < slow on BOTH last N closed bars
  • crossed_above_within             — fast crossed above slow within last N closed bars
"""

import numpy as np
import pandas as pd

# ─── BASIC INDICATORS ────────────────────────────────────────────────────────

def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def sma(series, n):
    return series.rolling(n).mean()

def true_range(df):
    h, l, c = df['High'], df['Low'], df['Close']
    return pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)

def atr(df, n=14):
    return true_range(df).ewm(alpha=1.0 / n, adjust=False).mean()


# ─── ICHIMOKU ────────────────────────────────────────────────────────────────

def ichimoku_cloud_top(df, tenkan=9, kijun=26, senkou_b=52):
    """Upper boundary of the Ichimoku cloud (max of Span A, Span B)."""
    t = (df['High'].rolling(tenkan).max() + df['Low'].rolling(tenkan).min()) / 2
    k = (df['High'].rolling(kijun).max() + df['Low'].rolling(kijun).min()) / 2
    span_a = ((t + k) / 2).shift(kijun)
    span_b = ((df['High'].rolling(senkou_b).max() +
               df['Low'].rolling(senkou_b).min()) / 2).shift(kijun)
    return pd.concat([span_a, span_b], axis=1).max(axis=1)

def ichimoku_cloud_bottom(df, tenkan=9, kijun=26, senkou_b=52):
    """Lower boundary of the Ichimoku cloud (min of Span A, Span B). For sell side."""
    t = (df['High'].rolling(tenkan).max() + df['Low'].rolling(tenkan).min()) / 2
    k = (df['High'].rolling(kijun).max() + df['Low'].rolling(kijun).min()) / 2
    span_a = ((t + k) / 2).shift(kijun)
    span_b = ((df['High'].rolling(senkou_b).max() +
               df['Low'].rolling(senkou_b).min()) / 2).shift(kijun)
    return pd.concat([span_a, span_b], axis=1).min(axis=1)


# ─── MACD ────────────────────────────────────────────────────────────────────

def macd_lines(df, fast=12, slow=26, signal=9):
    """
    Returns (macd_line, signal_line) — the 'green' and 'red' lines on a TOS
    MACD panel. EXPONENTIAL moving averages, matching TOS MACD(12,26,9,EXP).
    macd_line  = EMA(close,12) - EMA(close,26)        (green)
    signal_line = EMA(macd_line, 9)                    (red)
    """
    macd_line = ema(df['Close'], fast) - ema(df['Close'], slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line


# ─── WILLIAMS A/D ────────────────────────────────────────────────────────────

def williams_ad(df):
    """
    Williams Accumulation/Distribution — cumulative line.
    Rises when buyers dominate, falls when sellers dominate.
    """
    n = len(df)
    if n < 2:
        return pd.Series([0.0] * n, index=df.index)
    ad = np.zeros(n)
    H, L, C = df['High'].values, df['Low'].values, df['Close'].values
    for i in range(1, n):
        if C[i] > C[i - 1]:
            ad[i] = ad[i - 1] + (C[i] - min(L[i], C[i - 1]))
        elif C[i] < C[i - 1]:
            ad[i] = ad[i - 1] + (C[i] - max(H[i], C[i - 1]))
        else:
            ad[i] = ad[i - 1]
    return pd.Series(ad, index=df.index)


# ─── FISHER TRANSFORM (Ehlers) ───────────────────────────────────────────────

def fisher_transform(df, period=10):
    """
    Ehlers Fisher Transform on (H+L)/2, matching TOS FisherTransform((H+L)/2, 10).

    The TOS/Ehlers algorithm:
      price   = (High + Low) / 2
      raw     = normalize price to -1..+1 over `period` (using min/max of price)
      value   = 0.33 * 2 * raw + 0.67 * value[1]   (smoothing)
      value   = clamp to (-0.999, 0.999)
      fisher  = 0.5 * ln((1+value)/(1-value)) + 0.5 * fisher[1]

    Returns a pandas Series (the 'fish' line). On a TOS chart the indicator
    plots this line and a 1-bar lag of it; in the scanner the lag is just
    fisher.shift(1), handled by the caller.
    """
    n = len(df)
    if n == 0:
        return pd.Series([], dtype=float)
    price = ((df['High'] + df['Low']) / 2.0).values
    max_h = pd.Series(price).rolling(period).max().values
    min_l = pd.Series(price).rolling(period).min().values

    value = np.zeros(n)
    fisher = np.zeros(n)
    for i in range(n):
        if i < period - 1 or np.isnan(max_h[i]) or np.isnan(min_l[i]):
            # Not enough history yet — leave as 0, carry forward
            value[i] = value[i - 1] if i > 0 else 0.0
            fisher[i] = fisher[i - 1] if i > 0 else 0.0
            continue
        rng = max_h[i] - min_l[i]
        if rng <= 0:
            raw = 0.0
        else:
            raw = (price[i] - min_l[i]) / rng - 0.5  # -0.5..+0.5
        prev_value = value[i - 1] if i > 0 else 0.0
        v = 0.33 * 2.0 * raw + 0.67 * prev_value
        # clamp
        v = max(min(v, 0.999), -0.999)
        value[i] = v
        prev_fisher = fisher[i - 1] if i > 0 else 0.0
        fisher[i] = 0.5 * np.log((1.0 + v) / (1.0 - v)) + 0.5 * prev_fisher
    return pd.Series(fisher, index=df.index)


# ─── RSI LAGUERRE w/ FRACTAL ENERGY (Mobius) ─────────────────────────────────

def rsi_laguerre(df, nFE=13):
    """
    Direct port of the Mobius "RSI in Laguerre Time Self Adjusting With
    Fractal Energy" thinkScript study.

    Returns (rsi, gamma):
      rsi   — the cyan line: Laguerre-filtered RSI, ranges 0..1
      gamma — the yellow line: Fractal Energy, ranges 0..1

    The two are independent measurements (RSI is momentum, gamma is
    fractal energy / compression) — they are NOT a fast/slow pair, but the
    scanner treats a cyan-crossing-yellow event as a signal per the user's
    strategy.

    thinkScript reference (Mobius V03.06.15.2016):
      o = (open + close[1]) / 2
      h = Max(high, close[1])
      l = Min(low, close[1])
      c = (o + h + l + close) / 4
      gamma = Log( Sum(Max(high,close[1]) - Min(low,close[1]), nFE)
                   / (Highest(high,nFE) - Lowest(low,nFE)) ) / Log(nFE)
      L0 = (1-gamma)*c + gamma*L0[1]
      L1 = -gamma*L0 + L0[1] + gamma*L1[1]
      L2 = -gamma*L1 + L1[1] + gamma*L2[1]
      L3 = -gamma*L2 + L2[1] + gamma*L3[1]
      CU/CD accumulate up/down movement across L0..L3
      RSI = CU / (CU + CD)   (0 if CU+CD == 0)
    """
    n = len(df)
    if n == 0:
        return pd.Series([], dtype=float), pd.Series([], dtype=float)

    openv = df['Open'].values
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values

    # close[1] = previous close; for the first bar thinkScript uses the bar's
    # own close as the "previous" (no prior data)
    prev_close = np.empty(n)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]

    o = (openv + prev_close) / 2.0
    h = np.maximum(high, prev_close)
    l = np.minimum(low, prev_close)
    c = (o + h + l + close) / 4.0

    # gamma (Fractal Energy) — yellow line
    # numerator   = Sum( Max(high,close[1]) - Min(low,close[1]), nFE )
    # denominator = Highest(high,nFE) - Lowest(low,nFE)
    hl_range = h - l  # Max(high,close[1]) - Min(low,close[1])  per bar
    num = pd.Series(hl_range).rolling(nFE).sum().values
    highest_high = pd.Series(high).rolling(nFE).max().values
    lowest_low = pd.Series(low).rolling(nFE).min().values
    denom = highest_high - lowest_low

    gamma = np.full(n, np.nan)
    log_nfe = np.log(nFE)
    for i in range(n):
        if np.isnan(num[i]) or np.isnan(denom[i]) or denom[i] <= 0 or num[i] <= 0:
            gamma[i] = 0.5  # neutral fallback before enough data / degenerate range
        else:
            gamma[i] = np.log(num[i] / denom[i]) / log_nfe
        # gamma in thinkScript is unbounded in principle but practically 0..1-ish;
        # clamp lightly to keep the Laguerre recursion stable
        if gamma[i] < 0:
            gamma[i] = 0.0
        elif gamma[i] > 1:
            gamma[i] = 1.0

    # Laguerre filter cascade L0..L3, then CU/CD, then RSI
    L0 = np.zeros(n)
    L1 = np.zeros(n)
    L2 = np.zeros(n)
    L3 = np.zeros(n)
    rsi = np.zeros(n)

    for i in range(n):
        g = gamma[i]
        if i == 0:
            # thinkScript: L0[1] etc are 0 on the first bar (uninitialized → 0)
            L0[i] = (1 - g) * c[i]
            L1[i] = -g * L0[i]
            L2[i] = -g * L1[i]
            L3[i] = -g * L2[i]
        else:
            L0[i] = (1 - g) * c[i] + g * L0[i - 1]
            L1[i] = -g * L0[i] + L0[i - 1] + g * L1[i - 1]
            L2[i] = -g * L1[i] + L1[i - 1] + g * L2[i - 1]
            L3[i] = -g * L2[i] + L2[i - 1] + g * L3[i - 1]

        # CU/CD accumulation
        if L0[i] >= L1[i]:
            cu1 = L0[i] - L1[i]
            cd1 = 0.0
        else:
            cd1 = L1[i] - L0[i]
            cu1 = 0.0
        if L1[i] >= L2[i]:
            cu2 = cu1 + L1[i] - L2[i]
            cd2 = cd1
        else:
            cd2 = cd1 + L2[i] - L1[i]
            cu2 = cu1
        if L2[i] >= L3[i]:
            cu = cu2 + L2[i] - L3[i]
            cd = cd2
        else:
            cu = cu2
            cd = cd2 + L3[i] - L2[i]

        rsi[i] = cu / (cu + cd) if (cu + cd) != 0 else 0.0

    return pd.Series(rsi, index=df.index), pd.Series(gamma, index=df.index)


# ─── CROSS / STATE HELPERS ───────────────────────────────────────────────────

def most_recent_cross_held(fast, slow, window):
    """
    True if:
      1. fast is strictly above slow on the current bar
      2. the most recent clean cross of fast above slow happened on a CLOSED
         bar within `window` bars (bars_ago in 1..window — current bar excluded,
         per Option B: only act on completed candles)
      3. fast has been strictly above slow on every bar since that cross
    A bar where fast == slow counts as a break (no clear direction).

    fast, slow: array-like, most recent value last.
    """
    f = np.asarray(fast, dtype=float)
    s = np.asarray(slow, dtype=float)
    n = len(f)
    if n < 2:
        return False
    if not (f[-1] > s[-1]):
        return False
    # Walk back to find start of the current strictly-above run
    run_start = n - 1
    while run_start > 0 and f[run_start - 1] > s[run_start - 1]:
        run_start -= 1
    if run_start == 0:
        return False  # run extends to data start — no confirmable clean cross
    # Bar before the run must be STRICTLY below (equal = ambiguous = not clean)
    if not (f[run_start - 1] < s[run_start - 1]):
        return False
    bars_ago = (n - 1) - run_start
    return 1 <= bars_ago <= window


def most_recent_cross_below_held(fast, slow, window):
    """Mirror of most_recent_cross_held: clean cross of fast BELOW slow,
    on a closed bar within `window`, held strictly below since."""
    f = np.asarray(fast, dtype=float)
    s = np.asarray(slow, dtype=float)
    n = len(f)
    if n < 2:
        return False
    if not (f[-1] < s[-1]):
        return False
    run_start = n - 1
    while run_start > 0 and f[run_start - 1] < s[run_start - 1]:
        run_start -= 1
    if run_start == 0:
        return False
    if not (f[run_start - 1] > s[run_start - 1]):
        return False
    bars_ago = (n - 1) - run_start
    return 1 <= bars_ago <= window


def falling_sustained(fast, slow, bars=2):
    """
    True if fast < slow on EACH of the last `bars` CLOSED bars.
    Used for the LONG exit: FT falling, sustained — no flicker.
    'Closed bars' = excludes the current in-progress bar, so we look at
    indices [-(bars+1) : -1].
    """
    f = np.asarray(fast, dtype=float)
    s = np.asarray(slow, dtype=float)
    n = len(f)
    if n < bars + 1:
        return False
    closed = slice(n - 1 - bars, n - 1)  # last `bars` closed bars
    return bool(np.all(f[closed] < s[closed]))


def crossed_above_within(fast, slow, bars=2):
    """
    True if fast crossed above slow within the last `bars` CLOSED bars.
    Used for the SHORT exit: FT crossing back up (event, within window).
    A cross 'within' means: on at least one of the last `bars` closed bars,
    fast went from <= slow to > slow.
    """
    f = np.asarray(fast, dtype=float)
    s = np.asarray(slow, dtype=float)
    n = len(f)
    if n < bars + 2:
        return False
    # Closed bars are indices ... n-2 (n-1 is in-progress, excluded).
    # Check the last `bars` closed bars for a cross event.
    for idx in range(n - 1 - bars, n - 1):
        if idx < 1:
            continue
        if f[idx - 1] <= s[idx - 1] and f[idx] > s[idx]:
            return True
    return False
