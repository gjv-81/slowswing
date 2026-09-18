#!/usr/bin/env python3
"""
download_daily_yf.py
====================
Downloads ~10 years of DAILY bars via yfinance for the same universe
as the existing Schwab download (it reads the ticker list straight
from the daily_data/ folder, so the universes match exactly).

Writes to a SEPARATE folder — daily_data_10y/ — and never touches
the Schwab daily_data/ files.

Then run the sweep against it:
    python3.12 backtest_uts_exit_sweep.py daily_data_10y

Notes
  - auto_adjust=True: prices are split/dividend adjusted, which is
    what the indicators need for continuity across 10 years.
  - Survivorship warning: this is TODAY's ticker list backfilled
    10 years. Names that died along the way are invisible, so
    absolute results are a ceiling. Era-vs-era comparisons remain
    fair because every era shares the bias.

Run:  cd ~/Documents/STS/15min && python3.12 download_daily_yf.py
"""

import time
from pathlib import Path

import pandas as pd

HERE     = Path(__file__).resolve().parent
SRC_DIR  = HERE / 'daily_data'        # existing universe (ticker list only)
OUT_DIR  = HERE / 'daily_data_10y'    # new 10-year files land here
START    = '2016-01-01'
MIN_BARS = 750                        # ~3 years minimum to keep a ticker
PAUSE    = 0.4                        # polite delay between requests


def main():
    try:
        import yfinance as yf
    except ImportError:
        raise SystemExit('yfinance missing — run: pip3.12 install yfinance')

    if not SRC_DIR.exists():
        raise SystemExit(f'{SRC_DIR} not found — run from ~/Documents/STS/15min')

    OUT_DIR.mkdir(exist_ok=True)
    tickers = sorted(p.stem.upper() for p in SRC_DIR.glob('*.csv'))
    if 'SPY' not in tickers:
        tickers.append('SPY')
    print(f'  {len(tickers)} tickers | {START} -> today | out: {OUT_DIR.name}/')

    done = {p.stem.upper() for p in OUT_DIR.glob('*.csv')}
    todo = [t for t in tickers if t not in done]
    if done:
        print(f'  {len(done)} already downloaded — resuming with {len(todo)}')

    ok, failed, short = len(done), [], []
    for i, tk in enumerate(todo, 1):
        try:
            df = yf.download(tk, start=START, interval='1d',
                             auto_adjust=True, progress=False)
            # flatten possible MultiIndex columns
            df.columns = [c[0] if isinstance(c, tuple) else c
                          for c in df.columns]
            df = df.rename(columns=str.title)
            need = ['Open', 'High', 'Low', 'Close', 'Volume']
            df = df[[c for c in need if c in df.columns]].dropna()
            if len(df) < MIN_BARS:
                short.append(f'{tk}({len(df)})')
                continue
            out = df.reset_index().rename(columns={'index': 'Date'})
            out.to_csv(OUT_DIR / f'{tk}.csv', index=False)
            ok += 1
        except Exception as e:
            failed.append(tk)
        if i % 25 == 0:
            print(f'  [{i}/{len(todo)}]  saved {ok}  '
                  f'failed {len(failed)}  short {len(short)}')
        time.sleep(PAUSE)

    print(f'\n  DONE: {ok} saved to {OUT_DIR.name}/')
    if short:
        print(f'  Short history (<{MIN_BARS} bars, skipped): '
              f'{", ".join(short[:15])}'
              + (' ...' if len(short) > 15 else ''))
    if failed:
        print(f'  Failed: {", ".join(failed[:15])}'
              + (' ...' if len(failed) > 15 else ''))
    print('\n  Next:  python3.12 backtest_uts_exit_sweep.py daily_data_10y')


if __name__ == '__main__':
    main()
