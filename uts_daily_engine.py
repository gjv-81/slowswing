#!/usr/bin/env python3
"""
uts_daily_engine.py — UTS Aggressive BUY logic on DAILY bars
=============================================================
Ported from the Mandeep Bhullar UTS thinkScript (v5.0), AGGRESSIVE style,
LONG side only. Evaluates a daily OHLCV DataFrame and classifies the most
recent bar as FIRED, PRIMED, or no-signal.

UTS AGGRESSIVE long entry (from the thinkScript `case flat:` block):
  buySig = 1  when ALL of:
    numbar == 1           → Aggressive: ichiState == 1 AND smalleststate_MACD == 1
    TTM SqueezeAlert true  → coming out of a volatility squeeze
    direction > 0          → Volatility Stop bullish
    WilliamsAD > EMA(WilliamsAD, 57)
    close > EMA(close, 8)  AND > EMA(close,34) AND > EMA(close,55) AND > EMA(close,89)
    high[-1] > high        → NEXT bar makes a higher high (1-bar confirmation)

The `high[-1] > high` term is a forward reference in thinkScript — UTS only
PRINTS the arrow once the following bar confirms with a higher high. We use
that to split the output:

  FIRED   — every condition is met AND the confirmation bar has a higher
            high. The UTS arrow would be printed.
  PRIMED  — every condition is met EXCEPT the confirmation. This is the
            "about to fire" state — the end-of-day watch list.

This module is BUY-ONLY by design (the daily model does not trade SELL).

No network, no engine import — pure logic over a DataFrame. Self-test at
the bottom: run `python3.12 uts_daily_engine.py`.
"""

import numpy as np
import pandas as pd

from sts_indicators import ema, ichimoku_cloud_top, ichimoku_cloud_bottom, \
                           macd_lines, williams_ad
from uts_exit import volatility_stop_direction   # already built + tested

# minimum daily bars to evaluate (Ichimoku senkou-B alone needs 52 + shift)
MIN_BARS_DAILY = 120


# ─── UTS SQUEEZE STATE ───────────────────────────────────────────────────────
#
# Ported from the Mandeep Bhullar "Momentum Squeeze" thinkScript (v1.0).
# IMPORTANT — this is NOT the textbook "BB inside KC fires an alert" study.
# Reading the actual source:
#
#   SDup  = SMA(close,20) + 2.0 * StdDev(close,20)     ("BB-style" upper band)
#   ATRup = SMA(close,20) + 1.5 * ATR(20)              ("KC-style" upper band)
#   Squeeze = (SDup < ATRup)                           squeeze is ON
#
#   smalleststate = +1 if NO squeeze, -1 if squeeze ON, 0 otherwise
#
# So in the UTS convention, state = +1 means the squeeze is OFF — volatility
# has EXPANDED, the stock is moving. state = -1 means coiled/quiet. The UTS
# BUY condition wants the squeeze OFF (expansion), i.e. squeeze_off == True.
#
# This is a STATE (true for many bars during a move), not a one-bar release
# event. An earlier version of this engine modelled it as a single-bar
# "release" trigger AND with the polarity inverted — that produced almost no
# signals. This version matches the source.

def ttm_squeeze(df, length=20, sd_mult=2.0, atr_mult=1.5):
    """Return (squeeze_on, squeeze_off) boolean Series, per the UTS source.
       squeeze_on  : SDup < ATRup  — coiled, low volatility
       squeeze_off : SDup >= ATRup — volatility expanded (UTS BUY wants this)
    """
    close = df['Close']
    avg = close.rolling(length).mean()
    sd = close.rolling(length).std()
    sd_up = avg + sd_mult * sd

    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift()).abs(),
        (df['Low'] - df['Close'].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(length).mean()
    atr_up = avg + atr_mult * atr

    squeeze_on = (sd_up < atr_up).fillna(False)
    squeeze_off = (sd_up >= atr_up) & sd_up.notna() & atr_up.notna()
    return squeeze_on, squeeze_off.fillna(False)


# ─── ichiState ───────────────────────────────────────────────────────────────

def _ichi_state(df):
    """+1 above cloud, -1 below cloud, 0 inside (UTS ichiState)."""
    top = ichimoku_cloud_top(df)
    bot = ichimoku_cloud_bottom(df)
    c = df['Close']
    s = pd.Series(0, index=df.index)
    s[c > top] = 1
    s[c < bot] = -1
    return s


# ─── MACD STATE ──────────────────────────────────────────────────────────────

def _macd_state(df):
    """+1 if MACD line above signal, -1 if below (UTS smalleststate_MACD).

    NOTE: the UTS thinkScript defines smalleststate_MACD from the MACD
    HISTOGRAM vs the zero line (Diff > 0). MACD-line-above-signal is the
    same thing — the histogram IS (line - signal). Kept as line vs signal
    for clarity; identical result.
    """
    macd_line, signal_line = macd_lines(df)
    s = pd.Series(0, index=df.index)
    s[macd_line > signal_line] = 1
    s[macd_line < signal_line] = -1
    return s


# ─── THE UTS AGGRESSIVE BUY EVALUATION ───────────────────────────────────────

def compute_uts_daily_buy(df):
    """Compute, for every bar, the UTS Aggressive BUY component states and
    the FIRED / PRIMED classification. Returns a DataFrame indexed like df
    with one row per bar. Use the LAST row for an end-of-day scan, or any
    row for backtesting.

    Columns:
      ichi, macd, vstop, wad_rising, above_emas, squeeze_off  — components
      core_ok      — all six UTS Aggressive conditions met on this bar
      broke_out    — today's close above the prior bar's high
      signal       — core_ok AND broke_out (fresh breakout today)
      primed       — core_ok AND NOT broke_out (coiled, ready)
      fired        — alias of 'signal' (back-compat)
    """
    n = len(df)
    out = pd.DataFrame(index=df.index)
    if n < MIN_BARS_DAILY:
        for c in ['ichi', 'macd', 'vstop', 'wad_rising', 'above_emas',
                  'squeeze_off', 'core_ok', 'broke_out', 'signal',
                  'primed', 'fired']:
            out[c] = False
        return out

    ich = _ichi_state(df)
    macd = _macd_state(df)
    direction = volatility_stop_direction(df)

    wad = williams_ad(df)
    wad_ema = ema(wad, 57)
    wad_rising = wad > wad_ema

    close = df['Close']
    above_emas = ((close > ema(close, 8)) & (close > ema(close, 34)) &
                  (close > ema(close, 55)) & (close > ema(close, 89)))

    _, squeeze_off = ttm_squeeze(df)

    # numbar == 1  (Aggressive)
    numbar_buy = (ich == 1) & (macd == 1)

    # core: all six UTS Aggressive conditions met on this bar
    core_ok = (numbar_buy & (direction > 0) & wad_rising &
               above_emas & squeeze_off)

    # ── BREAKOUT-TODAY confirmation (replaces the old next-bar rule) ──
    # The UTS thinkScript uses `high[-1] > high` — a FORWARD reference
    # (the NEXT bar's high). On a live repainting TOS chart that works,
    # but in an end-of-day batch scan there is no "next bar": the latest
    # bar could never qualify, and on historical bars the FIRED/PRIMED
    # label just flickered on a meaningless coin-flip (diag_uts_daily.py
    # showed this clearly). So confirmation is redefined here as a
    # BACKWARD-looking, computable-today event:
    #
    #   broke_out = today's close is above the PRIOR bar's high
    #
    # This is honest (no future data), stable (no flicker), and gives a
    # genuinely useful split for an end-of-day swing scan.
    broke_out = df['Close'] > df['High'].shift(1)

    # 'signal' — all conditions met AND a fresh breakout today
    signal = core_ok & broke_out.fillna(False)
    # 'primed' — all conditions met, but no breakout today (coiled, ready)
    primed = core_ok & (~broke_out.fillna(False))

    out['ichi']         = ich
    out['macd']         = macd
    out['vstop']        = (direction > 0)
    out['wad_rising']   = wad_rising
    out['above_emas']   = above_emas
    out['squeeze_off']  = squeeze_off
    out['core_ok']      = core_ok
    out['broke_out']    = broke_out.fillna(False)
    out['primed']       = primed
    out['signal']       = signal
    # back-compat: keep 'fired' as an alias of 'signal' so any code that
    # imported the old name still works.
    out['fired']        = signal
    return out


def evaluate_daily(ticker, df):
    """Classify the MOST RECENT bar for an end-of-day scan.
    Returns a dict: {ticker, status, price, date, reason}.
    status is one of 'SIGNAL', 'PRIMED', 'none'.
      SIGNAL — all six UTS conditions met AND a fresh breakout today
               (close above the prior bar's high)
      PRIMED — all six conditions met, but no breakout today (coiled)"""
    if df is None or len(df) < MIN_BARS_DAILY:
        return {'ticker': ticker, 'status': 'none', 'price': None,
                'date': None, 'reason': f'insufficient daily bars '
                f'({0 if df is None else len(df)} < {MIN_BARS_DAILY})'}

    states = compute_uts_daily_buy(df)
    last = states.iloc[-1]
    price = float(df['Close'].iloc[-1])
    date = df.index[-1].date()

    if last['signal']:
        status = 'SIGNAL'
    elif last['primed']:
        status = 'PRIMED'
    else:
        status = 'none'

    # human-readable reason — which conditions are met / missing
    parts = []
    parts.append('cloud+' if last['ichi'] == 1 else 'cloud-')
    parts.append('macd+'  if last['macd'] == 1 else 'macd-')
    parts.append('vstop+' if last['vstop'] else 'vstop-')
    parts.append('wad+'   if last['wad_rising'] else 'wad-')
    parts.append('emas+'  if last['above_emas'] else 'emas-')
    parts.append('sqz+'   if last['squeeze_off'] else 'sqz-')
    reason = ' '.join(parts)

    return {'ticker': ticker, 'status': status, 'price': price,
            'date': date, 'reason': reason}


# ─── SELF-TEST ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import pytz
    print("=" * 60)
    print("  UTS DAILY ENGINE — self-test")
    print("=" * 60)
    ET = pytz.timezone('US/Eastern')
    rng = np.random.RandomState(13)

    checks = []

    # ── frame 1: a coiled base then a breakout — should reach core_ok ──
    idx = pd.date_range('2024-01-02', periods=300, freq='B', tz=ET)
    price = [100.0]
    for i in range(1, 300):
        if i < 220:
            drift = rng.normal(0.0, 0.004)        # choppy base (squeeze)
        else:
            drift = rng.normal(0.006, 0.004)      # breakout up
        price.append(max(1.0, price[-1] * (1 + drift)))
    price = np.array(price)
    df = pd.DataFrame({
        'Open':  price * (1 + rng.normal(0, 0.001, 300)),
        'High':  price * (1 + np.abs(rng.normal(0, 0.004, 300))),
        'Low':   price * (1 - np.abs(rng.normal(0, 0.004, 300))),
        'Close': price,
        'Volume': rng.randint(1e6, 5e6, 300),
    }, index=idx)

    states = compute_uts_daily_buy(df)
    checks.append(("output has one row per bar",
                   len(states) == len(df)))
    checks.append(("all classification columns are boolean",
                   all(states[c].dtype == bool for c in
                       ['core_ok', 'broke_out', 'signal', 'primed'])))
    checks.append(("SIGNAL and PRIMED are mutually exclusive",
                   not (states['signal'] & states['primed']).any()))
    checks.append(("SIGNAL implies core_ok",
                   (states['signal'] <= states['core_ok']).all()))
    checks.append(("PRIMED implies core_ok",
                   (states['primed'] <= states['core_ok']).all()))
    checks.append(("every core_ok bar is exactly one of SIGNAL or PRIMED",
                   ((states['signal'] | states['primed']) ==
                    states['core_ok']).all()))
    checks.append(("'fired' alias equals 'signal'",
                   (states['fired'] == states['signal']).all()))
    # signals should be CONCENTRATED in the breakout, not the base.
    # (A random-walk base can incidentally satisfy the conditions on the
    #  odd bar — that is correct, not a misfire. What matters is that the
    #  breakout produces far more signals than the choppy base.)
    base_hits = int(states['core_ok'].iloc[50:200].sum())
    breakout_hits = int(states['core_ok'].iloc[220:].sum())
    checks.append(("signals concentrate in the breakout, not the base "
                   f"(base={base_hits}, breakout={breakout_hits})",
                   breakout_hits > base_hits))

    # ── frame 2: pure downtrend — should NEVER fire a long ──
    dn = [100.0]
    for i in range(1, 300):
        dn.append(max(1.0, dn[-1] * (1 + rng.normal(-0.004, 0.004))))
    dn = np.array(dn)
    df_dn = pd.DataFrame({
        'Open':  dn * (1 + rng.normal(0, 0.001, 300)),
        'High':  dn * (1 + np.abs(rng.normal(0, 0.004, 300))),
        'Low':   dn * (1 - np.abs(rng.normal(0, 0.004, 300))),
        'Close': dn,
        'Volume': rng.randint(1e6, 5e6, 300),
    }, index=pd.date_range('2024-01-02', periods=300, freq='B', tz=ET))
    st_dn = compute_uts_daily_buy(df_dn)
    checks.append(("downtrend never produces SIGNAL",
                   not st_dn['signal'].any()))
    checks.append(("downtrend never produces PRIMED",
                   not st_dn['primed'].any()))

    # ── frame 3: too-short frame — graceful empty ──
    short = df.iloc[:50]
    st_short = compute_uts_daily_buy(short)
    checks.append(("short frame returns all-False, no crash",
                   not st_short['core_ok'].any()))

    # ── evaluate_daily smoke test ──
    res = evaluate_daily('TEST', df)
    checks.append(("evaluate_daily returns a valid status",
                   res['status'] in ('SIGNAL', 'PRIMED', 'none')))
    checks.append(("evaluate_daily reports price and reason",
                   res['price'] is not None and len(res['reason']) > 0))
    res_short = evaluate_daily('TEST', short)
    checks.append(("evaluate_daily handles short frame",
                   res_short['status'] == 'none' and
                   'insufficient' in res_short['reason']))

    print()
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    n_pass = sum(1 for _, ok in checks if ok)
    print()
    print(f"  {n_pass}/{len(checks)} checks passed")
    if n_pass == len(checks):
        # show how many signals the breakout frame produced, for sanity
        print(f"\n  (breakout frame: {int(states['signal'].sum())} SIGNAL, "
              f"{int(states['primed'].sum())} PRIMED bars across "
              f"{len(df)} days)")
    print("=" * 60)
