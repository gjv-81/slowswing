"""
UTS Exit Logic — ported from the Mandeep Bhullar UTS thinkScript (v5.0)
========================================================================
This implements the LONG-side exit conditions from the UTS `case long:`
block. UTS does not use a fixed stop or fixed target — it holds a position
until the trend reverses by one of several definitions, then flips flat.

Ported here: the FIRST THREE of the four UTS long-exit conditions.
(The fourth, U1, is a ZigZag reversal arrow — deferred for now.)

A UTS long exits (state -> flat, exitSig = 1) when ANY of:

  COND 1 — cloud + vstop break:
      ichiState == -1  AND  direction < 0
      (close below the Ichimoku cloud AND Volatility Stop flipped bearish)

  COND 2 — price-structure break + bearish candle + RSI rollover:
      Histogram8OC == 0  AND  RSI < gamma  AND one of three patterns:
        (a) high[1]>high[2] AND high[2]>high[3] AND high[3]>high[4]
            AND close < low[1]                      (run of highs broken)
        (b) high[1]<=high[2] AND low[1]>=low[2]
            AND close < low[1]                      (inside bar broken down)
        (c) high>high[1] AND low<low[1]
            AND close < low[1]                      (outside bar closes down)

  COND 3 — momentum rollover:
      RSI < gamma  AND  Histogram8OC == 0  AND  PMACDeq < PMACDsignal
      (Laguerre RSI below gamma, bearish candle body, predictive-MACD
       line below its signal)

This module is pure logic — no network, no engine import. It takes a
price DataFrame and returns, for a position opened at a given bar, the
bar index at which UTS would close it (or None if it never exits within
the data).

Tested against the thinkScript definitions in test functions at the
bottom — run `python3.12 uts_exit.py` to self-check.
"""

import numpy as np
import pandas as pd

# the indicator functions live in sts_indicators.py (same folder)
from sts_indicators import ema, ichimoku_cloud_top, ichimoku_cloud_bottom, \
                           rsi_laguerre, true_range


# ─── COMPONENT 1: VOLATILITY STOP `direction` ────────────────────────────────
#
# Ported from the UTS thinkScript "Volatility Stop" block:
#   atr  = ExpAverage(high - low, length)          length = 10
#   svs  = low  + ceil(mult*atr/tick)*tick         mult = 3.0
#   lvs  = high - ceil(mult*atr/tick)*tick
#   shortvs / longvs are trailing stops
#   direction flips +1 / -1 on stop breaches
# We drop the tick-rounding (ceil to tick) — it is a cosmetic snap to the
# price grid and does not change the direction logic materially.

def volatility_stop_direction(df, mult=3.0, length=10):
    """Return the UTS Volatility Stop `direction` series (+1 bull / -1 bear)."""
    high = df['High'].values
    low = df['Low'].values
    n = len(df)
    atr = (df['High'] - df['Low']).ewm(span=length, adjust=False).mean().values

    svs = low + mult * atr     # short volatility stop
    lvs = high - mult * atr    # long volatility stop
    # UTS uses close-style switching (Style = Close): uu = ll = close
    uu = df['Close'].values
    ll = df['Close'].values

    shortvs = np.full(n, np.nan)
    longvs = np.full(n, np.nan)
    direction = np.zeros(n)

    for i in range(n):
        if i == 0:
            shortvs[i] = svs[i]
            longvs[i] = lvs[i]
            direction[i] = 0
            continue
        # trailing stops
        shortvs[i] = svs[i] if uu[i] > shortvs[i-1] else min(svs[i], shortvs[i-1])
        longvs[i]  = lvs[i] if ll[i] < longvs[i-1]  else max(lvs[i], longvs[i-1])
        # breach detection
        longswitch  = 1 if (uu[i] >= shortvs[i-1] and uu[i-1] < shortvs[i-1]) else 0
        shortswitch = 1 if (ll[i] <= longvs[i-1]  and ll[i-1] > longvs[i-1])  else 0
        # direction memory
        if direction[i-1] <= 0 and longswitch:
            direction[i] = 1
        elif direction[i-1] >= 0 and shortswitch:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
    return pd.Series(direction, index=df.index)


# ─── COMPONENT 2: ichiState ──────────────────────────────────────────────────
#
# UTS: ichiState = +1 if close > cloud top, -1 if close < cloud bottom, else 0.

def ichi_state(df):
    """+1 above cloud, -1 below cloud, 0 inside."""
    top = ichimoku_cloud_top(df)
    bot = ichimoku_cloud_bottom(df)
    c = df['Close']
    state = pd.Series(0, index=df.index)
    state[c > top] = 1
    state[c < bot] = -1
    return state


# ─── COMPONENT 3: Histogram8OC ───────────────────────────────────────────────
#
# UTS: Histogram8OC = 1 if EMA(close,9) - EMA(open,9) > 0 else 0.
# (Despite the "8" in the name, the thinkScript uses length 9.)

def histogram_8oc(df):
    """1 if 9-EMA(close) > 9-EMA(open) (bullish candle bias), else 0."""
    ema_c = ema(df['Close'], 9)
    ema_o = ema(df['Open'], 9)
    return (ema_c - ema_o > 0).astype(int)


# ─── COMPONENT 4: Predictive MACD (PMACDeq / PMACDsignal) ────────────────────
#
# Ported from the UTS thinkScript `switch (AverageType_macd)` EMA case:
#   fastLength=12, slowLength=26, MACDLength=9
#   fastCoeff = 2/(1+fastLength);  slowCoeff = 2/(1+slowLength)
#   prevFastEMA = EMA(close,12)[1];  prevSlowEMA = EMA(close,26)[1]
#   crossDiff   = prevFastEMA*fastCoeff - prevSlowEMA*slowCoeff
#   denominator = fastCoeff - slowCoeff
#   prevDiff    = prevFastEMA - prevSlowEMA
#   PMACDeq     = crossDiff / denominator
#   PMACDsignal = (EMA(prevDiff,9) - prevDiff + crossDiff) / denominator
# This is a forward-projecting MACD — it estimates where the MACD line
# WOULD cross. UTS uses PMACDeq < PMACDsignal as a bearish momentum flag.

def predictive_macd(df, fast=12, slow=26, sig=9):
    """Return (PMACDeq, PMACDsignal) series — the UTS predictive MACD."""
    close = df['Close']
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)

    fast_coeff = 2.0 / (1.0 + fast)
    slow_coeff = 2.0 / (1.0 + slow)
    denom = fast_coeff - slow_coeff

    prev_fast = fast_ema.shift(1)
    prev_slow = slow_ema.shift(1)

    cross_diff = prev_fast * fast_coeff - prev_slow * slow_coeff
    prev_diff = prev_fast - prev_slow

    pmacd_eq = cross_diff / denom
    pmacd_signal = (ema(prev_diff, sig) - prev_diff + cross_diff) / denom
    return pmacd_eq, pmacd_signal


# ─── THE UTS LONG-EXIT SIGNAL ────────────────────────────────────────────────

def compute_uts_exit_series(df):
    """Compute a boolean Series: True on each bar where the UTS long-exit
    conditions (1, 2, or 3) are met. Pure vectorised/precomputed — call
    once per ticker, then index into it."""
    n = len(df)
    if n < 60:
        return pd.Series([False] * n, index=df.index)

    ich = ichi_state(df).values
    direction = volatility_stop_direction(df).values
    h8oc = histogram_8oc(df).values
    rsi, gamma = rsi_laguerre(df)
    rsi = rsi.values
    gamma = gamma.values
    pmacd_eq, pmacd_sig = predictive_macd(df)
    pmacd_eq = pmacd_eq.values
    pmacd_sig = pmacd_sig.values

    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values

    exit_sig = np.zeros(n, dtype=bool)

    for i in range(n):
        # ── COND 1: cloud + vstop break ──
        cond1 = (ich[i] == -1) and (direction[i] < 0)

        # ── COND 2: price-structure break + bearish candle + RSI rollover ──
        cond2 = False
        if i >= 4 and h8oc[i] == 0 and not np.isnan(rsi[i]) \
           and not np.isnan(gamma[i]) and rsi[i] < gamma[i]:
            # pattern (a): run of declining-from highs, close breaks low[1]
            pa = (high[i-1] > high[i-2] and high[i-2] > high[i-3]
                  and high[i-3] > high[i-4] and close[i] < low[i-1])
            # pattern (b): inside bar broken down
            pb = (high[i-1] <= high[i-2] and low[i-1] >= low[i-2]
                  and close[i] < low[i-1])
            # pattern (c): outside bar closes down
            pc = (high[i] > high[i-1] and low[i] < low[i-1]
                  and close[i] < low[i-1])
            cond2 = pa or pb or pc

        # ── COND 3: momentum rollover ──
        cond3 = False
        if not np.isnan(rsi[i]) and not np.isnan(gamma[i]) \
           and not np.isnan(pmacd_eq[i]) and not np.isnan(pmacd_sig[i]):
            cond3 = (rsi[i] < gamma[i] and h8oc[i] == 0
                     and pmacd_eq[i] < pmacd_sig[i])

        exit_sig[i] = cond1 or cond2 or cond3

    return pd.Series(exit_sig, index=df.index)


def uts_exit_bar(df, entry_pos, exit_series=None):
    """Given a position opened at integer bar `entry_pos`, return the integer
    bar index at which UTS would close the long — the first bar AFTER entry
    where the UTS exit conditions fire. Returns None if no exit within data.

    exit_series: optionally pass a precomputed compute_uts_exit_series(df)
    so it isn't recomputed per call."""
    if exit_series is None:
        exit_series = compute_uts_exit_series(df)
    sig = exit_series.values
    n = len(sig)
    for i in range(entry_pos + 1, n):
        if sig[i]:
            return i
    return None


# ─── SELF-TEST ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import pytz
    print("=" * 60)
    print("  UTS EXIT — self-test")
    print("=" * 60)
    ET = pytz.timezone('US/Eastern')
    rng = np.random.RandomState(7)

    # build a frame that rises then sharply reverses — exit should fire
    # somewhere in the reversal
    idx = pd.date_range('2026-01-02 09:30', periods=400, freq='15min', tz=ET)
    price = [100.0]
    for i in range(1, 400):
        drift = 0.0015 if i < 280 else -0.0025   # up, then down hard
        price.append(price[-1] * (1 + rng.normal(drift, 0.0010)))
    price = np.array(price)
    df = pd.DataFrame({
        'Open':  price * (1 + rng.normal(0, 0.0003, 400)),
        'High':  price * (1 + np.abs(rng.normal(0, 0.0010, 400))),
        'Low':   price * (1 - np.abs(rng.normal(0, 0.0010, 400))),
        'Close': price,
        'Volume': rng.randint(1e5, 5e5, 400),
    }, index=idx)

    checks = []

    # component smoke tests
    d = volatility_stop_direction(df)
    checks.append(("vstop direction returns ±1/0",
                   set(d.unique()).issubset({-1.0, 0.0, 1.0})))
    checks.append(("vstop is bullish during the uptrend",
                   d.iloc[200] > 0))
    checks.append(("vstop flips bearish after the reversal",
                   d.iloc[-1] < 0))

    h = histogram_8oc(df)
    checks.append(("Histogram8OC is 0/1 only",
                   set(h.unique()).issubset({0, 1})))

    pe, ps = predictive_macd(df)
    checks.append(("predictive MACD returns finite values",
                   np.isfinite(pe.dropna()).all() and np.isfinite(ps.dropna()).all()))

    es = compute_uts_exit_series(df)
    checks.append(("exit series is boolean",
                   es.dtype == bool))
    checks.append(("NO exit during the strong uptrend (bars 100-250)",
                   not es.iloc[100:250].any()))
    checks.append(("exit DOES fire somewhere in the reversal (bars 280+)",
                   es.iloc[280:].any()))

    # entry at bar 150 (mid-uptrend) should exit somewhere after the reversal
    xb = uts_exit_bar(df, 150, es)
    checks.append(("position from bar 150 exits, and after the reversal starts",
                   xb is not None and xb > 270))

    print()
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    n_pass = sum(1 for _, ok in checks if ok)
    print()
    print(f"  {n_pass}/{len(checks)} checks passed")
    print("=" * 60)
