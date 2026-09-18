# STS → WEBSITE HANDOFF #2 — the new SPY regime dial (2026-08-26)
*Paste this into the website chat. It supersedes the "market-regime bar" description in
the earlier handoff. The backend now computes a 4-zone percentile dial; the site's
regime header should be rebuilt around it.*

---

## What changed and why
The old dial ((SPY − 200-day SMA) / ATR: RED < 0, GREEN 0..+5, YELLOW > +5) spent
**54% of all days in YELLOW** over the last 10 years — a warning zone that covers half
of history carries no information, and its 4-week drawdowns were actually *milder* than
GREEN's. We replaced it after a 10-year study (spy_regime_study.py, 1,886 trading days,
pre-committed reading rules).

## The new dial — 4 zones, graded against SPY's own trailing 3-year stretch distribution
"Stretch" = % SPY is above its 200-day average. Each day is ranked against the last
3 years of stretch readings (a percentile), so "extended" self-calibrates to the era
instead of using a fixed bar.

| Zone | Definition | What history says (10yr, hypothetical) |
|---|---|---|
| **RED** | SPY below its 200-day | Index unhealthy; biggest typical drawdowns (median 4wk dip −3.9%) |
| **GREEN** | Above the 200-day, stretch < 50th percentile | Recently reset; historically the friendliest forward window |
| **YELLOW** | 50th–90th percentile | Extended but ordinary — ~40% of days; nothing special either way |
| **ORANGE** | > 90th percentile | Over-extended. Median outcomes are FINE — but this is the **only zone where the bad tail lives**: worst-decile 4-week drawdowns exceeded −8%, worst-decile 12-week drawdowns reached −33% (the Feb-2020 and 2022 bear starts began here) |

Key nuance for copy: ORANGE is a **tail-risk flag, not a prediction**. Average returns
from ORANGE are unremarkable; what changes is that the rare disasters have historically
started there. Say "this is where crashes have started," never "a crash is coming."

## Site copy suggestions (compliance-safe)
- Header chip: `Market: ORANGE — SPY more stretched than 90% of the last 3 years`
- Tooltip: "We grade how far the S&P 500 sits above its long-term trend against its own
  last 3 years. ORANGE doesn't predict a decline — most ORANGE periods resolve quietly —
  but historically the market's worst 4–12-week drawdowns began from this zone. Extra
  awareness, not advice."
- KEEP the existing rule set: educational context only. Do **NOT** attach position-sizing
  instructions ("half size", "full size") to zones on the site — that drifts toward
  personalized advice. The dial informs; the visitor decides.
- Do NOT expose the mechanics beyond "stretched vs its own 3-year history" (no SMA
  lengths, no percentile window numbers in public copy — the table above is for you).

## Data contract addition (board.json)
```
"market": {
  "dial":       "ORANGE",          // RED | GREEN | YELLOW | ORANGE
  "stretch_pct": 9.2,              // % above 200-day (display optional)
  "pctile":      93,               // 0-100, drives the chip
  "as_of":       "2026-08-26"
}
```
Computed nightly by the backend pipeline (sts_ml_evening.py); the tracker also stamps
each position with the dial **at entry** (R/G/Y/O) so the track-record page can later
fan out results by entry regime once samples are big enough.

## Honest-metrics reminders (unchanged, still binding)
- All dial statistics above are 10-year historical/hypothetical, overlapping daily
  windows; label as such wherever quoted.
- The "5x regime lever" stat from the earlier handoff (+8.6% RED vs +1.7% YELLOW entries)
  is about the OLD red/yellow split and still stands — RED/post-correction entries were
  the best. The new dial refines the *above-the-200* side only.
- No performance promises, no "buy/enter" language, impersonal content to everyone.

---
## ✅ IMPLEMENTED on the website side (2026-08-30, site chat)
- **sts_site_live.html** — regime header rebuilt around the SPY 4-zone dial (RED/GREEN/YELLOW/ORANGE)
  with the "more stretched than N% of its last 3 years" phrasing + compliance-safe hover tooltip;
  `dialCell()` (per-position "Regime @ Add") now maps R/G/Y/O → Weak/Healthy/Extended/Over-extended
  (backward-compatible with old labels); the "How it works" dial card rewritten to the 4 zones with
  no ATR/percentile-window mechanics exposed. Published to the live artifact.
- **build_board.py** — `map_dial` upgraded to 4 zones; emits a top-level `market`
  {dial, stretch_pct, pctile, as_of} block into board.json (per the data contract).
- **build_regime.py** — now computes the 4-zone percentile dial (matches sts_ml_evening.py:
  stretch vs trailing-3yr, 757-day window) for SPY (+QQQ) and writes dial/pctile/stretch into
  regime.json; old atr_dist kept alongside. Logic verified against its definition (200/200 random-walk trials).
- Backups: build_board.py.bak, build_regime.py.bak.
- REMAINING: run the nightly pipeline tonight so the workbook/tracker/regime.json carry real O values,
  then rebuild board.json and re-inline into the site (site chat finishes this).
