# PREREGISTRATION: Volatility and smirk inside the slow lane setups (1 to 5 day outcomes)

*STATUS: APPROVED by GJ on Oct 3 2026 and FROZEN. v2 written Oct 2 2026 (v1 the same day had one model; v2 splits it into two models to lengthen the test, after confirming UW has IV from Jul 17 2023 and the smirk from Sep 16 2024). None of the inputs below has been compared with returns inside these setups. Once approved the text is frozen; later changes go in a dated amendment at the bottom.*

## 1. The question

When a stock is in an S2, B2, D200G or X200G setup, does its volatility picture predict which trades do better over the next 1 to 5 days? If so, how much weight does each input carry? And does the smirk add anything beyond implied volatility?

Long only, shares. The comparison is the setup's own trades: does the model pick a better subset than taking every signal?

## 2. Setups and trade definitions

* **S2, B2, D200G:** the slow lane definitions (first day of score at least 2, 20 day refractory; S2 within 10% of the 52 week high, B2 10 to 25% below, D200G at least 25% below and above the 200 day average). Same code as build_fast_features.py.
* **X200G:** exactly the frozen definition in STS_X200G_PREREG.md (x200g_observe.py logic), 40 bar refractory. This study is descriptive for X200G and changes nothing in its observation plan.
* **Analysis A, signal day only:** one trade per signal, entered at the next open after the signal day.
* **Analysis B, any day in the first 40:** every trading day inside the signal's first 40 days is a possible entry (the flame's frame). Rows from one signal overlap, so episodes (signals) are counted and reported.
* A and B are judged separately.
* Liquidity: price at least $10, 20 day median dollar volume at least $20M. Rows need every input of the model being tested.

## 3. Inputs (all known at the close of the entry decision day; nothing else enters)

* **V1 IV level:** UW 30 day implied volatility (vol_realized_5y, implied_volatility column).
* **V2 IV rank (6 month):** our own, the share of the trailing 126 trading days whose V1 was below today's V1, on a 0 to 100 scale. Chosen before any data was examined, to start the data in Jan 2024. UW's iv_rank and iv_rank_hist are not used.
* **V3 IV minus realized:** V1 minus our own trailing 21 day realized volatility from prices. UW's realized_volatility column is NOT used (it measures the future window).
* **V4 IV change:** V1 today minus V1 five sessions ago.
* **V5 Smirk:** 25 delta put IV minus call IV on the Jan 15 2027 expiry (rr_skew_jan27).
* **V6 Smirk change:** V5 today minus V5 five sessions ago.
* **Setup flags:** S2, B2, D200G, X200G (combined models; X200G has too few signals for its own weights).

Inputs are standardized with the TRAINING window's mean and standard deviation and clipped at 3 standard deviations.

## 4. The two models

| | Inputs | Data from | Test months (after at least 9 months of training) |
|---|---|---|---|
| **Model 1, volatility only** | V1, V2, V3, V4 + setup flags | Jan 2024 | about Oct 2024 to Sep 2026 |
| **Model 2, volatility plus smirk** | V1 to V6 + setup flags | Sep 16 2024 | about Jun 2025 to Sep 2026 |

Each model is run for Analysis A and Analysis B, so there are four graded combinations.

## 5. Outcomes

* Excess return = stock return minus SPY return, from the next open to the close of the horizon day, minus 0.10% round trip cost.
* **Primary horizons:** d1, d2, d3, d4, d5. **Pass/fail is judged at d3.**
* **Secondary (reported, no bar):** wk2 (10 sessions) and wk4 (20 sessions).
* Every table shows: n, average, win %, median, average win, average loss, win/loss ratio.

## 6. Model and validation

* Ridge regression (the same family as the slow lane score), one model per horizon, target capped at its 1st and 99th percentile.
* Walk forward: expanding training window of at least 9 months, retrained monthly, scoring the next month only. A purge gap equal to the horizon (5 sessions for d1 to d5, 10 for wk2, 20 for wk4) separates training from test. Only out of sample scores are graded.
* **Weights reported two ways:** (1) the average out of sample weights across the monthly refits (what the test actually used); (2) descriptive per setup ridge fits on the full sample (no pass/fail, labelled descriptive).

## 7. Pass bar (same as the fast score, per GJ), applied to each of the four combinations

Rank each test month's trades by model score. The **top 10%** passes only if ALL hold at d3:

1. Average excess return at least **+0.40%** after costs.
2. Win rate at least **54%**.
3. Average win at least as large as average loss (ratio at least 1.0).
4. Positive in both halves of that combination's test window.
5. Deciles 8, 9 and 10 in rising order.
6. **Beats the comparison:** the top 10% average beats the average of ALL trades in the same setups and months by at least 0.30%.

**Smirk question:** the smirk "adds value" only if Model 2 passes AND, on Model 2's test months, its top 10% beats Model 1's top 10% by at least 0.20% at d3. Otherwise the smirk adds nothing beyond implied volatility.

Core versus expansion names are reported but not required.

## 8. Robustness (reported, not used for pass/fail)

* Same results excluding each day's top 10% of names by borrow fee (Muravyev, Pearson and Pollet 2025).
* Each setup's top 10% separately (X200G descriptive only).
* Single input sorts: each input alone, top third versus bottom third inside the setups.
* Model 1 rerun with a 12 month IV rank on its shorter window, to show the 6 month choice is not driving the result.

## 9. What a result means

* **Pass:** the volatility filter becomes a forward tag on the nightly board for 3 months. It becomes a rule only if the live record confirms. It never changes X200G's frozen definition before its Q1 2027 review.
* **Fail:** volatility inputs add nothing at 1 to 5 days inside these setups. The wk2 and wk4 numbers may motivate a separate preregistration at those horizons, never a reinterpretation of this one.
* House rules apply: nothing found after looking becomes a filter; bars do not move.

## Amendment log

*(empty)*
