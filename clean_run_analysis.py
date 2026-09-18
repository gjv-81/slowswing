#!/usr/bin/env python3.12
# ============================================================================
# clean_run_analysis.py  —  "did the setup run CLEAN to the target?"
#
# For every RETIRED paper trade (>= 4 weeks / 20 trading days held), replay the
# daily bars from entry and measure the DIP that happened only UP TO the first
# time price touched +5% and +10%. Answers:
#   Of the trades that touched +X%, how many got there with...
#     * no dip at all (never traded below entry before the touch)
#     * never dipping more than 1%
#     * never dipping more than 5%
#
# Conventions match sts_ml_paper_tracker.py exactly:
#   entry price = Open of entry_date (or CSV override), touch = daily HIGH,
#   dip = daily LOW, auto_adjust=True.
#
# Same-day note: on the touch day we can't know if the low came before or after
# the +X% high, so we report TWO numbers — "incl" counts the touch-day low as a
# possible pre-touch dip (conservative), "excl" ignores it (optimistic). Truth
# is between; they usually agree.
#
# RUN:  cd ~/STS/15min && python3.12 clean_run_analysis.py
# Writes clean_run_detail.csv beside this script for your own verification.
# ============================================================================
import os, sys
import numpy as np
import pandas as pd

_DIR = os.path.dirname(os.path.abspath(__file__))
CSV  = os.path.join(_DIR, "sts_ml_paper_trades.csv")
W4   = 20                      # trading days that define "retired"
LEVELS = [5.0, 10.0]
DIP_BANDS = [("no dip at all", 0.0), ("dip never > 1%", 1.0), ("dip never > 5%", 5.0)]

def fetch(tickers, start):
    import yfinance as yf
    out = {}
    for t in tickers:
        try:
            df = yf.download(t, start=start, progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if len(df):
                out[t] = df[["Open", "High", "Low", "Close"]].copy()
        except Exception as e:
            print(f"  WARN {t}: {e}")
    return out

def main():
    tr = pd.read_csv(CSV)
    tr["entry_date"] = pd.to_datetime(tr["entry_date"])
    if "close_date" not in tr.columns:
        tr["close_date"] = pd.NaT
    tr["close_date"] = pd.to_datetime(tr["close_date"], errors="coerce")
    start = (tr["entry_date"].min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    tickers = sorted(set(tr["ticker"]))
    print(f"Fetching daily bars for {len(tickers)} tickers from {start} ...")
    px = fetch(tickers, start)

    detail = []
    for _, r in tr.iterrows():
        t = r["ticker"]
        if t not in px:
            continue
        df = px[t]
        after = df[df.index >= r["entry_date"]]
        if not pd.isna(r["close_date"]):
            after = after[after.index <= r["close_date"]]
        after = after.dropna(subset=["Close"])
        if len(after) < W4:            # not retired yet
            continue
        e_px = (float(r["entry_price"]) if pd.notna(r.get("entry_price"))
                and str(r.get("entry_price")).strip() != "" else float(after["Open"].iloc[0]))
        hi = (after["High"].values / e_px - 1.0) * 100.0
        lo = (after["Low"].values  / e_px - 1.0) * 100.0
        row = dict(ticker=t, entry=r["entry_date"].date(), bars=len(after),
                   peak=round(float(hi.max()), 2))
        for L in LEVELS:
            hits = np.where(hi >= L)[0]
            if len(hits) == 0:
                row[f"touch{int(L)}"] = 0
                row[f"dip_incl{int(L)}"] = np.nan
                row[f"dip_excl{int(L)}"] = np.nan
            else:
                k = int(hits[0])
                dip_incl = float(lo[:k + 1].min())        # includes touch-day low
                dip_excl = float(lo[:k].min()) if k > 0 else 0.0
                row[f"touch{int(L)}"] = 1
                row[f"dip_incl{int(L)}"] = round(dip_incl, 2)
                row[f"dip_excl{int(L)}"] = round(dip_excl, 2)
        detail.append(row)

    D = pd.DataFrame(detail)
    D.to_csv(os.path.join(_DIR, "clean_run_detail.csv"), index=False)
    N = len(D)
    print(f"\nRETIRED setups analysed: {N}")
    print("(dip is the deepest low vs entry, measured only UP TO the first touch of the level)\n")

    for L in LEVELS:
        Li = int(L)
        g = D[D[f"touch{Li}"] == 1]
        n = len(g)
        print(f"=== Touched +{Li}% : {n} of {N} retired ({round(100*n/N)}%) ===")
        print(f"{'':22}{'incl touch-day':>16}{'excl touch-day':>16}")
        for label, band in DIP_BANDS:
            ci = int((g[f'dip_incl{Li}'] >= -band - 1e-9).sum())
            ce = int((g[f'dip_excl{Li}'] >= -band - 1e-9).sum())
            pi = f"{ci} ({round(100*ci/n) if n else 0}%)"
            pe = f"{ce} ({round(100*ce/n) if n else 0}%)"
            print(f"  {label:20}{pi:>16}{pe:>16}")
        print()
    print("Wrote clean_run_detail.csv (per-trade peak + pre-touch dip) for verification.")

if __name__ == "__main__":
    main()
