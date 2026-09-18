#!/usr/bin/env python3
"""
compare_sources.py — is Marketstack history interchangeable with the yfinance
history already in daily_data_10y/?

Downloads a SAMPLE of tickers from Marketstack and compares, day by day, against
the stored yfinance series. Nothing is written to daily_data_10y/ and nothing in
the pipeline changes — this only tells you whether a migration is a swap or a
recalibration.

Why it compares adjusted prices
-------------------------------
daily_data_10y/ was built with yfinance auto_adjust=True, i.e. every historical
bar is restated when a split or dividend occurs. Marketstack returns raw OHLC and
separate adj_* fields. Comparing raw against adjusted disagrees enormously on any
name that has ever split, so this compares Marketstack's adj_close by default.

Usage
-----
    cd ~/STS/15min
    /usr/local/bin/python3.12 compare_sources.py                 # default sample
    /usr/local/bin/python3.12 compare_sources.py --years 3
    /usr/local/bin/python3.12 compare_sources.py --tickers NVDA,AAPL,KO
    /usr/local/bin/python3.12 compare_sources.py --raw           # compare raw close instead

Reads MARKETSTACK_API_KEY / EOD_PROVIDER from .env, same as the pipeline.
"""
import argparse, os, sys, csv, math, datetime as dt
from pathlib import Path

DIR = Path(__file__).resolve().parent
UNIVERSE = DIR / "daily_data_10y"

# A deliberately awkward sample, not a random one. Each group stresses a different
# way two vendors can disagree; a clean result on these is worth far more than a
# clean result on twenty quiet large caps.
SAMPLE = [
    # recent splits — the single most likely source of a mismatch
    "NVDA",   # 10:1 in 2024
    "AAPL",   # 4:1 in 2020
    "TSLA",   # 3:1 in 2022
    "AMZN",   # 20:1 in 2022
    # meaningful dividends — separates "splits only" from "splits + dividends"
    "KO", "JNJ", "XOM", "T",
    # no dividend, no split — the control group; these SHOULD match almost exactly
    "GOOGL", "META", "AMD", "CRM",
    # benchmarks the pipeline itself depends on
    "SPY", "RSP", "QQQ",
]

TOL_PCT = 0.10          # a day is "clean" if the two sources are within 0.10%
LOUD_PCT = 1.00         # a day above this is called out individually


def load_yf(ticker: str, start: str):
    """Stored yfinance series -> {date: close}. Handles .csv and .parquet."""
    csv_path = UNIVERSE / f"{ticker}.csv"
    if csv_path.exists():
        out = {}
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                d = str(row.get("Date", ""))[:10]
                if d >= start:
                    try:
                        out[d] = float(row["Close"])
                    except (KeyError, TypeError, ValueError):
                        pass
        return out
    pq = UNIVERSE / f"{ticker}.parquet"
    if pq.exists():
        try:
            import pandas as pd
        except ImportError:
            return {}
        df = pd.read_parquet(pq)
        df.index = df.index.astype(str)
        return {str(i)[:10]: float(c) for i, c in df["Close"].items() if str(i)[:10] >= start}
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="comma-separated; default is the built-in sample")
    ap.add_argument("--years", type=float, default=2.0, help="how far back to compare")
    ap.add_argument("--raw", action="store_true", help="compare raw close instead of adjusted")
    ap.add_argument("--show-divs", action="store_true",
                    help="print the dividend rows Marketstack returned for each ticker (find duplicates / off-by-one ex-dates)")
    ap.add_argument("--split-only", action="store_true",
                    help="compare Marketstack adj_close as delivered (splits only), without the dividend adjustment")
    args = ap.parse_args()

    sys.path.insert(0, str(DIR))
    try:
        from eod_adapter import get_provider, EODError, total_return_adjust
    except ImportError as e:
        sys.exit(f"cannot import eod_adapter: {e}")

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else SAMPLE
    start = (dt.date.today() - dt.timedelta(days=int(args.years * 365.25))).isoformat()
    end = dt.date.today().isoformat()
    field = "raw close" if args.raw else ("split-adjusted close" if args.split_only else "total-return close (splits + dividends)")

    prov = get_provider()
    print(f"provider={prov.name}  comparing {field}  from {start}  ({len(tickers)} tickers)\n")
    # `oldest%` and `newest%` are the diagnosis, not the size. A gap that is large
    # in the past and ~0 today is CUMULATIVE — dividend adjustment, where one source
    # back-adjusts history and the other doesn't. A gap that is constant across time
    # is a units/source difference. A sudden step is a split handled differently.
    print(f"{'ticker':<7} {'days':>5} {'median%':>8} {'max%':>8} {'oldest%':>8} {'newest%':>8} {'>1%':>5}  shape")
    print("-" * 82)

    verdicts, calls = [], 0
    for t in tickers:
        yf = load_yf(t, start)
        if not yf:
            print(f"{t:<7} {'-':>5} {'':>8} {'':>7} {'':>8} {'':>6} {'':>5}  no local history")
            continue
        try:
            bars = prov.get_history(t, start, end)
            calls += 1
            if not args.raw and not args.split_only:
                # only ex-dates inside the window move prices inside the window
                divs = prov.get_dividends(t, start, end)
                calls += 1
                if args.show_divs:
                    print(f"  {t} dividends from marketstack ({len(divs)}):")
                    seen = {}
                    for d, amt in divs:
                        dup = "   <-- DUPLICATE?" if seen.get(amt) and (dt.date.fromisoformat(d) - seen[amt]).days < 60 else ""
                        print(f"      {d}  {amt:.4f}{dup}")
                        seen[amt] = dt.date.fromisoformat(d)
                    print(f"  stored yfinance history ends {max(yf)}")
                bars = total_return_adjust(bars, divs)
        except Exception as e:                      # noqa: BLE001
            print(f"{t:<7} {'-':>5} {'':>8} {'':>7} {'':>8} {'':>6} {'':>5}  FETCH FAILED: {e}")
            continue

        diffs, loud, series = [], [], []
        for b in bars:
            v = b.close if args.raw else (b.adj_close if b.adj_close is not None else b.close)
            y = yf.get(b.date)
            if y is None or not y or v is None or v <= 0:
                continue
            signed = (v - y) / y * 100.0          # keep the sign: direction is the clue
            pct = abs(signed)
            diffs.append(pct)
            series.append((b.date, signed))
            if pct > LOUD_PCT:
                loud.append((b.date, y, v, pct))
        series.sort()

        if not diffs:
            print(f"{t:<7} {'0':>5} {'':>8} {'':>7} {'':>8} {'':>6} {'':>5}  NO OVERLAPPING DATES")
            continue

        diffs.sort()
        med = diffs[len(diffs) // 2]
        mx = diffs[-1]
        over_loud = len(loud)
        # average the first/last 10 overlapping days so one odd bar can't set the shape
        head = sum(v for _, v in series[:10]) / min(10, len(series))
        tail = sum(v for _, v in series[-10:]) / min(10, len(series))
        ok = med <= TOL_PCT and over_loud == 0
        if ok:
            shape = "match"
        elif abs(tail) < 0.05 and abs(head) > 0.15:
            shape = "CUMULATIVE (dividends)"
        elif abs(abs(head) - abs(tail)) < 0.10:
            shape = "CONSTANT offset"
        else:
            shape = "DIFFERS"
        verdicts.append(ok)
        print(f"{t:<7} {len(diffs):>5} {med:>8.3f} {mx:>8.3f} {head:>8.3f} {tail:>8.3f} {over_loud:>5}  {shape}")
        for d, y, v, pct in loud[:3]:
            print(f"        {d}  stored={y:.4f}  marketstack={v:.4f}  ({pct:.2f}%)")
        if len(loud) > 3:
            print(f"        ... and {len(loud)-3} more days over {LOUD_PCT}%")

    print("-" * 82)
    good = sum(1 for v in verdicts if v)
    print(f"{good}/{len(verdicts)} tickers match within {TOL_PCT}% median and no day over {LOUD_PCT}%")
    print(f"api calls used: ~{calls}")
    if verdicts and good == len(verdicts):
        print("\nVERDICT: sources look interchangeable on this sample.")
        print("Next: backfill the full universe, then re-run the scan on both and")
        print("compare the score>=2 candidate sets before changing the pipeline.")
    else:
        print("\nVERDICT: at least one ticker disagrees. Look at the days printed above")
        print("before backfilling anything — a split handled differently will silently")
        print("corrupt the 200-day and 52-week features for that name only.")


if __name__ == "__main__":
    main()
