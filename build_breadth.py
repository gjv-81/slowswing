#!/usr/bin/env python3.12
"""
build_breadth.py — nightly "Market Health" numbers for the website (added 2026-11-22, GJ).

Writes site/breadth.json: the share of stocks trading above their long-term and short-term
trend, for three views (all stocks we track / S&P 500 members / Nasdaq-100 members), a weekly
history since 2021 against SPY or QQQ (indexed, no prices), and a by-sector table.

DESCRIPTIVE ONLY. Breadth failed as a predictor in STS_INTERNAL_DIAL_PREREG.md; the site must
present it as the market's current state, never as a signal. Percentages only (no price display).
Source: daily_data_10y/ (the licensed feed) for every stock the model tracks. Index members that
are NOT in that folder (~100 S&P 500 / ~15 Nasdaq-100 names) are read from EXTRA_DIRS, first hit
wins: daily_data_mh/ (licensed, to be created once the Marketstack quota is raised) then
daily_data_v2/ (Yahoo research folder — TEMPORARY, GJ 2026-11-22, until Marketstack replies).
An extra name with no bar tonight keeps its last reading for up to 5 sessions.
Membership lists: sp500_tickers.txt, nasdaq100_tickers.txt (today's members — history is
therefore "today's members, back in time"). "All stocks" uses ONLY the licensed folder.
Site wording: "in an uptrend" — never name the averages (mechanics rule).

Run:  python3.12 build_breadth.py            (prints a one-line summary; exit 0 even if thin)
"""
import glob, json, os, sys, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE / "daily_data_10y"
OUT = HERE / "site" / "breadth.json"
EXTRA_DIRS = ["daily_data_mh", "daily_data_v2"]   # for index members missing from SRC; first hit wins
CARRY = 5                                        # sessions an extra name may lag before it is dropped
LONG, SHORT, AGO = 200, 50, 20          # sessions; AGO = "4 weeks ago"
HIST_START = "2021-01-01"
NOT_STOCKS = {"SPY", "QQQ", "RSP", "IWM", "DIA"}

def _list(name):
    p = HERE / name
    if not p.exists(): return []
    toks = []
    for line in p.read_text().splitlines():
        if line.strip().startswith("#"): continue
        toks += line.split()
    return [t.strip().upper().replace(".", "-") for t in toks if t.strip()]

def describe(l, s, l4, s4):
    if l < 35:
        if s > l and s > s4: return "Recovering", "Short-term participation is rising from a low."
        return "Washed out", "Fewer than about one in three stocks is in an uptrend."
    if l >= 60 and s >= 60: return "Broad advance", "Most stocks are in an uptrend, long-term and short-term."
    if s > l and s > s4 and l < 55: return "Recovering", "Short-term participation is rising and now leads the long-term reading."
    if l < 55 and l < l4: return "Narrowing", "Fewer than about half of stocks are in an uptrend, and the share is falling."
    return "Mixed", "About half of stocks are in an uptrend, with no clear direction."

def main():
    a_long, a_short, idx = {}, {}, {}
    def _load(fp):
        c = pd.read_csv(fp, index_col=0, parse_dates=True)["Close"].astype(float).sort_index()
        return c[~c.index.duplicated(keep="last")]
    def _flags(c):
        ml, ms = c.rolling(LONG).mean(), c.rolling(SHORT).mean()
        return (c > ml).where(ml.notna()), (c > ms).where(ms.notna())
    for fp in glob.glob(str(SRC / "*.csv")):
        t = os.path.basename(fp)[:-4].upper()
        try:
            c = _load(fp)
        except Exception:
            continue
        if t in ("SPY", "QQQ"): idx[t] = c
        if t in NOT_STOCKS or len(c) < LONG + 60: continue
        a_long[t], a_short[t] = _flags(c)
    if "SPY" not in idx or len(a_long) < 100:
        print("build_breadth: not enough data — nothing written"); return 0
    asof = idx["SPY"].index.max()
    cal = idx["SPY"].index
    licensed = set(a_long)
    # index members not in the licensed folder -> EXTRA_DIRS (carry forward up to CARRY sessions)
    spx_all, ndx_all = _list("sp500_tickers.txt"), _list("nasdaq100_tickers.txt")
    extra_src = {}
    for t in sorted((set(spx_all) | set(ndx_all)) - licensed - NOT_STOCKS):
        for d in EXTRA_DIRS:
            fp = HERE / d / f"{t}.csv"
            if not fp.exists(): continue
            try:
                c = _load(fp)
            except Exception:
                continue
            c = c[c.index <= asof]
            if len(c) < LONG + 60 or len(cal[cal > c.index.max()]) > CARRY: continue
            fl, fs = _flags(c)
            a_long[t] = fl.reindex(cal).ffill(limit=CARRY); a_short[t] = fs.reindex(cal).ffill(limit=CARRY)
            extra_src[t] = d; break
    AL = pd.DataFrame(a_long).astype(float); AS = pd.DataFrame(a_short).astype(float)
    AL = AL[AL.index <= asof]; AS = AS[AS.index <= asof]
    fresh_all = [t for t in AL.columns if pd.notna(AL[t].get(asof, np.nan))]
    fresh = [t for t in fresh_all if t in licensed]                            # "All stocks" = licensed folder only
    spx = [t for t in spx_all if t in fresh_all]
    ndx = [t for t in ndx_all if t in fresh_all]
    views = {}
    for key, label, members, ix, ixlab in (("all", "All stocks", fresh, "SPY", "S&P 500 (SPY)"),
                                           ("spx", "S&P 500", spx, "SPY", "S&P 500 (SPY)"),
                                           ("ndx", "Nasdaq-100", ndx, "QQQ" if "QQQ" in idx else "SPY",
                                            "Nasdaq-100 (QQQ)" if "QQQ" in idx else "S&P 500 (SPY)")):
        if len(members) < 30: continue
        bl = 100 * AL[members].mean(axis=1); bs = 100 * AS[members].mean(axis=1)
        w = bl[bl.index >= HIST_START].resample("W-FRI").last().dropna()
        if w.index[-1] != asof:                       # make the last point tonight's reading
            w = pd.concat([w[w.index < asof], pd.Series([bl.loc[asof]], index=[asof])])
        ixs = idx[ix].reindex(w.index, method="ffill"); ixs = 100 * ixs / ixs.iloc[0]   # indexed, no prices
        l, s, l4, s4 = bl.iloc[-1], bs.iloc[-1], bl.iloc[-1 - AGO], bs.iloc[-1 - AGO]
        state, text = describe(l, s, l4, s4)
        views[key] = dict(label=label, n=len(members), index_label=ixlab,
                          n_extra=sum(1 for t in members if t in extra_src),
                          now=dict(long=round(l), short=round(s), long_4w=round(l4), short_4w=round(s4),
                                   hi_12m=round(bl.iloc[-252:].max()), lo_12m=round(bl.iloc[-252:].min())),
                          state=state, text=text,
                          history=dict(dates=[d.strftime("%Y-%m-%d") for d in w.index],
                                       breadth=[round(float(v), 1) for v in w.values],
                                       index=[round(float(v), 1) for v in ixs.values]))
    sectors = []
    sm = HERE / "sector_map.csv"
    if sm.exists():
        m = pd.read_csv(sm); S = dict(zip(m.ticker.str.upper(), m.sector))
        df = pd.DataFrame({"now": AL.loc[asof, fresh], "ago": AL.iloc[-1 - AGO][fresh], "sec": [S.get(t) for t in fresh]}).dropna()
        g = df.groupby("sec").agg(now=("now", "mean"), ago=("ago", "mean"), n=("now", "size"))
        for k, r in g[g.n >= 8].sort_values("now", ascending=False).iterrows():
            sectors.append(dict(name=k, now=round(100 * r.now), ago=round(100 * r.ago), n=int(r.n)))
    out = dict(as_of=asof.strftime("%Y-%m-%d"), generated_at=dt.datetime.now().isoformat(timespec="seconds"),
               views=views, sectors=sectors,
               extras=dict(count=len(extra_src), sources=sorted(set(extra_src.values()))),
               note="Share of stocks in an uptrend. Descriptive only: not a forecast, a signal, or advice. "
                    "Index views use today's members.")
    OUT.parent.mkdir(exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp"); tmp.write_text(json.dumps(out, separators=(",", ":"))); os.replace(tmp, OUT)
    print("build_breadth " + out["as_of"] + ": " + " | ".join(
        f"{v['label']} {v['now']['long']}% (n={v['n']}, {v['state']})" for v in views.values()) + f" | sectors {len(sectors)} | extras {len(extra_src)} from {sorted(set(extra_src.values()))}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
