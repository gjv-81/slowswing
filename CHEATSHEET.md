# QualGate cheat-sheet

A quality/safety filter for your STS swing universe. It answers one question per ticker:
**is this company sound enough that I'd hold it through a drawdown when STS signals?**
It does NOT predict the swing move — that's STS's job.

## The daily flow (automated via cron, 7:50pm)

```
sts_ml_evening.py            # your job: regenerates the tracker xlsx
   └── build_holy_grail.py   # chained after it: rebuilds STS_holy_grail.xlsx
```

`build_holy_grail.py` is non-destructive — it reads the tracker and writes a NEW
workbook, so it can't corrupt your tracker. Logs to `holy_grail.log`.

## The files

| File | Role |
|---|---|
| `qualgate.py` | The scoring engine + veto logic. All the tunable knobs live here. |
| `enrich_trades.py` | Scores tickers with a per-ticker cache; adds gate columns to the trades CSV. |
| `build_holy_grail.py` | Consolidates tracker + trades + scores into one 3-sheet workbook. |
| `qualgate_cache.csv` | Per-ticker scores. Auto-refreshes new/stale names; delete it to force a full re-score. |
| `STS_holy_grail.xlsx` | The output. Sheets: **Tracker** (gate next to ticker), **QualGate** (full breakdown), **Trades**. |

## Reading the tag (e.g. `FAIL/GS`)

Gate (safety): **PASS** ≥65 & no veto · **WATCH** 50–64 · **FAIL** <50 or any hard veto.

Profile (archetype, the part after the slash):

| Code | Meaning | Swing read |
|---|---|---|
| (none) | CORE — mature/stable | ordinary established name |
| GS | Growth stock (rev ≥20%/yr) | `FAIL/GS` = momentum, no fundamental floor — trade small, don't marry it |
| SPEC | Pre-revenue / story (P/S >40 or no gross profit) | highest drawdown risk |
| IPO | <3yr public history | thin record, caution |
| LEV | Failing on balance-sheet leverage (Altman-Z) | real leverage risk |
| DECL | Revenue shrinking | possible value trap / secular decline |

## The score = 6 research-backed factors

| Factor | Weight | Why (research) |
|---|---|---|
| Piotroski F-score | 0.24 | Piotroski 2000 — 9 checks of improving financial health |
| Gross profitability (GP/assets) | 0.22 | Novy-Marx 2013 — most robust quality signal |
| Altman Z-score | 0.16 | Altman 1968 — distress; also a hard veto <1.81 |
| FCF yield | 0.14 | QMJ — can it self-fund |
| Solvency (int-cov, D/E, current) | 0.14 | balance-sheet strength |
| 4-yr margin/ROIC trend | 0.10 | direction, not just level |

**Cash-flow-aware refinement:** negative GAAP operating margin, weak interest
coverage, or negative book equity are NOT vetoed if the company is FCF-positive
(rescues SaaS with heavy stock-based comp and buyback-heavy blue chips).

## Common tasks

Run it by hand:
```
python3 build_holy_grail.py --tracker sts_ml_paper_tracker.xlsx --trades sts_ml_paper_trades.csv --out STS_holy_grail.xlsx
```

Rebuild the workbook without hitting Yahoo (cache only):  add `--no-refresh`

Force a full re-score (after you change weights/logic, or bump `GATE_VERSION`):
```
rm qualgate_cache.csv
```

Tighten/loosen the universe:  edit `PASS_THRESHOLD` in `qualgate.py` (default 65),
or pass `--pass-threshold 70` to `qualgate.py` / `enrich_trades.py`.

Retune a factor:  edit `WEIGHTS` and `ANCHORS` at the top of `qualgate.py`, then bump
`GATE_VERSION` so the cache auto-refreshes.

Check the nightly run worked:  `tail holy_grail.log`

## Caveats

yfinance is restated (not point-in-time) and ~4 years deep — fine for a *filter*,
not for training an ML model. Altman-Z is skipped for financial-sector names.
A high score means "sound enough to hold," not "will go up."
