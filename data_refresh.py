#!/usr/bin/env python3
"""
data_refresh.py — nightly price-history refresh, Marketstack-first, Yahoo as fallback.

WHY
  The nightly used to re-download two years of bars for ~600 (live) and ~1,000
  (v2) tickers from Yahoo every evening. Yahoo is unlicensed for this use, lags
  (2026-10-16: the session's row came back with NaN prices at 8:33 pm), and
  blocks datacenter IPs. Marketstack is the licensed feed already used for board
  prices. This module keeps every data folder current by APPENDING only the
  sessions that are missing, from Marketstack, in a handful of multi-symbol
  requests — then re-adjusts stored history for any dividend or split, so the
  CSVs stay total-return adjusted exactly the way yfinance (auto_adjust=True)
  built them and the model was trained on.

HOW THE ADJUSTMENT STAYS CONSISTENT
  yfinance's adjusted series has the LATEST bar equal to the raw bar; every
  earlier bar is scaled by the dividends and splits that happened after it.
  So appending a raw Marketstack bar is correct as long as no corporate action
  has occurred since the last stored bar. When one has:
    dividend (ex-date x, amount a): every stored bar dated < x is multiplied by
      (1 - a / raw_close_before_x)        — same formula as total_return_adjust()
    split (date s, factor f):      every stored bar dated < s has prices / f,
      volume * f
  Actions are applied oldest-first. On a normal night there are none.

REQUEST BUDGET — Marketstack bills PER SYMBOL (each symbol in a multi-symbol
  call counts as one request, per page). Verified the hard way on 2026-10-22:
  3 endpoints x ~3,250 tickers/night blew through Basic's 10,000 in four nights
  ($125 overage). Now ONE call per symbol per night (dividends and split factors
  are read from the EOD rows themselves). Use it only for folders that must be
  licensed: daily_data_10y (605 names ≈ 13k/month). Research folders stay on Yahoo.

FALLBACK
  If Marketstack fails for a whole folder (network, auth, quota), the caller
  falls back to the old yfinance path (fetch_batch + write_back / refresh_v2).
  Per-ticker gaps (a name Marketstack does not carry) are left for the Yahoo
  retry list and reported.

USAGE
  from data_refresh import refresh_folder
  report = refresh_folder("daily_data_10y", extra=["SPY", "RSP"])
  # report.updated, report.unchanged, report.missing (tickers with no new bar),
  # report.actions (dividends/splits applied), report.requests
  CLI:  python3 data_refresh.py daily_data_10y daily_data_v2 ...   [--dry-run]
"""
from __future__ import annotations
import os, sys, glob, time, datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eod_adapter import MarketstackProvider, EODError, _load_dotenv  # noqa: E402

COLS = ["Open", "High", "Low", "Close", "Volume"]
CHUNK = 100                    # Marketstack: max symbols per request
MAX_GAP_SESSIONS = 60          # a ticker further behind than this is treated as dead (closed/delisted) — not refreshed
SEED_PER_NIGHT = 25            # tickers with no CSV at all: seed at most this many per night (1 history request each + dividends)
SEED_YEARS = 10


@dataclass
class Report:
    folder: str
    updated: int = 0
    unchanged: int = 0
    missing: list = field(default_factory=list)      # tickers that got no new bar
    dead: list = field(default_factory=list)         # skipped: too far behind (closed/delisted)
    seeded: list = field(default_factory=list)
    actions: list = field(default_factory=list)      # (ticker, kind, date, value)
    requests: int = 0
    latest_date: Optional[str] = None
    errors: list = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.folder}: {self.updated} updated, {self.unchanged} unchanged, "
                f"{len(self.missing)} no-new-bar, {len(self.dead)} dormant, {len(self.seeded)} seeded, "
                f"{len(self.actions)} corporate actions, {self.requests} requests"
                + (f", latest {self.latest_date}" if self.latest_date else "")
                + (f", {len(self.errors)} errors" if self.errors else ""))


class _MS(MarketstackProvider):
    """Marketstack with multi-symbol range endpoints and a request counter."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.requests = 0

    def _get(self, url, params, timeout=30, tries=3):
        self.requests += 1
        return super()._get(url, params, timeout=timeout, tries=tries)

    def eod_range_many(self, tickers: list[str], date_from: str, date_to: str) -> dict[str, list]:
        """Raw EOD rows for many symbols over a date range. One request per 100
        symbols per 1000-row page (a 10-session catch-up for 100 names fits in one)."""
        out: dict[str, list] = {t: [] for t in tickers}
        self.events = getattr(self, "events", {"div": {}, "split": {}})
        for i in range(0, len(tickers), CHUNK):
            chunk = tickers[i:i + CHUNK]
            rows = self._paged("eod", {"access_key": self.key, "symbols": ",".join(chunk),
                                       "date_from": date_from, "date_to": date_to, "sort": "ASC"})
            for r in rows:
                b = self._bar(r)
                if b is not None:
                    out.setdefault(b.ticker, []).append(b)
                # Each EOD row carries that day's dividend and split_factor, so the
                # corporate actions come free with the bars. The separate
                # /dividends and /splits endpoints TRIPLED the bill (Marketstack
                # charges per SYMBOL per call, not per call — see 2026-10-22).
                sym = str(r.get("symbol", "")).upper(); d = str(r.get("date", ""))[:10]
                dv = self._f(r, "dividend"); sf = self._f(r, "split_factor")
                if sym and d and dv and dv > 0:
                    self.events["div"].setdefault(sym, []).append((d, float(dv)))
                if sym and d and sf and sf > 0 and abs(sf - 1.0) > 1e-9:
                    self.events["split"].setdefault(sym, []).append((d, float(sf)))
        return out

    def _events_many(self, path: str, tickers: list[str], date_from: str, date_to: str,
                     value_key: str) -> dict[str, list[tuple[str, float]]]:
        out: dict[str, list] = {}
        for i in range(0, len(tickers), CHUNK):
            chunk = tickers[i:i + CHUNK]
            try:
                rows = self._paged(path, {"access_key": self.key, "symbols": ",".join(chunk),
                                          "date_from": date_from, "date_to": date_to, "sort": "ASC"})
            except EODError as e:
                # Multi-symbol may be refused on some plans: fall back to per-symbol
                # for this chunk only if it is small; otherwise report and skip.
                if len(chunk) <= 10:
                    rows = []
                    for t in chunk:
                        rows += self._paged(path, {"access_key": self.key, "symbols": t,
                                                   "date_from": date_from, "date_to": date_to, "sort": "ASC"})
                else:
                    raise EODError(f"{path} multi-symbol failed: {e}")
            for r in rows:
                v = self._f(r, value_key)
                d = str(r.get("date", ""))[:10]
                sym = str(r.get("symbol", "")).upper()
                if v and v > 0 and d and sym:
                    out.setdefault(sym, []).append((d, float(v)))
        for k in out:
            out[k].sort()
        return out

    def dividends_many(self, tickers, date_from, date_to):
        return self._events_many("dividends", tickers, date_from, date_to, "dividend")

    def splits_many(self, tickers, date_from, date_to):
        return self._events_many("splits", tickers, date_from, date_to, "split_factor")


# --------------------------------------------------------------------------- #
#  CSV helpers
# --------------------------------------------------------------------------- #
def _read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    df = df[[c for c in COLS if c in df.columns]]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "Date"
    df = df[~df.index.duplicated(keep="last")]
    return df


def _write_csv(path: Path, df: pd.DataFrame) -> None:
    df = df.sort_index()
    df.index.name = "Date"
    tmp = path.with_suffix(".csv.tmp")
    df.reset_index().to_csv(tmp, index=False)
    os.replace(tmp, path)


def _bars_to_df(bars) -> pd.DataFrame:
    """Raw (unadjusted) bars -> DataFrame in CSV layout. The newest bars of a
    total-return-adjusted series are, by construction, the raw bars."""
    rows = []
    for b in bars:
        rows.append(dict(Date=pd.Timestamp(b.date), Open=b.open, High=b.high, Low=b.low,
                         Close=b.close, Volume=(b.volume if b.volume is not None else np.nan)))
    if not rows:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame(rows).set_index("Date").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[COLS]


def apply_dividend(df: pd.DataFrame, ex_date: pd.Timestamp, amount: float) -> tuple[pd.DataFrame, Optional[float]]:
    """yfinance-style: scale every bar before ex_date by (1 - amount/prev_close),
    prev_close = the close of the last bar before ex_date (which is raw at that
    point, because no later action has touched it yet). Returns (df, factor)."""
    before = df.index < ex_date
    if not before.any():
        return df, None
    prev = float(df.loc[before, "Close"].iloc[-1])
    if not (prev > 0) or not (amount < prev):
        return df, None
    f = 1.0 - amount / prev
    df = df.copy()
    df.loc[before, ["Open", "High", "Low", "Close"]] *= f
    return df, f


def apply_split(df: pd.DataFrame, date: pd.Timestamp, factor: float) -> tuple[pd.DataFrame, Optional[float]]:
    """Split with `factor` new shares per old share, effective on `date`:
    prices before the date / factor, volume * factor."""
    before = df.index < date
    if not before.any() or not factor or factor <= 0 or abs(factor - 1.0) < 1e-9:
        return df, None
    df = df.copy()
    df.loc[before, ["Open", "High", "Low", "Close"]] /= factor
    if "Volume" in df.columns:
        df.loc[before, "Volume"] = (df.loc[before, "Volume"] * factor).round()
    return df, factor


def merge_new_bars(old: pd.DataFrame, new: pd.DataFrame,
                   dividends: list[tuple[str, float]], splits: list[tuple[str, float]]):
    """Append the new raw bars, then apply every corporate action dated after
    the last stored bar (oldest first) to the combined frame. Appending first
    matters when the catch-up spans several sessions: a dividend ex Thursday
    must also scale the freshly fetched Tuesday/Wednesday bars, and its
    previous close is Wednesday's raw close — exactly as yfinance computes it.
    Returns (df, actions_applied)."""
    applied = []
    last = old.index.max() if len(old) else None
    df = old
    if len(new):
        if last is not None:
            new = new[new.index > last]
        df = pd.concat([df, new]).sort_index() if len(df) else new
        df = df[~df.index.duplicated(keep="last")]
    events = [("div", pd.Timestamp(d), a) for d, a in dividends] + \
             [("split", pd.Timestamp(d), f) for d, f in splits]
    events.sort(key=lambda e: e[1])
    for kind, when, val in events:
        if last is not None and when <= last:
            continue                                  # already reflected in stored history
        if kind == "div":
            df, f = apply_dividend(df, when, val)
        else:
            df, f = apply_split(df, when, val)
        if f is not None:
            applied.append((kind, when.date().isoformat(), val))
    return df, applied


# --------------------------------------------------------------------------- #
#  Folder refresh
# --------------------------------------------------------------------------- #
def _tickers_in(folder: Path) -> list[str]:
    return sorted({os.path.splitext(os.path.basename(f))[0].upper() for f in glob.glob(str(folder / "*.csv"))})


def refresh_folder(folder: str | Path, extra: Iterable[str] = (), provider: Optional[_MS] = None,
                   today: Optional[dt.date] = None, dry_run: bool = False, verbose: bool = True) -> Report:
    folder = Path(folder) if os.path.isabs(str(folder)) else HERE / folder
    rep = Report(folder=folder.name)
    today = today or dt.date.today()
    date_to = today.isoformat()
    prov = provider or _MS()
    existing = _tickers_in(folder)
    want = sorted(set(existing) | {t.upper() for t in extra})
    if not want:
        rep.errors.append("empty folder"); return rep

    # where each ticker stands
    last: dict[str, Optional[pd.Timestamp]] = {}
    frames: dict[str, pd.DataFrame] = {}
    for t in want:
        p = folder / f"{t}.csv"
        if p.exists():
            try:
                df = _read_csv(p); frames[t] = df
                last[t] = df.index.max() if len(df) else None
            except Exception as e:                    # noqa: BLE001
                rep.errors.append(f"{t}: unreadable CSV ({e})"); last[t] = None
        else:
            last[t] = None

    # business-day calendar guess for "how far behind"
    # sessions strictly AFTER the last stored bar, up to and including today
    # (busday_count is half-open: [last+1, today+1) — a Sunday run after a Friday bar = 0)
    bdays_since = lambda d: int(np.busday_count(d.date() + dt.timedelta(days=1), today + dt.timedelta(days=1))) if d is not None else None
    active, seed, dead = [], [], []
    for t in want:
        if t not in frames:
            seed.append(t); continue
        n = bdays_since(last[t])
        if n is None or n > MAX_GAP_SESSIONS:
            dead.append(t)
        elif n >= 1:
            active.append(t)
        else:
            rep.unchanged += 1
    rep.dead = dead
    on_disk = [last[t] for t in want if last.get(t) is not None]
    if on_disk:                       # latest bar already on disk (so a no-op night still reports it)
        rep.latest_date = max(on_disk).date().isoformat()
    if verbose:
        print(f"[{rep.folder}] {len(want)} tickers: {len(active)} to refresh, {rep.unchanged} current, "
              f"{len(dead)} dormant, {len(seed)} to seed")

    # ---- fetch new bars + corporate actions for the active set ----
    # Tickers are chunked in order of how far behind they are, and each chunk
    # asks only from ITS earliest missing session: one laggard (a name that
    # stopped printing weeks ago) must not turn every chunk into a 2-month pull.
    if active:
        active.sort(key=lambda t: last[t])
        bars, divs, spl = {}, {}, {}
        try:
            for i in range(0, len(active), CHUNK):
                chunk = active[i:i + CHUNK]
                date_from = (last[chunk[0]] + pd.Timedelta(days=1)).date().isoformat()
                prov.events = {"div": {}, "split": {}}
                bars.update(prov.eod_range_many(chunk, date_from, date_to))
                divs.update(prov.events["div"]); spl.update(prov.events["split"])
        except EODError as e:
            rep.errors.append(f"marketstack: {e}"); rep.requests = prov.requests
            return rep
        for t in active:
            new = _bars_to_df(bars.get(t, []))
            old = frames[t]
            df, applied = merge_new_bars(old, new, divs.get(t, []), spl.get(t, []))
            for kind, when, val in applied:
                rep.actions.append((t, kind, when, val))
            if len(df) > len(old) or applied:
                if not dry_run:
                    _write_csv(folder / f"{t}.csv", df)
                rep.updated += 1
                if len(df):
                    d = df.index.max().date().isoformat()
                    rep.latest_date = max(rep.latest_date or "", d)
            else:
                rep.missing.append(t)

    # ---- seed brand-new tickers (no CSV yet): full history, capped per night ----
    for t in seed[:SEED_PER_NIGHT]:
        start = (today - dt.timedelta(days=365 * SEED_YEARS)).isoformat()
        try:
            hist = prov.get_history(t, start, date_to)
            dv = prov.get_dividends(t, start, date_to)
        except EODError as e:
            rep.errors.append(f"{t}: seed failed ({e})"); continue
        if not hist:
            rep.missing.append(t); continue
        from eod_adapter import total_return_adjust
        adj = total_return_adjust(hist, dv)
        vol = lambda b: (b.adj_volume if b.adj_volume is not None else (b.volume if b.volume is not None else np.nan))
        rows = [dict(Date=pd.Timestamp(b.date), Open=b.adj_open, High=b.adj_high, Low=b.adj_low,
                     Close=b.adj_close, Volume=vol(b)) for b in adj]
        df = pd.DataFrame(rows).set_index("Date").sort_index()[COLS]
        if not dry_run:
            _write_csv(folder / f"{t}.csv", df)
        rep.seeded.append(t); rep.updated += 1
    if len(seed) > SEED_PER_NIGHT:
        rep.errors.append(f"{len(seed) - SEED_PER_NIGHT} new tickers deferred to later nights")

    rep.requests = prov.requests
    if verbose:
        print("  " + rep.summary())
        for t, kind, when, val in rep.actions:
            print(f"  action: {t} {kind} {when} {val}")
    return rep


def refresh_all(folders: Iterable[str], extra_by_folder: Optional[dict] = None,
                dry_run: bool = False) -> list[Report]:
    """Refresh several folders with ONE provider (shared request counter)."""
    _load_dotenv()
    prov = _MS()
    reps = []
    for f in folders:
        extra = (extra_by_folder or {}).get(f, ())
        reps.append(refresh_folder(f, extra=extra, provider=prov, dry_run=dry_run))
    return reps


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    folders = args or ["daily_data_10y"]
    extra = {"daily_data_10y": ["SPY", "RSP"], "daily_data_v2": ["SPY", "RSP"]}
    try:
        reps = refresh_all(folders, extra, dry_run=dry)
    except EODError as e:
        raise SystemExit(f"data_refresh: {e}")
    bad = [r for r in reps if r.errors]
    for r in reps:
        print(r.summary())
        for e in r.errors:
            print("  !", e)
    sys.exit(1 if any("marketstack:" in e for r in bad for e in r.errors) else 0)
