#!/usr/bin/env python3
"""
verify_optimization.py
======================
Proves the optimized timeframe_test.py produces BIT-IDENTICAL signals to the
old (slow) version — run against your REAL local data, not synthetic.

It reconstructs the old unoptimised replay_one inline, runs both the old and
the new version over a sample of tickers/dates from your data/ folder, and
diffs every signal field. If it prints ALL MATCH, the optimization is safe
and you can trust the fast timeframe_test.py.

Run:
    cd ~/Documents/STS/15min
    python3.12 verify_optimization.py
"""
import sys, time, importlib.util
from pathlib import Path
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

# load the (optimized) timeframe_test module
spec = importlib.util.spec_from_file_location('tf', SCRIPT_DIR / 'timeframe_test.py')
tf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tf)

from sts_signal_engine import evaluate_ticker as ev5
from sts_signal_engine import MIN_BARS_5M, MIN_BARS_DAILY
from sts_signal_engine_15m import evaluate_ticker as ev15
from sts_signal_engine_15m import MIN_BARS_BASE, MIN_BARS_DAILY as MBD15


def replay_one_OLD(ticker, df_base, df_daily, target_date, evaluate_fn,
                   min_bars_base, min_bars_daily):
    """The ORIGINAL unoptimised replay_one — verbatim, for comparison."""
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
    for T in today.index:
        upto = df_base[df_base.index <= T]
        if len(upto) < min_bars_base:
            continue
        today_upto = today[today.index <= T]
        d_asof = tf.build_synthetic_daily(df_d_prior, today_upto)
        try:
            res = evaluate_fn(ticker, d_asof, upto)
        except Exception:
            continue
        if res['signal'] in ('BUY', 'SELL'):
            e, s, t = tf.levels_for(res['signal'], res['price'], res['atr'],
                                    res['recent_low_5m'], res['recent_high_5m'])
            return {'ticker': ticker, 'time': T, 'signal': res['signal'],
                    'entry': e, 'stop': s, 'target': t, 'atr': res['atr'] or 0.0}
    return None


def main():
    print("=" * 70)
    print("  VERIFY OPTIMIZATION — old vs new replay_one, bit-identical check")
    print("=" * 70)

    have = sorted(p.stem for p in (SCRIPT_DIR / 'data').glob('*.csv')
                  if not p.stem.startswith('_'))
    if not have:
        print("  No data/ CSVs found — run download_market_data.py first.")
        sys.exit(1)

    # sample: first 40 tickers, ~30 weekday span — enough to hit real signals
    sample = have[:40]
    dates = [d.date() for d in pd.bdate_range('2026-04-01', '2026-05-15')]
    print(f"  Sample: {len(sample)} tickers x {len(dates)} dates")
    print(f"  (this runs the SLOW version too, so give it a few minutes)\n")

    for label, ev, mbb, mbd, resample in [
        ('5-min',  ev5,  MIN_BARS_5M,   MIN_BARS_DAILY, False),
        ('15-min', ev15, MIN_BARS_BASE, MBD15,          True),
    ]:
        mm = 0; tot = 0; osig = 0; nsig = 0
        t_old = t_new = 0.0
        examples = []
        for tk in sample:
            df5 = tf.load_ticker_csv(tk)
            if df5 is None:
                continue
            df_base = tf.resample_ohlcv(df5, '15min') if resample else df5
            dd = tf.build_daily(df5)
            for td in dates:
                tot += 1
                a = time.time()
                old = replay_one_OLD(tk, df_base, dd, td, ev, mbb, mbd)
                t_old += time.time() - a
                a = time.time()
                new = tf.replay_one(tk, df_base, dd, td, ev, mbb, mbd)
                t_new += time.time() - a
                if old: osig += 1
                if new: nsig += 1
                if (old is None) != (new is None):
                    mm += 1
                    print(f"  MISMATCH {label} {tk} {td}: "
                          f"old={'signal' if old else 'None'} "
                          f"new={'signal' if new else 'None'}")
                elif old is not None:
                    bad = False
                    for k in ('ticker', 'signal', 'entry', 'stop',
                              'target', 'atr', 'time'):
                        if old[k] != new[k]:
                            mm += 1; bad = True
                            print(f"  FIELD MISMATCH {label} {tk} {td} "
                                  f"[{k}]: old={old[k]} new={new[k]}")
                            break
                    if not bad and len(examples) < 3:
                        examples.append(f"{tk} {td} {old['signal']} @ {old['time']}")
        print(f"  {label}: replays={tot}  signals_old={osig}  signals_new={nsig}  "
              f"MISMATCHES={mm}")
        print(f"         time  old={t_old:.1f}s  new={t_new:.1f}s  "
              f"speedup={t_old / max(t_new, 0.01):.1f}x")
        if examples:
            print(f"         matched signal examples: {examples}")
        print()

    print("=" * 70)
    print("  If both engines show MISMATCHES=0 and signals_old>0, the")
    print("  optimization is VERIFIED bit-identical — trust timeframe_test.py.")
    print("  If signals_old=0, the sample window had no signals — widen it.")
    print("=" * 70)


if __name__ == '__main__':
    main()
