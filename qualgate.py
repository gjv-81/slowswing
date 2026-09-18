#!/usr/bin/env python3
"""
qualgate — a research-backed QUALITY / SAFETY gate for swing-trade universe filtering.

Purpose: NOT to predict returns (fundamentals are weak at swing horizons) but to
decide, PASS / FAIL, whether a name is a good-enough business with a strong-enough
balance sheet to be *eligible* for your STS technical model. It screens out junk and
blow-up risk so STS only times entries on sound companies.

Every factor is chosen because peer-reviewed research shows it separates strong
businesses from weak/fragile ones (see docstrings and SSI2-lite-design.md):

  * Gross profitability  = gross profit / total assets   — Novy-Marx (2013)
  * Piotroski F-score    = 9 accounting checks           — Piotroski (2000)
  * Altman Z-score       = distress / bankruptcy risk    — Altman (1968)   [hard veto]
  * Accruals (OCF>NI)    = earnings quality              — Sloan (1996)    [inside F-score]
  * FCF yield + trend    = self-funding quality          — QMJ, Asness et al.
  * Solvency (coverage / leverage / liquidity)           — SSI2 balance-sheet gate

Data source: yfinance (annual + quarterly statements, ~4yr). No credentials needed.
A mock loader reads fixtures/<SYM>_stmts.json (same shape) so the math is testable
offline.

Usage:
    python qualgate.py AAPL
    python qualgate.py AAPL MSFT NVDA --csv gate.csv
    python qualgate.py STRONGCO --source mock
    python qualgate.py AAPL --pass-threshold 70 --json
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# CONFIG — research-informed weights and thresholds. Tune here.
# Weights reflect relative robustness in the factor literature: gross
# profitability and the F-score carry the most weight; Altman-Z is both a
# weighted factor AND a hard veto.
# ---------------------------------------------------------------------------

WEIGHTS = {
    "gross_profitability": 0.22,   # Novy-Marx: among the most robust quality signals
    "f_score":             0.24,   # Piotroski: strongest single quality/safety composite
    "altman_z":            0.16,   # Altman: distress axis (also a veto below)
    "fcf":                 0.14,   # self-funding: FCF yield + positive trajectory
    "solvency":            0.14,   # coverage / leverage / liquidity
    "trend":               0.10,   # 4-yr margin/ROIC direction
}

# Piecewise (raw, 0..100) anchors. higher_better=False -> smaller raw scores higher.
ANCHORS = {
    "gross_profitability": {"points": [(0.05, 0), (0.20, 50), (0.40, 90), (0.60, 100)]},
    "f_score":             {"points": [(2, 0), (5, 50), (7, 85), (9, 100)]},
    "altman_z":            {"points": [(1.81, 0), (2.99, 70), (5.0, 100)]},
    "fcf_yield":           {"points": [(0, 0), (3, 45), (6, 80), (10, 100)]},
    "interest_cov":        {"points": [(1, 0), (5, 70), (12, 100)]},
    "debt_to_equity":      {"points": [(0, 100), (1.0, 60), (2.5, 0)], "higher_better": False},
    "current_ratio":       {"points": [(0.8, 0), (1.0, 50), (2.0, 100)]},
    "margin_trend":        {"points": [(-3, 0), (0, 60), (3, 100)]},
    "roic_trend":          {"points": [(-3, 0), (0, 60), (3, 100)]},
}

PASS_THRESHOLD = 65     # score >= -> PASS (if no veto)
WATCH_THRESHOLD = 50    # score >= -> WATCH; below -> FAIL

# Bumped whenever scoring/veto logic changes, so cached scores auto-invalidate.
GATE_VERSION = "1.1"

# Line-item aliases: Yahoo's labels drift, so resolve each concept from a list.
ALIASES = {
    "revenue":        ["Total Revenue", "Operating Revenue", "Revenue"],
    "cogs":           ["Cost Of Revenue", "Cost of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit":   ["Gross Profit"],
    "op_income":      ["Operating Income", "Total Operating Income As Reported"],
    "ebit":           ["EBIT", "Operating Income", "Normalized EBITDA"],
    "interest_exp":   ["Interest Expense", "Interest Expense Non Operating", "Net Interest Income"],
    "net_income":     ["Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"],
    "diluted_shares": ["Diluted Average Shares", "Basic Average Shares"],
    "total_assets":   ["Total Assets"],
    "current_assets": ["Current Assets", "Total Current Assets"],
    "current_liab":   ["Current Liabilities", "Total Current Liabilities"],
    "total_liab":     ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "total_debt":     ["Total Debt"],
    "long_term_debt": ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"],
    "retained_earn":  ["Retained Earnings"],
    "equity":         ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"],
    "working_capital":["Working Capital"],
    "shares_out":     ["Ordinary Shares Number", "Share Issued", "Common Stock Shares Outstanding"],
    "ocf":            ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex":          ["Capital Expenditure", "Purchase Of PPE"],
    "fcf":            ["Free Cash Flow"],
}

STATEMENT_OF = {  # which statement each concept lives in
    "income":  {"revenue", "cogs", "gross_profit", "op_income", "ebit", "interest_exp",
                "net_income", "diluted_shares"},
    "balance": {"total_assets", "current_assets", "current_liab", "total_liab", "total_debt",
                "long_term_debt", "retained_earn", "equity", "working_capital", "shares_out"},
    "cashflow":{"ocf", "capex", "fcf"},
}
FINANCIAL_SECTORS = {"Financial Services", "Financial", "Banks", "Insurance"}


# ---------------------------------------------------------------------------
# STATEMENT ACCESS
# ---------------------------------------------------------------------------

def _which_stmt(concept: str) -> str:
    for stmt, concepts in STATEMENT_OF.items():
        if concept in concepts:
            return stmt
    raise KeyError(concept)


def get(stmts: dict, concept: str, year_idx: int = 0) -> Optional[float]:
    """Value of a concept for a given year index (0 = most recent). Resolves aliases.
    Interest expense is returned as a positive magnitude."""
    stmt = stmts.get(_which_stmt(concept), {})
    years = stmts["_years"]
    if year_idx >= len(years):
        return None
    y = years[year_idx]
    for label in ALIASES[concept]:
        row = stmt.get(label)
        if row is None:
            continue
        v = row.get(str(y), row.get(y))
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if concept == "interest_exp":
            f = abs(f)
        return f
    return None


def _ratio(n, d):
    if n is None or d is None or d == 0:
        return None
    return n / d


# ---------------------------------------------------------------------------
# FACTORS
# ---------------------------------------------------------------------------

def gross_profitability(s) -> Optional[float]:
    """Novy-Marx: gross profit / total assets. Falls back to (revenue-cogs)."""
    gp = get(s, "gross_profit", 0)
    if gp is None:
        rev, cogs = get(s, "revenue", 0), get(s, "cogs", 0)
        gp = (rev - cogs) if (rev is not None and cogs is not None) else None
    return _ratio(gp, get(s, "total_assets", 0))


def piotroski_f(s) -> tuple[Optional[int], dict]:
    """Piotroski (2000) 9-point F-score using year t vs t-1. Returns (score, detail)."""
    if len(s["_years"]) < 2:
        return None, {}
    ta0, ta1 = get(s, "total_assets", 0), get(s, "total_assets", 1)
    ni0, ni1 = get(s, "net_income", 0), get(s, "net_income", 1)
    ocf0 = get(s, "ocf", 0)
    rev0, rev1 = get(s, "revenue", 0), get(s, "revenue", 1)
    gp0, gp1 = get(s, "gross_profit", 0), get(s, "gross_profit", 1)
    ltd0, ltd1 = get(s, "long_term_debt", 0), get(s, "long_term_debt", 1)
    ca0, ca1 = get(s, "current_assets", 0), get(s, "current_assets", 1)
    cl0, cl1 = get(s, "current_liab", 0), get(s, "current_liab", 1)
    sh0, sh1 = get(s, "shares_out", 0), get(s, "shares_out", 1)

    roa0, roa1 = _ratio(ni0, ta0), _ratio(ni1, ta1)
    cr0, cr1 = _ratio(ca0, cl0), _ratio(ca1, cl1)
    ltr0, ltr1 = _ratio(ltd0, ta0), _ratio(ltd1, ta1)
    gm0, gm1 = _ratio(gp0, rev0), _ratio(gp1, rev1)
    at0, at1 = _ratio(rev0, ta0), _ratio(rev1, ta1)

    checks = {}
    checks["roa_positive"]    = (roa0 is not None and roa0 > 0)
    checks["ocf_positive"]    = (ocf0 is not None and ocf0 > 0)
    checks["roa_rising"]      = (roa0 is not None and roa1 is not None and roa0 > roa1)
    checks["accruals_ok"]     = (ocf0 is not None and ni0 is not None and ocf0 > ni0)   # Sloan
    checks["leverage_down"]   = (ltr0 is not None and ltr1 is not None and ltr0 < ltr1)
    checks["liquidity_up"]    = (cr0 is not None and cr1 is not None and cr0 > cr1)
    checks["no_dilution"]     = (sh0 is not None and sh1 is not None and sh0 <= sh1 * 1.001)
    checks["margin_up"]       = (gm0 is not None and gm1 is not None and gm0 > gm1)
    checks["turnover_up"]     = (at0 is not None and at1 is not None and at0 > at1)
    score = sum(1 for v in checks.values() if v)
    return score, checks


def altman_z(s) -> tuple[Optional[float], dict]:
    """Altman (1968) Z-score. Manufacturing form; less meaningful for financials."""
    ta = get(s, "total_assets", 0)
    if not ta:
        return None, {}
    wc = get(s, "working_capital", 0)
    if wc is None:
        ca, cl = get(s, "current_assets", 0), get(s, "current_liab", 0)
        wc = (ca - cl) if (ca is not None and cl is not None) else None
    re = get(s, "retained_earn", 0)
    ebit = get(s, "ebit", 0)
    tl = get(s, "total_liab", 0)
    sales = get(s, "revenue", 0)
    mcap = s["_meta"].get("market_cap")
    x1 = _ratio(wc, ta); x2 = _ratio(re, ta); x3 = _ratio(ebit, ta)
    x4 = _ratio(mcap, tl); x5 = _ratio(sales, ta)
    if None in (x1, x2, x3, x4, x5):
        return None, {"x1": x1, "x2": x2, "x3": x3, "x4": x4, "x5": x5}
    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    return z, {"x1": x1, "x2": x2, "x3": x3, "x4": x4, "x5": x5}


def fcf_yield(s) -> tuple[Optional[float], Optional[float]]:
    """(FCF yield %, FCF for latest year). FCF = Free Cash Flow row, else OCF + capex."""
    fcf = get(s, "fcf", 0)
    if fcf is None:
        ocf, capex = get(s, "ocf", 0), get(s, "capex", 0)   # capex stored negative
        fcf = (ocf + capex) if (ocf is not None and capex is not None) else None
    mcap = s["_meta"].get("market_cap")
    y = _ratio(fcf, mcap)
    return (y * 100 if y is not None else None), fcf


def _roic(s, i) -> Optional[float]:
    ebit = get(s, "ebit", i)
    debt = get(s, "total_debt", i) or 0
    eq = get(s, "equity", i)
    if ebit is None or eq is None:
        return None
    inv = debt + eq
    if inv <= 0:
        return None
    return (ebit * 0.79) / inv * 100     # NOPAT ~ EBIT*(1-21% tax)


def trends(s) -> dict:
    """Direction of operating margin and ROIC from earliest available year to latest (pp)."""
    yrs = len(s["_years"])
    last = yrs - 1
    om0 = _ratio(get(s, "op_income", 0), get(s, "revenue", 0))
    omN = _ratio(get(s, "op_income", last), get(s, "revenue", last))
    margin_trend = (om0 - omN) * 100 if (om0 is not None and omN is not None) else None
    r0, rN = _roic(s, 0), _roic(s, last)
    roic_trend = (r0 - rN) if (r0 is not None and rN is not None) else None
    return {"margin_trend": margin_trend, "roic_trend": roic_trend,
            "op_margin_ttm": om0 * 100 if om0 is not None else None,
            "roic_ttm": r0}


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------

def piecewise(raw, points, higher_better=True):
    if raw is None:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    if raw <= xs[0]:
        return float(ys[0])
    if raw >= xs[-1]:
        return float(ys[-1])
    for i in range(len(xs) - 1):
        if xs[i] <= raw <= xs[i + 1]:
            span = xs[i + 1] - xs[i]
            t = 0 if span == 0 else (raw - xs[i]) / span
            return float(ys[i] + t * (ys[i + 1] - ys[i]))
    return float(ys[-1])


@dataclass
class GateResult:
    symbol: str
    score: float
    gate: str                    # PASS / WATCH / FAIL
    vetoes: list = field(default_factory=list)
    sub: dict = field(default_factory=dict)     # component scores
    metrics: dict = field(default_factory=dict) # raw metrics for display/CSV
    f_checks: dict = field(default_factory=dict)
    profile: str = "CORE"        # SPEC / IPO / GROWTH / LEVERAGED / DECLINING / CORE
    profile_note: str = ""


# Short codes used in the combined tag (e.g. "FAIL/GS").
PROFILE_CODE = {"SPECULATIVE": "SPEC", "NEW-IPO": "IPO", "GROWTH": "GS",
                "LEVERAGED": "LEV", "DECLINING": "DECL", "CORE": ""}
GROWTH_CAGR = 20.0      # % revenue growth that marks a "growth stock"
PRE_REV_PS = 40.0       # price/sales above this = market pricing a pre-commercial story


def _revenue_growth(s) -> dict:
    """Latest YoY and multi-year CAGR of revenue, plus latest revenue level."""
    n = len(s["_years"])
    rev0 = get(s, "revenue", 0)
    rev1 = get(s, "revenue", 1) if n >= 2 else None
    revL = get(s, "revenue", n - 1) if n >= 2 else None
    yoy = ((rev0 / rev1 - 1) * 100) if (rev0 and rev1 and rev1 > 0) else None
    cagr = None
    if rev0 and revL and revL > 0 and n >= 2:
        cagr = ((rev0 / revL) ** (1 / (n - 1)) - 1) * 100
    return {"rev0": rev0, "yoy": yoy, "cagr": cagr, "n_years": n}


def classify_profile(s, metrics: dict, has_leverage_veto: bool) -> tuple[str, str]:
    """Tag the company archetype (orthogonal to PASS/FAIL) so a FAIL can be read
    as 'growth stock' vs 'declining/value-trap' vs 'pre-revenue story'."""
    g = _revenue_growth(s)
    rev0, yoy, cagr, n = g["rev0"], g["yoy"], g["cagr"], g["n_years"]
    gp = metrics.get("gross_profitability")
    fcf = metrics.get("fcf")
    ni = metrics.get("net_income")
    mcap = s["_meta"].get("market_cap")
    ipo_age = s["_meta"].get("ipo_age_years")
    ps = (mcap / rev0) if (mcap and rev0 and rev0 > 0) else None   # price/sales, scale-free

    grow = (cagr is not None and cagr >= GROWTH_CAGR) or (yoy is not None and yoy >= 25)
    profitable_safe = (ni is not None and ni > 0) and (fcf is not None and fcf > 0)

    # 1) pre-revenue / story stock: no real product economics, or the market is
    #    pricing a company on almost no sales (very high P/S).
    if (gp is not None and gp <= 0) or (ps is not None and ps > PRE_REV_PS):
        note = f"pre-commercial (P/S {ps:.0f})" if ps else "pre-commercial (minimal revenue)"
        return "SPECULATIVE", note
    # 2) recent IPO (short public/financial history)
    if (ipo_age is not None and ipo_age < 3) or n < 3:
        extra = " + high growth" if grow else ""
        return "NEW-IPO", f"<3yr public history{extra}"
    # 3) growth stock (fast revenue, not yet safely self-funding)
    if grow and not profitable_safe:
        return "GROWTH", f"rev +{(cagr or yoy):.0f}%/yr, not yet FCF-safe"
    if grow and profitable_safe:
        return "GROWTH", f"rev +{(cagr or yoy):.0f}%/yr, profitable"
    # 4) leverage-driven risk
    if has_leverage_veto:
        return "LEVERAGED", "distress/leverage flag"
    # 5) shrinking business
    if yoy is not None and yoy < 0:
        return "DECLINING", f"revenue {yoy:.0f}% YoY"
    return "CORE", "mature / stable"


def evaluate_gate(s: dict, pass_threshold=PASS_THRESHOLD, watch_threshold=WATCH_THRESHOLD) -> GateResult:
    sym = s["_meta"].get("symbol", "?")
    sector = s["_meta"].get("sector", "")
    is_financial = any(f.lower() in (sector or "").lower() for f in FINANCIAL_SECTORS)

    gp = gross_profitability(s)
    f, fchecks = piotroski_f(s)
    z, zparts = altman_z(s)
    fcfy, fcf_val = fcf_yield(s)
    tr = trends(s)
    icov = _ratio(get(s, "ebit", 0), get(s, "interest_exp", 0))
    d2e = _ratio(get(s, "total_debt", 0), get(s, "equity", 0))
    cratio = _ratio(get(s, "current_assets", 0), get(s, "current_liab", 0))
    ni0 = get(s, "net_income", 0)
    equity0 = get(s, "equity", 0)

    # ---- component scores ----
    sub = {}
    sub["gross_profitability"] = piecewise(gp, ANCHORS["gross_profitability"]["points"])
    sub["f_score"] = piecewise(f, ANCHORS["f_score"]["points"]) if f is not None else None
    sub["altman_z"] = piecewise(z, ANCHORS["altman_z"]["points"]) if (z is not None and not is_financial) else None
    sub["fcf"] = piecewise(fcfy, ANCHORS["fcf_yield"]["points"]) if fcfy is not None else None
    solv_parts = [
        piecewise(icov, ANCHORS["interest_cov"]["points"]),
        piecewise(d2e, ANCHORS["debt_to_equity"]["points"], higher_better=False),
        piecewise(cratio, ANCHORS["current_ratio"]["points"]),
    ]
    solv_present = [p for p in solv_parts if p is not None]
    sub["solvency"] = sum(solv_present) / len(solv_present) if solv_present else None
    trend_parts = [
        piecewise(tr["margin_trend"], ANCHORS["margin_trend"]["points"]),
        piecewise(tr["roic_trend"], ANCHORS["roic_trend"]["points"]),
    ]
    trend_present = [p for p in trend_parts if p is not None]
    sub["trend"] = sum(trend_present) / len(trend_present) if trend_present else None

    # ---- weighted score (renormalized over available components) ----
    num = den = 0.0
    for k, w in WEIGHTS.items():
        if sub.get(k) is not None:
            num += sub[k] * w
            den += w
    score = num / den if den else 0.0

    # ---- hard safety vetoes (any -> FAIL) ----
    # Refinement: cash generation rescues GAAP-accounting artifacts. Negative GAAP
    # operating margin / interest coverage at a FCF-positive company is usually a
    # stock-based-comp effect, not a solvency threat; negative book equity at a
    # profitable, cash-generative company is usually buybacks, not insolvency.
    fcf_positive = fcf_val is not None and fcf_val > 0
    vetoes = []
    if z is not None and z < 1.81 and not is_financial:
        vetoes.append(f"Altman-Z {z:.2f} in distress zone (<1.81)")
    if f is not None and f <= 2:
        vetoes.append(f"Piotroski F-score {f}/9 (<=2, fundamentally weak)")
    if gp is not None and gp <= 0:
        vetoes.append("Gross profit <= 0 (not a viable business)")
    if tr["op_margin_ttm"] is not None and tr["op_margin_ttm"] < 0 and not fcf_positive:
        vetoes.append(f"Operating margin negative ({tr['op_margin_ttm']:.1f}%) and FCF not positive")
    if icov is not None and icov < 1.0 and not fcf_positive:
        vetoes.append(f"Interest coverage {icov:.1f}x < 1.0x and FCF not positive")
    if equity0 is not None and equity0 <= 0 and not (fcf_positive and (ni0 is None or ni0 > 0)):
        vetoes.append("Negative equity with losses/cash burn (balance-sheet insolvent)")
    if fcf_val is not None and fcf_val < 0 and ni0 is not None and ni0 < 0:
        vetoes.append("Burning cash and unprofitable (FCF<0 and NI<0)")

    if vetoes:
        gate = "FAIL"
    elif score >= pass_threshold:
        gate = "PASS"
    elif score >= watch_threshold:
        gate = "WATCH"
    else:
        gate = "FAIL"

    metrics = {
        "gross_profitability": gp, "f_score": f, "altman_z": z, "fcf_yield_pct": fcfy,
        "fcf": fcf_val, "interest_cov": icov, "debt_to_equity": d2e, "current_ratio": cratio,
        "op_margin_ttm": tr["op_margin_ttm"], "roic_ttm": tr["roic_ttm"],
        "margin_trend_pp": tr["margin_trend"], "roic_trend_pp": tr["roic_trend"],
        "net_income": ni0, "sector": sector,
    }
    has_lev_veto = any("Altman-Z" in v for v in vetoes)
    profile, profile_note = classify_profile(s, metrics, has_lev_veto)
    return GateResult(sym, score, gate, vetoes, sub, metrics, fchecks or {}, profile, profile_note)


# ---------------------------------------------------------------------------
# DATA LOADERS
# ---------------------------------------------------------------------------

def load_mock(fixtures_dir: str, symbol: str) -> dict:
    with open(os.path.join(fixtures_dir, f"{symbol.upper()}_stmts.json")) as fh:
        return json.load(fh)


def load_yfinance(symbol: str) -> dict:
    """Build the internal statements dict from live yfinance data."""
    try:
        import yfinance as yf
    except ImportError as e:
        raise SystemExit("yfinance not installed. Run: pip install yfinance") from e
    t = yf.Ticker(symbol)

    def frame_to_dict(df):
        out, years = {}, []
        if df is None or getattr(df, "empty", True):
            return out, years
        years = [c.year for c in df.columns]
        for label in df.index:
            row = {}
            for c in df.columns:
                v = df.loc[label, c]
                if v is not None and str(v) != "nan":
                    try:
                        row[str(c.year)] = float(v)
                    except (TypeError, ValueError):
                        pass
            out[str(label)] = row
        return out, years

    income, years = frame_to_dict(t.income_stmt)
    balance, _ = frame_to_dict(t.balance_sheet)
    cashflow, _ = frame_to_dict(t.cashflow)
    years = sorted(set(years), reverse=True)

    meta = {"symbol": symbol.upper()}
    try:
        fi = t.fast_info
        meta["market_cap"] = fi.get("marketCap") if hasattr(fi, "get") else fi["marketCap"]
        meta["price"] = fi.get("lastPrice") if hasattr(fi, "get") else fi["lastPrice"]
    except Exception:
        pass
    try:
        info = t.get_info()
        meta.setdefault("market_cap", info.get("marketCap"))
        meta["sector"] = info.get("sector", "")
        epoch = info.get("firstTradeDateEpochUtc") or info.get("firstTradeDateMilliseconds")
        if epoch:
            secs = epoch / 1000 if epoch > 1e11 else epoch
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromtimestamp(secs, dt.timezone.utc)).days / 365.25
            meta["ipo_age_years"] = round(age, 1)
    except Exception:
        meta.setdefault("sector", "")

    return {"_meta": meta, "_years": years, "income": income, "balance": balance, "cashflow": cashflow}


def load(source: str, symbol: str) -> dict:
    if source == "mock":
        here = os.path.dirname(os.path.abspath(__file__))
        return load_mock(os.path.join(here, "fixtures"), symbol)
    return load_yfinance(symbol)


# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------

def _f(v, nd=2, suf=""):
    return "n/a" if v is None else f"{v:.{nd}f}{suf}"


def render(r: GateResult) -> str:
    L = []
    tag = f"{r.gate}/{PROFILE_CODE.get(r.profile, '')}".rstrip("/")
    L.append(f"\n{'='*60}")
    L.append(f"  qualgate | {r.symbol}    {tag}   score {r.score:.0f}/100")
    L.append(f"  profile: {r.profile} ({r.profile_note})")
    L.append(f"{'='*60}")
    m = r.metrics
    L.append(f"  Gross profitability {_f(m['gross_profitability'])}   "
             f"F-score {m['f_score']}/9   Altman-Z {_f(m['altman_z'])}")
    L.append(f"  FCF yield {_f(m['fcf_yield_pct'],1,'%')}   Int.cov {_f(m['interest_cov'],1,'x')}   "
             f"D/E {_f(m['debt_to_equity'])}   Curr {_f(m['current_ratio'])}")
    L.append(f"  Op margin {_f(m['op_margin_ttm'],1,'%')} (trend {_f(m['margin_trend_pp'],1,'pp')})   "
             f"ROIC {_f(m['roic_ttm'],1,'%')} (trend {_f(m['roic_trend_pp'],1,'pp')})")
    L.append("")
    L.append("  Component scores:")
    for k in WEIGHTS:
        v = r.sub.get(k)
        L.append(f"    {k:22}{('n/a' if v is None else f'{v:.0f}'):>6}   (wt {WEIGHTS[k]:.2f})")
    if r.f_checks:
        passed = [k for k, v in r.f_checks.items() if v]
        L.append(f"  F-score checks passed: {', '.join(passed) if passed else 'none'}")
    if r.vetoes:
        L.append("  SAFETY VETOES (force FAIL):")
        for v in r.vetoes:
            L.append(f"    ✗ {v}")
    else:
        L.append("  Safety vetoes: none")
    L.append("")
    return "\n".join(L)


def to_row(r: GateResult) -> dict:
    m = r.metrics
    return {
        "symbol": r.symbol, "gate": r.gate, "profile": r.profile,
        "tag": f"{r.gate}/{PROFILE_CODE.get(r.profile, '')}".rstrip("/"),
        "score": round(r.score, 1),
        "gross_profitability": _round(m["gross_profitability"], 3), "f_score": m["f_score"],
        "altman_z": _round(m["altman_z"], 2), "fcf_yield_pct": _round(m["fcf_yield_pct"], 1),
        "interest_cov": _round(m["interest_cov"], 1), "debt_to_equity": _round(m["debt_to_equity"], 2),
        "current_ratio": _round(m["current_ratio"], 2), "op_margin_ttm": _round(m["op_margin_ttm"], 1),
        "roic_ttm": _round(m["roic_ttm"], 1), "margin_trend_pp": _round(m["margin_trend_pp"], 1),
        "sector": m["sector"], "profile_note": r.profile_note, "vetoes": " | ".join(r.vetoes),
    }


def _round(v, nd):
    return None if v is None else round(v, nd)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Research-backed quality/safety gate for swing-trade universe filtering.")
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--source", default="yfinance", choices=["yfinance", "mock"])
    ap.add_argument("--pass-threshold", type=float, default=PASS_THRESHOLD)
    ap.add_argument("--watch-threshold", type=float, default=WATCH_THRESHOLD)
    ap.add_argument("--csv", metavar="PATH")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--pass-only", action="store_true", help="print only names that PASS")
    args = ap.parse_args(argv)

    results = []
    for sym in args.symbols:
        try:
            s = load(args.source, sym)
            results.append(evaluate_gate(s, args.pass_threshold, args.watch_threshold))
        except Exception as e:
            print(f"[{sym}] error: {e}", file=sys.stderr)
    results.sort(key=lambda r: r.score, reverse=True)

    shown = [r for r in results if (not args.pass_only or r.gate == "PASS")]
    if args.json:
        print(json.dumps([to_row(r) for r in shown], indent=2, default=str))
    else:
        for r in shown:
            print(render(r))
        if len(results) > 1:
            print(f"  {'GATE SUMMARY':<14}{'sym':<8}{'score':>7}  {'tag':<12}profile")
            for r in results:
                tag = f"{r.gate}/{PROFILE_CODE.get(r.profile, '')}".rstrip("/")
                print(f"  {'':<14}{r.symbol:<8}{r.score:>7.0f}  {tag:<12}{r.profile}")

    if args.csv:
        rows = [to_row(r) for r in results]
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
