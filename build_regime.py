#!/usr/bin/env python3
"""
build_regime.py — write regime.json for the board's market-regime header.

Computes the 4-ZONE PERCENTILE DIAL (validated in spy_regime_study.py, matches
sts_ml_evening.py): "stretch" = % the index sits above its 200-day average, ranked
against its OWN trailing-3-year stretch distribution so "extended" self-calibrates
to the era.

    RED    = below the 200-day (unhealthy)
    GREEN  = above, stretch < 50th percentile (recently reset — friendliest window)
    YELLOW = 50th-90th percentile (extended but ordinary)
    ORANGE = > 90th percentile (over-extended — the only zone where the bad tail lives)

The old ATR dial (atr_dist) is kept alongside for continuity. Fresh index data via
yfinance (same source as the pipeline). Writes regime.json next to this script;
build_board.py reads it into board.json (regime + market blocks). If yfinance is
unreachable, it leaves any existing regime.json untouched and exits 0.

RUN:  python3 build_regime.py           (run_local.sh calls this automatically)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "regime.json"

PCTILE_WINDOW = 757   # ~3 trading years for the self-calibrating percentile


def regime_of(df):
    import pandas as pd  # noqa
    C, H, L = df["Close"], df["High"], df["Low"]
    sma200 = C.rolling(200).mean()
    stretch = ((C / sma200 - 1) * 100).dropna()
    stretch_now = float(stretch.iloc[-1])
    win = stretch.iloc[-PCTILE_WINDOW:]
    pctile = float(100 * (win.iloc[:-1] < win.iloc[-1]).mean()) if len(win) > 100 else float("nan")

    if stretch_now < 0:
        dial = "RED"
    elif pctile != pctile:           # NaN — not enough history for the percentile
        dial = "YELLOW"
    elif pctile > 90:
        dial = "ORANGE"
    elif pctile >= 50:
        dial = "YELLOW"
    else:
        dial = "GREEN"

    # old ATR dial kept for continuity (not shown on the site anymore)
    pc = C.shift(1)
    tr = pd.concat([H - L, (H - pc).abs(), (L - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_dist = float((C.iloc[-1] - sma200.iloc[-1]) / atr.iloc[-1])

    return {"price": round(float(C.iloc[-1]), 2),
            "dial": dial,
            "stretch": round(stretch_now, 1),
            "pctile": (round(pctile) if pctile == pctile else None),
            "atr_dist": round(atr_dist, 1)}


def take_for(spy):
    z, p = spy["dial"], spy.get("pctile")
    if z == "ORANGE":
        pct = f"{p}%" if p is not None else "90%+"
        return (f"The S&P 500 is more stretched than about {pct} of its last three years. "
                "That doesn't predict a decline — most such stretches pass quietly — but "
                "historically the market's worst multi-week drops began from here. Extra "
                "awareness, not advice.")
    return {
        "GREEN":  "The S&P 500 recently reset and is calmer than most of its last three years — "
                  "historically a supportive backdrop. Context for sizing, not a signal.",
        "YELLOW": "The S&P 500 is moderately stretched above its trend — an ordinary reading. "
                  "Context for sizing, not a signal.",
        "RED":    "The S&P 500 is below its long-term trend — reduce size and lean on the "
                  "highest-quality names. Context, not a forecast.",
    }.get(z, "")


def main():
    try:
        import yfinance as yf
        import pandas as pd  # noqa
    except ImportError:
        print("build_regime: yfinance not installed — skipping (board keeps last regime.json).")
        return 0

    out = {}
    df = None
    for sym in ("SPY", "QQQ"):
        try:
            df = yf.download(sym, period="5y", progress=False, auto_adjust=True)
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.get_level_values(0)   # flatten yfinance multiindex
            df = df.dropna()
            if len(df) < 210:
                raise ValueError("not enough history")
            out[sym.lower()] = regime_of(df)
        except Exception as e:
            print(f"build_regime: {sym} failed ({e}) — leaving existing regime.json untouched.")
            return 0

    as_of = None
    try:
        as_of = str(df.index[-1].date())
    except Exception:
        pass

    spy = out["spy"]
    regime = {"as_of": as_of,
              "spy": spy, "qqq": out["qqq"],
              "dial": spy["dial"], "state": spy["dial"],
              "pctile": spy.get("pctile"), "stretch": spy.get("stretch"),
              "take": take_for(spy)}
    OUT.write_text(json.dumps(regime, indent=2))
    print(f"build_regime: wrote {OUT.name}  SPY {spy['price']} dial={spy['dial']} "
          f"(pctile {spy.get('pctile')}, stretch {spy.get('stretch')}%) · QQQ dial={out['qqq']['dial']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
