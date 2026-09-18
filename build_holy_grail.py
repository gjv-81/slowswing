#!/usr/bin/env python3
"""
build_holy_grail.py — one Excel workbook to rule them all.

Reads your STS paper tracker (.xlsx) and paper-trades (.csv), runs the qualgate
quality/safety gate over every ticker (cached), and writes ONE workbook with:

  * "Tracker"  — a faithful copy of your tracker sheet, with a `qualgate`
                 PASS/FAIL column inserted immediately to the RIGHT of ticker.
                 The insert is region-aware: only the positions table is shifted,
                 so the summary block and the column legend stay aligned.
  * "QualGate" — full per-ticker breakdown (gate, profile tag, score, the six
                 factors, and veto reasons), sorted best-to-worst.
  * "Trades"   — your paper-trades CSV with the gate columns appended.

It is NON-DESTRUCTIVE: it never touches your tracker file, it writes a brand-new
workbook. So it's safe to run right after your 7:50pm tracker job regenerates the
source file (schedule it at, say, 7:55pm — see README).

Usage:
    python build_holy_grail.py --tracker sts_ml_paper_tracker.xlsx \
                               --trades sts_ml_paper_trades.csv \
                               --out STS_holy_grail.xlsx
    python build_holy_grail.py --tracker t.xlsx --no-refresh     # use cache as-is
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import datetime as dt

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

import qualgate as qg
import enrich_trades as et

# gate -> fill colour
FILLS = {
    "PASS":  PatternFill("solid", fgColor="C6EFCE"),
    "WATCH": PatternFill("solid", fgColor="FFEB9C"),
    "FAIL":  PatternFill("solid", fgColor="FFC7CE"),
    "ERROR": PatternFill("solid", fgColor="D9D9D9"),
}
HDR_FILL = PatternFill("solid", fgColor="1F4E78")
HDR_FONT = Font(bold=True, color="FFFFFF")
BOLD = Font(bold=True)


def gate_fill(gate):
    return FILLS.get((gate or "").split("/")[0], None)


# ---------------------------------------------------------------------------
# read tracker
# ---------------------------------------------------------------------------

def read_tracker(path):
    """Return (all_rows_as_values, header_row_idx, ticker_col_idx0, last_data_row_idx).
    Row/col indices are 1-based for rows, 0-based for the ticker column."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    header = tkr_col = None
    for i, r in enumerate(rows, start=1):
        cells = [str(c).strip().lower() if c is not None else "" for c in r]
        if "ticker" in cells and ("entry_date" in cells or "symbol" in cells or "entry" in cells):
            header = i
            tkr_col = cells.index("ticker")
            break
    if header is None:
        raise SystemExit("Could not find a positions header row containing 'ticker' in the tracker.")
    last = header
    for i in range(header + 1, len(rows) + 1):
        b = rows[i - 1][tkr_col] if tkr_col < len(rows[i - 1]) else None
        if isinstance(b, str) and b.strip() and b.strip().replace(".", "").isalnum() and len(b.strip()) <= 6:
            last = i
        else:
            break
    return rows, header, tkr_col, last


def tracker_tickers(rows, header, tkr_col, last):
    out = []
    for i in range(header + 1, last + 1):
        v = rows[i - 1][tkr_col]
        if isinstance(v, str) and v.strip():
            out.append(v.strip().upper())
    return out


# ---------------------------------------------------------------------------
# refresh scores through the cache
# ---------------------------------------------------------------------------

def refresh(tickers, cache_path, source, max_age_days, do_refresh):
    cache = et.load_cache(cache_path)
    scored = skipped = errored = 0
    for sym in sorted(set(tickers)):
        if sym in cache and et.is_fresh(cache[sym], max_age_days):
            skipped += 1
            continue
        if not do_refresh:
            skipped += 1
            continue
        try:
            cache[sym] = et.score_ticker(sym, source, qg.PASS_THRESHOLD, qg.WATCH_THRESHOLD)
            scored += 1
            print(f"  scored {sym:6} -> {cache[sym]['gate']:5} {cache[sym]['score']}")
        except Exception as e:
            errored += 1
            cache[sym] = {"ticker": sym, "gate": "ERROR", "tag": "ERROR", "score": "",
                          "asof": dt.date.today().isoformat(), "vetoes": str(e)[:120]}
            print(f"  ERROR  {sym:6} -> {e}", file=sys.stderr)
    if do_refresh:
        et.save_cache(cache_path, cache)
    print(f"  refresh: {scored} scored, {skipped} cached/skipped, {errored} errors")
    return cache


# ---------------------------------------------------------------------------
# build workbook
# ---------------------------------------------------------------------------

def _style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = Alignment(vertical="center")


def build_legend_sheet(wb):
    """Setup-code cheat sheet — first tab, so the codes are always one click away."""
    ws = wb.create_sheet("Legend")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 9    # code
    ws.column_dimensions["B"].width = 70   # meaning
    ws.column_dimensions["C"].width = 24   # research
    ws.column_dimensions["D"].width = 30   # how to trade
    ARIAL = "Arial"
    DARK = "1F3864"; GOLD = "FFF2CC"; GRAY = "EDEDED"

    def cell(r, cidx, val, *, bold=False, size=10, italic=False,
             color="000000", fill=None, wrap=True, valign="top"):
        c = ws.cell(row=r, column=cidx, value=val)
        c.font = Font(name=ARIAL, size=size, bold=bold, italic=italic, color=color)
        c.alignment = Alignment(wrap_text=wrap, vertical=valign)
        if fill:
            c.fill = PatternFill("solid", fgColor=fill)
        return c

    # title (merged, single line, normal height)
    ws.merge_cells("A1:D1")
    cell(1, 1, "STS SETUP CODES — the recovery ladder", bold=True, size=14, wrap=False)
    ws.row_dimensions[1].height = 24
    ws.merge_cells("A2:D2")
    cell(2, 1, "Weakest evidence  →  strongest:    LB  →  DLB  →  X200  →  D200  →  D200G",
         bold=True, size=11, wrap=False)
    ws.row_dimensions[2].height = 20

    # header row (dark bg, white text)
    hdr = 4
    for cidx, h in enumerate(["CODE", "MEANING", "RESEARCH (12wk, no-stop)", "HOW TO TRADE"], 1):
        cell(hdr, cidx, h, bold=True, color="FFFFFF", fill=DARK)
    ws.row_dimensions[hdr].height = 20

    rows = [
        ("D200G", "Deep + above the 200-day SMA + score ≥ 2.  (Deep = 25%+ below the 52-week high.)  The best cell.", "+16.2% avg", "TRADE FIRST — front of the SSI2 queue.", GOLD, 42),
        ("D200",  "Deep + above the 200-day SMA (score not required).  Recovery structurally confirmed; catches sprint-recoveries the score misses (UNH in May).", "+14.0% avg", "Trade second.", GOLD, 56),
        ("B2",    "BREATHER: score ≥ 2 + 10–25% below the high.  The 'up 8 weeks, soft 4 weeks' pullback, measured by depth.", "+14.1% avg  (best excess)", "Trade. Best form: RS+ green but cooling.", None, 42),
        ("G2",    "The whole score ≥ 2 green bucket, any depth (the nightly candidate list).", "+13.1% avg", "The candidate universe.", None, 30),
        ("S2",    "SPRINTER: score ≥ 2 + within 10% of the high (momentum type, hasn't pulled back yet).", "+11.3% avg", "Valid, but LAST in line.", None, 30),
        ("X200",  "Day one of D200: a deep stock FRESHLY crossing above its 200-day SMA.", "+10.5% avg  (weaker than the settled state)", "No urgency — it ripens into D200. Never chase the cross.", GRAY, 42),
        ("DLB",   "Deep + BELOW the 200-day SMA + score ≥ 2.  D = Deep, LB = Lane B (below the 200).  The 'score-qualified crash' — model likes it, trend not yet reclaimed.  Riskiest score ≥ 2 cell.", "+12.2% avg  (broken-trend risk)", "Only with a PASS gate, small size. Never FAIL/SPEC.", GRAY, 56),
        ("LB",    "LANE B: crashed AND below the 200-day, score gray (< 2).  No systematic signal — technicals proven useless here.", "n/a  (thesis only)", "SSI2 ONLY. Small size (UNH at $287).", GRAY, 42),
    ]
    r = hdr + 1
    for code, mean, res, act, fill, ht in rows:
        cell(r, 1, code, bold=True, size=11, fill=fill, wrap=False, valign="center")
        cell(r, 2, mean, fill=fill)
        cell(r, 3, res, fill=fill)
        cell(r, 4, act, fill=fill)
        ws.row_dimensions[r].height = ht
        r += 1

    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    cell(r, 1, "MODIFIERS  (describe a name alongside its code)", bold=True, size=11, wrap=False)
    ws.row_dimensions[r].height = 20
    r += 1
    for m, d, ht in [
        ("RS+",      "RSvs column green = leading the market. NOT an entry rule (tested: adds nothing) — it's a tie-break between similar scores and the leader-picker within a sector cluster.", 42),
        ("RING",     "GREEN = cap ≥ $10B, price ≥ $15, $70M/day, listed 3yr+ (full trust). AMBER = $3–10B or 1–3yr (half size). RED = below (formula only, no evidence).", 42),
        ("DIAL",     "SPY stretch PERCENTILE vs its own trailing 3yr (replaces the old ATR dial, which sat in YELLOW 54% of days).  RED = below the 200-day | GREEN = above + <50th pctile (recently reset) | YELLOW = 50-90th (extended but ordinary) | ORANGE = >90th (over-extended: the only zone where bad-tail 4wk drawdowns exceeded -8% and bear markets began).  Informational context, never a veto.", 42),
        ("QUALGATE", "Fundamental safety gate (PASS / WATCH / FAIL). Not a return booster — it thins the value-trap / blow-up tail. Matters most inside DLB.", 42),
    ]:
        cell(r, 1, m, bold=True, wrap=False, valign="center")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        cell(r, 2, d)
        ws.row_dimensions[r].height = ht
        r += 1

    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    cell(r, 1, 'Say a stock in one breath:  "MU = D200G, RS+, green ring, orange dial."   '
               "All codes share the same hold rules: 4–5% size · no stops (catastrophe −40% only) · "
               "no profit targets · hold 12–24 weeks · score decay while winning = success.   "
               "The 200-day is a SIMPLE moving average, no displacement.",
         italic=True, size=9, color=DARK)
    ws.row_dimensions[r].height = 46
    # no freeze pane — this sheet is short and static
    return ws


def build_tracker_sheet(wb, rows, header, tkr_col, last, cache):
    ws = wb.create_sheet("Tracker")
    ins_at = tkr_col + 1                       # 0-based position of the new column

    # split the source into three regions (header/last are 1-based)
    pre  = rows[:header - 1]    # summary + score-bucket + setup mini-tables
    pos  = rows[header - 1:last]  # positions header row + all data rows
    post = rows[last:]         # column legend

    def emit(src, is_positions, start_row):
        """Write src rows starting at start_row; return next free row + header row."""
        r = start_row
        hdr_row = None
        for k, row in enumerate(src):
            is_hdr  = is_positions and k == 0
            is_data = is_positions and k > 0
            if is_hdr or is_data:
                c = cache.get(str(row[tkr_col]).strip().upper(), {})
                gate_val = "qualgate" if is_hdr else (c.get("tag") or c.get("gate", ""))
                newrow = list(row[:ins_at]) + [gate_val] + list(row[ins_at:])
            else:
                newrow = list(row)
            for j, val in enumerate(newrow, start=1):
                cell = ws.cell(row=r, column=j, value=val)
                if isinstance(val, dt.datetime):
                    cell.number_format = "yyyy-mm-dd"
            if is_data:
                gcell = ws.cell(row=r, column=ins_at + 1)
                f = gate_fill(gcell.value)
                if f:
                    gcell.fill = f
                    gcell.font = BOLD
            if is_hdr:
                hdr_row = r
            r += 1
        return r, hdr_row

    r = 1
    r, pos_hdr = emit(pos, True, r)   # positions table AT THE TOP
    r += 1                            # spacer row
    r, _ = emit(pre, False, r)        # summary / buckets / setups below
    r += 1                            # spacer row
    r, _ = emit(post, False, r)       # legend at the very bottom

    ncols = max(len(rr) for rr in rows) + 1
    if pos_hdr:
        _style_header(ws, pos_hdr, ncols)
    # freeze ONLY the positions header row (row 1) so scrolling is easy
    ws.column_dimensions[get_column_letter(1)].width = 13           # entry_date
    ws.column_dimensions[get_column_letter(2)].width = 10           # ticker
    ws.column_dimensions[get_column_letter(ins_at + 1)].width = 12  # qualgate
    return ws


DETAIL_COLS = [
    ("ticker", "ticker"), ("gate", "gate"), ("tag", "tag"), ("profile", "profile"),
    ("score", "score"), ("gross_profitability", "gross_prof"), ("f_score", "F"),
    ("altman_z", "altman_z"), ("fcf_yield_pct", "fcf_yield%"), ("interest_cov", "int_cov"),
    ("debt_to_equity", "debt/eq"), ("op_margin_ttm", "op_margin%"), ("sector", "sector"),
    ("profile_note", "profile_note"), ("vetoes", "vetoes"),
]


def build_qualgate_sheet(wb, cache):
    ws = wb.create_sheet("QualGate")
    ws.append([label for _, label in DETAIL_COLS])
    _style_header(ws, 1, len(DETAIL_COLS))
    def sort_key(t):
        try:
            return -float(cache[t].get("score") or -999)
        except ValueError:
            return 1e9
    for t in sorted(cache, key=sort_key):
        r = cache[t]
        ws.append([r.get(key, "") for key, _ in DETAIL_COLS])
        gcell = ws.cell(row=ws.max_row, column=2)   # gate col
        f = gate_fill(gcell.value)
        if f:
            gcell.fill = f
            gcell.font = BOLD
    for col, w in {"A": 9, "B": 8, "C": 10, "D": 12, "E": 7, "O": 60, "N": 26, "M": 20}.items():
        ws.column_dimensions[col].width = w
    return ws


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2, 2)


def _pct(cond_list):
    xs = [c for c in cond_list if c is not None]
    return round(100 * sum(1 for c in xs if c) / len(xs), 1) if xs else None


SCORE_COLS = ["bucket", "n", "n_with_ret", "avg_ret%", "med_ret%", "win%",
              "avg_excess%", "avg_MAE%", "worst_MAE%", "deep_DD%(MAE<=-20)",
              "avg_MFE%", "n_wk12", "avg_wk12%"]


def _bucket_stats(name, recs):
    rets = [r["ret"] for r in recs]
    return {
        "bucket": name,
        "n": len(recs),
        "n_with_ret": len([r for r in recs if r["ret"] is not None]),
        "avg_ret%": _mean(rets),
        "med_ret%": _median(rets),
        "win%": _pct([(r["ret"] > 0) if r["ret"] is not None else None for r in recs]),
        "avg_excess%": _mean([r["exc"] for r in recs]),
        "avg_MAE%": _mean([r["mae"] for r in recs]),
        "worst_MAE%": min([r["mae"] for r in recs if r["mae"] is not None], default=None),
        "deep_DD%(MAE<=-20)": _pct([(r["mae"] <= -20) if r["mae"] is not None else None for r in recs]),
        "avg_MFE%": _mean([r["mfe"] for r in recs]),
        "n_wk12": len([r for r in recs if r["wk12"] is not None]),
        "avg_wk12%": _mean([r["wk12"] for r in recs]),
    }


def build_scorecard_sheet(wb, rows, header, tkr_col, last, cache):
    """Group tracker positions by gate and compare risk/return — does the gate work?"""
    hdr = rows[header - 1]
    colmap = {str(n).strip().lower(): i for i, n in enumerate(hdr) if isinstance(n, str)}

    def val(r, name):
        i = colmap.get(name)
        return _num(r[i]) if (i is not None and i < len(r)) else None

    buckets = {"PASS": [], "WATCH": [], "FAIL": []}
    for i in range(header + 1, last + 1):
        r = rows[i - 1]
        tk = str(r[tkr_col]).strip().upper() if r[tkr_col] else None
        if not tk:
            continue
        gate = (cache.get(tk, {}).get("gate") or "").split("/")[0]
        if gate not in buckets:
            continue
        buckets[gate].append({"ret": val(r, "ret_pct"), "exc": val(r, "excess_pct"),
                              "mae": val(r, "mae_pct"), "mfe": val(r, "mfe_pct"),
                              "wk12": val(r, "wk12_ret_pct")})

    ws = wb.create_sheet("Scorecard")
    ws.append(["Does the gate work? Positions grouped by qualgate. "
               "The gate targets DRAWDOWN/BLOW-UP risk, so watch avg_MAE%, worst_MAE% and deep_DD% first."])
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws.append([])
    ws.append(SCORE_COLS)
    _style_header(ws, 3, len(SCORE_COLS))
    order = ["PASS", "WATCH", "FAIL"]
    allrecs = [x for b in order for x in buckets[b]]
    for name in order:
        st = _bucket_stats(name, buckets[name])
        ws.append([st[c] for c in SCORE_COLS])
        f = gate_fill(name)
        if f:
            ws.cell(row=ws.max_row, column=1).fill = f
            ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.append(_row_from(_bucket_stats("ALL", allrecs)))

    # headline comparison
    p = _bucket_stats("PASS", buckets["PASS"])
    fl = _bucket_stats("FAIL", buckets["FAIL"])
    ws.append([])
    def cmp(label, key, better_low=True):
        pv, fv = p[key], fl[key]
        if pv is None or fv is None:
            return f"{label}: n/a (need more closed data)"
        if abs(pv - fv) < 0.3:
            side = "~tie"
        else:
            pass_better = (pv < fv) if better_low else (pv > fv)
            side = "PASS better" if pass_better else "FAIL better"
        return f"{label}: PASS {pv} vs FAIL {fv}  ->  {side}"
    ws.append(["HEADLINE (directional only — sample too young to conclude):"])
    ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.append([cmp("Avg drawdown (MAE%, less-negative is better)", "avg_MAE%", better_low=False)])
    ws.append([cmp("Deep-drawdown rate (MAE<=-20%)", "deep_DD%(MAE<=-20)", better_low=True)])
    ws.append([cmp("Avg return %", "avg_ret%", better_low=False)])
    ws.append([cmp("Win rate %", "win%", better_low=False)])

    # caveats
    ws.append([])
    for c in [
        "Caveats:",
        "1) Sample is young — treat as directional, not proof. Your tracker needs ~100 twelve-week checkpoints before conclusions.",
        "2) Mild look-ahead: qualgate uses CURRENT fundamentals, not fundamentals as of each entry date. Fine for recent entries; grows with position age.",
        "3) The gate is a SAFETY filter, not a return predictor. Success = shallower drawdowns and fewer blow-ups in PASS, more than higher raw return.",
        "4) MAE = Max Adverse Excursion (worst dip vs entry). wk12 columns fill only after 60 trading days.",
    ]:
        ws.append([c])
        ws.cell(row=ws.max_row, column=1).font = Font(italic=True, size=9)
    ws.column_dimensions["A"].width = 22
    for col in "BCDEFGHIJKLM":
        ws.column_dimensions[col].width = 12
    return ws


def _row_from(st):
    return [st[c] for c in SCORE_COLS]


def build_trades_sheet(wb, trades_csv, cache):
    if not trades_csv or not os.path.exists(trades_csv):
        return None
    rows = list(csv.DictReader(open(trades_csv)))
    if not rows:
        return None
    rows = rows[::-1]          # CSV is append-order (oldest first) -> show NEWEST on top
    ws = wb.create_sheet("Trades")
    base = list(rows[0].keys())
    tcol = "ticker" if "ticker" in base else base[0]
    extra = ["qualgate", "qualgate_tag", "qualgate_profile", "qualgate_score"]
    header = base + [c for c in extra if c not in base]
    ws.append(header)
    _style_header(ws, 1, len(header))
    for r in rows:
        c = cache.get(str(r[tcol]).strip().upper(), {})
        r = dict(r)
        r["qualgate"] = c.get("gate", "")
        r["qualgate_tag"] = c.get("tag", "")
        r["qualgate_profile"] = c.get("profile", "")
        r["qualgate_score"] = c.get("score", "")
        ws.append([r.get(k, "") for k in header])
        # colour the qualgate cell
        gi = header.index("qualgate") + 1
        gcell = ws.cell(row=ws.max_row, column=gi)
        f = gate_fill(gcell.value)
        if f:
            gcell.fill = f
    return ws


def main(argv=None):
    ap = argparse.ArgumentParser(description="Consolidate STS tracker + trades + qualgate into one workbook.")
    ap.add_argument("--tracker", required=True, help="STS paper tracker .xlsx (from your 7:50pm job)")
    ap.add_argument("--trades", help="paper-trades .csv (optional extra sheet)")
    ap.add_argument("--out", default="STS_holy_grail.xlsx")
    ap.add_argument("--cache", default="qualgate_cache.csv")
    ap.add_argument("--source", default="yfinance", choices=["yfinance", "mock"])
    ap.add_argument("--max-age-days", type=int, default=30)
    ap.add_argument("--no-refresh", action="store_true", help="use the cache as-is, don't call yfinance")
    ap.add_argument("--no-archive", action="store_true",
                    help="don't also write a dated snapshot into ./holy_grail_archive/")
    args = ap.parse_args(argv)

    rows, header, tkr_col, last = read_tracker(args.tracker)
    tks = tracker_tickers(rows, header, tkr_col, last)
    trade_tks = []
    if args.trades and os.path.exists(args.trades):
        trade_tks = [r["ticker"].strip().upper() for r in csv.DictReader(open(args.trades))
                     if r.get("ticker", "").strip()]
    print(f"  tracker positions: {len(tks)} rows, {len(set(tks))} distinct tickers")

    cache = refresh(list(tks) + trade_tks, args.cache, args.source,
                    args.max_age_days, not args.no_refresh)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    build_legend_sheet(wb)
    build_tracker_sheet(wb, rows, header, tkr_col, last, cache)
    build_scorecard_sheet(wb, rows, header, tkr_col, last, cache)
    build_qualgate_sheet(wb, cache)
    build_trades_sheet(wb, args.trades, cache)

    # Atomic write: build to a temp file, then replace the target in one step.
    # This way, if the workbook is open in Excel, the on-disk file is either the
    # old one or the complete new one — never a half-written file — and the write
    # doesn't fail just because Excel holds a handle.
    tmp = args.out + ".tmp"
    wb.save(tmp)
    os.replace(tmp, args.out)

    # Dated snapshot: a copy Excel is never holding open, so you always have the
    # day's file even if STS_holy_grail.xlsx is open (and can't get clobbered by
    # an Excel re-save). Disable with --no-archive.
    dated = None
    if not args.no_archive:
        outdir = os.path.dirname(os.path.abspath(args.out)) or "."
        adir = os.path.join(outdir, "holy_grail_archive")
        os.makedirs(adir, exist_ok=True)
        base = os.path.splitext(os.path.basename(args.out))[0]
        dated = os.path.join(adir, f"{base}_{dt.date.today().isoformat()}.xlsx")
        shutil.copyfile(args.out, dated)

    # summary
    gates = [cache[t].get("gate") for t in set(tks) if t in cache]
    dist = {g: gates.count(g) for g in ("PASS", "WATCH", "FAIL", "ERROR")}
    print(f"  tracker gate split: {dist}")
    print(f"  wrote {args.out}  (sheets: {wb.sheetnames})")
    if dated:
        print(f"  dated snapshot: {dated}")


if __name__ == "__main__":
    main()
