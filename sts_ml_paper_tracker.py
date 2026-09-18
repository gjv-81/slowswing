#!/usr/bin/env python3.12
# ============================================================================
# STS ML PAPER TRACKER — forward validation of the learned-weight system
# ============================================================================
# DESIGN (per validation plan):
#   - Tracks EVERY scan qualifier (winners AND losers — no selection bias)
#   - 1 share per name (equal-weight stats reported alongside, since the
#     research edge was defined on equal-dollar positions)
#   - Score and RS at initiation stored with each trade -> lets us check
#     whether higher scores actually produced better 12-week outcomes
#     (live re-test of the research threshold table)
#   - NO stop-loss; catastrophe flag at -40% (flag only)
#   - Checkpoints at 12 weeks (60 trading days) and 24 weeks (120)
#   - SAMPLE TOO SMALL verdict until 100 twelve-week checkpoints
#
# HOW TO USE:
#   Add trades   -> rows in sts_ml_paper_trades.csv (entry_price blank =
#                   auto-filled from the open of entry_date / next session)
#   Close early  -> optional close_date column
#   Run          -> cd ~/Documents/STS/15min && python3.12 sts_ml_paper_tracker.py
#   Stateless — recomputed from CSV + yfinance each run; safe to skip days.
#
# CSV: entry_date,ticker,shares,entry_price,score_at_entry,rs_at_entry,notes[,close_date]
# ============================================================================

import os, sys, math
import numpy as np
import pandas as pd

_DIR       = os.path.dirname(os.path.abspath(__file__))   # location-independent
TRADES_CSV = os.path.join(_DIR, "sts_ml_paper_trades.csv")
OUT_XLSX   = os.path.join(_DIR, "sts_ml_paper_tracker.xlsx")
W2, W4     = 10, 20          # 2-week / 4-week horizons (trading days)
W12, W24   = 60, 120
CATASTROPHE = -40.0
# lifecycle: Active <2wk (still forming) | Extended 2-4wk (in the trade) |
# Retired >=4wk (short-term trade done — scorecard locks at 2wk/4wk return + max dip)

GLOSSARY = [
 ("entry", "Open of entry_date (or next trading day). Auto-filled; override by typing a price in the CSV."),
 ("score/rs at entry", "STS ML score and RS-vs-market at initiation, from the TOS columns. Frozen at entry — the whole point is testing whether they predicted the outcome."),
 ("MAE / MFE %", "Worst drawdown / best gain vs entry so far. Expect MAE near -15% on many eventual winners — that is the researched path."),
 ("wk12 / wk24 ret %", "Return at 60 / 120 trading days after entry. Blank until reached. The validation numbers."),
 ("equal-weight avg", "Simple average of position returns — matches how the research measured edge. The 1-share portfolio value is price-weighted (big-price stocks dominate), so judge the SYSTEM by the equal-weight line."),
 ("Score buckets", "Live re-test of the research threshold table: if the system works, the 5+ bucket should beat the 2-3 bucket at the 12-week checkpoints."),
 ("CATASTROPHE", "Below -40%: the only flag that demands a decision. Everything above it is designed-for noise."),
 ("SAMPLE TOO SMALL", "Fewer than 100 twelve-week checkpoints -> results are anecdotes, not conclusions. Pre-committed."),
]

def fetch_history(tickers, start):
    import yfinance as yf, time
    data = {}
    for t in tickers:
        for attempt in range(3):          # Yahoo rate-limits bursts; retry per ticker
            try:
                df = yf.download(t, start=start, progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                if len(df):
                    data[t] = df[["Open", "High", "Low", "Close"]].copy()
                    break
            except Exception:
                pass
            time.sleep(3 * (attempt + 1))
        else:
            print(f"  WARNING: could not fetch {t} after 3 tries")
    return data

def main():
    if not os.path.exists(TRADES_CSV):
        sys.exit(f"ERROR: {TRADES_CSV} not found.")
    trades = pd.read_csv(TRADES_CSV)
    trades["entry_date"] = pd.to_datetime(trades["entry_date"])
    if "close_date" not in trades.columns:
        trades["close_date"] = pd.NaT
    trades["close_date"] = pd.to_datetime(trades["close_date"], errors="coerce")
    if "shares" not in trades.columns:
        trades["shares"] = 1.0

    # fetch ~400 extra days so the 52-wk high / 200-SMA state can be
    # reconstructed AT the entry date (for setup-code classification)
    start = (trades["entry_date"].min() - pd.Timedelta(days=430)).strftime("%Y-%m-%d")
    tickers = sorted(set(trades["ticker"]) | {"SPY", "RSP"})   # RSP: equal-weight benchmark for rs_now
    print(f"Fetching daily history for {len(tickers)} tickers from {start} ...")
    px = fetch_history(tickers, start)
    if "SPY" not in px:
        sys.exit("ERROR: could not fetch SPY — check network / yfinance.")

    # CLOSED positions: Yahoo deletes a ticker's recent history once it stops
    # trading (LBRDA/LBRDK after the Charter merger came back with one bar since
    # entry, so they could never reach the 4-week Retired threshold). The local
    # daily_data_10y CSV keeps the real bars (filled from the vendor by
    # retire_lbrd.py), so for a closed position the CSV wins wherever Yahoo is
    # missing a date. Open positions are untouched.
    for _, tr in trades.iterrows():
        if pd.isna(tr["close_date"]):
            continue
        t = tr["ticker"]
        csv_path = os.path.join(_DIR, "daily_data_10y", f"{t}.csv")
        if not os.path.exists(csv_path):
            continue
        try:
            local = pd.read_csv(csv_path, index_col=0, parse_dates=True).sort_index()
            local = local[local.index >= pd.Timestamp(start)]
            local = local[local["Close"].notna() & (local["Close"] > 0)]
            have = px.get(t)
            merged = local if have is None else pd.concat([have, local[~local.index.isin(have.index)]]).sort_index()
            if have is None or len(merged) > len(have):
                px[t] = merged
                print(f"  {t}: closed position, {len(merged) - (0 if have is None else len(have))} bars restored from local CSV")
        except Exception as e:                      # noqa: BLE001
            print(f"  {t}: local CSV overlay skipped ({e})")
    spy = px["SPY"]
    # 40-day momentum of the equal-weight market, for the LIVE relative-strength
    # read (rs_now). Same formula as rs_at_entry in sts_ml_evening.py:
    #   rs = 100 * (stock 40-day return - RSP 40-day return), in points.
    rsp_mom40 = None
    if "RSP" in px and len(px["RSP"]) > 41:
        _rc = px["RSP"]["Close"].dropna()
        rsp_mom40 = float(_rc.iloc[-1] / _rc.iloc[-41] - 1)
    # long SPY history for the PERCENTILE dial (needs ~4yr: 200d SMA + 3yr window).
    # Prefer the local CSV (kept current by the evening write-back); fall back to
    # a long yfinance fetch, then to the short series (percentile approximate).
    spy_csv = os.path.join(_DIR, "daily_data_10y", "SPY.csv")
    try:
        spy_long = pd.read_csv(spy_csv, index_col=0, parse_dates=True).sort_index()["Close"]
        if (spy.index.max() - spy_long.index.max()).days > 7:
            raise ValueError("SPY.csv stale")
    except Exception:
        try:
            lf = fetch_history(["SPY"], (trades["entry_date"].min()
                 - pd.Timedelta(days=1600)).strftime("%Y-%m-%d"))
            spy_long = lf["SPY"]["Close"]
        except Exception:
            spy_long = spy["Close"]
    _spy_stretch = ((spy_long / spy_long.rolling(200).mean() - 1) * 100).dropna()

    def spy_dial(asof):
        """Percentile dial AT a date (point-in-time): R / G / Y / O.
        RED below 200d; else GREEN <50th, YELLOW 50-90th, ORANGE >90th pctile
        of the trailing-3yr stretch distribution (see spy_regime_study.py)."""
        s = _spy_stretch[_spy_stretch.index <= asof]
        if len(s) < 100: return "?"
        if float(s.iloc[-1]) < 0: return "R"
        w = s.iloc[-757:]
        p = 100 * (w.iloc[:-1] < w.iloc[-1]).mean()
        return "O" if p > 90 else ("Y" if p >= 50 else "G")

    rows, missing = [], []
    for _, tr in trades.iterrows():
        t = tr["ticker"]
        base = dict(ticker=t, score_at_entry=tr.get("score_at_entry", np.nan),
                    rs_at_entry=tr.get("rs_at_entry", np.nan),
                    notes=tr.get("notes", ""))
        if t not in px:
            missing.append(t); continue
        df = px[t]
        after = df[df.index >= tr["entry_date"]]
        if len(after) == 0:
            rows.append(base | dict(status="PENDING",
                                    entry_date=tr["entry_date"].date())); continue
        e_date = after.index[0]
        e_px = float(tr["entry_price"]) if pd.notna(tr.get("entry_price")) and str(tr.get("entry_price")).strip() != "" \
               else float(after["Open"].iloc[0])
        sh = float(tr["shares"])

        # ── setup-code classification at entry (D200G/D200/M2/N2/DLB) ──
        hist = df[df.index <= e_date]
        score = pd.to_numeric(tr.get("score_at_entry"), errors="coerce")
        sma200 = float(hist["Close"].rolling(200).mean().iloc[-1]) if len(hist) >= 200 else np.nan
        dist200_pct = (e_px / sma200 - 1) * 100 if sma200 == sma200 else np.nan
        # washout-recovery: deepest % below the 200-day in the trailing 8 weeks (40 bars)
        if len(hist) >= 240:
            _pct = (hist["Close"] / hist["Close"].rolling(200).mean() - 1) * 100
            wash_min8w = float(_pct.iloc[-40:].min())
        else:
            wash_min8w = np.nan
        # flag only when currently NEAR the line from below (-10%..0%) AND it round-tripped
        near_line = (dist200_pct == dist200_pct) and (-10 <= dist200_pct <= 0)
        wr = ""
        if near_line and wash_min8w == wash_min8w:
            if   wash_min8w <= -40: wr = "WR40"
            elif wash_min8w <= -30: wr = "WR30"
            elif wash_min8w <= -20: wr = "WR20"
        if len(hist) >= 253:
            h52 = e_px / float(hist["High"].rolling(252).max().iloc[-1]) - 1
            above200 = e_px > sma200
            deep, mid = h52 <= -0.25, (-0.25 < h52 <= -0.10)
            if deep and above200:
                setup = "D200G" if (pd.notna(score) and score >= 2) else "D200"
            elif pd.notna(score) and score >= 2:
                setup = "B2" if mid else ("S2" if h52 > -0.10 else "DLB")
            else:
                setup = "-"
        else:
            setup = "young"
        # ── SPY regime dial at entry (percentile version: R / G / Y / O) ──
        dial = spy_dial(e_date)

        win = after if pd.isna(tr["close_date"]) else after[after.index <= tr["close_date"]]
        win = win.dropna(subset=["Close"])          # ignore empty/NaN price bars
        if len(win) == 0:
            rows.append(base | dict(status="NO PRICE", entry_date=tr["entry_date"].date()))
            continue
        last = float(win["Close"].iloc[-1])
        # CURRENT distance from the 200-day (recomputed every run, not frozen)
        sma200_now = float(df["Close"].rolling(200).mean().iloc[-1]) if len(df) >= 200 else np.nan
        dist200_now = round((last / sma200_now - 1) * 100, 1) if sma200_now == sma200_now else np.nan
        # CURRENT relative strength vs the equal-weight market (recomputed every
        # run, like dist200_now). rs_at_entry stays frozen — that is the tested
        # value; this is the "where is it now" value the board shows beside it.
        # Blank once a position is closed: there is no "now" for it.
        rs_now = np.nan
        if rsp_mom40 is not None and pd.isna(tr["close_date"]):
            _c = df["Close"].dropna()
            if len(_c) > 41:
                rs_now = round(100 * ((float(_c.iloc[-1]) / float(_c.iloc[-41]) - 1) - rsp_mom40), 1)
        ret = (last / e_px - 1) * 100
        mae = (float(win["Low"].min())  / e_px - 1) * 100
        mfe = (float(win["High"].max()) / e_px - 1) * 100
        # days-to-peak: trading days from entry to the bar that printed the MFE high.
        # win is in date order starting at entry, so argmax of the highs = that offset.
        dtp = int(np.asarray(win["High"].values).argmax()) if len(win) else 0

        def chk(n):
            return (float(after["Close"].iloc[n]) / e_px - 1) * 100 if len(after) > n else np.nan
        w2, w4, w12, w24 = chk(W2), chk(W4), chk(W12), chk(W24)
        # max dip within the first 4 weeks (short-term trader's worst drawdown)
        first2 = after.iloc[:W2 + 1]
        first4 = after.iloc[:W4 + 1]
        mae_4wk = (float(first4["Low"].min()) / e_px - 1) * 100 if len(first4) else np.nan
        # highest point TOUCHED within the 2wk / 4wk window (peak/MFE) — for
        # strategy design only (profit-target testing). NOT an achievable exit,
        # NOT for the website. Lets us count "did it ever touch +5% / +10%".
        mfe_2wk = (float(first2["High"].max()) / e_px - 1) * 100 if len(first2) else np.nan
        mfe_4wk = (float(first4["High"].max()) / e_px - 1) * 100 if len(first4) else np.nan
        # "Did it run clean?" — the deepest dip below the signal price counted only
        # up to (and including) the bar that FIRST touched +5% / +10%. NaN if the
        # level was never touched. The site's run-clean panel is computed from
        # these; before this they were hand-typed and went stale.
        def dip_before_touch(level_pct):
            hi = np.asarray(win["High"].values, dtype=float); lo = np.asarray(win["Low"].values, dtype=float)
            hit = np.nonzero(hi >= e_px * (1 + level_pct / 100.0))[0]
            if len(hit) == 0:
                return np.nan
            return (float(lo[:hit[0] + 1].min()) / e_px - 1) * 100
        dip_to5, dip_to10 = dip_before_touch(5), dip_before_touch(10)
        # lifecycle phase — an ACTIONABILITY signal (can you still take the trade?):
        #   Retired  = >= 4 weeks held (short-term trade done; scorecard locks)
        #   Extended = < 4 weeks AND already ran UP >= 5% (the move happened -> DON'T chase)
        #   Active   = < 4 weeks AND up < 5% (still a valid entry — INCLUDING names that
        #              are DOWN, which are cheaper near the line and arguably better entries)
        dh = len(win)
        if dh >= W4:
            phase = "Retired"
        elif ret >= 5:
            phase = "Extended"
        else:
            phase = "Active"

        spy_after = spy[spy.index >= e_date]
        spy_e = float(spy_after["Open"].iloc[0])
        idx = min(len(win) - 1, len(spy_after) - 1)
        spy_ret = (float(spy_after["Close"].iloc[idx]) / spy_e - 1) * 100
        spy_w12 = (float(spy_after["Close"].iloc[W12]) / spy_e - 1) * 100 if len(spy_after) > W12 else np.nan

        rows.append(base | dict(
            setup=setup, dial=dial, phase=phase,
            wk2_ret_pct=round(w2, 2) if not math.isnan(w2) else np.nan,
            wk4_ret_pct=round(w4, 2) if not math.isnan(w4) else np.nan,
            maxdip_4wk_pct=round(mae_4wk, 2) if mae_4wk == mae_4wk else np.nan,
            touched_2wk_pct=round(mfe_2wk, 2) if mfe_2wk == mfe_2wk else np.nan,
            touched_4wk_pct=round(mfe_4wk, 2) if mfe_4wk == mfe_4wk else np.nan,
            dip_to5_pct=round(dip_to5, 2) if dip_to5 == dip_to5 else np.nan,
            dip_to10_pct=round(dip_to10, 2) if dip_to10 == dip_to10 else np.nan,
            dist200_pct=round(dist200_pct, 1) if dist200_pct == dist200_pct else np.nan,
            dist200_now=dist200_now, rs_now=rs_now,
            wr=wr, wash_min8w=round(wash_min8w, 1) if wash_min8w == wash_min8w else np.nan,
            sma200_at_entry=round(sma200, 2) if sma200 == sma200 else np.nan,
            status="CLOSED" if pd.notna(tr["close_date"]) else "OPEN",
            entry_date=e_date.date(), entry=round(e_px, 2), shares=sh,
            cost=round(e_px * sh, 2), last=round(last, 2),
            value=round(last * sh, 2), ret_pct=round(ret, 2),
            mae_pct=round(mae, 2), mfe_pct=round(mfe, 2), days_held=len(win), dtp=dtp,
            wk12_ret_pct=round(w12, 2) if not math.isnan(w12) else np.nan,
            wk24_ret_pct=round(w24, 2) if not math.isnan(w24) else np.nan,
            spy_ret_pct=round(spy_ret, 2),
            spy_wk12_pct=round(spy_w12, 2) if not math.isnan(spy_w12) else np.nan,
            excess_pct=round(ret - spy_ret, 2),
            flag="CATASTROPHE" if ret <= CATASTROPHE else ("dipping" if mae <= -13 else "")))
    pos = pd.DataFrame(rows)
    act = pos[pos["status"].isin(["OPEN", "CLOSED"])].copy() if len(pos) else pos

    # ── summary ─────────────────────────────────────────────────────────────
    if len(act):
        cost, val = act["cost"].sum(), act["value"].sum()
        ew_ret = act["ret_pct"].mean()
        ew_excess = act["excess_pct"].mean()
        w12v = act["wk12_ret_pct"].dropna()
        n12, wins12 = len(w12v), int((w12v > 0).sum())
    else:
        cost = val = ew_ret = ew_excess = 0; n12 = wins12 = 0
    summary = pd.DataFrame([
        ("Positions tracked", f"{len(act)} (+{int((pos['status']=='PENDING').sum())} pending)"),
        ("Cost basis (1 share each)", f"${cost:,.2f}"),
        ("Current value", f"${val:,.2f}  ({100*(val/cost-1):+.2f}% price-weighted)" if cost else "-"),
        ("EQUAL-WEIGHT avg return", f"{ew_ret:+.2f}%  <- judge the system by this line"),
        ("Equal-weight avg excess vs SPY", f"{ew_excess:+.2f}%"),
        ("12-week checkpoints", f"{n12} reached, {wins12} wins ({100*wins12/max(n12,1):.0f}%)"),
        ("Catastrophes (<-40%)", f"{int((act['flag']=='CATASTROPHE').sum()) if len(act) else 0}"),
        ("Verdict", "SAMPLE TOO SMALL — no conclusions before 100 twelve-week checkpoints"
                    if n12 < 100 else "Sample adequate — evaluate vs pre-committed rules"),
    ], columns=["metric", "value"])

    # ── score-bucket live re-test of the threshold table ────────────────────
    buckets = None
    if len(act) and act["score_at_entry"].notna().any():
        act["bucket"] = pd.cut(pd.to_numeric(act["score_at_entry"], errors="coerce"),
                               [0, 3, 5, 99], labels=["2.0-3.0", "3.1-5.0", "5.1+"])
        buckets = act.groupby("bucket", observed=True).agg(
            n=("ret_pct", "size"), avg_ret_pct=("ret_pct", "mean"),
            avg_excess_pct=("excess_pct", "mean"),
            avg_wk12_pct=("wk12_ret_pct", "mean"),
            win_rate_now_pct=("ret_pct", lambda s: 100 * (s > 0).mean()),
            avg_mae_pct=("mae_pct", "mean")).round(2).reset_index()

    # ── ONE sheet: summary block on top, buckets, then the running list ─────
    # (running list: date first column, sorted oldest entries first, then
    #  score descending within each date — a permanent chronological log)
    lead = ["entry_date", "ticker", "setup", "phase", "dial", "score_at_entry", "rs_at_entry", "rs_now",
            "wk2_ret_pct", "wk4_ret_pct", "maxdip_4wk_pct",
            "dist200_pct", "dist200_now", "wr", "wash_min8w", "sma200_at_entry", "status"]
    lead = [c for c in lead if c in pos.columns]   # robust if a column is absent
    rest = [c for c in pos.columns if c not in lead]
    sort_cols = [c for c in ["entry_date", "score_at_entry"] if c in pos.columns]
    pos = pos[lead + rest]
    if sort_cols:
        # NEWEST entries on top (entry_date descending; score desc within a day)
        pos = pos.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    # ── setup-code fan-out (D200G / D200 / M2 / N2 / DLB) ───────────────────
    setups = None
    if len(act) and "setup" in act.columns:
        order = ["D200G", "D200", "B2", "G2", "S2", "DLB", "-", "young"]
        setups = (act.groupby("setup").agg(
            n=("ret_pct", "size"), avg_ret_pct=("ret_pct", "mean"),
            win_pct=("ret_pct", lambda s: 100 * (s > 0).mean()),
            avg_excess_pct=("excess_pct", "mean"),
            avg_wk12_pct=("wk12_ret_pct", "mean"),
            avg_mae_pct=("mae_pct", "mean")).round(2)
            .reindex([s for s in order if s in set(act["setup"])])
            .dropna(how="all").reset_index())

    # ── RETIRED scorecard: short-term-trader view (>=4wk held) ──────────────
    # realistic 2-week / 4-week returns + worst dip, by setup. This is the
    # honest short-horizon scorecard (no peak/MFE — see glossary).
    retired = None
    if len(act) and "phase" in act.columns:
        rt = act[act["phase"] == "Retired"].copy()
        for c in ["wk2_ret_pct", "wk4_ret_pct", "maxdip_4wk_pct"]:
            rt[c] = pd.to_numeric(rt.get(c), errors="coerce")
        if len(rt):
            order = ["D200G", "D200", "B2", "G2", "S2", "DLB", "ALL"]
            rows_sc = []
            for grp in order[:-1] + [None]:
                g = rt if grp is None else rt[rt["setup"] == grp]
                if len(g) == 0: continue
                rows_sc.append(dict(setup=("ALL" if grp is None else grp), n=len(g),
                    avg_wk2_pct=round(g["wk2_ret_pct"].mean(), 2),
                    win_wk2_pct=round(100 * (g["wk2_ret_pct"] > 0).mean(), 0),
                    avg_wk4_pct=round(g["wk4_ret_pct"].mean(), 2),
                    win_wk4_pct=round(100 * (g["wk4_ret_pct"] > 0).mean(), 0),
                    avg_maxdip_pct=round(g["maxdip_4wk_pct"].mean(), 2)))
            retired = pd.DataFrame(rows_sc)

    # ── washout-recovery fan-out (WR20 / WR30 / WR40) ───────────────────────
    washes = None
    if len(act) and "wr" in act.columns and (act["wr"].astype(str).str.len() > 0).any():
        w = act[act["wr"].astype(str).str.startswith("WR")]
        if len(w):
            washes = (w.groupby("wr").agg(
                n=("ret_pct", "size"), avg_ret_pct=("ret_pct", "mean"),
                win_pct=("ret_pct", lambda s: 100 * (s > 0).mean()),
                avg_excess_pct=("excess_pct", "mean"),
                avg_mae_pct=("mae_pct", "mean")).round(2)
                .reindex([c for c in ["WR40", "WR30", "WR20"] if c in set(w["wr"])])
                .dropna(how="all").reset_index())

    col_gloss = pd.DataFrame([
        ("COLUMN GLOSSARY", ""),
        ("entry_date", "Date the paper trade was initiated (fills at that day's open, or the next session if it wasn't a trading day)."),
        ("setup", "Setup code AT ENTRY (see SETUP_CODES in the playbook workbook): D200G = >=25% off high + above 200-SMA + score>=2 (research: +16.2%). D200 = same, score<2 (+14.0%). B2 (Breather) = score>=2, 10-25% off (+14.1%). S2 (Sprinter) = score>=2, <=10% off (+11.3%). DLB = score>=2 but deep AND below the 200-SMA (the risky crash cohort). 'young' = under 1yr of data. Frozen at entry so the fan-out is analyzable later."),
        ("phase", "Can you still take this trade? Active = <4wk and up less than 5% (still a valid entry — INCLUDING names that are down, which are cheaper near the line). Extended = <4wk but already ran UP 5%+ (the move happened — don't chase). Retired = >=4wk held (short-term trade done; judge by wk2/wk4 return + max dip)."),
        ("wk2_ret_pct", "Actual close-to-close return 2 weeks (10 trading days) after entry. Achievable — what a 2-week holder got. Blank until reached."),
        ("wk4_ret_pct", "Actual close-to-close return 4 weeks (20 trading days) after entry. Achievable — what a 4-week holder got. Blank until reached."),
        ("maxdip_4wk_pct", "Worst intraday drawdown vs entry during the first 4 weeks — the max pain a short-term holder would have felt."),
        ("touched_2wk_pct / touched_4wk_pct", "HIGHEST point the stock touched vs entry within the 2wk / 4wk window (peak/MFE). For STRATEGY DESIGN ONLY (e.g. testing a profit-target exit) — this is NOT an achievable exit and must NEVER be shown as a return on the website. Use it to answer 'did it ever touch +5% / +10%'."),
        ("dial", "SPY stretch-percentile dial AT ENTRY (vs SPY's own trailing 3yr): R = below the 200-day, G = above + <50th pctile (recently reset — historically best entries), Y = 50-90th (extended but ordinary), O = >90th (over-extended — the only zone where the bad-tail 4wk drawdowns exceeded -8% and bear markets began). Informational, never an entry gate. Frozen at entry."),
        ("dist200_pct", "How far the ENTRY price sat above/below the stock's own 200-day SMA, in %. FROZEN AT ENTRY — never changes. Positive = above the line, negative = below. Tests whether outcomes depended on closeness to the 200-day when you bought."),
        ("dip_to5_pct / dip_to10_pct", "Deepest dip below the signal price counted only up to the bar that FIRST touched +5% / +10% (blank if never touched). Feeds the website's 'Did they run clean?' panel."),
        ("rs_now", "40-day relative strength vs the equal-weight market (RSP) AS OF THE LATEST RUN — LIVE, recomputed every day for every open position; blank once closed. Same formula as rs_at_entry, which stays frozen. The website shows both: 'Pulse @ Add' (frozen) and 'Pulse now' (this)."),
        ("dist200_now", "How far the stock sits above/below its 200-day SMA AS OF THE LATEST RUN — LIVE, recomputed every day for every open position. Compare with dist200_pct to see how the position has moved relative to its trend line since entry."),
        ("wr", "WASHOUT-RECOVERY flag: entry was NEAR the 200-day from below (-10%..0%) AND the stock had round-tripped from a deep washout in the prior 8 weeks. WR20 = was >=20% below at some point; WR30 = >=30%; WR40 = >=40%. Historically the deeper the washout, the bigger the 12wk return (WR40 backtested ~+12%). Blank = not a washout-recovery. The 'came back from the knife' filter."),
        ("wash_min8w", "The deepest the stock traded below its 200-day SMA in the trailing 8 weeks (%, frozen at entry). Drives the wr flag; shows the depth of the round-trip directly."),
        ("sma200_at_entry", "The stock's 200-day simple moving average value on the entry date."),
        ("score_at_entry / rs_at_entry", "STS ML score and RS-vs-market frozen at initiation. Never updated — the point is testing whether they predicted the outcome."),
        ("entry / shares / cost", "Fill price (open of entry date), share count (1), and entry cost = entry x shares."),
        ("last / value", "Latest close and current position value (shares x last)."),
        ("ret_pct", "Total return so far: (last / entry - 1) x 100. The live P&L of the position, in percent."),
        ("mae_pct", "Maximum Adverse Excursion: the WORST the trade has been vs entry, using intraday lows. -15% here with ret_pct +5% means it dipped 15% before recovering. Expect many winners to show -10 to -15% — that is the researched path, not a malfunction."),
        ("mfe_pct", "Maximum Favorable Excursion: the BEST the trade has been vs entry, using intraday highs. Together with mae_pct it shows the full round trip the position has traveled."),
        ("days_held", "Trading days since entry (not calendar days). 60 = the 12-week mark; 120 = the 24-week mark."),
        ("dtp", "Days-to-peak: trading days from entry to the day the MFE high was printed (0 = the high came on the entry bar itself). Powers the site's 'median ~2 weeks to peak' stat and the peak marker on each signal's chart."),
        ("wk12_ret_pct", "Return exactly 60 trading days after entry. Blank until reached, then frozen forever. THE primary validation number — the research edge was defined at this horizon."),
        ("wk24_ret_pct", "Return exactly 120 trading days after entry. Blank until reached. Tests the horizon study's finding that momentum persists to 24 weeks."),
        ("spy_ret_pct", "What the same dollars would have returned in SPY, bought at the same entry open, over the same days held. The opportunity-cost benchmark."),
        ("spy_wk12_pct", "SPY's return over the same 60-trading-day window. Compare with wk12_ret_pct: the system must beat this to justify existing."),
        ("excess_pct", "ret_pct minus spy_ret_pct. Positive = this position is beating the market; negative = SPY would have been better. The equal-weight average of this column is the single most honest measure of the system."),
        ("flag", "'dipping' = MAE beyond -13% (normal per research, no action). 'CATASTROPHE' = down 40%+ (the one flag demanding a decision)."),
        ("status", "OPEN / CLOSED (close_date set in CSV) / PENDING (entry date not yet reached)."),
    ], columns=["term", "meaning"])
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
        row = 0
        summary.to_excel(xw, sheet_name="Tracker", index=False, startrow=row)
        row += len(summary) + 2
        if buckets is not None:
            buckets.to_excel(xw, sheet_name="Tracker", index=False, startrow=row)
            row += len(buckets) + 2
        if setups is not None:
            setups.to_excel(xw, sheet_name="Tracker", index=False, startrow=row)
            row += len(setups) + 2
        if retired is not None:
            pd.DataFrame([{"setup": "RETIRED SCORECARD (>=4wk held): realistic 2wk/4wk return + max dip"}]).to_excel(
                xw, sheet_name="Tracker", index=False, header=False, startrow=row); row += 1
            retired.to_excel(xw, sheet_name="Tracker", index=False, startrow=row)
            row += len(retired) + 2
        if washes is not None:
            washes.to_excel(xw, sheet_name="Tracker", index=False, startrow=row)
            row += len(washes) + 2
        pos.to_excel(xw, sheet_name="Tracker", index=False, startrow=row)
        row += len(pos) + 3
        col_gloss.to_excel(xw, sheet_name="Tracker", index=False,
                           header=False, startrow=row)
        # widen column A so the entry_date is always readable
        xw.sheets["Tracker"].column_dimensions["A"].width = 13

    print("\n" + "=" * 68)
    print("STS ML PAPER TRACKER")
    print("=" * 68)
    for _, r in summary.iterrows():
        print(f"  {r['metric']:<32} {r['value']}")
    if setups is not None and len(setups):
        print("\nSETUP CODES (live fan-out):")
        for _, r in setups.iterrows():
            print(f"  {str(r['setup']):<6} n={int(r['n']):>3}  avg {r['avg_ret_pct']:+6.2f}%"
                  f"  win {r['win_pct']:.0f}%  excess {r['avg_excess_pct']:+6.2f}%")
    if retired is not None and len(retired):
        print("\nRETIRED SCORECARD (>=4wk held — realistic short-term view):")
        for _, r in retired.iterrows():
            print(f"  {str(r['setup']):<6} n={int(r['n']):>3}  wk2 {r['avg_wk2_pct']:+6.2f}% (win {r['win_wk2_pct']:.0f}%)"
                  f"  wk4 {r['avg_wk4_pct']:+6.2f}% (win {r['win_wk4_pct']:.0f}%)  maxdip {r['avg_maxdip_pct']:+.1f}%")
    if washes is not None and len(washes):
        print("\nWASHOUT-RECOVERY (near 200-day, came back from a deep dip):")
        for _, r in washes.iterrows():
            print(f"  {str(r['wr']):<5} n={int(r['n']):>3}  avg {r['avg_ret_pct']:+6.2f}%"
                  f"  win {r['win_pct']:.0f}%  excess {r['avg_excess_pct']:+6.2f}%")
    if buckets is not None and len(buckets):
        print("\nSCORE BUCKETS (live threshold-table re-test):")
        for _, r in buckets.iterrows():
            print(f"  score {r['bucket']:<8} n={int(r['n']):>3}  avg {r['avg_ret_pct']:+6.2f}%"
                  f"  excess {r['avg_excess_pct']:+6.2f}%  win {r['win_rate_now_pct']:.0f}%"
                  f"  MAE {r['avg_mae_pct']:+.1f}%")
    if len(act):
        top = act.nlargest(3, "ret_pct"); bot = act.nsmallest(3, "ret_pct")
        print("\nBest:  " + " | ".join(f"{r.ticker} {r.ret_pct:+.1f}%" for r in top.itertuples()))
        print("Worst: " + " | ".join(f"{r.ticker} {r.ret_pct:+.1f}%" for r in bot.itertuples()))
        ncat = act[act["flag"] == "CATASTROPHE"]
        if len(ncat):
            print("CATASTROPHE FLAGS: " + ", ".join(ncat["ticker"]))
    if missing:
        print(f"\nWARNING — no data for: {', '.join(missing)}")
    print(f"\nOutput written to: {OUT_XLSX}")

if __name__ == "__main__":
    main()
