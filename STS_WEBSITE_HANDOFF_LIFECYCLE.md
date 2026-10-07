# STS → WEBSITE HANDOFF #5 — Lifecycle change: Retired moves to 12 weeks (2026-10-06)
*Paste into the website chat. Backend (tracker phase logic) is DONE; this covers
the board display, scorecard layout, and the dated methodology note.*

## The change and the evidence
Retirement moves from 4 weeks to 12 weeks — the system's true horizon. Active
keeps its exact definition (up < 5%, down names included) but now runs to 12
weeks; Extended likewise. Validated on 4,865 historical DLB/D200G signals:
ENTERING an Active-state name at week 4 returned +6.2% (58.3% win) over the
following 8 weeks — and names DOWN >10% at week 4 (the BX-state) were the best
late entry of all: +8.0%, avgWin +25.2%. Extended names at week 4 paid least
(+5.3%) — "ran already, not prudent" is confirmed. Price defines actionability;
the calendar doesn't. (Context: crash-approach DLB averages +5.9% at wk4 but
+15.1% at wk12 — the 4-week grade was measuring a 12-week system with the
wrong ruler, and booking names like BX as losses at their statistically
ugliest moment: median path-low is day 5, and 19% of eventual +25% winners
dip more than 20% en route.)

## What changes on the site
1. BOARD: Active will grow (~18 -> ~70 names at current book size) because
   4-12 week names that haven't run stay enterable. Display needs to handle
   this: add an AGE column (weeks since signal), default-sort fresh-first,
   and consider a visual break or filter chip "Fresh (<4wk) / Seasoned
   (4-12wk)" INSIDE the Active tab. Extended tab similarly gains names.
2. SCORECARD / TRACK RECORD: the final grade is now the wk12 outcome.
   Show BOTH columns: wk4 ("early check-in") and wk12 ("final"), each locked
   at its own maturity, never restated. The Retired table will be EMPTY until
   ~Oct 13 when the first entries reach 12 weeks — show "first 12-week
   results arrive mid-October" rather than an empty table.
3. BALLOONS / MONTHLY SNAPSHOTS: UNCHANGED. build_stats.py computes from
   completed 4-week windows by entry date, not phase labels. Nothing restates.
4. METHODOLOGY NOTE (dated 2026-10-06), suggested copy:
   "Update: positions now remain on the board for their full 12-week tracking
   window (previously the scorecard closed at 4 weeks). The setups we publish
   are designed around a 12-week horizon, and our research shows names still
   near their signal price in weeks 4-12 historically remained attractive —
   while names that had already run 5%+ did not. The 4-week numbers remain in
   the track record as an early check-in; the final grade now comes at 12
   weeks. Nothing in past records has been restated."
5. COPY nuance: an Active name that is DOWN is still labeled Active on
   purpose — the research basis is in the methodology note; never phrase it
   as "buy the dip" (no entry language, as always).

## Backend already done
- sts_ml_paper_tracker.py: phase boundary W4 -> W12 (Retired at >60 sessions);
  comments carry the validation numbers. Retired rows always have wk12 filled.
- Internal cohort studies unaffected (they use entry dates + fixed windows).
