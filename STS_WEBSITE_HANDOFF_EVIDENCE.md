# STS → WEBSITE HANDOFF #6 — "The Evidence" section + homepage +20% panel (2026-10-13)
*Paste into the website chat. All data below is REAL, computed 2026-10-12/13 from the
10-year backtest (scripts: touch_curve_study.py, cone_study_both.py; JSON sources:
touch_curve_data.json, cone_data_both.json in ~/STS/15min). Two reference mockups the
user has approved visually: `touch_curve_chart.html` (3-panel touch curves) and
`fan_chart_demo.html` (journey cones) — match their styling, which already follows the
site theme (teal #0f766e, white cards, Robeco restraint).*

---

## 1. WHAT TO BUILD

### A. New top-bar section: **"The Evidence"**
(NOT "Us vs SPY" — that name implies a returns-vs-index comparison we don't make and
shouldn't advertise. "The Evidence" fits the educational-research posture.)

Page order:
1. **Touch curves** — three side-by-side panels (+5% / +10% / +20%), each with exactly
   TWO lines: solid colored = signals, gray dashed = typical S&P 500 stock. Panels
   stack on mobile. Per-panel headline pair on top (87% vs 78% · 74% vs 56% ·
   51% vs 25%). Amber dotted vertical marker at each panel's widest gap with
   "+27 pts, wk N" label. Light tint fill between the two curves (the gap IS the
   product). See §3 for all data.
2. **The journey cone** — "12 weeks in the life of a signal": median line, 25–75 band,
   10–90 band, week 0→12. Frame as the honesty exhibit: *"Services that promise the
   moon won't show you this chart. We lead with it."* The visible −26% bottom decile
   is intentional — it is the argument for position sizing and the 12-week horizon.
   See §4 for data.
3. **Methodology & labels block** (plain language, one place for all caveats — §5).

### B. Homepage addition: the **+20% panel only**, as a teaser
- Placement: below the existing balloons + bullets.
- The single panel from the touch curves: signals 51% vs market 25% touched +20%
  within 12 weeks ("half our signals touched +20%; one in four market stocks did").
- One-line caption: "10-year backtest on today's board rules — see the full evidence →"
  linking to The Evidence section.
- Rationale: the 2:1 ratio is the sharpest honest stat we own; it does NOT collide
  with the balloons (which are the LIVE record at +5/+10). Do NOT put the +5% panel
  on home — it reads "87 vs 78" (weak at a glance) and fights the live 90% balloon.

### C. Standing editorial rule (add to the site conventions)
The site now has TWO kinds of performance content that must never blend visually:
- **Live track record** (July 2026 onward): balloons, scorecard, board history.
  Label: "live, as published".
- **Backtest studies** (these charts, any 10-year stat): label every instance
  "hypothetical backtest — not a record of published signals". The model would have
  generated these signals under today's rules; the site did not exist before 2026.
Never place a live number and a backtest number about the same metric side by side
without both labels visible. (User caught exactly this confusion — a badge that said
"published-universe signals, 2017–2026" reads as a 2017 track record. Forbidden.)

---

## 2. COHORT DEFINITIONS (for captions/method block — do not expose mechanics)

- Signals: every signal the model would have generated 2017→Oct 2026 under today's
  board rules — both setups (Phoenix + Cruise), quality screen PASS/WATCH, entry
  price ≥ $50. Entry at next session's open, 20-trading-day per-ticker refractory,
  no stop-losses, no targets. Touch curves use only signals with complete 12-week
  windows (n=2,005); cone uses all (n=2,226).
- "Touched +X%": the intraday high reached entry×(1+X%) at any point by week N.
  Peak-based (MFE) — NOT returns earned. Say this every time.
- Baseline: current S&P 500 members (503 names, 7 too new excluded), EVERY 5th
  trading day as an arbitrary start, Oct 2023→present, 69,091 starts, same
  touch-by-week measurement.
- Known biases, disclosed: current constituents only (survivorship — flatters BOTH
  cohorts, baseline likely more); quality screen uses today's verdicts applied
  retroactively (no historical fundamentals data); baseline window (3yr) shorter
  than signal window (10yr).

## 3. TOUCH-CURVE DATA (weeks 0..12, % of cohort that had touched the level)

signals +5%:  [10.3,51.3,64.1,71.4,75.7,79.0,80.4,82.4,83.7,84.3,85.1,86.1,86.7]
signals +10%: [1.6,23.2,37.2,47.0,53.2,59.1,62.8,66.1,68.4,69.9,71.5,73.1,74.3]
signals +20%: [0.1,4.8,12.4,18.9,24.7,29.8,33.8,37.7,40.8,44.0,46.9,48.9,50.9]
market +5%:   [1.6,23.8,38.9,49.1,56.3,61.4,65.4,68.6,71.2,73.3,75.1,76.6,77.8]
market +10%:  [0.1,5.7,12.7,19.7,26.4,32.1,37.1,41.4,45.1,48.3,51.2,53.7,55.8]
market +20%:  [0.0,0.8,2.1,4.0,6.0,8.2,10.6,12.9,15.3,17.8,20.1,22.3,24.5]

Widest gaps (amber markers): +5% at wk1 (+27 pts, 51 vs 24) · +10% at wk3
(+27 pts, 47 vs 20) · +20% at wk10 (+27 pts, 47 vs 20).
Narrative line (approved): "the edge shows up in week one and never hands it back —
it just migrates to bigger targets."

## 4. CONE DATA (board-rules backtest, n=2,226, Apr 2017–Oct 2026; % return from
next-session-open entry, closing values at weeks 0..12)

p10: [-3.5,-9.74,-11.85,-14.59,-16.39,-18.74,-19.96,-20.78,-21.65,-23.61,-25.47,-25.91,-26.5]
p25: [-1.62,-4.35,-5.24,-6.35,-7.54,-8.19,-9.12,-9.9,-10.93,-11.16,-11.88,-12.07,-11.92]
p50: [0.08,0.64,1.16,1.83,1.64,1.87,1.59,2.27,2.24,2.57,3.64,4.03,3.79]
p75: [1.7,5.63,8.31,10.72,11.4,13.57,14.69,16.82,17.73,18.7,20.25,22.92,22.77]
p90: [3.64,11.13,16.14,19.9,23.38,26.63,29.15,32.24,34.49,37.41,40.87,43.4,45.79]
win% wk12: 55.4. Annotations: median ~+4% by wk 11-12; a quarter of paths past +23%;
one in ten past +46%. Y-axis −30..+50. Chart renders median line + 25-75 band +
10-90 band (see fan_chart_demo.html for exact styling/animation).
Do NOT publish the raw/ungated cone (16,745 signals, median +6.8) — research only;
it would invite "why does your unscreened universe look better" (answer: gate-coverage
subset + timing composition, still under study — Oct 15 checkpoint item).

## 5. METHODOLOGY BLOCK (suggested copy, plain language)

"Everything on this page is a hypothetical backtest: signals our model would have
generated over the past ten years under the same rules the board uses today. The
site began publishing signals in July 2026 — our live track record lives on the
Track Record page and is labeled separately. 'Reached +X%' means the price touched
that level at its intraday peak after the signal — it is not a return anyone earned,
and most positions trade below their peak at any given time. The comparison line is
a typical S&P 500 stock measured from arbitrary starting days over the past three
years (69,091 of them). Both measurements use today's index members, which flatters
the past (survivorship). Our quality screen is applied using today's verdicts —
historical screen data does not exist. We show you the full range of outcomes,
including the losing tail, because that is what using a system like this actually
feels like. Not a projection. Not advice."

## 6. COMPLIANCE CHECKLIST (all existing rules still bind)

- No "enter/buy/chase"; "conditions look ripe" language only.
- Peak/MFE stats always labeled "touched, not returns earned, not advice".
- "Hypothetical backtest — not a record of published signals" on every pre-2026 stat.
- No returns-vs-SPY equity comparisons; the baseline is touch-rate vs typical stock.
- Don't expose mechanics (no score math, no % thresholds beyond the setup-agnostic
  descriptions already public, no gate internals).
- Balloons on home remain the LIVE record and keep their existing label/as-of range.

## 7. ASSETS

- `touch_curve_chart.html` — approved 3-panel mockup (self-contained, inline SVG/JS,
  animations: dashed baseline fades in, solid line draws, gap tint fades, marker last).
- `fan_chart_demo.html` — approved cone mockup (panel A = board-rules cone to publish;
  panel B = raw cone, research only, do not publish).
- Data JSONs: touch_curve_data.json, cone_data_both.json (regenerate via the two
  study scripts if definitions ever change).
