#!/usr/bin/env python3
"""
enrich_trades.py — add a qualgate PASS/FAIL column to a growing STS trades CSV.

Workflow it's built for: your STS model appends rows (entry_date, ticker, ...) to a
CSV every day. Run this once daily. It:

  1. reads the trades file and finds the DISTINCT tickers,
  2. scores each with qualgate — but only if it's a NEW ticker or the cached score
     is older than --max-age-days (fundamentals change quarterly, so we don't
     re-pull the same name every day),
  3. writes/updates a per-ticker cache (qualgate_cache.csv),
  4. writes an enriched copy of the trades file with two new columns:
        qualgate        PASS / WATCH / FAIL / ERROR
        qualgate_score  0..100

So a row's `qualgate` tells you: when STS fires a signal on this name, is it a
company you should be comfortable holding through a drawdown?

Usage:
    python enrich_trades.py sts_ml_paper_trades.csv
    python enrich_trades.py sts_ml_paper_trades.csv --out enriched.csv
    python enrich_trades.py sts_ml_paper_trades.csv --max-age-days 30
    python enrich_trades.py trades.csv --source mock         # offline test
    python enrich_trades.py sts_ml_paper_trades.csv --pass-threshold 70
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys

import qualgate as qg

CACHE_FIELDS = ["ticker", "gate", "profile", "tag", "score", "asof", "version",
                "gross_profitability", "f_score", "altman_z", "fcf_yield_pct",
                "interest_cov", "debt_to_equity", "op_margin_ttm", "sector",
                "profile_note", "vetoes"]


def load_cache(path):
    cache = {}
    if os.path.exists(path):
        for r in csv.DictReader(open(path)):
            cache[r["ticker"].upper()] = r
    return cache


def save_cache(path, cache):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CACHE_FIELDS)
        w.writeheader()
        for t in sorted(cache):
            row = {k: cache[t].get(k, "") for k in CACHE_FIELDS}
            w.writerow(row)


def is_fresh(entry, max_age_days):
    if entry.get("version") != qg.GATE_VERSION:   # logic changed -> re-score
        return False
    try:
        asof = dt.date.fromisoformat(entry.get("asof", ""))
    except ValueError:
        return False
    return (dt.date.today() - asof).days <= max_age_days


def score_ticker(sym, source, pass_threshold, watch_threshold):
    s = qg.load(source, sym)
    r = qg.evaluate_gate(s, pass_threshold, watch_threshold)
    m = r.metrics
    return {
        "ticker": sym.upper(), "gate": r.gate, "profile": r.profile,
        "tag": f"{r.gate}/{qg.PROFILE_CODE.get(r.profile, '')}".rstrip("/"),
        "score": round(r.score, 1), "asof": dt.date.today().isoformat(),
        "version": qg.GATE_VERSION, "profile_note": r.profile_note,
        "gross_profitability": qg._round(m["gross_profitability"], 3),
        "f_score": m["f_score"], "altman_z": qg._round(m["altman_z"], 2),
        "fcf_yield_pct": qg._round(m["fcf_yield_pct"], 1),
        "interest_cov": qg._round(m["interest_cov"], 1),
        "debt_to_equity": qg._round(m["debt_to_equity"], 2),
        "op_margin_ttm": qg._round(m["op_margin_ttm"], 1),
        "sector": m["sector"], "vetoes": " | ".join(r.vetoes),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Add a qualgate PASS/FAIL column to an STS trades CSV.")
    ap.add_argument("trades_csv")
    ap.add_argument("--out", help="enriched output path (default: <trades>_gated.csv)")
    ap.add_argument("--cache", default="qualgate_cache.csv")
    ap.add_argument("--ticker-col", default="ticker")
    ap.add_argument("--max-age-days", type=int, default=30,
                    help="re-score a cached ticker only if older than this (default 30)")
    ap.add_argument("--source", default="yfinance", choices=["yfinance", "mock"])
    ap.add_argument("--pass-threshold", type=float, default=qg.PASS_THRESHOLD)
    ap.add_argument("--watch-threshold", type=float, default=qg.WATCH_THRESHOLD)
    args = ap.parse_args(argv)

    rows = list(csv.DictReader(open(args.trades_csv)))
    if not rows:
        sys.exit("trades file is empty")
    fieldnames = list(rows[0].keys())
    for col in ("qualgate", "qualgate_tag", "qualgate_profile", "qualgate_score"):
        if col not in fieldnames:
            fieldnames.append(col)

    distinct = sorted({r[args.ticker_col].strip().upper() for r in rows if r[args.ticker_col].strip()})
    cache = load_cache(args.cache)

    scored = skipped = errored = 0
    for sym in distinct:
        if sym in cache and is_fresh(cache[sym], args.max_age_days):
            skipped += 1
            continue
        try:
            cache[sym] = score_ticker(sym, args.source, args.pass_threshold, args.watch_threshold)
            scored += 1
            print(f"  scored {sym:6} -> {cache[sym]['gate']:5} {cache[sym]['score']}")
        except Exception as e:
            errored += 1
            cache[sym] = {"ticker": sym, "gate": "ERROR", "score": "",
                          "asof": dt.date.today().isoformat(), "vetoes": str(e)[:120]}
            print(f"  ERROR  {sym:6} -> {e}", file=sys.stderr)

    save_cache(args.cache, cache)

    # merge onto trades rows
    for r in rows:
        sym = r[args.ticker_col].strip().upper()
        c = cache.get(sym, {})
        r["qualgate"] = c.get("gate", "")
        r["qualgate_tag"] = c.get("tag", "")
        r["qualgate_profile"] = c.get("profile", "")
        r["qualgate_score"] = c.get("score", "")

    out = args.out or os.path.splitext(args.trades_csv)[0] + "_gated.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # summary
    gates = [cache[s].get("gate") for s in distinct]
    npass = gates.count("PASS")
    nwatch = gates.count("WATCH")
    nfail = gates.count("FAIL")
    nerr = gates.count("ERROR")
    print(f"\n  {len(distinct)} distinct tickers: "
          f"{scored} scored, {skipped} from cache, {errored} errors")
    print(f"  Gate distribution: PASS {npass}  WATCH {nwatch}  FAIL {nfail}  ERROR {nerr}")
    print(f"  Wrote {out}  (cache: {args.cache})")


if __name__ == "__main__":
    main()
