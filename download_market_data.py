#!/usr/bin/env python3
"""
STS — Market Data Downloader
============================
One-time (re-runnable) bulk download of 5-minute OHLCV candles from the
Saves one CSV file per ticker into ./data/ so that strategy research runs
offline against a FROZEN dataset — no live fetch, no rate limits, no token
issues, instant reads. CSV is used (not parquet) so there is no extra
library dependency to install.

Why 5-minute only:
    15-min and 30-min candles are just 5-min candles grouped. Storing all
    three triples the disk use and risks them disagreeing. Download 5-min
    as the master; resample to 15/30 in code (see resample_ohlcv below).

Run:
    cd ~/Documents/STS/15min
    python3.12 download_market_data.py

    # refresh later (overwrites with current data):
    python3.12 download_market_data.py

Output:
    ./data/{TICKER}.csv          — one file per ticker
    ./data/_download_manifest.csv — per-ticker row count + date range + status

Runtime: ~30-45 min for 634 tickers (throttled to avoid HTTP 429).
"""

import sys, ssl, warnings
import time as _time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pytz

warnings.filterwarnings('ignore')
ssl._create_default_https_context = ssl._create_unverified_context

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR   = SCRIPT_DIR / 'data'
MANIFEST   = DATA_DIR / '_download_manifest.csv'

# Schwab credentials — token confirmed working at this path (Desktop)
API_KEY    = 'rvtokLB0MCZNlXfY3QqY251qeXR8rCyQs8zBYzAp3w6m30Ek'
APP_SECRET = 'hjJ3ErG8mF7gyxk74ws6ujphCwr9CGlyen4rN7XlrqmJlqoRmqqrmSnX9Qpfjv3P'
TOKEN_PATH = '/Users/Gagan/Desktop/schwab_token.json'

# Throttle — proven settings that avoid HTTP 429 rate limiting
FETCH_WORKERS = 3       # concurrent fetch threads
FETCH_DELAY   = 0.12    # seconds between calls within a worker
FETCH_RETRIES = 3       # retry attempts on HTTP 429

ET = pytz.timezone('US/Eastern')

# Universe — read from sts_universe_list.py in the PARENT STS folder.
# The 15min folder is a sibling of the live files; the universe list lives
# one level up. Fall back to a path search if the import layout differs.
def load_universe():
    # try parent dir (…/STS/) and this dir
    for cand in (SCRIPT_DIR.parent, SCRIPT_DIR):
        if (cand / 'sts_universe_list.py').exists():
            sys.path.insert(0, str(cand))
            try:
                from sts_universe_list import UNIVERSE_TICKERS
                return list(UNIVERSE_TICKERS)
            except Exception as e:
                print(f"  found sts_universe_list.py in {cand} but import failed: {e}")
    return None

# ─── SCHWAB ──────────────────────────────────────────────────────────────────

_ERRORS = []

def init_schwab():
    import schwab
    return schwab.auth.client_from_token_file(
        token_path=TOKEN_PATH, api_key=API_KEY, app_secret=APP_SECRET)

def _to_df(candles):
    df = pd.DataFrame(candles)
    df['datetime'] = pd.to_datetime(df['datetime'], unit='ms', utc=True)
    df = df.set_index('datetime').rename(columns={
        'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'})
    df.index = df.index.tz_convert(ET)
    return df.dropna()

def fetch_5m(client, ticker):
    """Fetch maximum-available 5-minute history for one ticker.
    Returns a regular-session OHLCV DataFrame, or None on failure."""
    for attempt in range(FETCH_RETRIES):
        try:
            _time.sleep(FETCH_DELAY)
            # bare ticker => Schwab returns its maximum 5-min window
            resp = client.get_price_history_every_five_minutes(ticker)
            if resp.status_code == 429:
                _time.sleep(1.5 * (attempt + 1))   # back off, retry
                continue
            if resp.status_code != 200:
                _ERRORS.append(f"{ticker}: HTTP {resp.status_code}")
                return None
            candles = resp.json().get('candles', [])
            if not candles:
                _ERRORS.append(f"{ticker}: no candles returned")
                return None
            df = _to_df(candles)
            # regular session only: 09:30–15:59 ET
            df = df[((df.index.hour > 9) |
                     ((df.index.hour == 9) & (df.index.minute >= 30)))
                    & (df.index.hour < 16)]
            return df if len(df) else None
        except Exception as e:
            _ERRORS.append(f"{ticker}: {type(e).__name__}: {e}")
            return None
    _ERRORS.append(f"{ticker}: HTTP 429 (still throttled after {FETCH_RETRIES} retries)")
    return None

def download_one(client, ticker):
    """Fetch + save one ticker. Returns a manifest row dict."""
    df = fetch_5m(client, ticker)
    if df is None or len(df) == 0:
        return {'ticker': ticker, 'rows': 0, 'start': None,
                'end': None, 'status': 'FAILED'}
    out = DATA_DIR / f"{ticker}.csv"
    try:
        # CSV with the datetime index — no parquet engine dependency
        df.to_csv(out, index_label='datetime')
    except Exception as e:
        _ERRORS.append(f"{ticker}: CSV write failed: {e}")
        return {'ticker': ticker, 'rows': len(df), 'start': None,
                'end': None, 'status': 'WRITE_FAILED'}
    return {'ticker': ticker, 'rows': len(df),
            'start': df.index.min().strftime('%Y-%m-%d'),
            'end':   df.index.max().strftime('%Y-%m-%d'),
            'status': 'OK'}

# ─── RESAMPLE HELPER (used later by the 15-min strategy, not the download) ───

def load_ticker_csv(ticker, data_dir=None):
    """Read a downloaded ticker CSV back into a DataFrame with the
    timezone-aware (ET) datetime index restored. CSV does not preserve the
    tz-aware index on its own, so this re-parses it. Returns None if missing."""
    d = Path(data_dir) if data_dir else DATA_DIR
    path = d / f"{ticker}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    # force a real datetime index (the saved string carries a tz offset)
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
    df = df.set_index('datetime')
    df.index = df.index.tz_convert(ET)
    return df

def resample_ohlcv(df_5m, rule):
    """Resample a 5-min OHLCV frame to a higher timeframe.
    rule e.g. '15min' or '30min'. Groups within each trading day so a
    candle never spans the overnight gap."""
    agg = {'Open': 'first', 'High': 'max', 'Low': 'min',
           'Close': 'last', 'Volume': 'sum'}
    out = []
    for _, day in df_5m.groupby(df_5m.index.date):
        r = day.resample(rule, label='left', closed='left').agg(agg).dropna()
        out.append(r)
    return pd.concat(out) if out else df_5m.iloc[0:0]

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  STS Market Data Downloader — 5-minute candles")
    print("=" * 70)

    tickers = load_universe()
    if not tickers:
        print("  ✖  Could not load sts_universe_list.py.")
        print("     Place this script in ~/Documents/STS/15min/ (sibling of")
        print("     the live STS files) so it can find the universe list.")
        sys.exit(1)
    print(f"  Universe: {len(tickers)} tickers")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Output:   {DATA_DIR}/")
    print(f"  Throttle: {FETCH_WORKERS} workers, {FETCH_DELAY}s spacing, "
          f"{FETCH_RETRIES}x retry on 429")
    print(f"  Token:    {TOKEN_PATH}")

    print("\n  Connecting to Schwab...")
    try:
        client = init_schwab()
    except Exception as e:
        print(f"  ✖  Schwab auth failed: {e}")
        print("     Refresh the token (weekly login-flow command) and retry.")
        sys.exit(1)
    print("  Connected. Starting download — this takes ~30-45 min.\n")

    t0 = _time.time()
    manifest = []
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = {ex.submit(download_one, client, t): t for t in tickers}
        done = 0
        for f in as_completed(futs):
            done += 1
            try:
                manifest.append(f.result())
            except Exception as e:
                tk = futs[f]
                _ERRORS.append(f"{tk}: worker crash: {e}")
                manifest.append({'ticker': tk, 'rows': 0, 'start': None,
                                 'end': None, 'status': 'CRASH'})
            if done % 50 == 0 or done == len(tickers):
                ok = sum(1 for m in manifest if m['status'] == 'OK')
                print(f"    {done}/{len(tickers)}   ({ok} saved)")

    mins = (_time.time() - t0) / 60.0

    # write manifest
    mdf = pd.DataFrame(manifest).sort_values('ticker')
    mdf.to_csv(MANIFEST, index=False)

    ok    = mdf[mdf['status'] == 'OK']
    bad   = mdf[mdf['status'] != 'OK']
    print(f"\n{'=' * 70}")
    print(f"  DONE in {mins:.1f} min")
    print(f"  Saved:  {len(ok)}/{len(tickers)} tickers")
    if len(ok):
        print(f"  Rows:   {int(ok['rows'].sum()):,} total 5-min candles")
        print(f"  Range:  {ok['start'].min()}  →  {ok['end'].max()}")
        # depth check — how much history did Schwab actually serve?
        spans = (pd.to_datetime(ok['end']) - pd.to_datetime(ok['start'])).dt.days
        print(f"  Depth:  median {int(spans.median())} days "
              f"(min {int(spans.min())}, max {int(spans.max())})")
    if len(bad):
        print(f"  ⚠  {len(bad)} tickers failed: "
              f"{', '.join(bad['ticker'].head(15))}"
              f"{' …' if len(bad) > 15 else ''}")
    if _ERRORS:
        print(f"  First few errors:")
        for e in _ERRORS[:5]:
            print(f"     - {e}")
    print(f"  Manifest: {MANIFEST}")
    print(f"\n  Next: point the 15-min strategy at ./data/ — it reads these")
    print(f"  CSV files instead of fetching Schwab live.")
    print("=" * 70)

if __name__ == '__main__':
    main()
