#!/usr/bin/env python3
"""
fill_watchlist_prices.py — fill Last_Close + Avg_Volume from Schwab
====================================================================
The enriched watchlist ships with Sector and Theme filled but the
Last_Close column blank — price is live data and must come from a
real market connection. This script fills it (and adds 20-day average
volume, which you need for the volume trim) using the same Schwab
client every other STS script uses.

Run ONCE, on the Mac, whenever you want fresh numbers:
  cd ~/Documents/STS/15min && python3.12 fill_watchlist_prices.py

It reads  swing_trading_watchlist_enriched.xlsx
and writes swing_trading_watchlist_priced.xlsx  (new file, original kept).
"""

import sys
from pathlib import Path
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from download_daily_data import get_client, fetch_daily

IN_PATH  = SCRIPT_DIR / 'swing_trading_watchlist_enriched.xlsx'
OUT_PATH = SCRIPT_DIR / 'swing_trading_watchlist_priced.xlsx'

VOL_WINDOW = 20   # trading days for average volume


def main():
    if not IN_PATH.exists():
        print(f'  Not found: {IN_PATH}')
        print('  Put swing_trading_watchlist_enriched.xlsx in this folder.')
        sys.exit(1)

    df = pd.read_excel(IN_PATH, sheet_name='Watchlist')
    tickers = [str(t).strip().upper() for t in df['Ticker'] if pd.notna(t)]
    print(f'  {len(tickers)} tickers to price')

    client = get_client()
    if client is None:
        print('  Schwab client unavailable — is the token current?')
        sys.exit(1)

    last_close, avg_vol = {}, {}
    for i, tk in enumerate(tickers, 1):
        bars, err = fetch_daily(client, tk)
        if bars is None or len(bars) == 0:
            print(f'  [{i}/{len(tickers)}] {tk}: no data ({err})')
            continue
        last_close[tk] = round(float(bars['Close'].iloc[-1]), 2)
        vol = bars['Volume'].tail(VOL_WINDOW)
        avg_vol[tk] = int(vol.mean()) if len(vol) else None
        if i % 25 == 0:
            print(f'  [{i}/{len(tickers)}] priced…')

    df['Last_Close'] = df['Ticker'].map(
        lambda t: last_close.get(str(t).strip().upper()))
    # insert Avg_Volume right after Last_Close if not already there
    if 'Avg_Volume_20d' not in df.columns:
        col = df['Ticker'].map(
            lambda t: avg_vol.get(str(t).strip().upper()))
        df.insert(df.columns.get_loc('Last_Close') + 1,
                  'Avg_Volume_20d', col)
    else:
        df['Avg_Volume_20d'] = df['Ticker'].map(
            lambda t: avg_vol.get(str(t).strip().upper()))

    df.to_excel(OUT_PATH, sheet_name='Watchlist', index=False)
    got = sum(1 for v in last_close.values() if v)
    print(f'\n  Priced {got}/{len(tickers)} tickers.')
    print(f'  Saved: {OUT_PATH}')
    print('  Now trim by Last_Close / Avg_Volume_20d, then load the '
          'kept tickers into uts_paper_tracker.py WATCHLIST.')


if __name__ == '__main__':
    main()
