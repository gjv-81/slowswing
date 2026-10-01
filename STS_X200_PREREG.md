# PRE-REGISTRATION — X200 revival (trend-initiation setup)
*Written 2026-09-30, BEFORE the backtest runs. Do not edit after results.*

## Motivation
The ML score is a markdown detector by construction (QQE −0.99 penalizes hot
rebounds; mom6 lags after crashes) — it structurally cannot catch a washed-out
stock BEGINNING its uptrend (case study: CRM, Aug 2026, score peaked 1.71).
X200 exists in the original ladder ("deep stock freshly crossing its 200-SMA",
10-yr backtest +10.5%/12wk) but was never wired into the score-gated pipeline.

## Signal definition (all conditions at the close of day t; enter next open)
1. Price >= $25 (universe floor; the site's $50 spec applies at publication).
2. WASHED OUT: at some point in the prior 126 bars the stock was >= 25% below
   its (then-current) 252-bar high.
3. TIME BELOW: >= 20 of the prior 60 bars closed below the 200-SMA
   (a genuine stay below the line, not a one-day wiggle).
4. FRESH CROSS: today's close > 200-SMA, the last 3 closes are all above it,
   and the first close of this above-streak occurred within the last 10 bars.
5. COOLED (the CRM lesson): QQE (smoothed-RSI feature, same formula as the
   score) < 0.20 today — excludes vertical-rebound crossings; we want the
   consolidation after the reclaim, not the spike through it.
6. Refractory: no X200 signal for this ticker in the prior 40 bars.
NO score requirement — that is the point.

## Outcomes
wk4 (20 td) and wk12 (60 td) returns from next-session open; excess vs SPY at
wk12; max dip within the 12 weeks. Walk-forward on 10 years of daily_data_v2
(primary cohort) and, when available, daily_data_slow_ext (quality mid/large
expansion — transfer cohort).

## PASS / FAIL BARS (pre-committed)
- PRIMARY: v2 cohort, n >= 300 signals over 10 years, avg wk12 >= +8%,
  excess vs SPY >= +2%, wk12 win >= 55%. (Original ladder figure: +10.5%.)
- TRANSFER: slow_ext cohort directionally consistent (positive excess).
- FAIL any -> X200 stays retired; the trend-initiation gap becomes a
  feature-engineering question for the options-native model instead.
- PASS -> X200 joins the nightly scan as its own code (score-exempt),
  paper-tracked like everything else; site publication decided separately
  at a later checkpoint once it has live history. Presented at the Oct 15
  review as agenda item 8.
