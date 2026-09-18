#!/usr/bin/env python3.12
"""
build_universe.py — expand the STS universe to the full liquid US large/mid-cap
population (S&P 500 + S&P 400 mid-cap) PLUS a personal watchlist, PLUS everything
already downloaded. This is the "green-ring-eligible" universe: the population the
ML model was trained on and where its edge is validated.

WHAT IT DOES
  1. Collects tickers from four sources:
       - S&P 500  (large cap)      via Wikipedia
       - S&P 400  (mid cap)        via Wikipedia
       - WATCHLIST (below)         your personal names (VEEV, SNOW, TTD, ARM, ...)
       - existing daily_data_10y/  (every name already in the live universe)
  2. Drops ETFs / index funds (they aren't equities).
  3. Downloads ~10 years of FRESH daily bars into daily_data_v2/ for every name
     that is missing OR stale (last bar older than a few days). This is REQUIRED
     for the 7/20 apples-to-apples replay: the live daily_data_10y/ CSVs are
     frozen at ~7/10 (the nightly scan fetches yfinance at runtime and never
     rewrites the CSVs), so they have NO forward data past the replay start.
  4. Writes daily_data_v2/<TICKER>.csv and a universe_v2_tickers.txt manifest.

SEPARATE / SANDBOXED: everything lands in daily_data_v2/ (NEVER the live
daily_data_10y/). We do NOT hard-link — a hard link shares the inode with the
live file, so refreshing in place would silently overwrite your live data.
Evaluate with eval_universe_v2.py before merging.

BAR THRESHOLDS
  - Index names (S&P 500/400): need >= 750 bars (~3yr) to match the training
    distribution the model was fit on.
  - Watchlist names: need only >= 260 bars (enough for a 200-SMA + 52wk high),
    so young explicit picks (ARM, CRWV, NBIS, ALAB, SNDK) are still included.

RUN (on your Mac, needs internet):
    cd ~/STS/15min && python3.12 build_universe.py         # builds daily_data_v2/
    cd ~/STS/15min && python3.12 eval_universe_v2.py       # -> STS_holy_grail_v2.xlsx
    # resumable: safe to re-run; it skips names already fresh in daily_data_v2/.

To MERGE later (only once you're happy): rsync daily_data_v2/ into daily_data_10y/.
"""
import os, time, sys, ssl
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

HERE   = Path(__file__).resolve().parent
LIVE   = HERE / "daily_data_10y"      # existing live universe (READ-ONLY here, never written)
OUTDIR = HERE / "daily_data_v2"       # the new, SEPARATE expanded universe
START  = "2016-01-01"
MIN_BARS_INDEX = 750                  # ~3yr, matches the model's training distribution
MIN_BARS_WATCH = 260                  # enough for a 200-SMA + 52wk high (young names)
STALE_DAYS = 4                        # re-download if the last bar is older than this
PAUSE  = 0.25

# --- your personal watchlist: names to guarantee inclusion regardless of index ---
WATCHLIST = [
    "VEEV", "SNOW", "TTD", "ARM", "ASML", "SE",       # the known gaps
    "RKLB", "CRWV", "HOOD", "COIN", "PLTR", "NBIS",    # growth/personal
    "ALAB", "SNDK", "MU", "MRVL", "WDC",               # already-owned names
]
WATCH_SET = {t.upper() for t in WATCHLIST}

# ETFs / index funds to exclude (not equities)
ETF = {"SPY","QQQ","IWM","DIA","GLD","SLV","USO","SOXX","SMH","RSP","TLT","HYG",
       "ARKK","VOO","VTI","XLB","XLE","XLF","XLI","XLK","XLU","XLV","XLY","UNG",
       "UUP","FXI","KWEB","IBB","XBI","IGV","ITB","KRE","XRT","XOP","GDX","JETS",
       "VNQ","AGG","BND","LQD","SQQQ","TQQQ","UVXY","VXX","BITO"}


def _read_html_any(url):
    """Fetch a URL's tables, working around the macOS urllib cert problem.
    Primary: requests (uses certifi's CA bundle, independent of the system store —
    this is the same path yfinance downloads work over). Fallback: urllib with an
    UNVERIFIED SSL context (last resort so a cert glitch never blocks the build)."""
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        return pd.read_html(StringIO(r.text))
    except Exception as e1:
        try:
            import urllib.request
            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                html = resp.read().decode("utf-8", "replace")
            return pd.read_html(StringIO(html))
        except Exception as e2:
            raise RuntimeError(f"requests:{e1} | urllib:{e2}")


def sp_constituents(url, label):
    """Fetch the Symbol column from a Wikipedia constituents table."""
    try:
        tables = _read_html_any(url)
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if "symbol" in cols:
                col = t.columns[cols.index("symbol")]
                syms = [str(s).strip().upper().replace(".", "-") for s in t[col].dropna()]
                syms = [s for s in syms if s and s.replace("-", "").isalnum()]
                print(f"  {label}: {len(syms)} tickers")
                return syms
        print(f"  {label}: no 'symbol' column found")
    except Exception as e:
        print(f"  {label}: FAILED ({e})")
    return []


def _last_bar_date(path):
    """Return the last date in a CSV quickly (read the final line), or None."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            back = min(size, 4096)
            fh.seek(size - back)
            last = fh.read().decode("utf-8", "replace").strip().splitlines()[-1]
        return pd.to_datetime(last.split(",")[0], errors="coerce")
    except Exception:
        return None


def main():
    OUTDIR.mkdir(exist_ok=True)
    print("Collecting the universe ...")
    tickers = set()
    tickers |= set(sp_constituents("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "S&P 500"))
    tickers |= set(sp_constituents("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "S&P 400 mid-cap"))
    tickers |= WATCH_SET
    live_files = {p.stem.upper() for p in LIVE.glob("*.csv")}
    tickers |= live_files
    tickers -= ETF
    tickers |= {"SPY", "RSP"}   # benchmarks: not scored, but the eval needs them for excess-vs-SPY
    tickers = sorted(t for t in tickers if t and t.replace("-", "").isalnum())
    print(f"\nUniverse v2 target: {len(tickers)} tickers "
          f"(watchlist {len(WATCH_SET)}, existing-live {len(live_files)})")

    (HERE / "universe_v2_tickers.txt").write_text("\n".join(tickers) + "\n")

    # decide what needs downloading: missing OR stale (last bar older than STALE_DAYS).
    cutoff = pd.Timestamp(datetime.now().date() - timedelta(days=STALE_DAYS))
    todo, fresh = [], 0
    for t in tickers:
        dst = OUTDIR / f"{t}.csv"
        if dst.exists() and not dst.is_symlink():
            last = _last_bar_date(dst)
            # if it's a hard link into live, os.stat links > 1 → treat as needing a clean rewrite
            if last is not None and last >= cutoff and os.stat(dst).st_nlink == 1:
                fresh += 1
                continue
        todo.append(t)
    print(f"  {fresh} already fresh in daily_data_v2/, {len(todo)} to (re)download\n")

    if not todo:
        print("Nothing to download — daily_data_v2/ is current."); return
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance missing — pip3.12 install yfinance --break-system-packages")

    ok = fresh; failed, short = [], []
    for i, tk in enumerate(todo, 1):
        try:
            df = yf.download(tk, start=START, interval="1d",
                             auto_adjust=True, progress=False)
            if df is None or len(df) == 0:
                failed.append(tk)
            else:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df = df.rename(columns=str.title)
                need = ["Open", "High", "Low", "Close", "Volume"]
                df = df[[c for c in need if c in df.columns]].dropna()
                floor = MIN_BARS_WATCH if tk in WATCH_SET else MIN_BARS_INDEX
                if len(df) < floor:
                    short.append(f"{tk}({len(df)})")
                else:
                    dst = OUTDIR / f"{tk}.csv"
                    # SAFETY: remove any existing file/hard-link FIRST so we never
                    # write through a shared inode into the live daily_data_10y CSV.
                    if dst.exists():
                        os.remove(dst)
                    df.reset_index().rename(columns={"index": "Date"}).to_csv(dst, index=False)
                    ok += 1
        except Exception:
            failed.append(tk)
        if i % 25 == 0:
            print(f"  [{i}/{len(todo)}] saved {ok} | failed {len(failed)} | short {len(short)}")
        time.sleep(PAUSE)

    print(f"\nDONE: daily_data_v2/ now holds {ok} tickers (through today).")
    if short:  print(f"  skipped (too few bars): {', '.join(short[:25])}" + (" ..." if len(short) > 25 else ""))
    if failed: print(f"  failed to fetch: {', '.join(failed[:25])}" + (" ..." if len(failed) > 25 else ""))
    print("\nNext: python3.12 eval_universe_v2.py  (7/20 apples-to-apples replay)")


if __name__ == "__main__":
    main()
