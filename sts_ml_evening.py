#!/usr/bin/env python3.12
# ============================================================================
# STS ML EVENING SCRIPT — auto-scan, auto-append, auto-update, Telegram
# ============================================================================
# Run once each evening after the close (manually or via cron):
#   cd ~/Documents/STS/15min && python3.12 sts_ml_evening.py
#
# WHAT IT DOES, in order:
#   1. Refreshes daily data for the research universe (ticker list =
#      daily_data_10y/ filenames) plus SPY and RSP — Marketstack-first via
#      data_refresh.py (append-only, licensed), Yahoo 2y download as fallback
#   2. Computes the STS ML score for every ticker — IDENTICAL formula to
#      the TOS column (same z-constants, same +/-3 sigma clipping), plus
#      RS vs RSP (40-day) and the SPY regime dial
#   3. Appends NEW qualifiers (score >= 2.0) to sts_ml_paper_trades.csv
#      with tomorrow's date, 1 share, and score/RS frozen at entry.
#      Tickers already in the CSV are NEVER re-added (dedupe by ticker).
#   4. Rebuilds sts_ml_paper_tracker.xlsx (runs the tracker)
#   5. Sends a Telegram summary: regime, new qualifiers, tracker headline
#
# NOTES
#   - Python vs TOS scores may differ by ~0.1-0.3 (data vendor rounding);
#     the ranking is what matters.
#   - To exclude a ticker forever (e.g. after SSI2 rejects it), leave it in
#     the CSV with a close_date — it still won't be re-added.
#   - Optional cron (weekdays 5:30pm PT):  30 17 * * 1-5  cd ~/Documents/STS/15min && /usr/local/bin/python3.12 sts_ml_evening.py >> evening.log 2>&1
# ============================================================================

import os, sys, glob, subprocess, datetime
import numpy as np
import pandas as pd

DIR         = os.path.dirname(os.path.abspath(__file__))   # folder this script lives in (location-independent)
UNIVERSE_DIR= os.path.join(DIR, "daily_data_10y")
TRADES_CSV  = os.path.join(DIR, "sts_ml_paper_trades.csv")
TRACKER_PY  = os.path.join(DIR, "sts_ml_paper_tracker.py")
THRESHOLD   = 2.0
MIN_PRICE   = 10.0
# ETFs/index funds in the data folder — scored universe is EQUITIES only
EXCLUDE = {"SPY","QQQ","IWM","DIA","GLD","SLV","USO","SOXX","SMH","RSP",
           "TLT","HYG","ARKK","VOO","VTI","XLB","XLE","XLF","XLI","XLK",
           "XLU","XLV","XLY","UNG","UUP","FXI","KWEB"}
TELEGRAM_ENABLED = True
# Telegram credentials live in .env (never in code — the code is in a git repo).
#   TG_TOKEN=<bot token from @BotFather>
#   TG_CHAT=<your chat id>
def _env(key, default=""):
    v = os.environ.get(key)
    if v: return v
    try:
        for line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return default
TG_TOKEN    = _env("TG_TOKEN")
TG_CHAT     = _env("TG_CHAT", "6499078442")

# z-constants — MUST match the TOS column exactly
ZC = {"high52": (-0.149772, 0.156737), "dist200": (1.681650, 6.240695),
      "mom6": (0.086250, 0.361377), "qqe": (0.044473, 0.194268),
      "hull": (0.027496, 0.303103), "mom40": (0.020000, 0.155298)}
W  = {"high52": -2.20, "dist200": 1.35, "mom6": 1.08,
      "qqe": -0.99, "mom40": 0.63, "hull": 0.60}

def zclip(v, key):
    m, s = ZC[key]
    return np.clip((v - m) / s, -3, 3)

def wilders(s, n):
    return s.ewm(alpha=1/n, adjust=False).mean()

def rsi_wilder(s, n=20):
    d = s.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    rs = wilders(up, n) / wilders(dn, n).replace(0, 1e-10)
    return 100 - 100 / (1 + rs)

def wma(s, n):
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

def score_ticker(df):
    """df: OHLCV daily; returns (score, mom40) at the last bar, or None."""
    if len(df) < 260: return None
    C, H, L = df["Close"], df["High"], df["Low"]
    pc = C.shift(1)
    tr = pd.concat([H - L, (H - pc).abs(), (L - pc).abs()], axis=1).max(axis=1)
    atr = wilders(tr, 14)
    high52 = C / H.rolling(252).max() - 1
    dist200 = (C - C.rolling(200).mean()) / atr
    mom6 = C.shift(10) / C.shift(126) - 1
    qqe = (rsi_wilder(C, 20).fillna(50).ewm(span=5, adjust=False).mean() - 50) / 50
    hma = wma(2 * wma(C, 10) - wma(C, 20), 4)
    hull = (hma - hma.shift(1)) / atr
    mom40 = C / C.shift(40) - 1
    vals = dict(high52=high52.iloc[-1], dist200=dist200.iloc[-1],
                mom6=mom6.iloc[-1], qqe=qqe.iloc[-1],
                hull=hull.iloc[-1], mom40=mom40.iloc[-1])
    if any(pd.isna(v) for v in vals.values()): return None
    score = sum(W[k] * zclip(vals[k], k) for k in W)
    # setup-relevant fields for re-qualification logic
    sma200 = C.rolling(200).mean()
    px = float(C.iloc[-1])
    dist200_pct = (px / float(sma200.iloc[-1]) - 1) * 100 if pd.notna(sma200.iloc[-1]) else np.nan
    pct_series = (C / sma200 - 1) * 100
    wash_min8w = float(pct_series.iloc[-40:].min()) if len(pct_series) >= 240 else np.nan
    off_high = float(high52.iloc[-1]) * 100   # % below 52-wk high (negative)
    return dict(score=round(float(score), 1), mom40=float(vals["mom40"]),
                dist200_pct=round(dist200_pct, 1) if dist200_pct == dist200_pct else np.nan,
                wash_min8w=round(wash_min8w, 1) if wash_min8w == wash_min8w else np.nan,
                off_high=round(off_high, 1))

def classify(score, off_high, dist200_pct, wash_min8w):
    """Return (setup_code, wr_tag) the same way the tracker does."""
    above200 = dist200_pct is not None and dist200_pct == dist200_pct and dist200_pct > 0
    deep = off_high <= -25; mid = -25 < off_high <= -10
    if deep and above200:
        setup = "D200G" if score >= 2 else "D200"
    elif score >= 2:
        setup = "B2" if mid else ("S2" if off_high > -10 else "DLB")
    else:
        setup = "-"
    wr = ""
    if dist200_pct == dist200_pct and -10 <= dist200_pct <= 0 and wash_min8w == wash_min8w:
        if   wash_min8w <= -40: wr = "WR40"
        elif wash_min8w <= -30: wr = "WR30"
        elif wash_min8w <= -20: wr = "WR20"
    return setup, wr

def fetch_batch(tickers):
    import yfinance as yf
    out = {}
    CH = 100
    for i in range(0, len(tickers), CH):
        chunk = tickers[i:i+CH]
        try:
            raw = yf.download(chunk, period="2y", progress=False,
                              auto_adjust=True, group_by="ticker", threads=True)
        except Exception as e:
            print(f"  batch failed: {e}"); continue
        for t in chunk:
            try:
                df = raw[t].dropna() if len(chunk) > 1 else raw.dropna()
                if len(df): out[t] = df
            except Exception:
                pass
        print(f"  {min(i+CH, len(tickers))}/{len(tickers)} downloaded")
    # Yahoo rate-limits bursts and can blank a whole chunk ("possibly delisted") —
    # retry the missing names individually, twice, before giving up on them
    import time
    missing = [t for t in tickers if t not in out]
    for attempt in range(2):
        if not missing: break
        time.sleep(10)
        print(f"  retrying {len(missing)} rate-limited tickers (pass {attempt+1}) ...")
        still = []
        for t in missing:
            try:
                df = yf.download(t, period="2y", progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna()
                if len(df): out[t] = df
                else: still.append(t)
            except Exception:
                still.append(t)
            time.sleep(0.5)
        missing = still
    if missing:
        print(f"  STILL MISSING after retries: {', '.join(missing[:20])}")
    return out

def expected_session(today=None):
    """The last session whose close should be on disk: today (ET) if it is a
    weekday AND the market has closed, else the previous weekday. Clock is New
    York time whatever the laptop is set to. (US holidays are not modelled — on
    a holiday the data is one day 'stale', which only costs a Yahoo fallback.)"""
    if today is None:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            now = datetime.datetime.now()
        today = now.date()
        if (now.hour, now.minute) < (16, 0):
            today -= datetime.timedelta(days=1)
    d = today
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d

def load_from_csvs(tickers, universe_dir, years=2):
    """Read the last `years` of each ticker's CSV into the same dict layout that
    fetch_batch() returns (DatetimeIndex, Open/High/Low/Close/Volume)."""
    cutoff = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=int(365.25 * years)))
    out = {}
    for t in tickers:
        p = os.path.join(universe_dir, f"{t}.csv")
        if not os.path.exists(p):
            continue
        try:
            df = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            df = df[(df.index >= cutoff) & (df["Close"] > 0)]
            if len(df): out[t] = df
        except Exception as e:                       # noqa: BLE001
            print(f"  {t}: CSV unreadable ({e})")
    return out

def load_universe_data(universe):
    """Marketstack-first (licensed, append-only, ~10 requests), Yahoo fallback.

    Path A — EOD_PROVIDER=marketstack in .env and STS_FORCE_YAHOO unset:
      data_refresh.refresh_folder() appends tonight's bars (and re-adjusts for
      any dividend/split) to daily_data_10y/*.csv, then the 2-year tails are
      read back from the CSVs. Falls back to path B if Marketstack errors out
      or has not published tonight's session yet.
    Path B — the old route: yfinance 2y download + write_back() merge.
    Returns (data, source) where source is "marketstack" or "yahoo"."""
    want = universe + ["SPY", "RSP"]
    use_ms = _env("EOD_PROVIDER", "").lower() == "marketstack" and not os.environ.get("STS_FORCE_YAHOO")
    if use_ms:
        try:
            from data_refresh import refresh_folder
            # open positions that came from the v2 scan have no CSV here yet — seed
            # them (25/night) so the tracker reads licensed bars instead of Yahoo
            extra = ["SPY", "RSP"]
            try:
                _tr = pd.read_csv(TRADES_CSV)
                if "close_date" in _tr.columns:
                    _tr = _tr[_tr["close_date"].isna()]
                extra += sorted({str(x).upper() for x in _tr["ticker"]} - set(universe))
            except Exception:
                pass
            rep = refresh_folder(UNIVERSE_DIR, extra=extra)
            fatal = [e for e in rep.errors if e.startswith("marketstack:")]
            exp = expected_session().isoformat()
            if fatal:
                print(f"  Marketstack refresh failed: {fatal[0]} -> falling back to Yahoo")
            elif not rep.latest_date or rep.latest_date < exp:
                print(f"  Marketstack latest session {rep.latest_date} < expected {exp} "
                      f"(not published yet?) -> falling back to Yahoo")
            else:
                data = load_from_csvs(want, UNIVERSE_DIR)
                if "SPY" in data and "RSP" in data and len(data) >= 0.9 * len(want):
                    if rep.missing:
                        print(f"  no new bar for {len(rep.missing)}: {', '.join(rep.missing[:15])}")
                    return data, "marketstack"
                print(f"  only {len(data)}/{len(want)} CSVs loaded after refresh -> falling back to Yahoo")
        except Exception as e:                       # noqa: BLE001
            print(f"  Marketstack path error: {e} -> falling back to Yahoo")
    print("  Downloading 2y daily data from Yahoo ...")
    data = fetch_batch(want)
    if data:
        print("Writing fresh bars back to CSVs ...")
        write_back(data, UNIVERSE_DIR)
    return data, "yahoo"

def write_back(data, universe_dir):
    """Merge the freshly-fetched bars into each ticker's on-disk CSV so the saved
    history stays current instead of frozen at first-download. Deep history is
    preserved (only the last ~2y get refreshed); on overlapping dates the FRESH
    (re-adjusted) values win. Non-fatal per ticker — a bad name never aborts the run."""
    cols = ["Open", "High", "Low", "Close", "Volume"]
    updated = 0
    for t, fresh in data.items():
        try:
            f = fresh.copy()
            f = f[[c for c in cols if c in f.columns]].dropna()
            if len(f) == 0:
                continue
            f.index = pd.to_datetime(f.index); f.index.name = "Date"
            path = os.path.join(universe_dir, f"{t}.csv")
            if os.path.exists(path):
                old = pd.read_csv(path, index_col=0, parse_dates=True)
                old = old[[c for c in cols if c in old.columns]]
                # True merge: fresh (re-adjusted) values win on every date Yahoo
                # returns, but a date Yahoo has STOPPED returning is kept, not
                # deleted. Yahoo drops a ticker's recent history once it stops
                # trading (LBRDA/LBRDK after the Charter merger came back with a
                # hole from Jul 20 to Aug 20), and the old code — replace the whole
                # 2y window — wiped the bars retire_lbrd.py had restored, every
                # single night. For a normally-trading ticker the result is
                # identical to before: Yahoo returns every session, so fresh wins
                # everywhere.
                merged = pd.concat([old, f]).sort_index()
                merged = merged[~merged.index.duplicated(keep="last")]
            else:
                merged = f
            merged.reset_index().rename(columns={"index": "Date"}).to_csv(path, index=False)
            updated += 1
        except Exception as e:
            print(f"  write-back {t} failed (non-fatal): {e}")
    print(f"Write-back: refreshed {updated} CSVs in {os.path.basename(universe_dir)}/ (now current)")

def send_telegram(msg, html=False):
    if not TELEGRAM_ENABLED: return
    try:
        import requests
        payload = {"chat_id": TG_CHAT, "text": msg}
        if html: payload["parse_mode"] = "HTML"
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json=payload, timeout=15)
        if html and r.status_code != 200:      # bad HTML? fall back to plain text
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": msg}, timeout=15)
        if r.status_code == 200:
            print("Telegram sent.")
        else:
            print(f"Telegram REJECTED ({r.status_code}): {r.text[:160]}")
    except Exception as e:
        print(f"Telegram failed (non-fatal): {e}")

def main():
    today = datetime.date.today()
    entry_date = (today + datetime.timedelta(days=1)).isoformat()

    universe = sorted({os.path.splitext(os.path.basename(f))[0].upper()
                       for f in glob.glob(os.path.join(UNIVERSE_DIR, "*.csv")) +
                                glob.glob(os.path.join(UNIVERSE_DIR, "*.parquet"))})
    if not universe: sys.exit(f"ERROR: no universe files in {UNIVERSE_DIR}")
    print(f"Universe: {len(universe)} tickers. Refreshing daily data ...")
    data, data_source = load_universe_data(universe)
    if "SPY" not in data or "RSP" not in data:
        sys.exit("ERROR: SPY/RSP data unavailable — cannot score. Try again.")
    print(f"Data source tonight: {data_source}; latest SPY bar {data['SPY'].index.max().date()}")

    # ── SPY regime dial — PERCENTILE version (validated in spy_regime_study.py) ──
    # "Extended" is graded against SPY's OWN trailing-3yr stretch distribution,
    # not a fixed ATR bar (the old dial sat in YELLOW 54% of all days).
    # Zones: RED = below the 200-day | GREEN = above, <50th pctile (recently
    # reset) | YELLOW = 50-90th (extended but ordinary) | ORANGE = >90th
    # (over-extended: medians are fine, but this is the only zone where the
    # bad-tail 4wk drawdowns exceeded -8% and bear markets historically began).
    # Informational context only — never an entry gate.
    spy = data["SPY"]
    spyC = spy["Close"]
    spy_csv = os.path.join(UNIVERSE_DIR, "SPY.csv")
    try:      # full history (write_back just refreshed it) for the 3yr percentile
        spy_full = pd.read_csv(spy_csv, index_col=0, parse_dates=True).sort_index()["Close"]
    except Exception:
        spy_full = spyC                      # fallback: 2y only (percentile approximate)
    _sma = spy_full.rolling(200).mean()
    _stretch = ((spy_full / _sma - 1) * 100).dropna()
    stretch_now = float(_stretch.iloc[-1])
    _win = _stretch.iloc[-757:]
    pctile = float(100 * (_win.iloc[:-1] < _win.iloc[-1]).mean()) if len(_win) > 100 else np.nan
    # old ATR number kept for continuity/comparison
    pc = spyC.shift(1)
    spy_tr = pd.concat([spy["High"] - spy["Low"], (spy["High"] - pc).abs(),
                        (spy["Low"] - pc).abs()], axis=1).max(axis=1)
    regime = float((spyC.iloc[-1] - spyC.rolling(200).mean().iloc[-1])
                   / wilders(spy_tr, 14).iloc[-1])
    if stretch_now < 0:
        zone = "RED (below 200-DMA: index unhealthy)"
    elif pctile != pctile:
        zone = "GREEN/YELLOW? (not enough history for percentile)"
    elif pctile > 90:
        zone = f"ORANGE (over-extended: {pctile:.0f}th pctile of 3yr — tail-risk zone)"
    elif pctile >= 50:
        zone = f"YELLOW (extended: {pctile:.0f}th pctile of 3yr — ordinary)"
    else:
        zone = f"GREEN (recently reset: {pctile:.0f}th pctile of 3yr)"

    rsp_mom40 = float(data["RSP"]["Close"].iloc[-1] / data["RSP"]["Close"].iloc[-41] - 1)

    print("Scoring universe ...")
    results = []
    spy_last = data["SPY"].index.max()
    stale = []
    for t in universe:
        if t in EXCLUDE or t not in data: continue
        df = data[t]
        # STALE-DATA GUARD: a ticker whose last bar is more than 5 sessions behind
        # SPY's has stopped trading (merger/delisting) or its vendor history is
        # broken. Scoring it produces nonsense — AVB on 2026-10-18 "qualified" at
        # 4.2 off a Yahoo file that ended Aug 24 with rewritten prices.
        if int(np.busday_count(df.index.max().date(), spy_last.date())) > 5:
            stale.append(t); continue
        if float(df["Close"].iloc[-1]) < MIN_PRICE: continue
        r = score_ticker(df)
        if r is None: continue
        setup, wr = classify(r["score"], r["off_high"], r["dist200_pct"], r["wash_min8w"])
        results.append(dict(ticker=t, score=r["score"],
                            rs=round(100 * (r["mom40"] - rsp_mom40), 1),
                            last=round(float(df["Close"].iloc[-1]), 2),
                            setup=setup, wr=wr, dist200_pct=r["dist200_pct"]))
    res = pd.DataFrame(results).sort_values("score", ascending=False)
    qual = res[res["score"] >= THRESHOLD]
    print(f"Scored {len(res)} tickers; {len(qual)} qualify (score >= {THRESHOLD})"
          + (f"; {len(stale)} skipped as stale/dead: {', '.join(stale[:12])}" if stale else ""))

    # ── append NEW tickers + premium RE-QUALIFICATIONS ──────────────────────
    # A ticker already in the book can re-enter ONLY if it has UPGRADED into a
    # premium setup (now D200G, or now carries a WR washout-recovery tag) that
    # its most recent prior entry did NOT have, and a cooldown has passed.
    # This catches e.g. LRCX going from stretched (D200G-by-momentum, +37% above
    # the line) to a genuine deep-discount-near-line setup weeks later.
    REQUAL_COOLDOWN_DAYS = 20   # calendar days since this ticker's last entry
    trades = pd.read_csv(TRADES_CSV) if os.path.exists(TRADES_CSV) else \
             pd.DataFrame(columns=["entry_date","ticker","shares","entry_price",
                                   "score_at_entry","rs_at_entry","notes"])
    known = set(trades["ticker"].astype(str))
    # last entry date + last setup/wr note per ticker (for upgrade detection)
    last_seen = {}
    if len(trades):
        td = trades.copy(); td["entry_date"] = pd.to_datetime(td["entry_date"], errors="coerce")
        for t, g in td.groupby("ticker"):
            g = g.sort_values("entry_date")
            last_seen[str(t)] = (g["entry_date"].iloc[-1], str(g["notes"].iloc[-1]))

    def is_premium(row):
        # a re-qual-worthy UPGRADE = a genuine NEAR-THE-LINE premium setup:
        # a washout-recovery (WR already implies near the line), or a D200G that
        # is now within +10% of its 200-day (not a stretched, run-away D200G).
        if str(row["wr"]).startswith("WR"):
            return True
        d = row.get("dist200_pct")
        return row["setup"] == "D200G" and d == d and d <= 10

    fresh, requal = [], []
    for _, row in qual.iterrows():
        t = row["ticker"]
        if t not in known:
            fresh.append(row); continue
        # already in the book — allow only a premium UPGRADE after cooldown
        if not is_premium(row): continue
        last_date, last_note = last_seen.get(t, (pd.NaT, ""))
        if pd.notna(last_date) and (pd.Timestamp(today) - last_date).days < REQUAL_COOLDOWN_DAYS:
            continue
        # only if the PRIOR entry wasn't already the same premium state
        tag = "D200G" if row["setup"] == "D200G" else str(row["wr"])
        if tag in str(last_note):
            continue
        requal.append(row)

    added_rows = []
    for row in fresh:
        added_rows.append((row, f"auto-added {today.isoformat()}"))
    for row in requal:
        tag = "D200G" if row["setup"] == "D200G" else str(row["wr"])
        added_rows.append((row, f"RE-QUAL {tag} {today.isoformat()}"))

    if added_rows:
        add = pd.DataFrame({
            "entry_date": entry_date,
            "ticker": [r["ticker"] for r, _ in added_rows],
            "shares": 1, "entry_price": "",
            "score_at_entry": [r["score"] for r, _ in added_rows],
            "rs_at_entry": [r["rs"] for r, _ in added_rows],
            "notes": [n for _, n in added_rows]})
        for col in trades.columns:
            if col not in add.columns: add[col] = ""
        trades = pd.concat([trades, add[trades.columns]], ignore_index=True)
        trades.to_csv(TRADES_CSV, index=False)
        nf = ", ".join(r["ticker"] for r, _ in added_rows if "RE-QUAL" not in _) or "none"
        nr = ", ".join(f"{r['ticker']}({('D200G' if r['setup']=='D200G' else r['wr'])})"
                       for r, _ in added_rows if "RE-QUAL" in _) or "none"
        print(f"Added — new: {nf} | re-qual: {nr}")
        new = pd.DataFrame([r for r, _ in added_rows])   # for the telegram summary
    else:
        print("No new qualifiers or re-quals today — CSV unchanged.")
        new = pd.DataFrame(columns=["ticker"])

    # rebuild tracker xlsx
    print("Updating tracker ...")
    try:
        r = subprocess.run([sys.executable, TRACKER_PY], capture_output=True, text=True, timeout=600)
        tracker_tail = "\n".join(r.stdout.strip().splitlines()[-14:])
        print(r.stdout)
    except Exception as e:
        tracker_tail = f"(tracker failed: {e})"

    # build the holy-grail workbook (adds qualgate PASS/FAIL + Scorecard/QualGate)
    print("Building holy-grail workbook ...")
    hg_status = ""
    try:
        hg = subprocess.run(
            [sys.executable, os.path.join(DIR, "build_holy_grail.py"),
             "--tracker", os.path.join(DIR, "sts_ml_paper_tracker.xlsx"),
             "--trades",  TRADES_CSV,
             "--out",     os.path.join(DIR, "STS_holy_grail.xlsx")],
            capture_output=True, text=True, timeout=1200)
        hg_status = "holy_grail OK" if hg.returncode == 0 else f"holy_grail FAILED: {hg.stderr.strip().splitlines()[-1] if hg.stderr.strip() else 'see log'}"
        print(hg.stdout)
        if hg.returncode != 0: print("HG STDERR:\n", hg.stderr)
    except Exception as e:
        hg_status = f"holy_grail error: {e}"
    print(hg_status)

    # ── telegram: NEW NAMES ONLY + SPY dial (redesigned 2026-09-30) ─────────
    # Quality gate per ticker, so the Telegram says which new names will
    # actually appear on the site. FAIL names are tracked in the book but never
    # published — on 2026-10-23 UAL/CTVA (both FAIL) were in this message while
    # the site showed only ALAB (PASS), which looked like a mismatch.
    _gate = {}
    try:
        _qg = pd.read_csv(os.path.join(DIR, "qualgate_cache.csv"))
        _gate = {str(a).upper(): str(b).upper() for a, b in zip(_qg["ticker"], _qg["gate"])}
    except Exception:
        pass
    def gate_mark(t):
        g = _gate.get(str(t).upper(), "")
        return {"PASS": "💎 published", "WATCH": "◆ published", "FAIL": "✗ gate FAIL — book only, not on site"}.get(g, "gate ? — not on site until scored")
    def tag(r):
        s = str(r["setup"]) + (f"/{r['wr']}" if str(r.get("wr","")) else "")
        return f"{r['ticker']}  ({s}  score {r['score']})  · {gate_mark(r['ticker'])}"
    freshtxt = "\n  ".join(tag(r) for r in fresh) if fresh else ""
    requaltxt = "\n  ".join(tag(r)+"  [re-qual]" for r in requal) if requal else ""

    # v2 new adds — deduped against a 30-day alert history so a name that sat
    # as "signal-tonight" for days never repeats in the message
    v2txt = ""
    tonight_univ = {r["ticker"] for r in fresh} | {r["ticker"] for r in requal}
    hist_path = os.path.join(DIR, "v2_alerted_history.csv")
    try:
        hist = {}
        if os.path.exists(hist_path):
            for ln in open(hist_path).read().splitlines():
                p = ln.split(",")
                if len(p) == 2: hist[p[0]] = p[1]
        cutoff = (pd.Timestamp(today) - pd.Timedelta(days=30))
        v2lines = open(os.path.join(DIR, "v2_new_today.txt")).read().strip().splitlines()
        v2_asof = v2lines[0].replace("asof=", "")
        names = []
        if (pd.Timestamp(today) - pd.Timestamp(v2_asof)).days <= 3:
            for ln in v2lines[1:]:
                p = ln.split(",")
                if len(p) >= 3:
                    t = p[0]
                    if t in tonight_univ:
                        continue                      # universe section already shows it
                    if t in hist and pd.Timestamp(hist[t]) >= cutoff:
                        continue                      # already alerted recently
                    names.append(f"{t}  ({p[1]}  score {p[2]})")
                    hist[t] = today
        v2txt = "\n  ".join(names)
        open(hist_path, "w").write("\n".join(f"{k},{v}" for k, v in hist.items()))
    except Exception:
        pass

    # X200-G observation signals logged tonight (x200g_observe.py runs first)
    xg = ""
    try:
        xl = pd.read_csv(os.path.join(DIR, "x200g_log.csv"))
        xl = xl[(xl["scan_date"] == today) & (xl["ticker"] != "NO SIGNAL")]
        xg = "\n  ".join(f"{r.ticker}  (gap {r.gap}%, ${r.close})" for r in xl.itertuples())
    except Exception:
        pass

    import html as _html
    dial_icon = {"R": "🔴", "O": "🟠", "Y": "🟡", "G": "🟢"}.get(zone[0], "⚪")
    esc = _html.escape
    sections = []
    if freshtxt:  sections.append(f"🆕 <b>New — universe</b>\n  {esc(freshtxt)}")
    if requaltxt: sections.append(f"🔁 <b>Re-qualified</b>\n  {esc(requaltxt)}")
    if v2txt:     sections.append(f"🌐 <b>New — v2 only</b> (not in universe)\n  {esc(v2txt)}")
    if xg:        sections.append(f"👁 <b>X200-G</b> (observation only)\n  {esc(xg)}")
    body = "\n\n".join(sections) if sections else "No new names tonight."
    msg = (f"🌙 <b>STS — {today.isoformat()}</b>\n"
           f"{dial_icon} {esc(zone)}\n"
           f"     stretch {stretch_now:+.1f}% vs 200d  ·  ATR {regime:+.1f}\n"
           f"\n{body}")
    if "OK" not in hg_status:
        msg += f"\n\n⚠️ {esc(hg_status)}"
    _src = {"marketstack": "data: Marketstack", "yahoo": "data: Yahoo (fallback)"}[data_source]
    msg += f"\n\n<i>{_src} · bars through {data['SPY'].index.max().date()}</i>"
    if data_source == "yahoo":
        msg = msg.replace("🌙 <b>STS", "🌙⚠️ <b>STS", 1)
    send_telegram(msg, html=True)
    print("\nDone.")

if __name__ == "__main__":
    main()
