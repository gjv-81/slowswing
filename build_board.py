"""
build_board.py — turn STS pipeline picks + fresh prices into board.json.

WHERE THIS SITS
---------------
    sts_ml_evening.py  ->  STS_holy_grail.xlsx   (Tracker sheet = live positions)
                                   |
    eod_adapter.get_eod_many() ->  |  refresh current price (pc)
                                   v
                             build_board.py   (this file)
                                   |  map codes -> board fields, strip secrets, guard freshness
                                   v
                              board.json   ->  static site reads it from a CDN

INPUT PRIORITY (first that exists wins):
  1. STS_holy_grail.xlsx  — the real pipeline output (Tracker + QualGate sheets).
     Override the path with env STS_XLSX=/path/to/STS_holy_grail.xlsx
  2. board_input.json     — a hand/JSON feed (see board_input.example.json)
  3. built-in SEED        — 3 fake names, so this always runs even with nothing set.

WHAT COMES FROM WHERE
  From the Tracker sheet (per OPEN position):
    ticker->t   setup->setup(branded)   qualgate->q   score_at_entry->score
    rs_at_entry->rs(graded)   entry_date->date   entry->pe   mfe_pct->mfe   mae_pct->mae
  From the QualGate sheet: sector, profile.
  From the adapter (live): pc (current price).
  Dropped at the boundary: dist200_pct, wash_min8w, sma200_at_entry, and everything
  else not on PUBLIC_FIELDS — the site can never see the recipe.
  NOTE: `dtp` (days-to-peak) is not emitted yet — it's the one pipeline addition
  your handoff flagged as still to build.

SAFETY
  - Freshness guard: any price whose bar date != the expected session is "stale".
    If too many are stale, WRITE NOTHING and keep yesterday's board.json.
  - Atomic write: temp file + rename, so a crash never leaves a half-written board.

RUN
    python3 build_board.py                              # real xlsx + .env vendor
    BOARD_SESSION=2026-08-20 python3 build_board.py     # force the trading day
    EOD_PROVIDER=mock BOARD_SESSION=2026-08-20 python3 build_board.py   # dry run, no key
"""

from __future__ import annotations

import os
import re
import sys
import json
import tempfile
import datetime as dt
from pathlib import Path

from eod_adapter import get_eod_many, EODError

try:
    from zoneinfo import ZoneInfo
    _EASTERN = ZoneInfo("America/New_York")
except Exception:                       # pragma: no cover
    _EASTERN = None


# --------------------------------------------------------------------------- #
#  Config                                                                       #
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
STS_XLSX = Path(os.environ.get("STS_XLSX", HERE / "STS_holy_grail.xlsx"))
INPUT_PATH = HERE / "board_input.json"
NAMES_PATH = HERE / "names.json"              # optional {ticker: "Company Name"}; build with fetch_names.py
OUTPUT_PATH = HERE / "board.json"

# Which positions make the public board:
PHASE_INCLUDE = {"Active", "Extended", "Retired"}  # lifecycle phases from the pipeline's `phase` column
INCLUDE_QUALGATES = {"PASS", "WATCH", "FAIL"} # show the full book (all tiers). Narrow to {"PASS","WATCH"} to hide FAIL.
DEDUPE_TICKERS = True                          # one row per ticker (a ticker can be entered twice: original + re-qual)
DEDUPE_KEEP = "recent"                         # which entry wins: "recent" (freshest) | "score" (strongest) | "first" (original)

EXTENDED_THRESHOLD = 0.05                     # >+5% past entry => "extended" board
STALE_ABORT_RATIO = 0.34                      # abort if >34% of names have a stale price
REGIME_TICKERS = ("SPY", "QQQ")

# Setup-code -> branded label the site shows (mechanics hidden).
# Recovery ladder: LB -> DLB -> X200 -> D200 -> D200G (deep-recovery = "phoenix").
# Shallow pullbacks near the highs (B2 / S2) read as an uptrend breather = "cruise".
# The two published setups, by pipeline code. ONLY these reach the site.
#   Phoenix = D200G (deep markdown, above the 200-day, score-qualified) + DLB
#             (deep, below the 200-day, score-qualified)
#   Cruise  = B2 (breather: score-qualified, 10-25% below the high)
# S2 (sprinter, <=10% below the high) was the weakest cell in the backtest and
# in the forward book, and was never meant to be a product setup; it stays in
# the tracker for research but is not published. Unclassified codes ("young",
# "-") are held back until the pipeline classifies them — they used to fall
# through to Phoenix by default. (Decision: GJ, 2026-09-16.)
PHOENIX_CODES = {"D200G", "DLB"}
CRUISE_CODES = {"B2"}

# RS grading (rs_at_entry ~ 40-day relative strength vs equal-weight, in points).
RS_STRONG, RS_WEAK = 5.0, -5.0

# The ONLY per-name fields allowed out to the site. Secret-by-default: anything
# not listed here is dropped, so a new proprietary column can never leak.
# This list == the fields sts_site_mockup.html reads. `chg` is derived (pc vs pe).
# `dtp` (days-to-peak) is emitted only once the pipeline logs it.
# Dollar prices are NOT emitted. The market-data vendor licenses its EOD data for
# internal company use only and sells no display licence at any tier, so a price
# shown to a subscriber is a price shown to a third party. Percentages are ours —
# computed from their data, not a copy of it — and `chg` alone reconstructs
# nothing without a price the reader has to go and find somewhere else.
# Set EMIT_PRICES = True only if a display licence is ever obtained in writing.
EMIT_PRICES = False
_PRICE_FIELDS = ["pe", "pc"]

PUBLIC_FIELDS = [
    "t", "n", "setup", "phase", "score", "q", "profile", "sector",
    "rs", "rsn", "date", "dial", "chg",
    "wk2", "wk4", "wk12", "mfe", "mae", "md4", "dtp", "d5", "d10",
] + (_PRICE_FIELDS if EMIT_PRICES else [])

_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,5}$")

SEED_INPUT = [
    {"t": "NVDA", "n": "NVIDIA", "setup": "cruise", "score": 16, "q": "pass",
     "profile": "Core", "sector": "Semis", "rs": "strong", "date": "2026-08-18",
     "pe": 210.0, "mfe": 7.2, "mae": -2.1,
     "sma200": 150.2, "dist200": 0.41, "wash_min8w": 1, "depth": 0.12},
]


# --------------------------------------------------------------------------- #
#  Small mappers / coercers                                                     #
# --------------------------------------------------------------------------- #
def _num(v):
    try:
        f = float(v)
        return None if f != f else round(f, 4)   # drop NaN
    except (TypeError, ValueError):
        return None


def _date(v, default: str) -> str:
    s = str(v)[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else default


def fmt_date(v, default: str = "") -> str:
    """ISO date -> "Aug 17" to match the site's display. Pass-through if already short."""
    s = str(v)[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        d = dt.date.fromisoformat(s)
        return f"{d:%b} {d.day}"
    return str(v) if v not in (None, "nan") else default


_NAMES: dict | None = None
_SUFFIX_RE = re.compile(
    r",?\s+(?:Inc\.?|Incorporated|Corp\.?|Corporation|Company|Co\.?|plc|PLC|"
    r"N\.V\.|S\.A\.|Ltd\.?|Limited|AG|SE)$", re.IGNORECASE)


def clean_name(nm: str) -> str:
    """Trim legal suffixes for a cleaner board: 'Ciena Corporation' -> 'Ciena'."""
    prev = None
    while nm and nm != prev:
        prev = nm
        nm = _SUFFIX_RE.sub("", nm).strip().rstrip(",").strip()
    return nm or prev or ""


def company_name(t: str) -> str:
    """Look up a friendly name from names.json (suffixes trimmed); fall back to the ticker."""
    global _NAMES
    if _NAMES is None:
        try:
            _NAMES = {k.upper(): v for k, v in json.loads(NAMES_PATH.read_text()).items()} \
                     if NAMES_PATH.is_file() else {}
        except Exception:
            _NAMES = {}
    raw = _NAMES.get(t.upper())
    if not raw:
        return t.upper()
    cleaned = clean_name(raw)
    # if trimming collapses to just the ticker (e.g. "APA Corporation"->"APA"), keep the fuller name
    return cleaned if cleaned and cleaned.upper() != t.upper() else raw


def brand_setup(code: str, wr: str = "") -> str:
    code = (code or "").upper().strip()
    if code in CRUISE_CODES:
        return "cruise"
    if code in PHOENIX_CODES:
        return "phoenix"
    raise ValueError(f"unpublishable setup code reached brand_setup: {code!r}")


def grade_rs(v) -> str:
    v = _num(v)
    if v is None:
        return "neutral"
    if v >= RS_STRONG:
        return "strong"
    if v <= RS_WEAK:
        return "weak"
    return "neutral"


def grade_q(qualgate: str) -> str:
    # "PASS/GS" / "WATCH/GS" / "FAIL/LEV" -> "pass"/"watch"/"fail"
    return str(qualgate).split("/")[0].strip().lower()


def map_dial(v) -> str | None:
    # SPY regime dial frozen AT ENTRY (percentile 4-zone, matches the header bar):
    #   R -> Weak | G -> Healthy | Y -> Extended | O -> Over-extended
    if v is None:
        return None
    return {"R": "Weak", "RED": "Weak", "WEAK": "Weak",
            "G": "Healthy", "GREEN": "Healthy", "HEALTHY": "Healthy",
            "Y": "Extended", "YELLOW": "Extended", "EXTENDED": "Extended",
            "O": "Over-extended", "ORANGE": "Over-extended",
            "OVER-EXTENDED": "Over-extended"}.get(str(v).strip().upper())


# --------------------------------------------------------------------------- #
#  Input loaders                                                                #
# --------------------------------------------------------------------------- #
def rows_from_workbook(path: Path) -> list[dict]:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("Reading the xlsx needs pandas + openpyxl:  pip install pandas openpyxl")

    xl = pd.ExcelFile(path)
    tr = xl.parse("Tracker")

    # The Tracker sheet has trailing summary rows — keep only real position rows,
    # filtered to the lifecycle phases (this also drops the summary/junk rows).
    tr = tr[tr["ticker"].astype(str).str.match(_TICKER_RE)]
    tr = tr.assign(_score=pd.to_numeric(tr["score_at_entry"], errors="coerce"))
    tr = tr[tr["_score"].notna()]
    tr = tr.assign(_phase=tr["phase"].astype(str).str.strip().str.capitalize())
    tr = tr[tr["_phase"].isin(PHASE_INCLUDE)]
    _code = tr["setup"].astype(str).str.upper().str.strip()
    _drop = tr[~_code.isin(PHOENIX_CODES | CRUISE_CODES)]
    if len(_drop):
        print(f"# setup gate: {len(_drop)} rows not published "
              f"({', '.join(f'{k}={v}' for k, v in _drop['setup'].astype(str).value_counts().items())})")
    tr = tr[_code.isin(PHOENIX_CODES | CRUISE_CODES)]
    tr = tr.assign(_q=tr["qualgate"].map(grade_q))
    tr = tr[tr["_q"].str.upper().isin(INCLUDE_QUALGATES)]

    # Dedup ONLY the live buy-board (Active/Extended) to one row per ticker; keep
    # EVERY Retired trade — the honest track record needs the full history, including
    # a ticker that later re-qualified into a new Active signal.
    if DEDUPE_TICKERS and len(tr):
        tr = tr.assign(_ed=pd.to_datetime(tr["entry_date"], errors="coerce"))
        live = tr[tr["_phase"] != "Retired"]
        retired = tr[tr["_phase"] == "Retired"]
        keep = "first" if DEDUPE_KEEP == "first" else "last"
        sort_cols = (["_ed"] if DEDUPE_KEEP == "first"
                     else ["_score", "_ed"] if DEDUPE_KEEP == "score"
                     else ["_ed", "_score"])
        live = live.sort_values(sort_cols).drop_duplicates("ticker", keep=keep)
        tr = pd.concat([live, retired], ignore_index=True)

    # QualGate sheet -> sector / profile per ticker.
    secmap: dict[str, dict] = {}
    try:
        qg = xl.parse("QualGate")
        qg = qg[qg["ticker"].astype(str).str.match(_TICKER_RE)]
        for _, g in qg.iterrows():
            secmap[str(g["ticker"]).upper()] = {
                "sector": (str(g.get("sector")).strip() or None) if g.get("sector") == g.get("sector") else None,
                "profile": (str(g.get("profile")).strip().title() or None) if g.get("profile") == g.get("profile") else None,
            }
    except Exception:
        pass

    rows = []
    for _, r in tr.iterrows():
        t = str(r["ticker"]).upper()
        meta = secmap.get(t, {})
        rows.append({
            "t": t,
            "n": company_name(t),                     # names.json lookup, falls back to ticker
            "setup": brand_setup(r.get("setup", ""), r.get("wr", "")),
            "phase": r["_phase"].lower(),             # active / extended / retired (from the pipeline)
            "score": _num(r.get("score_at_entry")),
            "q": grade_q(r.get("qualgate")),
            "profile": meta.get("profile"),
            "sector": meta.get("sector"),
            "rs": grade_rs(r.get("rs_at_entry")),      # Pulse @ Add — frozen at the signal
            "rsn": grade_rs(r.get("rs_now")) if _num(r.get("rs_now")) is not None else None,  # Pulse now — nightly
            "date": fmt_date(r.get("entry_date")),
            "dial": map_dial(r.get("dial")),          # SPY regime at the time this setup was added
            "pe": _num(r.get("entry")),
            "wk2": _num(r.get("wk2_ret_pct")),         # actual return 2 weeks after entry
            "wk4": _num(r.get("wk4_ret_pct")),         # actual return 4 weeks after entry
            "wk12": _num(r.get("wk12_ret_pct")),       # actual return 12 weeks after entry (sparse early on)
            "d5": _num(r.get("dip_to5_pct")),          # dip before the FIRST touch of +5% (null = never touched)
            "d10": _num(r.get("dip_to10_pct")),        # same for +10%
            "md4": _num(r.get("maxdip_4wk_pct")),      # worst intraday dip in the first 4 weeks
            "mfe": _num(r.get("mfe_pct")),
            "mae": _num(r.get("mae_pct")),
            "dtp": _num(r.get("dtp")),                 # present once the tracker logs it; dropped if absent
            "_last": _num(r.get("last")),              # workbook's own last price (offline PC_SOURCE=workbook)
            # --- private fields carried along so the stripper can prove it drops them ---
            "dist200_pct": _num(r.get("dist200_pct")),
            "wash_min8w": _num(r.get("wash_min8w")),
            "sma200_at_entry": _num(r.get("sma200_at_entry")),
        })
    return rows


def load_rows() -> list[dict]:
    if STS_XLSX.is_file():
        rows = rows_from_workbook(STS_XLSX)
        print(f"# input: {STS_XLSX.name} (Tracker: {len(rows)} names, "
              f"phases={sorted(PHASE_INCLUDE)}, qualgate={sorted(INCLUDE_QUALGATES)})")
        return rows
    if INPUT_PATH.is_file():
        rows = json.loads(INPUT_PATH.read_text())
        print(f"# input: {INPUT_PATH.name} ({len(rows)} names)")
        return rows
    print(f"# input: no xlsx/json found -> built-in SEED ({len(SEED_INPUT)} names)")
    return [dict(r) for r in SEED_INPUT]


# --------------------------------------------------------------------------- #
#  Session / freshness helpers                                                  #
# --------------------------------------------------------------------------- #
def expected_session() -> str:
    forced = os.environ.get("BOARD_SESSION")
    if forced:
        return forced.strip()
    now = dt.datetime.now(_EASTERN) if _EASTERN else dt.datetime.utcnow()
    d = now.date()
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def monday_of_week(session: str) -> dt.date:
    d = dt.date.fromisoformat(session)
    return d - dt.timedelta(days=d.weekday())


def public_only(row: dict) -> dict:
    return {k: row[k] for k in PUBLIC_FIELDS if k in row and row[k] is not None}


def atomic_write_json(path: Path, obj: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --------------------------------------------------------------------------- #
#  Build                                                                        #
# --------------------------------------------------------------------------- #
def build() -> int:
    session = expected_session()
    rows = load_rows()
    if not rows:
        print("! no names to publish (input empty after filters) — leaving board.json untouched.")
        return 1

    # Only LIVE names (active / extended) need tonight's price. A retired name's
    # record is frozen at retirement, so it keeps the workbook's own last price —
    # never stale, never a vendor request. That is the difference between ~64
    # requests a night and ~240.
    live = [r for r in rows if str(r.get("phase", "")).lower() != "retired"]
    names = [r["t"].upper() for r in live]
    want = list(dict.fromkeys(names + list(REGIME_TICKERS)))

    # PC_SOURCE=workbook -> use each position's own 'last' price from the workbook.
    # Offline, no vendor call, never trips the freshness guard. Ideal for local beta.
    # Default (unset) -> live prices via the eod_adapter (production nightly).
    if os.environ.get("PC_SOURCE", "").lower() == "workbook":
        from collections import namedtuple
        _WBar = namedtuple("_WBar", "close date source")
        bars = {r["t"].upper(): _WBar(r["_last"], session, "workbook")
                for r in rows if r.get("_last") is not None}
        provider = "workbook(last)"
    else:
        try:
            bars = get_eod_many(want)
        except EODError as e:
            print(f"! price pull failed entirely: {e}\n  leaving existing board.json untouched.")
            return 2
        provider = next((b.source for b in bars.values() if b), "?")
        # retired rows: frozen workbook price, stamped with the session so the
        # freshness guard (which is about LIVE prices) ignores them
        from collections import namedtuple
        _WBar = namedtuple("_WBar", "close date source")
        for r in rows:
            if str(r.get("phase", "")).lower() == "retired" and r.get("_last") is not None:
                bars.setdefault(r["t"].upper(), _WBar(r["_last"], session, "workbook"))

    print(f"# session={session}  provider={provider}  names={len(rows)}")

    out_names, stale = [], []
    for r in rows:
        t = r["t"].upper()
        bar = bars.get(t)
        if bar is None:
            stale.append(f"{t}(no data)")
            continue
        if bar.date != session:
            stale.append(f"{t}({bar.date})")
            continue
        pe = _num(r.get("pe"))
        pc = round(float(bar.close), 4)
        chg = round((pc / pe - 1.0) * 100, 1) if pe else None   # "Current %" column
        # Excursions are frozen at the nightly run but pc may be fresher; keep the
        # invariant  max-dip (mae) <= current (chg) <= peak (mfe)  so the board can
        # never show an impossible "current worse than the worst dip".
        mfe, mae = _num(r.get("mfe")), _num(r.get("mae"))
        if chg is not None:
            if mfe is not None:
                mfe = round(max(mfe, chg), 2)
            if mae is not None:
                mae = round(min(mae, chg), 2)
        out_names.append(public_only({**r, "pc": pc, "chg": chg, "mfe": mfe, "mae": mae}))

    total = len(rows)
    stale_ratio = len(stale) / total if total else 1.0
    if stale:
        shown = ", ".join(stale[:12]) + (f" …(+{len(stale)-12} more)" if len(stale) > 12 else "")
        print(f"! stale/missing ({len(stale)}/{total}): {shown}")
    if stale_ratio > STALE_ABORT_RATIO:
        print(f"! {stale_ratio:.0%} stale (> {STALE_ABORT_RATIO:.0%}) — NOT writing board.json. "
              f"Yesterday's board stays live.")
        return 1

    # Market-regime header: SPY/QQQ price + Healthy/Extended/Weak, from regime.json
    # (written by build_regime.py). Null-safe: the site shows a neutral bar if absent.
    regime = {"session": session, "as_of": None,
              "spy": None, "qqq": None, "state": None, "take": None}
    rj_path = HERE / "regime.json"
    if rj_path.is_file():
        try:
            rj = json.loads(rj_path.read_text())
            regime.update({k: rj.get(k) for k in ("as_of", "spy", "qqq", "state", "take")})
        except Exception:
            pass

    # Compact market-dial block (data contract): the 4-zone SPY dial for the header chip.
    market = None
    _sp = regime.get("spy") if isinstance(regime.get("spy"), dict) else None
    if _sp and _sp.get("dial"):
        market = {"dial": str(_sp.get("dial")).upper(),
                  "stretch_pct": _sp.get("stretch"),
                  "pctile": _sp.get("pctile"),
                  "as_of": regime.get("as_of")}

    board = {
        "generated_at": (dt.datetime.now(_EASTERN) if _EASTERN else dt.datetime.utcnow())
                        .replace(microsecond=0).isoformat(),
        "session_date": session,
        "regime": regime,
        "market": market,
        "names": out_names,
        "counts": {"total": len(out_names),
                   "active": sum(1 for n in out_names if n.get("phase") == "active"),
                   "extended": sum(1 for n in out_names if n.get("phase") == "extended"),
                   "retired": sum(1 for n in out_names if n.get("phase") == "retired")},
    }

    atomic_write_json(OUTPUT_PATH, board)
    leaked = set().union(*[set(n) for n in out_names]) - set(PUBLIC_FIELDS) if out_names else set()
    assert not leaked, f"PROPRIETARY LEAK into board.json: {leaked}"
    print(f"# wrote {OUTPUT_PATH.name}: {len(out_names)} names "
          f"({board['counts']['active']} active / {board['counts']['extended']} extended)")
    return 0


if __name__ == "__main__":
    sys.exit(build())
