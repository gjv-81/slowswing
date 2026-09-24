# PRE-REGISTRATION — Flame study, stage 2 (Unusual Whales classified flow)
*Written 2026-09-23, BEFORE any UW data is seen. Do not edit after data arrives.*

## Background (three raw-volume results already in hand)
- DLB/D200G ("Phoenix" pilot): flame added nothing (matched 3d gap +0.09%). NULL.
- B2/S2 pilot: matched 3d gap +0.37% (bar was +0.50) — near-miss, direction consistent.
- Flat-then-flame exploration: S2 quiet-flame d1 win ~57% vs ~48% control (all flat
  depths); B2 2-flat d3-d5 elevated (n=37). Found EXPLORING — hypothesis, not finding.

## New test variable
Ask-side (aggressive) call buying from UW classified flow, replacing raw chain volume:
daily per-ticker sum of call premium/volume executed AT OR ABOVE the ask (UW side
classification), flame = that quantity >= 3x its own trailing-21d median AND > put
ask-side equivalent. If UW's flow-alerts granularity is per-alert rather than
side-summed, use: count and premium of UW call alerts per ticker-day.

## PRIMARY cells (chosen from stage-1 results — declared as such)
1. S2 signals, prior 3 days each within ±1%, flame day within ±1% -> d1..d5 win rates
2. B2 signals, prior 2 days each within ±1%, flame day within ±1% -> d1..d5 win rates
Controls: identical flat/setup days without ask-side flame. Reference = flame-day close.

## CONSISTENCY REQUIREMENTS (protect against cell-picking)
- Report the FULL grid: {S2,B2} x {1,2,3 flat days} x {d1..d5}, plus all-days matched
  test (same-day-move buckets) for all four setups.
- A pass requires the primary cells to clear the bars AND the neighboring flat-depth
  cells to be directionally positive (graceful degradation, not two isolated spikes).

## PASS / FAIL BARS
- S2 primary: d1 win rate >= 57% with n >= 40 flame days AND >= +6 pts over control.
- B2 primary: d3 win rate >= +6 pts over control with n >= 30.
- Matched all-days gap (B2+S2 combined) >= +0.50% at 3d strengthens; not required.
- FAIL any of: primary cells below bars; neighbors contradict sign; n too small ->
  the flame idea is CLOSED (three nulls + failed confirmation). No further spend.
- PASS -> justify $63/mo UW dashboard/API for a 3-month live forward test, badge still
  NOT on the website until the forward test confirms.

## Trial mechanics
- UW API 7-day free trial (card required — CANCEL BY DAY 7).
- Hour 1: probe historical depth (one ticker, 2025-09 date). If history does not
  reach ~Sep 2025, abort trial (cancel immediately), study closed as UNTESTABLE-CHEAP.
- Endpoints: /api/ticker/{t}/flow-alerts (date param), option-contract flow as needed.
- Tickers: only the ~150 B2/S2 tickers with flat-window signal days (list generated
  from stage-1: options_pilot_cruise/_signals.csv) — small, focused download.
