#!/usr/bin/env python3.12
"""
refresh_v2.py — nightly data refresh for the SEPARATE v2 universe (daily_data_v2/)
plus the expansion folders daily_data_ext/ and daily_data_slow_ext/.

Marketstack-first (append-only via data_refresh.py: only the missing sessions
are fetched, ~3 requests per 100 tickers, history re-adjusted for any
dividend/split). If Marketstack fails for a folder, or has not published the
expected session yet, that folder falls back to the old Yahoo route: 2y (v2) /
1y (ext) batch download merged into each CSV, fresh values winning on overlap.
STS_FORCE_YAHOO=1 skips Marketstack. Run by run_v2_evening.sh before
eval_universe_v2.py.
"""
import os, glob
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
OUTDIR = HERE / "daily_data_v2"
COLS = ["Open", "High", "Low", "Close", "Volume"]

EXTDIR = HERE / "daily_data_ext"     # fast-lane expansion universe (refreshed too)

SLOWDIR = HERE / "daily_data_slow_ext"

def _env(key, default=""):
    v = os.environ.get(key)
    if v: return v
    try:
        for line in open(HERE / ".env"):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return default

def _expected_session():
    """Last closed session, New York time: today after 16:00 ET on a weekday,
    otherwise the previous weekday."""
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = dt.datetime.now()
    d = now.date()
    if (now.hour, now.minute) < (16, 0):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()

def refresh_marketstack():
    """Returns the set of folders that are current after the Marketstack pass
    (the caller runs the Yahoo route for the rest)."""
    # OFF unless V2_MARKETSTACK=1 is set in .env: Marketstack bills per SYMBOL and
    # these three research folders are ~2,650 names a night (~56k/month) — far more
    # than any affordable plan. They are never displayed, so Yahoo is acceptable
    # here (GJ, Sep 16). Found out via a $125 overage on 2026-10-22.
    if _env("V2_MARKETSTACK", "") != "1":
        return set()
    if _env("EOD_PROVIDER", "").lower() != "marketstack" or os.environ.get("STS_FORCE_YAHOO"):
        return set()
    try:
        from data_refresh import refresh_all
        reps = refresh_all(["daily_data_v2", "daily_data_ext", "daily_data_slow_ext"],
                           {"daily_data_v2": ["SPY", "RSP"]})
    except Exception as e:                           # noqa: BLE001
        print(f"Marketstack refresh failed: {e} -> Yahoo for all folders")
        return set()
    exp = _expected_session(); ok = set()
    for r in reps:
        fatal = [e for e in r.errors if e.startswith("marketstack:")]
        if fatal:
            print(f"  {r.folder}: {fatal[0]} -> Yahoo")
        elif r.folder != "daily_data_slow_ext" and (not r.latest_date or r.latest_date < exp):
            print(f"  {r.folder}: latest {r.latest_date} < expected {exp} -> Yahoo")
        else:
            ok.add(r.folder)
    return ok

def main():
    tickers = sorted({os.path.splitext(os.path.basename(f))[0].upper()
                      for f in glob.glob(str(OUTDIR / "*.csv"))} | {"SPY", "RSP"})
    ext = sorted({os.path.splitext(os.path.basename(f))[0].upper()
                  for f in glob.glob(str(EXTDIR / "*.csv"))} - set(tickers))
    if not tickers:
        raise SystemExit("daily_data_v2/ is empty — run build_universe.py first")
    done = refresh_marketstack()
    if "daily_data_v2" in done:
        tickers = []
    if "daily_data_ext" in done:
        ext = []
    if not tickers and not ext:
        print("All folders refreshed from Marketstack."); return
    import yfinance as yf
    updated = failed = 0
    CH = 100
    if tickers: print(f"Refreshing {len(tickers)} v2 tickers from Yahoo (2y batch) ...")
    for i in range(0, len(tickers), CH):
        chunk = tickers[i:i+CH]
        try:
            raw = yf.download(chunk, period="2y", progress=False,
                              auto_adjust=True, group_by="ticker", threads=True)
        except Exception as e:
            print(f"  batch {i//CH+1} failed: {e}"); failed += len(chunk); continue
        for t in chunk:
            try:
                f = (raw[t] if len(chunk) > 1 else raw).dropna()
                f = f[[c for c in COLS if c in f.columns]]
                if len(f) == 0: failed += 1; continue
                f.index = pd.to_datetime(f.index); f.index.name = "Date"
                path = OUTDIR / f"{t}.csv"
                if path.exists():
                    old = pd.read_csv(path, index_col=0, parse_dates=True)
                    old = old[[c for c in COLS if c in old.columns]]
                    merged = pd.concat([old[old.index < f.index.min()], f]).sort_index()
                    merged = merged[~merged.index.duplicated(keep="last")]
                else:
                    merged = f
                merged.reset_index().to_csv(path, index=False)
                updated += 1
            except Exception:
                failed += 1
        print(f"  {min(i+CH, len(tickers))}/{len(tickers)} done")
    if tickers: print(f"v2 refresh (Yahoo): {updated} updated, {failed} failed")
    # ---- fast-lane expansion universe (daily_data_ext) — same merge, 1y window ----
    if ext:
        print(f"Refreshing {len(ext)} ext tickers from Yahoo ...")
        eupd = 0
        for i in range(0, len(ext), CH):
            chunk = ext[i:i+CH]
            try:
                raw = yf.download(chunk, period="1y", progress=False,
                                  auto_adjust=True, group_by="ticker", threads=True)
            except Exception:
                continue
            for t in chunk:
                try:
                    f = (raw[t] if len(chunk) > 1 else raw).dropna()
                    f = f[[c for c in COLS if c in f.columns]]
                    if len(f) == 0: continue
                    f.index = pd.to_datetime(f.index); f.index.name = "Date"
                    path = EXTDIR / f"{t}.csv"
                    old = pd.read_csv(path, index_col=0, parse_dates=True)
                    old = old[[c for c in COLS if c in old.columns]]
                    merged = pd.concat([old[old.index < f.index.min()], f]).sort_index()
                    merged = merged[~merged.index.duplicated(keep="last")]
                    merged.reset_index().to_csv(path, index=False)
                    eupd += 1
                except Exception: pass
        print(f"ext refresh: {eupd} updated")

if __name__ == "__main__":
    main()
