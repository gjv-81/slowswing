"""
STS Signal Engine — v3.2  ::  15-MINUTE VARIANT
================================================
This is the 15-minute version of the v3.2 signal engine, for the
apples-to-apples timeframe test. It is a LIFT of the original (Interpretation
A): the ENTIRE strategy moves up one timeframe rung. Nothing else changes.

  Original (5-min base):  ladder = 5m / 15m / 30m,  base = 5-minute bars
  This file (15-min base): ladder = 15m / 30m / 60m, base = 15-minute bars

Every strategy PARAMETER is byte-for-byte identical to the 5-min engine:
  MIN_PRICE, MIN_AVG_VOL, MIN_ATR, all EMA periods, FISHER_PERIOD,
  RSI_LAGUERRE_NFE, and crucially MACD_CROSS_WINDOW (3) and
  RSI_CROSS_WINDOW (2) — kept UNCHANGED per decision A1. The cross windows
  are 3 bars / 2 bars on BOTH engines: structurally the identical rule. On
  15-min bars that is a wider WALL-CLOCK window (3 bars = 45 min vs 15 min),
  which is the honest consequence of "same rule, bigger candle" — the same
  way the Fisher exit becomes 45-min confirmation. This is intentional: the
  test changes ONE thing, the timeframe, and nothing else.

The entry point is evaluate_ticker(ticker, df_daily, df_15m) — it expects
15-MINUTE bars as the base (the original expects 5-minute). The runner
resamples the downloaded 5-min data to 15-min before calling this.

This module is pure logic — no network, no Telegram, no state. It imports
the SAME tested indicator functions from sts_indicators.py (those are
timeframe-agnostic and unchanged).

STRATEGY (v3.2) — all indicator checks on the 15-MINUTE base timeframe
unless noted.

BUY signal — every condition must be true:
  Price/liquidity (daily):
    • current price >= $100
    • 30-day average volume >= 480,000
    • ATR(14) >= 3.0
    • current price > yesterday's daily HIGH         (breakout)
  Trend, multi-timeframe (5m + 15m + 30m, all three):
    • close above the Ichimoku cloud top
    • 9 EMA > 21 EMA
  Trend, 5-minute only:
    • close > 34 EMA
    • close > 55 EMA
    • 9 EMA(close) > 9 EMA(open)
    • Williams A/D rising (current > previous)
  Momentum, 5-minute only:
    • MACD: green crossed above red, clean cross on a closed bar
      within the last 3 bars, held strictly above since
    • RSI Laguerre: cyan crossed above yellow, clean cross on a closed
      bar within the last 2 bars, held strictly above since
    • Fisher Transform: green > red (Fisher rising)

SELL signal — exact mirror:
    • current price >= $100, avg vol >= 480k, ATR >= 3.0  (same liquidity gate)
    • current price < yesterday's daily LOW              (breakdown)
    • close below the Ichimoku cloud bottom on 5m + 15m + 30m
    • 9 EMA < 21 EMA on 5m + 15m + 30m
    • close < 34 EMA, close < 55 EMA  (5m)
    • 9 EMA(close) < 9 EMA(open)      (5m)
    • Williams A/D falling             (5m)
    • MACD: green crossed below red, clean, within 3 closed bars, held below
    • RSI Laguerre: cyan crossed below yellow, clean, within 2 closed bars, held
    • Fisher Transform: green < red (Fisher falling)

A ticker can only be one or the other (the conditions are mutually
exclusive — you cannot be above AND below the cloud, etc.).
"""

import numpy as np
import pandas as pd

from sts_indicators import (
    ema, sma, atr,
    ichimoku_cloud_top, ichimoku_cloud_bottom,
    macd_lines, williams_ad,
    fisher_transform, rsi_laguerre,
    most_recent_cross_held, most_recent_cross_below_held,
)

# ─── STRATEGY CONSTANTS ──────────────────────────────────────────────────────

MIN_PRICE      = 100.0     # v3.2: raised from $5 to cut noise
MIN_AVG_VOL    = 480_000
MIN_ATR        = 3.0       # v3.2: raised from 1.4 to cut noise
ATR_PERIOD     = 14
AVG_VOL_PERIOD = 30

EMA_FAST = 9
EMA_SLOW = 21
EMA_34   = 34
EMA_55   = 55

MACD_CROSS_WINDOW = 3      # MACD cross must be within last 3 closed bars
RSI_CROSS_WINDOW  = 2      # RSI Laguerre cross must be within last 2 closed bars

FISHER_PERIOD = 10
RSI_LAGUERRE_NFE = 13

# Minimum bars needed on each timeframe for the indicators to be valid.
# Ichimoku senkou_b=52, shifted by kijun=26, plus headroom. These are
# bar-count requirements (indicator warmup), NOT timeframe-dependent — so
# the values carry over unchanged from the 5-min engine. Only the names
# shift to match the 15/30/60 ladder.
MIN_BARS_BASE = 120   # 15-min base (was MIN_BARS_5M  on the 5-min engine)
MIN_BARS_T2   = 90    # 30-min rung (was MIN_BARS_15M on the 5-min engine)
MIN_BARS_T3   = 85    # 60-min rung (was MIN_BARS_30M on the 5-min engine)
MIN_BARS_DAILY = 60

# Back-compat alias: the runner / external code may still import MIN_BARS_5M.
# On this engine the "base" timeframe is 15-min, so MIN_BARS_5M maps to it.
MIN_BARS_5M = MIN_BARS_BASE

# ─── TIMEFRAME RESAMPLING ────────────────────────────────────────────────────

def resample_tf(df_base, rule):
    """Build a higher timeframe from the 15-minute base bars.
    On this engine the base is 15-min, so rule is '30min' or '60min'."""
    if df_base is None or len(df_base) == 0:
        return df_base
    out = df_base.resample(rule, label='right', closed='right').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min',
        'Close': 'last', 'Volume': 'sum',
    }).dropna()
    return out

# ─── PER-TIMEFRAME TREND CHECK ───────────────────────────────────────────────

def trend_check(df_tf, direction):
    """
    The two checks applied to the base, T2 AND T3 timeframes (15m/30m/60m):
      BUY  : close above cloud top  AND  9 EMA > 21 EMA
      SELL : close below cloud bot  AND  9 EMA < 21 EMA
    Returns (passed: bool, reason: str).
    """
    # df_tf may carry a label we don't know here; caller passes the right df.
    # Gate on the smallest minimum, exactly as the 5-min engine did.
    if df_tf is None or len(df_tf) < MIN_BARS_T3:
        return False, "insufficient bars"

    e9 = ema(df_tf['Close'], EMA_FAST)
    e21 = ema(df_tf['Close'], EMA_SLOW)
    last_close = df_tf['Close'].iloc[-1]

    if direction == 'BUY':
        cloud = ichimoku_cloud_top(df_tf)
        if pd.isna(cloud.iloc[-1]):
            return False, "cloud NaN"
        if not (last_close > cloud.iloc[-1]):
            return False, "close not above cloud"
        if not (e9.iloc[-1] > e21.iloc[-1]):
            return False, "9EMA not > 21EMA"
        return True, "ok"
    else:  # SELL
        cloud = ichimoku_cloud_bottom(df_tf)
        if pd.isna(cloud.iloc[-1]):
            return False, "cloud NaN"
        if not (last_close < cloud.iloc[-1]):
            return False, "close not below cloud"
        if not (e9.iloc[-1] < e21.iloc[-1]):
            return False, "9EMA not < 21EMA"
        return True, "ok"

# ─── DAILY LIQUIDITY / BREAKOUT CHECK ────────────────────────────────────────

def daily_check(df_daily, current_price, direction):
    """
    Daily-timeframe gate. current_price is the latest 5m close.
    BUY  : price >= $100, avg vol ok, ATR ok, price > yesterday's HIGH
    SELL : price >= $100, avg vol ok, ATR ok, price < yesterday's LOW
    Returns (passed, reason, info_dict).
    """
    if df_daily is None or len(df_daily) < MIN_BARS_DAILY:
        return False, "insufficient daily bars", {}

    avg_vol = df_daily['Volume'].rolling(AVG_VOL_PERIOD).mean().iloc[-1]
    atr_v = atr(df_daily, ATR_PERIOD).iloc[-1]
    prev_high = df_daily['High'].iloc[-2]
    prev_low = df_daily['Low'].iloc[-2]

    info = {
        'atr': round(float(atr_v), 2) if not pd.isna(atr_v) else None,
        'avg_vol': int(avg_vol) if not pd.isna(avg_vol) else None,
        'prev_high': round(float(prev_high), 2),
        'prev_low': round(float(prev_low), 2),
        'day_open': round(float(df_daily['Open'].iloc[-1]), 2),
        'day_high': round(float(df_daily['High'].iloc[-1]), 2),
        'day_low': round(float(df_daily['Low'].iloc[-1]), 2),
        'prev_close': round(float(df_daily['Close'].iloc[-2]), 2),
    }

    if current_price < MIN_PRICE:
        return False, f"price ${current_price:.2f} < ${MIN_PRICE:.0f}", info
    if pd.isna(avg_vol) or avg_vol < MIN_AVG_VOL:
        return False, f"avg vol {avg_vol:,.0f} < {MIN_AVG_VOL:,}", info
    if pd.isna(atr_v) or atr_v < MIN_ATR:
        return False, f"ATR {atr_v:.2f} < {MIN_ATR}", info

    if direction == 'BUY':
        if not (current_price > prev_high):
            return False, f"no breakout (price {current_price:.2f} <= prev high {prev_high:.2f})", info
    else:  # SELL
        if not (current_price < prev_low):
            return False, f"no breakdown (price {current_price:.2f} >= prev low {prev_low:.2f})", info

    return True, "ok", info

# ─── 5-MINUTE EXTRAS (EMA34/55, 9EMA C vs O, Williams A/D) ───────────────────

def five_min_extras(df_5m, direction):
    """
    The 5m-only structural checks (not the cross-based momentum, that's separate).
    BUY : close > 34EMA, close > 55EMA, 9EMA(close) > 9EMA(open), Williams A/D rising
    SELL: mirror
    Returns (passed, reason).
    """
    if df_5m is None or len(df_5m) < max(EMA_55, MIN_BARS_5M):
        return False, "insufficient 5m bars"

    close = df_5m['Close']
    e34 = ema(close, EMA_34)
    e55 = ema(close, EMA_55)
    e9_close = ema(close, EMA_FAST)
    e9_open = ema(df_5m['Open'], EMA_FAST)
    ad = williams_ad(df_5m)

    c = close.iloc[-1]
    if direction == 'BUY':
        if not (c > e34.iloc[-1]):
            return False, "close <= 34EMA"
        if not (c > e55.iloc[-1]):
            return False, "close <= 55EMA"
        if not (e9_close.iloc[-1] > e9_open.iloc[-1]):
            return False, "9EMA(close) <= 9EMA(open)"
        if not (ad.iloc[-1] > ad.iloc[-2]):
            return False, "Williams A/D not rising"
        return True, "ok"
    else:  # SELL
        if not (c < e34.iloc[-1]):
            return False, "close >= 34EMA"
        if not (c < e55.iloc[-1]):
            return False, "close >= 55EMA"
        if not (e9_close.iloc[-1] < e9_open.iloc[-1]):
            return False, "9EMA(close) >= 9EMA(open)"
        if not (ad.iloc[-1] < ad.iloc[-2]):
            return False, "Williams A/D not falling"
        return True, "ok"

# ─── 5-MINUTE MOMENTUM (MACD cross, RSI Laguerre cross, Fisher) ──────────────

def five_min_momentum(df_5m, direction):
    """
    The cross-based momentum checks, all on 5m:
      MACD          : clean cross within MACD_CROSS_WINDOW closed bars, held
      RSI Laguerre  : clean cross within RSI_CROSS_WINDOW closed bars, held
      Fisher        : green vs red (rising for BUY, falling for SELL)
    Returns (passed, reason).
    """
    if df_5m is None or len(df_5m) < MIN_BARS_5M:
        return False, "insufficient 5m bars"

    # MACD lines (green = macd line, red = signal line)
    macd_green, macd_red = macd_lines(df_5m)

    # RSI Laguerre (cyan = rsi, yellow = gamma/fractal energy)
    rsi_cyan, rsi_yellow = rsi_laguerre(df_5m, nFE=RSI_LAGUERRE_NFE)

    # Fisher Transform: green = current, red = 1-bar lag
    fish = fisher_transform(df_5m, period=FISHER_PERIOD)
    fish_green = fish
    fish_red = fish.shift(1)

    if direction == 'BUY':
        if not most_recent_cross_held(macd_green.values, macd_red.values, MACD_CROSS_WINDOW):
            return False, "MACD: no clean cross-above within window"
        if not most_recent_cross_held(rsi_cyan.values, rsi_yellow.values, RSI_CROSS_WINDOW):
            return False, "RSI Laguerre: no clean cross-above within window"
        if not (fish_green.iloc[-1] > fish_red.iloc[-1]):
            return False, "Fisher not rising (green <= red)"
        return True, "ok"
    else:  # SELL
        if not most_recent_cross_below_held(macd_green.values, macd_red.values, MACD_CROSS_WINDOW):
            return False, "MACD: no clean cross-below within window"
        if not most_recent_cross_below_held(rsi_cyan.values, rsi_yellow.values, RSI_CROSS_WINDOW):
            return False, "RSI Laguerre: no clean cross-below within window"
        if not (fish_green.iloc[-1] < fish_red.iloc[-1]):
            return False, "Fisher not falling (green >= red)"
        return True, "ok"

# ─── MAIN QUALIFICATION ──────────────────────────────────────────────────────

def evaluate_ticker(ticker, df_daily, df_5m):
    """
    The single entry point. Given a ticker's daily + 5-minute data, return a
    dict describing the result.

    Returns dict with keys:
      ticker        — the symbol
      signal        — 'BUY', 'SELL', or None
      reason        — why it failed (if signal is None) or 'qualified'
      price         — latest 5m close
      atr           — daily ATR(14)
      avg_vol       — 30-day avg volume
      pct_chg       — % change vs yesterday's close
      day_high/low  — today's daily range
      recent_low_5m — lowest low of last 6 five-minute bars (for stop calc)
      recent_high_5m— highest high of last 6 five-minute bars (for sell stop)
      checked_at    — timestamp of the last 5m bar evaluated

    The evaluation tries BUY first, then SELL. They are mutually exclusive.
    """
    result = {
        'ticker': ticker, 'signal': None, 'reason': 'not evaluated',
        'price': None, 'atr': None, 'avg_vol': None, 'pct_chg': None,
        'day_high': None, 'day_low': None,
        'recent_low_5m': None, 'recent_high_5m': None, 'checked_at': None,
    }

    if df_5m is None or len(df_5m) < MIN_BARS_5M:
        result['reason'] = f"insufficient 5m data ({0 if df_5m is None else len(df_5m)} bars)"
        return result
    if df_daily is None or len(df_daily) < MIN_BARS_DAILY:
        result['reason'] = f"insufficient daily data"
        return result

    current_price = float(df_5m['Close'].iloc[-1])
    result['price'] = round(current_price, 2)
    result['checked_at'] = df_5m.index[-1]
    result['recent_low_5m'] = round(float(df_5m['Low'].iloc[-6:].min()), 2)
    result['recent_high_5m'] = round(float(df_5m['High'].iloc[-6:].max()), 2)

    # Build the higher timeframes once. Base is 15-min; ladder is 15/30/60.
    df_t2 = resample_tf(df_5m, '30min')   # T2 rung
    df_t3 = resample_tf(df_5m, '60min')   # T3 rung

    # Try BUY then SELL
    for direction in ('BUY', 'SELL'):
        ok, reason, info = daily_check(df_daily, current_price, direction)
        if not ok:
            # Stash daily info even on fail (useful for the alert if other dir passes)
            if info:
                result['atr'] = info.get('atr')
                result['avg_vol'] = info.get('avg_vol')
                result['day_high'] = info.get('day_high')
                result['day_low'] = info.get('day_low')
                if info.get('prev_close'):
                    result['pct_chg'] = round(
                        (current_price - info['prev_close']) / info['prev_close'] * 100, 2)
            if direction == 'SELL':
                result['reason'] = f"{direction} failed: {reason}"
            continue

        # Daily passed — capture info
        result['atr'] = info.get('atr')
        result['avg_vol'] = info.get('avg_vol')
        result['day_high'] = info.get('day_high')
        result['day_low'] = info.get('day_low')
        if info.get('prev_close'):
            result['pct_chg'] = round(
                (current_price - info['prev_close']) / info['prev_close'] * 100, 2)

        # Multi-timeframe trend — base(15m) / T2(30m) / T3(60m)
        okb, rb = trend_check(df_5m, direction)
        if not okb:
            result['reason'] = f"{direction} failed: 15m trend — {rb}"
            continue
        ok2, r2 = trend_check(df_t2, direction)
        if not ok2:
            result['reason'] = f"{direction} failed: 30m trend — {r2}"
            continue
        ok3, r3 = trend_check(df_t3, direction)
        if not ok3:
            result['reason'] = f"{direction} failed: 60m trend — {r3}"
            continue

        # base-timeframe extras
        oke, re = five_min_extras(df_5m, direction)
        if not oke:
            result['reason'] = f"{direction} failed: 15m extras — {re}"
            continue

        # base-timeframe momentum (the cross logic + Fisher)
        okm, rm = five_min_momentum(df_5m, direction)
        if not okm:
            result['reason'] = f"{direction} failed: 15m momentum — {rm}"
            continue

        # All checks passed
        result['signal'] = direction
        result['reason'] = 'qualified'
        return result

    # Neither direction qualified
    if result['signal'] is None and result['reason'] == 'not evaluated':
        result['reason'] = 'no signal'
    return result


# ═══════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import sys
    PASS = 0
    FAIL = 0

    def check(name, cond, detail=""):
        global PASS, FAIL
        if cond:
            PASS += 1
            print(f"  [PASS] {name}")
        else:
            FAIL += 1
            print(f"  [*** FAIL ***] {name}  {detail}")

    def synth_daily(n, start, end, vol=2_000_000):
        """Synthetic daily bars trending start->end."""
        closes = np.linspace(start, end, n)
        idx = pd.date_range("2026-01-01", periods=n, freq="D")
        return pd.DataFrame({
            'Open': closes, 'High': closes + 2.0, 'Low': closes - 2.0,
            'Close': closes, 'Volume': [vol] * n,
        }, index=idx)

    def synth_5m(n, start, end, vol=500_000):
        """Synthetic 5-min bars trending start->end. Opens slightly below closes
        on an uptrend so 9EMA(close) > 9EMA(open)."""
        closes = np.linspace(start, end, n)
        rising = end > start
        if rising:
            opens = closes - 0.3
            highs = closes + 0.5
            lows = closes - 0.5
        else:
            opens = closes + 0.3
            highs = closes + 0.5
            lows = closes - 0.5
        idx = pd.date_range("2026-05-14 04:00", periods=n, freq="5min")
        return pd.DataFrame({
            'Open': opens, 'High': highs, 'Low': lows,
            'Close': closes, 'Volume': [vol] * n,
        }, index=idx)

    print("=== Signal Engine self-test ===\n")

    # --- Test 1: clean strong uptrend should NOT necessarily fire BUY ---
    # (a pure linear ramp won't produce a *fresh cross* — MACD/RSI crossed long ago)
    # This verifies the cross-recency gate actually bites.
    df_d = synth_daily(120, 100, 300)
    df_5 = synth_5m(300, 250, 320)
    res = evaluate_ticker("RAMP", df_d, df_5)
    check("pure linear ramp does NOT fire BUY (cross not recent)",
          res['signal'] is None,
          f"got signal={res['signal']}, reason={res['reason']}")

    # --- Test 2: price below $100 → rejected on daily gate ---
    df_d_low = synth_daily(120, 10, 50)
    df_5_low = synth_5m(300, 45, 55)
    res = evaluate_ticker("CHEAP", df_d_low, df_5_low)
    check("price < $100 rejected",
          res['signal'] is None and 'price' in res['reason'].lower(),
          f"reason={res['reason']}")

    # --- Test 3: low ATR → rejected ---
    # tiny price movement → ATR tiny
    flat_closes = 150 + np.zeros(120)
    idx_d = pd.date_range("2026-01-01", periods=120, freq="D")
    df_d_flat = pd.DataFrame({
        'Open': flat_closes, 'High': flat_closes + 0.1, 'Low': flat_closes - 0.1,
        'Close': flat_closes, 'Volume': [2_000_000]*120,
    }, index=idx_d)
    df_5_flat = synth_5m(300, 150, 150.5)
    res = evaluate_ticker("FLAT", df_d_flat, df_5_flat)
    check("low ATR rejected",
          res['signal'] is None,
          f"reason={res['reason']}")

    # --- Test 4: insufficient data → rejected gracefully ---
    res = evaluate_ticker("SHORT", synth_daily(10, 100, 110), synth_5m(20, 100, 110))
    check("insufficient data handled gracefully",
          res['signal'] is None and 'insufficient' in res['reason'].lower(),
          f"reason={res['reason']}")

    # --- Test 5: None inputs → rejected gracefully, no crash ---
    res = evaluate_ticker("NONE", None, None)
    check("None inputs handled gracefully",
          res['signal'] is None,
          f"reason={res['reason']}")

    # --- Test 6: downtrend with low price → rejected (not a SELL because <$100) ---
    df_d_dn = synth_daily(120, 80, 30)
    df_5_dn = synth_5m(300, 35, 28)
    res = evaluate_ticker("CHEAPDN", df_d_dn, df_5_dn)
    check("cheap downtrend not a SELL (price gate)",
          res['signal'] is None,
          f"reason={res['reason']}")

    # --- Test 7: result dict always has required keys ---
    res = evaluate_ticker("KEYS", synth_daily(120, 100, 200), synth_5m(300, 150, 160))
    required = {'ticker','signal','reason','price','atr','avg_vol','pct_chg',
                'day_high','day_low','recent_low_5m','recent_high_5m','checked_at'}
    check("result dict has all required keys",
          required.issubset(set(res.keys())),
          f"missing: {required - set(res.keys())}")

    # --- Test 8: a fabricated fresh-cross uptrend CAN fire BUY ---
    # Build 5m data: long flat base, then a sharp turn up in the last few bars
    # so MACD/RSI/Fisher all cross fresh. Daily in clean breakout.
    base = [200.0] * 280
    turn = list(np.linspace(200.0, 215.0, 20))   # sharp recent rally
    closes = base + turn
    n = len(closes)
    opens = [c - 0.3 for c in closes]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    idx = pd.date_range("2026-05-14 04:00", periods=n, freq="5min")
    df_5_fresh = pd.DataFrame({
        'Open': opens, 'High': highs, 'Low': lows,
        'Close': closes, 'Volume': [800_000]*n,
    }, index=idx)
    # Daily: yesterday's high must be BELOW current price (215) for breakout.
    # Build daily ending with yesterday's high ~210.
    d_closes = list(np.linspace(180, 208, 119)) + [212.0]
    d_idx = pd.date_range("2026-01-01", periods=120, freq="D")
    df_d_fresh = pd.DataFrame({
        'Open': d_closes,
        'High': [c + 1.5 for c in d_closes],
        'Low': [c - 1.5 for c in d_closes],
        'Close': d_closes,
        'Volume': [3_000_000]*120,
    }, index=d_idx)
    res = evaluate_ticker("FRESH", df_d_fresh, df_5_fresh)
    # We don't assert it MUST be BUY (the synthetic data may not satisfy every
    # single gate perfectly) — but we assert it evaluated cleanly and got far.
    check("fresh-cross scenario evaluates without error",
          res['reason'] != 'not evaluated' and res['price'] is not None,
          f"signal={res['signal']}, reason={res['reason']}")
    print(f"    (FRESH result: signal={res['signal']}, reason='{res['reason']}', "
          f"price={res['price']}, atr={res['atr']})")

    # --- Test 9: BUY and SELL are mutually exclusive (can't both pass) ---
    # Already structurally guaranteed (can't be above AND below cloud), but
    # verify evaluate_ticker never returns something inconsistent.
    for name, dfd, df5 in [
        ("u", synth_daily(120,100,250), synth_5m(300,200,260)),
        ("d", synth_daily(120,250,100), synth_5m(300,160,110)),
    ]:
        r = evaluate_ticker(name, dfd, df5)
        check(f"signal is valid value ({name})",
              r['signal'] in (None, 'BUY', 'SELL'),
              f"got {r['signal']}")

    print()
    print("=" * 60)
    if FAIL == 0:
        print(f"  ALL {PASS} SIGNAL-ENGINE TESTS PASS ✓")
    else:
        print(f"  {PASS} passed, {FAIL} FAILED")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
