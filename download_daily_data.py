#!/usr/bin/env python3
"""
download_daily_data.py — bulk Schwab DAILY candle downloader
============================================================
Foundation for the UTS daily swing model. Pulls ~2 years of daily OHLCV
for the whole universe and saves one CSV per ticker into  daily_data/.

Why a separate downloader (not the 5-min one):
  - the UTS daily model needs DAILY bars, years of them
  - Schwab's daily endpoint gives long history readily (unlike the
    intraday endpoints, which are limited and were finicky)
  - kept separate so the 15-min research folder's data/ is untouched

KEY LESSON CARRIED FORWARD from the 5-min / observe-scanner bugs:
  call the Schwab price-history endpoint BARE — no start_datetime.
  Passing start_datetime made the intraday endpoints return tiny broken
  slices. The daily endpoint is called bare here too; we request a wide
  period via the period args and trim afterward.

Run:
  cd ~/Documents/STS/15min && caffeinate -i python3.12 download_daily_data.py

Output:
  ~/Documents/STS/15min/daily_data/<TICKER>.csv   (one per ticker)
  columns: datetime index (tz-aware ET) + Open High Low Close Volume
"""

import sys, time, traceback
from pathlib import Path
from datetime import datetime

import pandas as pd
import pytz

# ─── PATHS ───────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
STS_DIR    = SCRIPT_DIR.parent
OUT_DIR    = SCRIPT_DIR / 'daily_data'
OUT_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(STS_DIR))

# ─── UNIVERSE ────────────────────────────────────────────────────────────────

try:
    from sts_universe_list import UNIVERSE_TICKERS
except ImportError:
    print(f"ERROR: sts_universe_list.py not found in {STS_DIR} or {SCRIPT_DIR}")
    sys.exit(1)

# ─── SCHWAB CREDENTIALS (same as the observe scanner) ────────────────────────

API_KEY    = 'rvtokLB0MCZNlXfY3QqY251qeXR8rCyQs8zBYzAp3w6m30Ek'
APP_SECRET = 'hjJ3ErG8mF7gyxk74ws6ujphCwr9CGlyen4rN7XlrqmJlqoRmqqrmSnX9Qpfjv3P'
TOKEN_PATH = '/Users/Gagan/Desktop/schwab_token.json'

ET = pytz.timezone('US/Eastern')

# how much history to keep (calendar days). Schwab returns plenty; we trim.
LOOKBACK_DAYS = 730          # ~2 years
MIN_BARS_KEEP = 150          # skip a ticker if it has fewer daily bars
THROTTLE_SEC  = 0.18         # gentle pause between calls — avoid 429s

# ─── SCHWAB CLIENT ───────────────────────────────────────────────────────────

def get_client():
    try:
        import schwab
        client = schwab.auth.client_from_token_file(
            token_path=TOKEN_PATH, api_key=API_KEY, app_secret=APP_SECRET)
        print("Schwab client ready")
        return client
    except Exception as e:
        print(f"ERROR: Schwab auth failed: {e}")
        return None

# ─── FETCH ONE TICKER ────────────────────────────────────────────────────────

def fetch_daily(client, ticker):
    """Fetch daily OHLCV for one ticker. Returns a tz-aware DataFrame or None.

    Endpoint called BARE (no start_datetime) — same lesson as the 5-min fix.
    We request a long period and trim to LOOKBACK_DAYS afterward.
    """
    try:
        # schwab-py: get_price_history_every_day. Called bare for reliability.
        resp = client.get_price_history_every_day(ticker)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        candles = resp.json().get('candles', [])
        if not candles:
            return None, "no candles"
        df = pd.DataFrame(candles)
        df['datetime'] = pd.to_datetime(df['datetime'], unit='ms', utc=True)
        df = df.set_index('datetime').rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'})
        df.index = df.index.tz_convert(ET)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        # trim to the lookback window
        cutoff = pd.Timestamp.now(tz=ET) - pd.Timedelta(days=LOOKBACK_DAYS)
        df = df[df.index >= cutoff]
        return df, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

# ─── LOADER (for the engine / backtest to reuse) ─────────────────────────────

def load_daily_csv(ticker, data_dir=None):
    """Load a saved daily CSV back into a tz-aware DataFrame.
    The daily engine and backtest import THIS so the format stays consistent."""
    data_dir = Path(data_dir) if data_dir else OUT_DIR
    path = data_dir / f"{ticker}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0)
    # parse the index explicitly — parse_dates=True on read_csv is not
    # reliable for all CSV layouts, so convert here and assert it worked.
    df.index = pd.to_datetime(df.index, utc=True, errors='coerce')
    df = df[df.index.notna()]          # drop any unparseable index rows
    if len(df) == 0:
        return None
    df.index = df.index.tz_convert(ET)
    # keep only the OHLCV columns, coerce to numeric
    cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume']
            if c in df.columns]
    df = df[cols].apply(pd.to_numeric, errors='coerce').dropna()
    return df if len(df) else None

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  DAILY DATA DOWNLOADER — Schwab")
    print(f"  Universe : {len(UNIVERSE_TICKERS)} tickers")
    print(f"  History  : ~{LOOKBACK_DAYS} calendar days (~2 years)")
    print(f"  Output   : {OUT_DIR}")
    print("=" * 60)

    client = get_client()
    if client is None:
        sys.exit(1)

    ok, skipped, failed = 0, [], []
    total_bars = 0
    t0 = time.time()

    for i, ticker in enumerate(UNIVERSE_TICKERS, 1):
        df, err = fetch_daily(client, ticker)
        if df is None:
            failed.append((ticker, err))
            print(f"  [{i:>3}/{len(UNIVERSE_TICKERS)}] {ticker:<6} FAILED — {err}")
        elif len(df) < MIN_BARS_KEEP:
            skipped.append((ticker, len(df)))
            print(f"  [{i:>3}/{len(UNIVERSE_TICKERS)}] {ticker:<6} skip — only {len(df)} bars")
        else:
            df.to_csv(OUT_DIR / f"{ticker}.csv")
            total_bars += len(df)
            ok += 1
            if i % 50 == 0:
                print(f"  [{i:>3}/{len(UNIVERSE_TICKERS)}] {ticker:<6} "
                      f"{len(df)} bars  ({ok} saved so far)")
        time.sleep(THROTTLE_SEC)

    dt = time.time() - t0
    print("\n" + "=" * 60)
    print(f"  DONE in {dt/60:.1f} min")
    print(f"  Saved   : {ok} tickers, {total_bars:,} daily candles total")
    if ok:
        print(f"  Median depth: ~{total_bars // max(ok,1)} bars/ticker")
    if skipped:
        print(f"  Skipped (thin): {len(skipped)} — "
              f"{', '.join(t for t,_ in skipped[:12])}"
              f"{' ...' if len(skipped) > 12 else ''}")
    if failed:
        print(f"  Failed: {len(failed)} — "
              f"{', '.join(t for t,_ in failed[:12])}"
              f"{' ...' if len(failed) > 12 else ''}")
    print(f"  Files in: {OUT_DIR}")
    print("=" * 60)

if __name__ == '__main__':
    main()
