# PREREGISTRATION: Is the flow edge concentrated in a corner of the market?

*STATUS: APPROVED by GJ on Oct 3 2026 and FROZEN, with one change made at approval before any data was examined: every table reports d1, d3, d5, wk2 and wk4 (win rate, average, median, ratio), and for Corner 2 (sector rotation) wk2 is a second graded horizon alongside d3, because a rotation wave may run for weeks; this raises Corner 2's graded cells from 4 to 8 and the chance based expectation accordingly. GJ's own corner: none. Written after five preregistered null results on this archive (declared). None of the cells below has been computed. Once approved the text is frozen; later changes go in a dated amendment.*

## 0. The idea

Alpha, if it exists, is concentrated, otherwise it would be a market factor. The earlier tests pooled all liquid stocks (or split only by setup and quiet day). This study names three corners IN ADVANCE, each with a reason from the literature or from market structure, splits the same universe into the corner and its complement, and asks whether the flow signals work in the corner and not outside it. The complement is the control. No stock, sector or period is chosen after looking.

## 1. Data and universe

* Same rows as the extremes study: all liquid stocks (price at least $10, $20M daily dollar volume, 1,000 option contracts a day), Oct 2024 to Sep 2026, about 900 names a day.
* Measures: M1 call surge, M2 put surge, M3 net aggressive premium (ask side classified), each relative to the stock's own 21 day median. M4 vega flow where available (253 names), reported but not graded (too few names for corner splits).
* Outcomes: excess return vs SPY from the next open, after 0.10% cost. Reported at d1, d3, d5, wk2, wk4 with win rate, average, median, average win, average loss and ratio. Graded: d3 for Corners 1 and 3; d3 AND wk2 (either can pass) for Corner 2.

## 2. The three corners (declared; each splits the universe into thirds or halves by a rule)

**Corner 1: options are the venue.** Option to stock volume ratio = 21 day average option contracts x 100 / 21 day average share volume, computed per stock. Each day, stocks are split into thirds by this ratio. Corner = top third. Reason: informed traders choose options where options are liquid relative to the stock (Easley, O'Hara and Srinivas 1998; Johnson and So 2012; Ge, Lin and Pearson 2016 found flow effects concentrated here).

**Corner 2: leading sectors (sector rotation).** Sector from yfinance (11 GICS sectors). Sector relative strength = average 20 day return of the sector's stocks minus RSP's 20 day return, computed each day. Corner = stocks in the top 3 sectors that day. Reason: GJ's hypothesis that money rotates into themes in waves and flow catches the next wave. Also reported: bottom 3 sectors (is flow a bottom catcher instead?).

**Corner 3: hard to borrow and heavily shorted.** Each day, split by borrow fee (daily fee rate) into thirds; corner = top third. Also a second version: short interest at least 10% of float. Reason: Muravyev, Pearson and Pollet 2025 and Neuhierl et al. 2024 find option signals concentrated in costly to short names.

**GJ's corner:** none.

## 3. The signals tested inside each corner

* **S1 Flame style:** M1 at least 3 AND calls over puts on the ask side AND quiet day (close within 1%). Long. (Across all stocks, not only inside S2/B2; the setup version is already validated.)
* **S2 Put warning:** M2 at least 3 AND puts over calls on the ask side. Expected negative.
* **S3 Extreme call, top 1% within the corner** vs the corner's middle.
* **S4 Extreme put, top 1% within the corner** vs the corner's middle.
* Each signal is also run inside the complement (the stocks outside the corner) with identical rules.

## 4. The test

For each corner x signal: the signal's excess return (d3) vs matched non signal days inside the corner; the same inside the complement; and the **difference of differences**: (corner effect minus complement effect). One value per day, Newey West t, halves reported.

**Pass (per corner x signal):**
1. The signal effect inside the corner is at least **0.40% at d3** in the declared direction (S1, S3 positive; S2, S4 negative), |t| at least 2.5, same sign in both halves, at least 150 signal days from at least 40 distinct tickers.
2. The corner effect exceeds the complement effect by at least **0.30%** (the concentration claim), |t| at least 2.0 on the difference.
3. The neighbouring split (middle third) sits between the corner and the complement (graceful gradient, not an isolated cell). For Corner 2, the top 3 sectors must beat the middle 5 sectors as well as the bottom 3.

**Multiple comparisons:** Corners 1 and 3: 4 signals x 1 horizon = 8 cells; Corner 2: 4 signals x 2 horizons = 8 cells; 16 graded cells in all. About 0.8 would clear |t| 2.5 by chance. For wk2 the Newey West lag is 10 and the pass size is 0.75% (corner effect) and 0.50% (corner minus complement), scaled for the longer horizon. A single pass with no neighbour support is reported as "one cell, treat as chance" unless the gradient (condition 3) holds. Two or more passes in the same corner is the result that would count.

## 5. Robustness (reported, not graded)

* wk2 horizon.
* Each corner at the half split instead of thirds.
* Corner 2 with 60 day sector relative strength instead of 20.
* Setup interaction: corner x inside S2/B2 (small cells, descriptive).
* M4 vega flow inside each corner, 253 names, descriptive.

## 6. What a result means

* **Pass in a corner:** the corner becomes a declared universe for the flame style signal, logged as a forward tag for 3 months. Promotion to the fast lane only if the live record confirms.
* **Fail everywhere:** the flow edge is not concentrated in any corner we can name from end of day data. Options overlay research stops, per the extremes prereg, until intraday data is in hand.
* House rules apply: thresholds do not move; no corner is added or redefined after looking; survivorship makes every result a ceiling; X200G's observation plan is untouched.

## Amendment log

*(empty)*
