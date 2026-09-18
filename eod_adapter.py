"""
eod_adapter.py — vendor-agnostic end-of-day price adapter for STS.

WHY THIS FILE EXISTS
--------------------
The website only ever reads `board.json`. This adapter sits between your
nightly pipeline and whichever data vendor you licence, so that:

    pipeline  ->  get_eod()  ->  [ Polygon | Marketstack | ... ]

Switching vendors is a ONE-LINE change (an env var). Your pipeline code,
your board.json, and the site never change. That is the whole point of the
"decouple for reliability" principle in the handoff, applied to data supply.

QUICK START
-----------
Easiest — put your settings in a .env file next to this script (see .env.example):

    EOD_PROVIDER=marketstack
    MARKETSTACK_API_KEY=your_real_key

then just run — the key loads automatically, nothing to type:

    python3 eod_adapter.py NVDA AMD MU     # prints normalized bars for a quick smoke test

Or set them inline for a one-off (a real env var overrides the .env file):

    EOD_PROVIDER=mock python3 eod_adapter.py NVDA AMD MU     # fake data, no key needed

NOTE: never commit .env to git — the included .gitignore already excludes it.

IN YOUR PIPELINE
----------------
    from eod_adapter import get_eod, get_eod_many, get_eod_history, EODError

    bar  = get_eod("NVDA")                 # latest close for one ticker  -> EODBar
    bars = get_eod_many(WATCHLIST)         # {ticker: EODBar|None} in as few calls as the vendor allows
    hist = get_eod_history("NVDA", "2026-01-01", "2026-08-20")   # list[EODBar], oldest first

Every vendor is normalized to the SAME shape (EODBar). To update the board's
`pc` (current price) field, you read `bar.close`. If a pull fails, get_eod*
raises EODError (or returns None inside get_eod_many) so the caller can fall
back to yesterday's board instead of shipping a broken one.

DEPENDENCIES
------------
    pip install requests
"""

from __future__ import annotations

import os
import time
import datetime as dt
from dataclasses import dataclass, asdict, field
from typing import Iterable, Optional

try:
    import requests
except ImportError as _e:  # pragma: no cover
    raise SystemExit("eod_adapter needs the 'requests' package:  pip install requests")


# --------------------------------------------------------------------------- #
#  .env loading — tiny, dependency-free.                                        #
#  Reads KEY=VALUE lines from a .env file (next to this script and/or in the    #
#  current folder) so you never paste your key into the terminal again.         #
#  A real environment variable ALWAYS wins over the file, so you can still      #
#  override on the command line for a one-off.                                  #
# --------------------------------------------------------------------------- #
def _load_dotenv() -> None:
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    candidates = [pathlib.Path.cwd() / ".env", here / ".env"]
    loaded = set()
    for path in candidates:
        if path in loaded or not path.is_file():
            continue
        loaded.add(path)
        try:
            text = path.read_text()
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:   # real env vars win
                os.environ[key] = val


_load_dotenv()


# --------------------------------------------------------------------------- #
#  The one normalized shape every vendor is mapped into.                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EODBar:
    ticker: str          # "NVDA"
    date: str            # session date, "YYYY-MM-DD"
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None
    source: str = ""     # which vendor produced this bar ("polygon" / "marketstack")
    # Split/dividend-adjusted values where the vendor supplies them. The existing
    # daily_data_10y history is yfinance auto_adjust=True, so THESE are the fields
    # to compare against and to store — not the raw ones.
    adj_open: Optional[float] = None
    adj_high: Optional[float] = None
    adj_low: Optional[float] = None
    adj_close: Optional[float] = None
    adj_volume: Optional[float] = None

    def as_dict(self) -> dict:
        return asdict(self)


class EODError(RuntimeError):
    """Any failure to obtain data — network, auth, empty result, HTTP error."""


# --------------------------------------------------------------------------- #
#  Base provider: shared HTTP, retry/backoff, and rate-limit throttling.       #
# --------------------------------------------------------------------------- #
class EODProvider:
    name = "base"
    #: minimum seconds between per-ticker calls (used by the default loop).
    #: Set >0 for rate-limited free tiers, e.g. Polygon free = 5/min -> 13.
    min_interval: float = 0.0

    def __init__(self) -> None:
        self._last_call = 0.0

    # ---- public interface (subclasses implement the first two) ---- #
    def get_latest(self, ticker: str) -> EODBar:
        raise NotImplementedError

    def get_history(self, ticker: str, start: str, end: str) -> list[EODBar]:
        raise NotImplementedError

    def get_dividends(self, ticker: str, start: str, end: str) -> list[tuple[str, float]]:
        """[(ex_date, cash_amount), ...] ascending. Vendors without a dividends
        endpoint raise; callers that need total-return series must not swallow it."""
        raise NotImplementedError

    def get_latest_many(self, tickers: Iterable[str]) -> dict[str, Optional[EODBar]]:
        """Latest bar for many tickers.

        Default is a throttled per-ticker loop. Vendors with a batch endpoint
        (e.g. Marketstack) override this to do it in a single call.
        Missing/failed tickers map to None so one bad symbol never sinks the run.
        """
        out: dict[str, Optional[EODBar]] = {}
        for t in tickers:
            key = t.upper()
            try:
                out[key] = self.get_latest(t)
            except EODError:
                out[key] = None
            self._throttle()
        return out

    # ---- shared helpers ---- #
    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, url: str, params: dict, timeout: int = 20, tries: int = 3) -> dict:
        """GET JSON with retry/backoff on transient failures."""
        last_err: Optional[Exception] = None
        for attempt in range(tries):
            try:
                resp = requests.get(url, params=params, timeout=timeout)
            except requests.RequestException as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 200:
                return resp.json()
            # transient -> retry; everything else -> fail loudly
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = EODError(f"{self.name}: HTTP {resp.status_code}")
                time.sleep(2.0 * (attempt + 1))
                continue
            raise EODError(f"{self.name}: HTTP {resp.status_code} — {resp.text[:200]}")
        raise EODError(f"{self.name}: failed after {tries} attempts ({last_err})")


# --------------------------------------------------------------------------- #
#  Polygon.io  (branded "Massive").  Terms explicitly permit display in your   #
#  own app. Stocks Starter ~$29/mo, unlimited calls.                           #
#    latest  : GET /v2/aggs/ticker/{T}/prev                                    #
#    history : GET /v2/aggs/ticker/{T}/range/1/day/{from}/{to}                 #
# --------------------------------------------------------------------------- #
class PolygonProvider(EODProvider):
    name = "polygon"
    BASE = "https://api.polygon.io"

    def __init__(self, api_key: Optional[str] = None, adjusted: bool = True,
                 min_interval: float = 0.0) -> None:
        super().__init__()
        self.key = api_key or os.environ.get("POLYGON_API_KEY")
        if not self.key:
            raise EODError("POLYGON_API_KEY is not set")
        self.adjusted = adjusted
        self.min_interval = min_interval   # set 13.0 on the free 5/min tier

    def _bar(self, ticker: str, r: dict) -> EODBar:
        # Polygon 't' is the bar's start time in epoch milliseconds (UTC).
        d = dt.datetime.fromtimestamp(r["t"] / 1000, dt.timezone.utc).date().isoformat()
        return EODBar(
            ticker=ticker.upper(), date=d,
            open=float(r["o"]), high=float(r["h"]), low=float(r["l"]), close=float(r["c"]),
            volume=int(r.get("v", 0)), source=self.name,
        )

    def get_latest(self, ticker: str) -> EODBar:
        j = self._get(
            f"{self.BASE}/v2/aggs/ticker/{ticker.upper()}/prev",
            {"adjusted": str(self.adjusted).lower(), "apiKey": self.key},
        )
        results = j.get("results") or []
        if not results:
            raise EODError(f"polygon: no previous bar for {ticker}")
        return self._bar(ticker, results[0])

    def get_history(self, ticker: str, start: str, end: str) -> list[EODBar]:
        j = self._get(
            f"{self.BASE}/v2/aggs/ticker/{ticker.upper()}/range/1/day/{start}/{end}",
            {"adjusted": str(self.adjusted).lower(), "sort": "asc",
             "limit": 50000, "apiKey": self.key},
        )
        return [self._bar(ticker, r) for r in (j.get("results") or [])]


# --------------------------------------------------------------------------- #
#  Marketstack (APILayer).  Basic ~$9.99/mo lists "commercial use"; confirm    #
#  public-DISPLAY rights with support in writing before relying on it.         #
#    latest  : GET /v1/eod/latest?symbols=A,B,C   (multi-symbol in ONE call)   #
#    history : GET /v1/eod?symbols=T&date_from=&date_to=                       #
# --------------------------------------------------------------------------- #
class MarketstackProvider(EODProvider):
    name = "marketstack"
    BASE = "https://api.marketstack.com/v1"

    def __init__(self, api_key: Optional[str] = None, min_interval: float = 0.0) -> None:
        super().__init__()
        self.key = api_key or os.environ.get("MARKETSTACK_API_KEY")
        if not self.key:
            raise EODError("MARKETSTACK_API_KEY is not set")
        self.min_interval = min_interval

    @staticmethod
    def _f(row: dict, key: str):
        v = row.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _bar(self, row: dict):
        """Marketstack returns rows with null OHLC (holidays, halts, thin symbols).
        Those are not errors — they are non-sessions. Return None and let the
        caller drop them, rather than letting one bad row kill a whole ticker."""
        close = self._f(row, "close")
        # A zero close is a hole, not a price. Seen live on META 2026-04-07/08 and
        # 2026-06-04 and on SPY/RSP: real trading days returned with close=0.0.
        # Letting 0.0 through would put a -100% bar into every momentum feature.
        if close is None or close <= 0:
            return None
        o, h, l = self._f(row, "open"), self._f(row, "high"), self._f(row, "low")
        return EODBar(
            ticker=str(row["symbol"]).upper(),
            date=str(row.get("date", ""))[:10],           # "2026-08-20T00:00:00+0000" -> "2026-08-20"
            open=o if o is not None else close,
            high=h if h is not None else close,
            low=l if l is not None else close,
            close=close,
            volume=int(row["volume"]) if row.get("volume") is not None else None,
            source=self.name,
            adj_open=self._f(row, "adj_open"), adj_high=self._f(row, "adj_high"),
            adj_low=self._f(row, "adj_low"), adj_close=self._f(row, "adj_close"),
            adj_volume=self._f(row, "adj_volume"),
        )

    def _check_error(self, j: dict) -> None:
        # Marketstack signals problems as {"error": {"code":..., "message":...}}
        if isinstance(j, dict) and j.get("error"):
            err = j["error"]
            raise EODError(f"marketstack: {err.get('code')} — {err.get('message')}")

    def get_latest(self, ticker: str) -> EODBar:
        j = self._get(f"{self.BASE}/eod/latest",
                      {"access_key": self.key, "symbols": ticker.upper()})
        self._check_error(j)
        data = j.get("data") or []
        if not data:
            raise EODError(f"marketstack: no latest bar for {ticker}")
        bar = self._bar(data[0])
        if bar is None:
            raise EODError(f"marketstack: latest bar for {ticker} has no close")
        return bar

    def get_latest_many(self, tickers: Iterable[str]) -> dict[str, Optional[EODBar]]:
        tickers = list(dict.fromkeys(t.upper() for t in tickers))
        out: dict[str, Optional[EODBar]] = {t: None for t in tickers}
        # Marketstack takes a comma-separated list, but at most 100 symbols per
        # call (HTTP 422 above that). Billing is per symbol either way, so
        # chunking costs nothing extra.
        for i in range(0, len(tickers), 100):
            chunk = tickers[i:i + 100]
            j = self._get(f"{self.BASE}/eod/latest",
                          {"access_key": self.key, "symbols": ",".join(chunk)})
            self._check_error(j)
            for row in (j.get("data") or []):
                bar = self._bar(row)
                if bar is not None:
                    out[bar.ticker] = bar
        return out

    def _paged(self, path: str, params: dict) -> list[dict]:
        """Walk Marketstack's offset pagination. One page is 1000 rows, which is
        four years of daily bars; a ten-year backfill needs three."""
        rows, offset = [], 0
        while True:
            j = self._get(f"{self.BASE}/{path}", {**params, "limit": 1000, "offset": offset})
            self._check_error(j)
            page = j.get("data") or []
            rows.extend(page)
            pg = j.get("pagination") or {}
            total = pg.get("total")
            offset += len(page)
            if not page or total is None or offset >= total:
                return rows

    def get_history(self, ticker: str, start: str, end: str) -> list[EODBar]:
        rows = self._paged("eod", {"access_key": self.key, "symbols": ticker.upper(),
                                   "date_from": start, "date_to": end, "sort": "ASC"})
        return [b for b in (self._bar(r) for r in rows) if b is not None]

    def get_dividends(self, ticker: str, start: str, end: str) -> list[tuple[str, float]]:
        rows = self._paged("dividends", {"access_key": self.key, "symbols": ticker.upper(),
                                         "date_from": start, "date_to": end, "sort": "ASC"})
        out = []
        for r in rows:
            amt = self._f(r, "dividend")
            d = str(r.get("date", ""))[:10]
            if amt and amt > 0 and d:
                out.append((d, amt))
        out.sort()
        return out


# --------------------------------------------------------------------------- #
#  Mock provider — deterministic fake data so you can exercise the pipeline    #
#  and the board with NO API key and NO network. EOD_PROVIDER=mock             #
# --------------------------------------------------------------------------- #
class MockProvider(EODProvider):
    name = "mock"

    def _synth(self, ticker: str, date: str, seed: float) -> EODBar:
        base = 50 + (sum(ord(c) for c in ticker.upper()) % 400)  # stable per-ticker price
        base += seed
        return EODBar(ticker.upper(), date,
                      open=round(base, 2), high=round(base * 1.03, 2),
                      low=round(base * 0.98, 2), close=round(base * 1.015, 2),
                      volume=1_000_000, source=self.name)

    def get_latest(self, ticker: str) -> EODBar:
        return self._synth(ticker, "2026-08-20", 0.0)

    def get_history(self, ticker: str, start: str, end: str) -> list[EODBar]:
        return [self._synth(ticker, start, 0.0), self._synth(ticker, end, 5.0)]


# --------------------------------------------------------------------------- #
#  Factory + module-level convenience functions.                              #
# --------------------------------------------------------------------------- #
_PROVIDERS = {
    "polygon": PolygonProvider,
    "marketstack": MarketstackProvider,
    "mock": MockProvider,
}


def dedupe_dividends(dividends, window_days: int = 20, ratio: float = 2.0):
    """Drop phantom dividend rows. Seen live: Marketstack listed T paying $0.28 on
    2026-07-10 and again $0.33 on 2026-07-17 — a second row that never happened,
    which over-adjusted two years of history by 1.6%. A REAL second payment
    inside a quarter is a special dividend, and those run 5-50x the regular one;
    so two rows within `window_days` whose amounts are within `ratio` of each
    other are one dividend recorded twice. The earlier row is kept."""
    import datetime as _dt
    out = []
    for d, amt in sorted(dividends):
        if out:
            pd_, pa = out[-1]
            gap = (_dt.date.fromisoformat(d) - _dt.date.fromisoformat(pd_)).days
            if gap <= window_days and pa > 0 and max(amt, pa) / min(amt, pa) <= ratio:
                print(f"  ! dividend row dropped as duplicate: {d} {amt} (kept {pd_} {pa})")
                continue
        out.append((d, amt))
    return out


def total_return_adjust(bars: list[EODBar], dividends: list[tuple[str, float]]) -> list[EODBar]:
    """Turn a split-adjusted series into a total-return series, the way yfinance
    auto_adjust=True does (and the way the daily_data_10y history was built).

    Marketstack's adj_* fields restate history for SPLITS only. yfinance also
    restates for DIVIDENDS: on each ex-date every earlier price is multiplied by
    (1 - dividend / previous close), so the series shows what a holder actually
    experienced instead of a fake drop on every ex-date. Two years of a 4.5%
    yield is a ~9% gap in the 2024 prices — measured on T in compare_sources.py.
    The model's six features were trained on the adjusted series, so this is the
    series the pipeline must keep feeding it.

    The ratio uses the RAW previous close and the dividend as Marketstack reports
    it, i.e. both in the units of that date. The factor is applied to the
    split-adjusted prices. Returns new EODBar objects; input is untouched.
    """
    if not bars:
        return []
    dividends = dedupe_dividends(dividends)
    bars = sorted(bars, key=lambda b: b.date)
    # cumulative factor to apply to each bar, built from the newest ex-date back
    factor = [1.0] * len(bars)
    running = 1.0
    divs = sorted(dividends, reverse=True)
    di = 0
    for i in range(len(bars) - 1, -1, -1):
        b = bars[i]
        # every ex-date AFTER this bar (and not yet applied) contributes
        while di < len(divs) and divs[di][0] > b.date:
            ex_date, amt = divs[di]
            # previous close = this bar's raw close (it is the last bar before ex_date)
            prev = b.close
            if prev and prev > 0 and amt < prev:
                running *= (1.0 - amt / prev)
            di += 1
        factor[i] = running
    out = []
    for b, f in zip(bars, factor):
        base = lambda adj, raw: (adj if adj is not None else raw)
        out.append(EODBar(
            ticker=b.ticker, date=b.date,
            open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume,
            source=b.source,
            adj_open=base(b.adj_open, b.open) * f,
            adj_high=base(b.adj_high, b.high) * f,
            adj_low=base(b.adj_low, b.low) * f,
            adj_close=base(b.adj_close, b.close) * f,
            adj_volume=b.adj_volume,
        ))
    return out


def get_provider(name: Optional[str] = None, **kwargs) -> EODProvider:
    """Build a provider by name (defaults to $EOD_PROVIDER, then 'polygon').

    THIS is the switch. Change EOD_PROVIDER=marketstack (and set its key) and
    every call below routes to Marketstack instead — nothing else changes.
    """
    name = (name or os.environ.get("EOD_PROVIDER") or "polygon").lower()
    if name not in _PROVIDERS:
        raise EODError(f"unknown EOD_PROVIDER {name!r}; choose one of {sorted(_PROVIDERS)}")
    return _PROVIDERS[name](**kwargs)


_default_provider: Optional[EODProvider] = None


def _prov() -> EODProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = get_provider()
    return _default_provider


def get_eod(ticker: str, provider: Optional[EODProvider] = None) -> EODBar:
    """Latest EOD bar for one ticker."""
    return (provider or _prov()).get_latest(ticker)


def get_eod_many(tickers: Iterable[str],
                 provider: Optional[EODProvider] = None) -> dict[str, Optional[EODBar]]:
    """Latest EOD bar for many tickers, in as few calls as the vendor allows."""
    return (provider or _prov()).get_latest_many(list(tickers))


def get_eod_history(ticker: str, start: str, end: str,
                    provider: Optional[EODProvider] = None) -> list[EODBar]:
    """Daily bars for a date range (YYYY-MM-DD), oldest first."""
    return (provider or _prov()).get_history(ticker, start, end)


# --------------------------------------------------------------------------- #
#  CLI smoke test:  python3 eod_adapter.py NVDA AMD MU                          #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    import json

    tickers = sys.argv[1:] or ["NVDA", "AMD", "MU"]
    try:
        prov = get_provider()
    except EODError as e:
        raise SystemExit(f"Setup error: {e}\n"
                         f"Set EOD_PROVIDER (polygon|marketstack|mock) and the matching *_API_KEY.")

    print(f"# provider = {prov.name}   tickers = {', '.join(t.upper() for t in tickers)}")
    bars = prov.get_latest_many(tickers)
    ok = 0
    for t, bar in bars.items():
        if bar is None:
            print(json.dumps({"ticker": t, "error": "no data"}))
        else:
            ok += 1
            print(json.dumps(bar.as_dict()))
    print(f"# {ok}/{len(bars)} tickers returned data")
