#!/usr/bin/env python3.12
"""
spy_regime_study.py — does sub-dividing "extended" carry real information?

QUESTION: the current dial ((SPY-200SMA)/ATR14: RED<0, GREEN 0..5, YELLOW>5)
is YELLOW most of the time, so it stops discriminating. Test three candidate
refinements of "how extended is SPY" and see which (if any) actually separates
FORWARD RISK — the thing the dial exists to warn about (beta drag on open trades).

METRICS (all computed point-in-time, trailing data only — no look-ahead):
  1. Z      = (Close - SMA200) / stdev(Close,200)     "σ above the 200-day"
  2. PCT    = trailing-3yr percentile of %-above-200   "stretched vs its own recent history"
  3. SLOPE  = 20-day momentum sign                     "is the advance still healthy?"
  plus the CURRENT ATR dial for comparison (to show the occupancy problem).

FOR EACH BUCKET, forward stats (overlapping daily windows — treat as descriptive):
  fwd 4wk (20d) and 12wk (60d) SPY return, win rate,
  fwd MAX DRAWDOWN within 4wk / 12wk (worst Low vs today's Close) — the beta-risk number,
  % of days spent in the bucket, and # of distinct episodes (autocorrelation honesty).

PRE-COMMITTED READING RULES (decided before looking at results):
  - A refinement "earns its place" only if its top bucket shows clearly worse
    forward max-drawdown than the middle buckets (>= ~1.5% worse median 4wk maxDD
    or a visibly monotone risk gradient), across BOTH horizons.
  - If buckets have < ~8 distinct episodes, treat as anecdote, not signal.
  - If nothing separates, the dial stays coarse — no decorative complexity.

RUN:  cd ~/STS/15min && python3.12 spy_regime_study.py
OUT:  STS_spy_regime_study.xlsx + console tables. Uses daily_data_10y/SPY.csv.
"""
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
SPY_CSV = HERE / "daily_data_10y" / "SPY.csv"
OUT = HERE / "STS_spy_regime_study.xlsx"
PCT_WIN = 756          # trailing 3yr window for the percentile
F4, F12 = 20, 60       # forward horizons (trading days)

d = pd.read_csv(SPY_CSV, index_col=0, parse_dates=True).sort_index()
C, H, L = d["Close"], d["High"], d["Low"]
sma = C.rolling(200).mean()
stretch = (C / sma - 1) * 100                       # % above 200-day
z = (C - sma) / C.rolling(200).std()                # sigma above 200-day
pc = C.shift(1)
tr = pd.concat([H - L, (H - pc).abs(), (L - pc).abs()], axis=1).max(axis=1)
atr_dist = (C - sma) / tr.ewm(alpha=1/14, adjust=False).mean()   # current dial metric
mom20 = C / C.shift(20) - 1

# trailing percentile of stretch (strictly point-in-time: rank today within the
# PRIOR PCT_WIN days + today; min 500 days before emitting a value)
def roll_pct(s, win, minp=500):
    return s.rolling(win, min_periods=minp).apply(
        lambda x: 100.0 * (x[:-1] < x[-1]).mean(), raw=True)
pct = roll_pct(stretch, PCT_WIN)

# forward stats
fwd4  = C.shift(-F4)  / C - 1
fwd12 = C.shift(-F12) / C - 1
# forward max drawdown: worst Low over the NEXT n days vs today's close
def fwd_maxdd(n):
    fmin = L.shift(-1).rolling(n).min().shift(-(n - 1))   # min(Low[t+1..t+n])
    return (fmin / C - 1) * 100
dd4, dd12 = fwd_maxdd(F4), fwd_maxdd(F12)

df_all = pd.DataFrame(dict(stretch=stretch, z=z, pct=pct, atr=atr_dist, mom20=mom20,
                           fwd4=fwd4*100, fwd12=fwd12*100, dd4=dd4, dd12=dd12))
df = df_all.dropna()          # study rows need complete forward windows
print(f"SPY study window: {df.index.min().date()} -> {df.index.max().date()}  ({len(df)} days)\n")

def episodes(mask):
    m = mask.astype(int)
    return int(((m.diff() == 1) | ((m == 1) & (m.index == m.index[0]))).sum())

def table(df, col, edges, labels, title):
    b = pd.cut(df[col], edges, labels=labels)
    rows = []
    for lab in labels:
        g = df[b == lab]
        if len(g) == 0:
            rows.append(dict(bucket=lab, days=0)); continue
        rows.append(dict(bucket=lab,
            days=len(g), pct_of_days=round(100*len(g)/len(df),1),
            episodes=episodes((b == lab)),
            fwd4_med=round(g["fwd4"].median(),2), fwd4_win=round(100*(g["fwd4"]>0).mean(),1),
            dd4_med=round(g["dd4"].median(),2),  dd4_p10=round(g["dd4"].quantile(0.10),2),
            fwd12_med=round(g["fwd12"].median(),2), fwd12_win=round(100*(g["fwd12"]>0).mean(),1),
            dd12_med=round(g["dd12"].median(),2), dd12_p10=round(g["dd12"].quantile(0.10),2)))
    t = pd.DataFrame(rows)
    print(f"=== {title} ===")
    print(t.to_string(index=False)); print()
    return t

# 0) the CURRENT ATR dial — the occupancy problem, stated with numbers
t0 = table(df, "atr", [-100, 0, 5, 100], ["RED <0", "GREEN 0..5", "YELLOW >5"],
           "CURRENT DIAL — (SPY-200)/ATR (shows why GREEN is rare)")

# 1) sigma above the 200-day
t1 = table(df, "z", [-100, 0, 1, 2, 3, 100], ["<0 (RED)", "0..1σ", "1..2σ", "2..3σ", ">3σ"],
           "OPTION 1 — STDEV above 200-day (Bollinger position)")

# 2) trailing-3yr percentile of stretch
t2 = table(df, "pct", [-1, 25, 50, 75, 90, 101], ["<25th", "25-50th", "50-75th", "75-90th", ">90th"],
           "OPTION 2 — STRETCH PERCENTILE vs its own trailing 3yr")

# 4) two-axis: stretched (top quartile of pct) x 20d momentum sign — above-200 days only
up = df[df["stretch"] > 0].copy()
up["cell"] = np.where(up["pct"] > 75,
                      np.where(up["mom20"] > 0, "Extended + mom UP", "Extended + mom DOWN"),
                      np.where(up["mom20"] > 0, "Normal + mom UP", "Normal + mom DOWN"))
rows = []
for lab in ["Normal + mom UP", "Normal + mom DOWN", "Extended + mom UP", "Extended + mom DOWN"]:
    g = up[up["cell"] == lab]
    rows.append(dict(cell=lab, days=len(g), pct_of_days=round(100*len(g)/len(up),1),
        episodes=episodes(up["cell"] == lab),
        fwd4_med=round(g["fwd4"].median(),2), fwd4_win=round(100*(g["fwd4"]>0).mean(),1),
        dd4_med=round(g["dd4"].median(),2), dd4_p10=round(g["dd4"].quantile(0.10),2),
        fwd12_med=round(g["fwd12"].median(),2), dd12_med=round(g["dd12"].median(),2),
        dd12_p10=round(g["dd12"].quantile(0.10),2)))
t4 = pd.DataFrame(rows)
print("=== OPTION 4 — TWO-AXIS: stretch(>75th pct) x 20d momentum (above-200 days only) ===")
print(t4.to_string(index=False)); print()

# where is SPY TODAY on each metric? (last bar in the file — no forward window needed)
last = df_all.dropna(subset=["stretch", "z", "pct", "atr", "mom20"]).iloc[-1]
today = pd.DataFrame([dict(metric="as of", value=str(last.name.date())),
    dict(metric="% above 200-day", value=round(float(last["stretch"]),2)),
    dict(metric="sigma above 200 (z)", value=round(float(last["z"]),2)),
    dict(metric="3yr stretch percentile", value=round(float(last["pct"]),1)),
    dict(metric="ATR dial (current)", value=round(float(last["atr"]),2)),
    dict(metric="20d momentum %", value=round(float(last["mom20"])*100,2))])
print("=== SPY TODAY ==="); print(today.to_string(index=False))

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    r = 0
    for nm, t in [("CURRENT ATR dial", t0), ("Opt1 sigma", t1),
                  ("Opt2 percentile", t2), ("Opt4 two-axis", t4), ("SPY today", today)]:
        pd.DataFrame([{"": nm}]).to_excel(xw, sheet_name="Study", index=False, header=False, startrow=r); r += 1
        t.to_excel(xw, sheet_name="Study", index=False, startrow=r); r += len(t) + 2
print(f"\nwrote {OUT}")
print("\nREADING NOTES: overlapping daily windows -> episodes column is the honest sample size."
      "\ndd = forward max drawdown (worst Low vs today's close), the beta-risk number."
      "\np10 = 10th percentile (the bad-tail outcome).")
