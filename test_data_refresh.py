#!/usr/bin/env python3
"""Synthetic tests for data_refresh.py — no network, no key.
Run:  python3 test_data_refresh.py
"""
import os, sys, datetime as dt, tempfile
from pathlib import Path
os.environ.setdefault("MARKETSTACK_API_KEY", "test-key")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
from eod_adapter import EODBar, total_return_adjust
import data_refresh as dr

def raw_series(n=300, start="2025-01-02", seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    df = pd.DataFrame({"Open": close * (1 + rng.normal(0, .003, n)),
                       "High": close * 1.01, "Low": close * 0.99, "Close": close,
                       "Volume": rng.integers(1e6, 5e6, n).astype(float)}, index=dates)
    df.index.name = "Date"
    return df

def to_bars(df, t="TST"):
    return [EODBar(t, d.date().isoformat(), r.Open, r.High, r.Low, r.Close, int(r.Volume))
            for d, r in df.iterrows()]

def adjusted_reference(raw, divs):
    """What yfinance auto_adjust would store: total_return_adjust on raw bars."""
    adj = total_return_adjust(to_bars(raw), divs)
    df = pd.DataFrame([dict(Date=pd.Timestamp(b.date), Open=b.adj_open, High=b.adj_high,
                            Low=b.adj_low, Close=b.adj_close, Volume=b.volume) for b in adj]).set_index("Date")
    df.index.name = "Date"; return df

def check(name, a, b, tol=1e-9):
    a, b = a.sort_index(), b.sort_index()
    assert a.index.equals(b.index), f"{name}: index mismatch {len(a)} vs {len(b)}"
    diff = (a[dr.COLS] - b[dr.COLS]).abs().max().max()
    assert diff < tol, f"{name}: max abs diff {diff}"
    print(f"  ok  {name}  (max diff {diff:.2e})")

# ---------------------------------------------------------------- 1. dividends
raw = raw_series()
dates = raw.index
d1, d2 = dates[150].date().isoformat(), dates[260].date().isoformat()
divs = [(d1, 0.40), (d2, 0.45)]
ref_full = adjusted_reference(raw, divs)

# stored = adjusted history up to bar 255 (knows d1, not d2); refresh adds 256..299 with d2 inside
cut = 256
stored = adjusted_reference(raw.iloc[:cut], [(d1, 0.40)])
new = raw.iloc[cut:]
got, applied = dr.merge_new_bars(stored, new, divs, [])
assert applied == [("div", d2, 0.45)], applied
check("multi-session catch-up with ex-date inside the new bars", got, ref_full)

# one-night refresh exactly on the ex-date (the normal case)
cut = 260
stored = adjusted_reference(raw.iloc[:cut], [(d1, 0.40)])
got, applied = dr.merge_new_bars(stored, raw.iloc[cut:cut + 1], divs, [])
assert applied == [("div", d2, 0.45)]
check("single-night refresh on ex-date", got, adjusted_reference(raw.iloc[:cut + 1], divs))

# normal night, no action: pure append, nothing rescaled
cut = 200
stored = adjusted_reference(raw.iloc[:cut], [(d1, 0.40)])
got, applied = dr.merge_new_bars(stored, raw.iloc[cut:cut + 1], [(d1, 0.40)], [])
assert applied == []
check("plain append, old dividend ignored", got, adjusted_reference(raw.iloc[:cut + 1], [(d1, 0.40)]))

# idempotent: running again with the same bars changes nothing
got2, applied2 = dr.merge_new_bars(got, raw.iloc[cut:cut + 1], [(d1, 0.40)], [])
assert applied2 == [] and got2.equals(got)
print("  ok  idempotent re-run")

# ---------------------------------------------------------------- 2. splits
s_date = dates[280].date().isoformat()
# raw post-split world: prices /10 and volume *10 from s_date on
raw_split = raw.copy()
m = raw_split.index >= pd.Timestamp(s_date)
raw_split.loc[m, ["Open", "High", "Low", "Close"]] /= 10
raw_split.loc[m, "Volume"] *= 10
# the vendor's split-adjusted history restates everything before s_date the same way
vendor_adj = raw_split.copy()
vendor_adj.loc[~m, ["Open", "High", "Low", "Close"]] /= 10
vendor_adj.loc[~m, "Volume"] *= 10
divs_ps = [(d, a / 10) for d, a in divs]                     # yfinance restates past dividends for the split too
ref_split = adjusted_reference(vendor_adj, divs_ps)         # yfinance view after the split
cut = 278
stored = adjusted_reference(raw.iloc[:cut], divs)           # pre-split store (dividends known)
got, applied = dr.merge_new_bars(stored, raw_split.iloc[cut:], divs, [(s_date, 10.0)])
assert applied == [("split", s_date, 10.0)], applied
check("10:1 split inside a 22-session catch-up", got, ref_split, tol=1e-6)

# ---------------------------------------------------------------- 3. refresh_folder end-to-end with a fake provider
class Fake:
    """Stands in for _MS: serves raw_split bars + the two dividends + the split."""
    requests = 0
    def eod_range_many(self, tickers, date_from, date_to):
        self.requests += 1
        sl = raw_split.loc[date_from:date_to]
        return {t: to_bars(sl, t) for t in tickers if t != "GONE"}
    def dividends_many(self, tickers, date_from, date_to):
        self.requests += 1
        ev = [(d, a) for d, a in divs if date_from <= d <= date_to]
        return {t: ev for t in tickers if t != "GONE"}
    def splits_many(self, tickers, date_from, date_to):
        self.requests += 1
        ev = [(s_date, 10.0)] if date_from <= s_date <= date_to else []
        return {t: ev for t in tickers if t != "GONE"}
    def get_history(self, t, start, end):
        # Marketstack history carries raw OHLC plus split-adjusted adj_* fields
        self.requests += 1
        return [EODBar(t, d.date().isoformat(), r.Open, r.High, r.Low, r.Close, int(r.Volume),
                       adj_open=a.Open, adj_high=a.High, adj_low=a.Low, adj_close=a.Close, adj_volume=a.Volume)
                for (d, r), (_, a) in zip(raw_split.iterrows(), vendor_adj.iterrows())]
    def get_dividends(self, t, start, end):
        # ASSUMPTION (verify on NVDA around 2024-06-10 during the Mac dry-run): Marketstack
        # reports each dividend in the units of its own date, i.e. pre-split amounts are NOT
        # restated. total_return_adjust() and apply_dividend() both rely on this.
        self.requests += 1; return list(divs)

with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp) / "daily_data_x"; folder.mkdir()
    today = dates[-1].date()
    dr._write_csv(folder / "AAA.csv", adjusted_reference(raw.iloc[:278], divs))        # 22 sessions behind, split ahead
    dr._write_csv(folder / "BBB.csv", adjusted_reference(vendor_adj, divs_ps))            # already current
    dr._write_csv(folder / "GONE.csv", adjusted_reference(raw.iloc[:100], [(d1, .4)])) # dormant (>60 sessions)
    dr._write_csv(folder / "LATE.csv", adjusted_reference(vendor_adj.iloc[:-1], divs_ps)) # one session behind
    fk = Fake()
    rep = dr.refresh_folder(folder, extra=["NEWT"], provider=fk, today=today, verbose=False)
    assert rep.updated == 3 and rep.unchanged == 1, rep.summary()        # AAA, LATE, NEWT(seeded)
    assert rep.dead == ["GONE"] and rep.seeded == ["NEWT"] and not rep.errors, rep.summary()
    assert rep.requests == 5, rep.requests                                 # 3 range calls + 2 seed calls
    assert [a[:2] for a in rep.actions] == [("AAA", "split")], rep.actions
    check("refresh_folder AAA", dr._read_csv(folder / "AAA.csv"), ref_split, tol=1e-6)
    check("refresh_folder LATE", dr._read_csv(folder / "LATE.csv"), ref_split, tol=1e-6)
    check("refresh_folder NEWT (seeded)", dr._read_csv(folder / "NEWT.csv"), ref_split, tol=1e-6)
    assert len(dr._read_csv(folder / "GONE.csv")) == 100
    # dry run touches nothing
    dr._write_csv(folder / "AAA.csv", adjusted_reference(raw.iloc[:278], divs))
    rep = dr.refresh_folder(folder, provider=Fake(), today=today, dry_run=True, verbose=False)
    assert rep.updated >= 1 and len(dr._read_csv(folder / "AAA.csv")) == 278
    print("  ok  refresh_folder dry-run leaves files untouched")
    print("  " + rep.summary())

print("ALL TESTS PASSED")
