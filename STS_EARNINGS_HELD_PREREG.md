# PRE-REGISTRATION — "Earnings held" (gap-up that held, signal 3–9 sessions later)
*Written 2026-10-10, BEFORE the holdout is touched. Do not edit after results.*

## Where this came from (declared honestly)
The "Earnings tailwind" study (2026-10-09) FAILED its primary cell (gap-up then faded).
In the SAME full grid, the opposite cell looked good: a Phoenix/Cruise signal firing while
price was still at or above the earnings reaction-day close (gap HELD), pooled
+3.4% excess vs +1.0% control at 20 sessions, 63% vs 57% win, n=212, positive in both
eras; and a by-timing split suggested signals 3–9 sessions after the reaction did
better than 0–2. That cell was found AFTER looking at the data on daily_data_v2
(1,025 tickers). It therefore cannot be confirmed on daily_data_v2. This study
confirms or kills it on a universe never used in that search.

## Hypothesis
Signals (S2/B2/DLB/D200G) that fire 3–9 sessions after an earnings reaction session
with a gap-up of ≥ +4%, with the signal-day close ≥ the reaction-day close (the gap
HELD), outperform signals with no earnings reaction in the prior 10 sessions, at 20
sessions, excess vs SPY.

## Holdout data
- Universe: daily_data_ext tickers NOT present in daily_data_v2 (1,239 names; mostly
  smaller caps — a tougher, different universe, which is the point).
- Earnings tags and outcomes computed exactly as in earnings_tailwind_study.py.
- Cells: CONTROL (no reaction in prior 10 sessions); HELD_3_9 (PRIMARY);
  HELD_0_2; FADED (any timing); E_FLAT; E_DOWN.

## Pass / fail
- PASS: HELD_3_9 pooled over DLB+D200G+B2 has n ≥ 60 AND mean xs20 ≥ CONTROL + 2.0 pts
  AND win(r20>0) ≥ CONTROL + 5 pts AND xs20 is ≥ CONTROL in BOTH eras (2016–2020,
  2021–2026) AND HELD_0_2 is not below CONTROL − 2 pts (graceful degradation).
- FAIL otherwise → closed; the two earnings studies together are recorded as
  "post-earnings timing does not add to the setups". No further cells will be tried.
- PASS → forward test on the live book for 3 months (tag only in the tracker), then
  a "⚡ Earnings held" badge on the board if the forward cohort agrees. Not before.
