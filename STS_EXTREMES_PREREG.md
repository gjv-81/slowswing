# PREREGISTRATION: Extreme flow, the bearish side, and events

*STATUS: APPROVED by GJ on Oct 3 2026 and FROZEN. Written after four preregistered null results on the same archive (fast score, literature features, volatility inside setups, seller exhaustion), which is declared openly. None of the cells below has been computed. Once approved the text is frozen; later changes go in a dated amendment.*

## 0. Why this study, and what would make it different

The earlier tests ranked all stocks into fifths and asked whether the top fifth beat the bottom fifth. That averages over about 180 names a day. The flame, the one signal that works, is a cutoff at the extreme (3x normal), inside a setup. This study asks three questions the earlier tests did not:

1. Do the **extreme 1%** readings of each flow measure predict, even though typical readings do not?
2. Does **aggressive put buying** warn, and is "do not enter this name this week" a useful rule inside the setups? (Long only system; the bearish signal is used as an avoid, never as a short.)
3. Before a stock's own **earnings**, does an unusual call or put surge point to the reaction direction?

## 1. Data

* `options_volume` and `options_volume_ext`: daily ask side and bid side call and put volume and premium, Oct 2024 to Sep 2026, about 1,760 names.
* `greek_flow_daily`: directional vega and delta flow, 253 liquid names, Jan 2025 on (Part A only, reported separately because of the smaller universe).
* `earnings_hist`: report dates and pre or post market timing.
* Prices: daily_data_v2 and daily_data_ext; SPY benchmark.
* Liquidity: price at least $10, 20 day median dollar volume at least $20M, 21 day median option volume at least 1,000 contracts.
* Survivorship: current constituents only; every result is a ceiling.

## 2. Measures (close of day t)

Each measure is expressed relative to the stock's own trailing 21 day median (ratio), so "extreme" means extreme for that stock:

* **M1 Call surge:** ask side call volume / its 21 day median.
* **M2 Put surge:** ask side put volume / its 21 day median.
* **M3 Net aggressive premium:** (bullish premium minus bearish premium) / 21 day average total premium.
* **M4 Directional vega flow:** dir_vega_flow / 21 day median absolute dir_vega_flow (253 names).
* **M5 Directional delta flow:** dir_delta_flow / 21 day median absolute (253 names).
* **Quiet day flag:** absolute close to close move at most 1% (the flame's context).

## 3. Part A: extremes across all stocks

* Each day, rank eligible stocks on each measure. **Top 1%** (about 9 names a day), **bottom 1%**, and the **middle 98%**.
* Outcomes: excess return vs SPY from the next open, after 0.10% cost, at d1, d3, d5 and wk2. Primary: **d3 for M1, M2, M3; wk2 reported.**
* Also split each extreme by the quiet day flag (the flame's logic) and by whether an S2, B2, DLB, D200 or D200G signal is active.
* Statistics use one value per day (that day's extreme group average minus the middle), Newey West t with lag 3. Halves reported. Count distinct tickers in the extreme group.

**Pass (per measure, per side):** the extreme group beats (for M1, M3 top and M4, M5 top) or trails (for M2 top and M3 bottom) the middle 98% by at least **0.40% at d3**, same sign in both halves, |t| at least 2.5, at least 40 days and 150 extreme observations.

## 4. Part B: the bearish side as an avoid rule inside the setups

* Universe: every day inside the first 40 days of S2, B2, DLB, D200, D200G signals (X200G descriptive).
* **Warning flag W1:** M2 at least 3 (put surge 3x) AND ask side put volume greater than ask side call volume, on a quiet day (mirror image of the flame). **W2:** same without the quiet day requirement.
* **Question 1 (does the warning predict):** days with W1 vs matched setup days without, d3, d5, wk2, wk4 excess.
* **Question 2 (is the avoid rule useful):** take every signal's **signal day entry** (the slow lane trade). Split signals into "W1 fired in the 5 sessions before or on the signal day" vs not. Compare wk4 and wk12 (where available) excess. Then the forward version: among entries on any day in the window, does skipping days with W1 in the prior 5 sessions raise the average wk4 of the remaining entries by at least 0.75%?
* Report win %, average, median, average win, average loss, ratio, and number of signals affected (an avoid rule that removes 2% of signals is not worth having even if it passes).

**Pass:** W1 days trail matched non W1 days by at least **0.75% at wk2**, same sign in both halves and in both setup groups (recovery: DLB, D200, D200G; momentum: S2, B2), |t| at least 2.5, and the avoid rule removes at least 5% of entries.

## 5. Part C: before earnings

* For every eligible stock and every company reported earnings date (pre market: that day is the reaction session; post market: the next session).
* **Pre window:** the 5 sessions ending the day before the reaction session.
* **Unusual for this stock:** M1 or M2 maximum in the pre window at least 3, compared against the stock's own pre earnings windows for its prior 4 reports where available (so routine pre earnings call buying is not counted as unusual). Two flavours reported: raw 3x, and 3x AND above the stock's own prior pre earnings maximums.
* **Outcome:** reaction session return (open to close of the reaction session, and prior close to reaction close), and d3 after the reaction, both vs SPY.
* **Direction test:** call surge events, mean reaction return and share positive; put surge events, mean and share negative; events with neither, as the base.

**Pass:** call surge events show a reaction at least **+1.0%** above the base and put surge events at least **1.0%** below, both with |t| at least 2.5 (one value per event, events are independent), same sign in both halves, at least 150 events per side. Partial pass (one side only) is reported as such.

## 6. Robustness (reported, not graded)

* Top 2% and top 0.5% versions of Part A (the 1% cut is primary; neighbours must be directionally consistent for a pass to be read as robust).
* Excluding each day's top 10% borrow fee names.
* Core vs expansion names.

## 7. What a result means

* Any pass becomes a **forward tag** logged nightly for 3 months (a bearish pass becomes an "avoid" tag on the board, never an exit), promoted to a rule only if the live record confirms.
* Fail on all three parts: the remaining edge in this data, if any, lives in intraday discretionary use, which the archive cannot test. Research on options overlays stops until a different data type (intraday) is in hand.
* House rules: thresholds and bars do not move; anything noticed after looking is a tag, never a filter; X200G's observation plan is untouched.

## Amendment log

*(empty)*
