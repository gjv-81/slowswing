#!/usr/bin/env python3.12
"""
case_dates.py — for the blog case studies, print the exact SIGNAL / MAX-DIP / PEAK
dates (and %) for a few tickers, using the same entry basis as the tracker
(entry = Open of the signal date). Writes case_dates.json for the site chat to read.

RUN:  cd ~/STS/15min && python3.12 case_dates.py
"""
import json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "sts_ml_paper_trades.csv")
TICKERS = ["NFLX", "SNDK", "CPRI"]     # winner / turnaround / earnings-loser
HOLD_TD = 25                            # ~5 weeks of trading days to cover the 4-week scorecard

def main():
    import yfinance as yf
    tr = pd.read_csv(CSV); tr["entry_date"] = pd.to_datetime(tr["entry_date"])
    out = {}
    for t in TICKERS:
        rows = tr[tr["ticker"] == t]
        if rows.empty:
            print(f"{t}: not in trades csv"); continue
        ed = rows["entry_date"].min()
        df = yf.download(t, start=(ed - pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        after = df[df.index >= ed].head(HOLD_TD + 1)
        if after.empty:
            print(f"{t}: no bars after {ed.date()}"); continue
        e_px = float(after["Open"].iloc[0]); sig = after.index[0]
        hi_i = after["High"].values.argmax(); lo_i = after["Low"].values.argmin()
        peak_d = after.index[hi_i]; trough_d = after.index[lo_i]
        peak_pct = (float(after["High"].iloc[hi_i]) / e_px - 1) * 100
        trough_pct = (float(after["Low"].iloc[lo_i]) / e_px - 1) * 100
        out[t] = {"signal": sig.strftime("%b %-d, %Y"),
                  "trough": trough_d.strftime("%b %-d, %Y"), "trough_pct": round(trough_pct, 1),
                  "peak": peak_d.strftime("%b %-d, %Y"), "peak_pct": round(peak_pct, 1)}
        print(f"{t}: signal {out[t]['signal']} | max dip {out[t]['trough']} ({out[t]['trough_pct']}%) "
              f"| top {out[t]['peak']} (+{out[t]['peak_pct']}%)")
    json.dump(out, open(os.path.join(HERE, "case_dates.json"), "w"), indent=2)
    print("\nwrote case_dates.json")

if __name__ == "__main__":
    main()
