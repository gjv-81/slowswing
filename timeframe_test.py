#!/usr/bin/env python3
"""
STS — Timeframe Test  ::  5-minute vs 15-minute, apples-to-apples
==================================================================
Runs the EXACT SAME v3.2 strategy on two timeframes against the SAME frozen
local dataset, and lays the results side by side. The only variable is the
timeframe. If the strategy is broken it will be broken on both; if 15-min
genuinely helps, the numbers will show it.

  5-min run : uses sts_signal_engine.py      (base = 5-min,  ladder 5/15/30)
  15-min run: uses sts_signal_engine_15m.py  (base = 15-min, ladder 15/30/60)

Both engines are byte-for-byte identical in every PARAMETER (decision A1:
MACD_CROSS_WINDOW=3, RSI_CROSS_WINDOW=2 unchanged on both). Only the
timeframe ladder differs.

DATA: reads the frozen CSV archive in ./data/ produced by
download_market_data.py — no live Schwab fetch. Both runs read the identical
files; the 15-min run just resamples them to 15-min first. THIS is what makes
the comparison honest — same candles, two resolutions.

EXIT LAB: every signal is scored against all exit rules including
fisher_3bar (the v3.2 design) and fisher_2bar (the faster variant). Same
rules on both timeframes.

Run:
    cd ~/Documents/STS/15min
    python3.12 timeframe_test.py                       # default date range
    python3.12 timeframe_test.py 2026-05-01 2026-05-15  # custom range
"""

import sys, warnings
from pathlib import Path
from datetime import datetime, timedelta, time

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR   = SCRIPT_DIR / 'data'
sys.path.insert(0, str(SCRIPT_DIR))
# parent STS folder holds the original 5-min engine + universe list
sys.path.insert(0, str(SCRIPT_DIR.parent))

# ─── ENGINES ─────────────────────────────────────────────────────────────────
# 5-min: the original, from the parent STS folder.
# 15-min: the lifted copy, from this folder.
try:
    from sts_signal_engine import evaluate_ticker as evaluate_5m
    from sts_signal_engine import MIN_BARS_5M as MIN_BARS_5M_5, \
                                  MIN_BARS_DAILY as MIN_BARS_DAILY_5
except ImportError as e:
    print(f"ERROR importing 5-min engine (sts_signal_engine.py) from "
          f"{SCRIPT_DIR.parent}: {e}")
    sys.exit(1)

try:
    from sts_signal_engine_15m import evaluate_ticker as evaluate_15m
    from sts_signal_engine_15m import MIN_BARS_BASE as MIN_BARS_15M_BASE, \
                                      MIN_BARS_DAILY as MIN_BARS_DAILY_15
    from sts_indicators import fisher_transform
    from uts_exit import compute_uts_exit_series
except ImportError as e:
    print(f"ERROR importing 15-min engine (sts_signal_engine_15m.py) from "
          f"{SCRIPT_DIR}: {e}")
    sys.exit(1)

FISHER_PERIOD = 10

# ─── DATA LOADING ────────────────────────────────────────────────────────────

def load_universe():
    for cand in (SCRIPT_DIR.parent, SCRIPT_DIR):
        if (cand / 'sts_universe_list.py').exists():
            sys.path.insert(0, str(cand))
            from sts_universe_list import UNIVERSE_TICKERS
            return list(UNIVERSE_TICKERS)
    return None

def load_ticker_csv(ticker):
    """Load a frozen 5-min CSV with the tz-aware ET index restored."""
    path = DATA_DIR / f"{ticker}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
        df = df.set_index('datetime')
        df.index = df.index.tz_convert('US/Eastern')
        return df if len(df) else None
    except Exception:
        return None

def resample_ohlcv(df_5m, rule):
    """Resample 5-min OHLCV up to a higher timeframe, grouped per trading
    day so no candle spans the overnight gap."""
    agg = {'Open': 'first', 'High': 'max', 'Low': 'min',
           'Close': 'last', 'Volume': 'sum'}
    parts = []
    for _, day in df_5m.groupby(df_5m.index.date):
        r = day.resample(rule, label='right', closed='right').agg(agg).dropna()
        parts.append(r)
    return pd.concat(parts) if parts else df_5m.iloc[0:0]

def build_daily(df_5m):
    """Build a daily OHLCV frame from 5-min bars (one row per trading day)."""
    agg = {'Open': 'first', 'High': 'max', 'Low': 'min',
           'Close': 'last', 'Volume': 'sum'}
    rows = []
    for d, day in df_5m.groupby(df_5m.index.date):
        rows.append({
            'Open': day['Open'].iloc[0], 'High': day['High'].max(),
            'Low': day['Low'].min(), 'Close': day['Close'].iloc[-1],
            'Volume': day['Volume'].sum(),
            '_date': pd.Timestamp(d),
        })
    if not rows:
        return None
    daily = pd.DataFrame(rows).set_index('_date')
    return daily

# ─── REPLAY ──────────────────────────────────────────────────────────────────
#
# For one ticker and one target date, walk the base-timeframe bars of that day
# and call the engine as-of each bar. First bar that qualifies = the signal.
# OUTCOME WINDOW: measured forward up to OUTCOME_DAYS trading days, so late-day
# 15-min signals (few bars left in their own day) are not truncated.

OUTCOME_DAYS = 2   # measure MFE/MAE / exits over signal day + this many more

def build_synthetic_daily(df_d_prior, today_bars):
    synth = pd.DataFrame({
        'Open':   [float(today_bars['Open'].iloc[0])],
        'High':   [float(today_bars['High'].max())],
        'Low':    [float(today_bars['Low'].min())],
        'Close':  [float(today_bars['Close'].iloc[-1])],
        'Volume': [float(today_bars['Volume'].sum())],
    }, index=[today_bars.index[-1].normalize()])
    return pd.concat([df_d_prior, synth])

def levels_for(direction, price, atr, recent_low, recent_high):
    atr_v = atr or 0.0
    if direction == 'BUY':
        stop   = recent_low if recent_low is not None else price - atr_v
        target = price + 2 * atr_v
    else:
        stop   = recent_high if recent_high is not None else price + atr_v
        target = price - 2 * atr_v
    return round(price, 2), round(stop, 2), round(target, 2)

def replay_one(ticker, df_base, df_daily, target_date, evaluate_fn,
               min_bars_base, min_bars_daily):
    """Replay one ticker for one date on one timeframe. Returns a signal
    dict (first qualifying bar) or None.

    SPEED: the engine can ONLY produce a signal on a bar where price has
    broken yesterday's high (BUY) or low (SELL) — that is a hard gate inside
    daily_check. So before doing the expensive evaluate_fn call (which
    resamples + recomputes every indicator), we cheaply check that breakout
    condition. Bars that cannot possibly signal are skipped without calling
    the engine. This changes NOTHING about results — a skipped bar is one
    the engine would have rejected at daily_check anyway — it only avoids
    the wasted computation. Verified bit-identical to the unoptimised path.
    """
    if df_base is None or len(df_base) < min_bars_base:
        return None
    if df_daily is None or len(df_daily) < min_bars_daily:
        return None
    df_d_prior = df_daily[df_daily.index.date < target_date]
    if len(df_d_prior) < min_bars_daily:
        return None
    today = df_base[df_base.index.date == target_date]
    if len(today) == 0:
        return None

    # Yesterday's high/low — the fixed breakout levels for the whole day.
    prev_high = float(df_d_prior['High'].iloc[-1])
    prev_low  = float(df_d_prior['Low'].iloc[-1])

    # Precompute the cumulative position in df_base so the per-bar slice is
    # an integer cut, not a boolean scan of the whole history each time.
    base_idx = df_base.index
    # index position of the last bar at-or-before each 'today' bar
    today_positions = base_idx.searchsorted(today.index, side='right')

    for k, T in enumerate(today.index):
        pos = today_positions[k]            # number of bars up to & incl. T
        if pos < min_bars_base:
            continue
        price = float(df_base['Close'].iloc[pos - 1])
        # CHEAP PRE-GATE: a signal needs price > prev_high (BUY) or
        # price < prev_low (SELL). If neither holds, the engine's
        # daily_check would reject both directions — skip the call.
        if not (price > prev_high or price < prev_low):
            continue

        upto = df_base.iloc[:pos]
        today_upto = today.iloc[:k + 1]
        d_asof = build_synthetic_daily(df_d_prior, today_upto)
        try:
            res = evaluate_fn(ticker, d_asof, upto)
        except Exception:
            continue
        if res['signal'] in ('BUY', 'SELL'):
            entry, stop, target = levels_for(
                res['signal'], res['price'], res['atr'],
                res['recent_low_5m'], res['recent_high_5m'])
            return {
                'ticker': ticker, 'time': T, 'signal': res['signal'],
                'entry': entry, 'stop': stop, 'target': target,
                'atr': res['atr'] or 0.0,
            }
    return None

# ─── OUTCOME + EXIT SIMULATION ───────────────────────────────────────────────

def post_signal_bars(signal, df_base, target_date):
    """Bars after the signal, up to OUTCOME_DAYS trading days forward."""
    after = df_base[df_base.index > signal['time']]
    if len(after) == 0:
        return after
    days = sorted(set(after.index.date))
    keep = days[:OUTCOME_DAYS + 1]
    return after[np.isin(after.index.date, keep)]

def mfe_mae(signal, post):
    if len(post) == 0:
        return 0.0, 0.0
    entry = signal['entry']
    if signal['signal'] == 'BUY':
        mfe = float(post['High'].max()) - entry
        mae = float(post['Low'].min()) - entry
    else:
        mfe = entry - float(post['Low'].min())
        mae = entry - float(post['High'].max())
    return round(mfe, 2), round(mae, 2)

EXIT_RULES = [
    'hold_to_close',
    'target_1atr', 'target_1.5atr', 'target_2atr',
    'trail_1atr', 'trail_0.5atr',
    'fisher_3bar',   # v3.2 designed exit: Fisher falling 3 consecutive bars
    'fisher_2bar',   # faster variant: Fisher falling 2 consecutive bars
    'uts_exit',      # ported UTS exit: cloud+vstop / structure / momentum
    'perfect',       # ceiling benchmark
]

def _target_mult(rule):
    return {'target_1atr': 1.0, 'target_1.5atr': 1.5, 'target_2atr': 2.0}[rule]

def _trail_mult(rule):
    return {'trail_1atr': 1.0, 'trail_0.5atr': 0.5}[rule]

def simulate_exit(signal, post, rule, fisher_post, uts_post=None):
    """Exit price for one rule against this signal's post-entry bars."""
    direction = signal['signal']
    entry = signal['entry']
    atr   = signal['atr'] or 0.0
    stop  = signal['stop']
    if len(post) == 0:
        return entry
    closes = post['Close'].values
    highs  = post['High'].values
    lows   = post['Low'].values
    n = len(post)

    if rule == 'hold_to_close':
        return float(closes[-1])

    if rule == 'perfect':
        return float(highs.max()) if direction == 'BUY' else float(lows.min())

    if rule.startswith('target_'):
        mult = _target_mult(rule)
        target = entry + mult*atr if direction == 'BUY' else entry - mult*atr
        for i in range(n):
            if direction == 'BUY':
                hit_s = lows[i] <= stop
                hit_t = highs[i] >= target
            else:
                hit_s = highs[i] >= stop
                hit_t = lows[i] <= target
            if hit_s:
                return stop
            if hit_t:
                return target
        return float(closes[-1])

    if rule.startswith('trail_'):
        k = _trail_mult(rule)
        if direction == 'BUY':
            hwm = entry
            for i in range(n):
                hwm = max(hwm, highs[i])
                trail = max(stop, hwm - k*atr)
                if lows[i] <= trail:
                    return trail
            return float(closes[-1])
        else:
            lwm = entry
            for i in range(n):
                lwm = min(lwm, lows[i])
                trail = min(stop, lwm + k*atr)
                if highs[i] >= trail:
                    return trail
            return float(closes[-1])

    if rule in ('fisher_3bar', 'fisher_2bar'):
        # fisher_post = Fisher line aligned to the post-entry bars.
        # 3bar: Fisher down (BUY) / up (SELL) on 3 consecutive bars.
        # 2bar: same, 2 consecutive bars. Hard stop respected either way.
        nbars = 3 if rule == 'fisher_3bar' else 2
        if fisher_post is None or len(fisher_post) != n:
            return float(closes[-1])
        f = np.asarray(fisher_post, dtype=float)
        for i in range(n):
            if direction == 'BUY' and lows[i] <= stop:
                return stop
            if direction == 'SELL' and highs[i] >= stop:
                return stop
            if i >= nbars - 1:
                if direction == 'BUY' and all(
                        f[i-k] < f[i-k-1] for k in range(nbars - 1)):
                    return float(closes[i])
                if direction == 'SELL' and all(
                        f[i-k] > f[i-k-1] for k in range(nbars - 1)):
                    return float(closes[i])
        return float(closes[-1])

    if rule == 'uts_exit':
        # uts_post = boolean UTS-exit series aligned to the post-entry bars.
        # Exit at the first post-entry bar where the UTS long-exit conditions
        # fire (cloud+vstop break / structure break / momentum rollover).
        # Hard stop is still respected — whichever comes first.
        # NOTE: the UTS exit conditions are LONG-side only (ported from the
        # UTS `case long:` block). For SELL signals there is no ported UTS
        # short-exit yet, so SELL falls back to hold_to_close.
        if direction != 'BUY':
            return float(closes[-1])
        if uts_post is None or len(uts_post) != n:
            return float(closes[-1])
        u = np.asarray(uts_post, dtype=bool)
        for i in range(n):
            if lows[i] <= stop:
                return stop
            if u[i]:
                return float(closes[i])
        return float(closes[-1])

    return float(closes[-1])

def rule_pnl(signal, exit_price):
    if signal['signal'] == 'BUY':
        return round(exit_price - signal['entry'], 2)
    return round(signal['entry'] - exit_price, 2)

# ─── ONE TIMEFRAME'S FULL RUN ────────────────────────────────────────────────

def run_timeframe(tf_name, tickers, dates, base_csv_loader, evaluate_fn,
                  min_bars_base, min_bars_daily):
    """Run one engine over all tickers x dates. Returns a list of review dicts
    (one per signal) with MFE/MAE and per-rule exit P&L attached."""
    reviews = []
    n_done = 0
    for ticker in tickers:
        n_done += 1
        if n_done % 100 == 0:
            print(f"    [{tf_name}] {n_done}/{len(tickers)} tickers, "
                  f"{len(reviews)} signals so far")
        df5 = base_csv_loader(ticker)
        if df5 is None:
            continue
        # base timeframe frame: 5-min as-is, or resampled to 15-min
        if tf_name == '5min':
            df_base = df5
        else:
            df_base = resample_ohlcv(df5, '15min')
        df_daily = build_daily(df5)
        if df_daily is None:
            continue

        # Per-ticker precompute — both the Fisher line and the UTS exit
        # series are computed ONCE over the whole base frame here, then
        # aligned to each signal's post-entry bars in the loop below.
        # (Previously Fisher was recomputed per-signal — wasteful.)
        try:
            fish_full = fisher_transform(df_base, period=FISHER_PERIOD)
        except Exception:
            fish_full = None
        try:
            uts_full = compute_uts_exit_series(df_base)
        except Exception:
            uts_full = None

        for target_date in dates:
            sig = replay_one(ticker, df_base, df_daily, target_date,
                             evaluate_fn, min_bars_base, min_bars_daily)
            if sig is None:
                continue
            post = post_signal_bars(sig, df_base, target_date)
            mfe, mae = mfe_mae(sig, post)
            # Fisher aligned to post bars (for the fisher exit rules)
            if fish_full is not None:
                fpost = fish_full.reindex(post.index).values
            else:
                fpost = None
            # UTS exit aligned to post bars (for the uts_exit rule)
            if uts_full is not None:
                upost = uts_full.reindex(post.index).fillna(False).values
            else:
                upost = None
            rules = {r: rule_pnl(sig, simulate_exit(sig, post, r, fpost, upost))
                     for r in EXIT_RULES}
            reviews.append({**sig, 'mfe': mfe, 'mae': mae, 'rules': rules,
                            'eod_pnl': rules['hold_to_close']})
    return reviews

# ─── ANALYSIS ────────────────────────────────────────────────────────────────

def pct(x, base):
    return (x / base * 100.0) if base else 0.0

def trigger_stats(reviews):
    """MFE/MAE distribution stats for a set of reviews."""
    n = len(reviews)
    if n == 0:
        return None
    mfe_pcts = [pct(r['mfe'], r['entry']) for r in reviews]
    ratios = []
    for r in reviews:
        if r['mae'] < 0:
            ratios.append(abs(r['mfe']) / abs(r['mae']))
        elif r['mfe'] > 0:
            ratios.append(99.0)
    return {
        'n': n,
        'med_mfe_pct': float(np.median(mfe_pcts)),
        'mfe_lt1_pct': 100 * sum(1 for v in mfe_pcts if v < 1.0) / n,
        'med_ratio': float(np.median(ratios)) if ratios else 0.0,
        'mfe_le0_pct': 100 * sum(1 for v in mfe_pcts if v <= 0) / n,
        'top_q_mfe': float(np.percentile([r['mfe'] for r in reviews], 75)),
    }

def exit_totals(reviews):
    """Per-rule total P&L + win% over a set of reviews."""
    n = len(reviews)
    out = {}
    for rule in EXIT_RULES:
        pnls = [r['rules'][rule] for r in reviews]
        out[rule] = {'total': sum(pnls),
                     'win': 100 * sum(1 for p in pnls if p > 0) / n if n else 0}
    return out

def print_side(label, reviews):
    s = trigger_stats(reviews)
    if s is None:
        print(f"\n  {label}: NO SIGNALS")
        return
    print(f"\n  {label}  (n={s['n']})")
    print(f"    median MFE        {s['med_mfe_pct']:.2f}%")
    print(f"    %MFE < 1%         {s['mfe_lt1_pct']:.0f}%")
    print(f"    %never green      {s['mfe_le0_pct']:.0f}%")
    print(f"    median MFE/MAE    {s['med_ratio']:.2f}")
    print(f"    top-quartile MFE  ${s['top_q_mfe']:.2f}   (the 'big winners')")
    et = exit_totals(reviews)
    print(f"    {'exit rule':<16}{'total P&L':>11}{'win%':>7}")
    for rule in EXIT_RULES:
        tag = '  <- ceiling' if rule == 'perfect' else ''
        print(f"    {rule:<16}{et[rule]['total']:>+11.2f}"
              f"{et[rule]['win']:>6.0f}%{tag}")

# ─── MAIN ────────────────────────────────────────────────────────────────────

def resolve_dates():
    if len(sys.argv) >= 3:
        d0 = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
        d1 = datetime.strptime(sys.argv[2], '%Y-%m-%d').date()
    else:
        # default: the last ~3 weeks ending at the data's last day
        d1 = None  # resolved from data below
        d0 = None
    return d0, d1

def main():
    print("=" * 78)
    print("  STS TIMEFRAME TEST  —  5-minute vs 15-minute, apples-to-apples")
    print("=" * 78)

    if not DATA_DIR.exists() or not any(DATA_DIR.glob('*.csv')):
        print(f"  ✖  No data in {DATA_DIR}/")
        print(f"     Run download_market_data.py first.")
        sys.exit(1)

    tickers = load_universe()
    if not tickers:
        print("  ✖  Could not load sts_universe_list.py")
        sys.exit(1)

    # only tickers we actually have CSV files for
    have = [t for t in tickers if (DATA_DIR / f"{t}.csv").exists()]
    print(f"  Universe: {len(tickers)} | with local data: {len(have)}")

    # date range
    d0, d1 = resolve_dates()
    if d0 is None:
        # infer from a sample file's last date, use the final 15 trading days
        sample = load_ticker_csv(have[0])
        last = sample.index.max().date()
        all_days = sorted(set(d for d in sample.index.date
                              if d <= last))[-15:]
        dates = [d for d in all_days
                 if datetime(d.year, d.month, d.day).weekday() < 5]
    else:
        span = [(d0 + timedelta(days=i)) for i in range((d1 - d0).days + 1)]
        dates = [d for d in span if d.weekday() < 5]
    print(f"  Test dates: {dates[0]} → {dates[-1]}  ({len(dates)} weekdays)")
    print(f"  Outcome window: signal day + {OUTCOME_DAYS} trading days")
    print(f"  Parameters: IDENTICAL on both engines (decision A1)")

    # ── 5-min run ──
    print(f"\n  Running 5-MINUTE engine (base 5m, ladder 5/15/30)...")
    rev5 = run_timeframe('5min', have, dates, load_ticker_csv,
                         evaluate_5m, MIN_BARS_5M_5, MIN_BARS_DAILY_5)
    print(f"    -> {len(rev5)} signals")

    # ── 15-min run ──
    print(f"\n  Running 15-MINUTE engine (base 15m, ladder 15/30/60)...")
    rev15 = run_timeframe('15min', have, dates, load_ticker_csv,
                          evaluate_15m, MIN_BARS_15M_BASE, MIN_BARS_DAILY_15)
    print(f"    -> {len(rev15)} signals")

    # ── side-by-side ──
    for side in ('BUY', 'SELL'):
        b5  = [r for r in rev5  if r['signal'] == side]
        b15 = [r for r in rev15 if r['signal'] == side]
        print(f"\n{'=' * 78}")
        print(f"  {side} SIGNALS  —  5-min vs 15-min")
        print('=' * 78)
        print_side(f"5-MINUTE  {side}", b5)
        print_side(f"15-MINUTE {side}", b15)

    # ── verdict ──
    buy5  = [r for r in rev5  if r['signal'] == 'BUY']
    buy15 = [r for r in rev15 if r['signal'] == 'BUY']
    s5, s15 = trigger_stats(buy5), trigger_stats(buy15)
    print(f"\n{'=' * 78}")
    print("  VERDICT — does the strategy work better on 15-min? (BUY side)")
    print("=" * 78)
    if s5 and s15:
        print(f"  {'metric':<22}{'5-min':>12}{'15-min':>12}")
        print(f"  {'-'*46}")
        print(f"  {'signals':<22}{s5['n']:>12}{s15['n']:>12}")
        print(f"  {'median MFE/MAE':<22}{s5['med_ratio']:>12.2f}{s15['med_ratio']:>12.2f}")
        print(f"  {'%MFE<1%':<22}{s5['mfe_lt1_pct']:>11.0f}%{s15['mfe_lt1_pct']:>11.0f}%")
        print(f"  {'median MFE%':<22}{s5['med_mfe_pct']:>11.2f}%{s15['med_mfe_pct']:>11.2f}%")
        print(f"  {'top-quartile MFE $':<22}{s5['top_q_mfe']:>12.2f}{s15['top_q_mfe']:>12.2f}")
        e5  = exit_totals(buy5)
        e15 = exit_totals(buy15)
        print(f"  {'hold_to_close P&L':<22}{e5['hold_to_close']['total']:>+12.2f}"
              f"{e15['hold_to_close']['total']:>+12.2f}")
        print()
        rd = s15['med_ratio'] - s5['med_ratio']
        if rd > 0.3:
            print(f"  -> 15-min BUY triggers are CLEANER (MFE/MAE +{rd:.2f}). "
                  f"The higher timeframe helps.")
        elif rd < -0.3:
            print(f"  -> 15-min BUY triggers are WORSE (MFE/MAE {rd:.2f}). "
                  f"Higher timeframe does not help here.")
        else:
            print(f"  -> No meaningful difference (MFE/MAE {rd:+.2f}). The "
                  f"strategy behaves the SAME on both timeframes —")
            print(f"     which means the timeframe is not the lever. If both "
                  f"are weak, the strategy itself needs rethinking.")
    print()
    print("  HOW TO READ:")
    print("  • Same strategy, same parameters, same frozen data — only the")
    print("    timeframe differs. This is the apples-to-apples test.")
    print("  • 'top-quartile MFE' is the big-winners metric: if 15-min lifts")
    print("    this, the higher timeframe is catching bigger moves.")
    print("  • fisher_3bar = the v3.2 designed exit. fisher_2bar = faster")
    print("    variant. Compare both columns across timeframes.")
    print("=" * 78)

if __name__ == '__main__':
    main()
