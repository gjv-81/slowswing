# PREREGISTRATION: STS Fast Lane (1 to 5 day model)

*Draft written Sep 30 2026, BEFORE any of the new data (greek flow, IV rank history, 3 year greeks) has been compared with returns. Once GJ approves it, the text is frozen. Any later change is added as a dated amendment at the bottom, never edited in place.*

Companion files: STS_DATA_HANDOFF.md (datasets), STS_FLAME_UW_PREREG.md (template and flame history), STS_flame_final.xlsx and STS_flame_expansion.xlsx (flame results that form the benchmark).

## 1. The question

Which options and tape features predict a stock's 1 to 5 day return relative to SPY? And does a weighted combination of them (the "fast score") beat the flame rules we already have?

The model is for trading **shares** and is **long only** for version 1. Bearish readings enter as features that lower the score, not as short trades. The website is the eventual destination, so every feature is tagged by whether a licensed commercial feed could supply it later.

## 2. Data windows and universe

* **Window A (options aggregates):** Oct 2024 to Sep 2026, about 500 trading days, options_volume for core plus expansion names.
* **Window B (greek flow):** Jan 2025 to Sep 2026, about 436 trading days, 253 most liquid names plus SPY, QQQ, IWM and the 17 watchlist names.
* **Greeks (GEX):** Sep 2023 onward, about 1,670 names.
* **IV rank:** Sep 2025 onward only. For earlier dates a proxy is used: the percentile of 20 day realized volatility within its trailing year. It is reported separately so the proxy never passes for the real thing.
* **Short interest, short volume, FTDs:** 2021 onward.
* **Dark pool:** only the first 40 days after slow lane signals, so it is tested **inside setups only**, never as a universal feature.
* **Price (setups, Stage 3):** daily_data_v2, 10 years, about 1,026 names; daily_data_ext, 3 years.
* **Liquidity floor (all stages):** price at least $10, 20 day median dollar volume at least $20M, median daily option volume at least 1,000 contracts (options stages only).
* **Survivorship:** every universe is today's constituents. All results are ceilings, and this is stated in every output.

## 3. Timing and target (no lookahead)

* Features use only data available at the close of day t.
* **Publication lags:** short interest becomes usable 10 trading days after its settlement date, and FTDs 15 trading days after their date. Everything else is end of day.
* **Entry:** the open of day t+1. The close of day t is also reported, to compare with the flame tables.
* **Horizons:** d1 through d5, measured from the entry to the close of day t+k.
* **Target:** the stock's return minus SPY's return over the same window ("excess return"). The primary horizon is **d3**. All five horizons are always reported.
* **Costs:** 0.10% round trip is subtracted from every trade.

## 4. Declared feature list (nothing gets added after data is seen)

**Options flow (Window A)**

* F1 Ask side call surge: log of today's ask side call volume over its own trailing 21 day median
* F2 Directional premium Z: bullish premium minus bearish premium, as a Z score against its trailing 21 days (UW's bullish premium = calls bought at the ask plus puts sold at the bid)
* F3 Call share of aggressive buying: ask side call volume divided by ask side call plus ask side put volume
* F4 Net premium trend: 5 day sum of net call premium minus net put premium, scaled by 21 day average total premium
* F5 Open interest change: 1 day and 5 day percentage change in call OI and in put OI

**Greek flow (Window B)**

* F6 Directional vega flow Z against its trailing 21 days, plus F6b: the last 60 minutes' share of the day's directional vega flow
* F7 Directional delta flow Z against its trailing 21 days

**Positioning and volatility**

* F8 Net GEX: call gamma plus put gamma, scaled by its trailing 21 day average absolute level, with a negative GEX flag
* F9 IV rank, or the realized volatility proxy before Sep 2025
* F10 Short interest as a share of float, and days to cover (with lag)
* F11 FTDs relative to average volume (with lag)
* F12 Short volume ratio Z against its trailing 21 days

**Price context**

* P1 Count of consecutive prior flat days (each within 1%)
* P2 5 day and 20 day return
* P3 Distance below the 52 week high
* P4 Above the 200 day average (flag)
* P5 Range compression: 5 day ATR over 50 day ATR
* P6 Today's gap
* P7 Volume Z against the trailing 50 days

**Membership flags:** S2, B2, DLB, D200G signal active; core or expansion name.

**Declared interactions (the only four allowed):**

* I1 F2 × negative GEX flag (does flow matter more when dealers are short gamma?)
* I2 F1 × P1 of 1 or more (the flame's quiet tape logic as a continuous term)
* I3 F1 × a 20 day run of 10% or more (B2 continuation)
* I4 F2 × quiet dark pool (setup level only, where dark pool exists)

## 5. Stage 1: screen each feature alone

* Each day, rank the eligible stocks into five buckets by the feature. Record the average excess return of each bucket, d1 to d5.
* Split the window into first half and second half, and report both.
* Statistics use one value per day (the day's top minus bottom spread), so thousands of correlated stocks on one day count once.

**A feature SURVIVES only if all of these hold:**

1. The d3 spread between the top and bottom buckets has the same sign in both halves.
2. The t statistic of that spread over days is at least 2.0 for F1 and F2 (prior evidence from the flame), and at least 2.5 for every other feature (no prior, many tests).
3. At least 3 of the 4 steps between adjacent buckets move in the same direction.

**A feature FAILS** if the sign flips between halves, even if the full period looks strong.

## 6. Stage 2: the fast score

* **Model:** ridge regression on the surviving features and interactions. Each day features are standardized across stocks and clipped at 3 standard deviations. The target is d3 excess return, with the extreme 1% at each end capped.
* **Walk forward:** an expanding training window of at least 9 months, retrained monthly, then used to score the following month. A 5 day gap between training and test prevents overlapping returns from leaking. Only out of sample scores are ever reported.
* **Evaluation:** deciles of the fast score each day. For the top decile, report the win rate, average, median, average win, average loss and their ratio, d1 to d5; the number of distinct tickers; and episodes (the same ticker within 5 days counts once). Core and expansion are reported separately, and first and second half separately.

**The fast score PASSES only if all of these hold:**

1. Top decile d3 average excess of at least +0.40% after costs, with a win rate of at least 54% and a win/loss ratio of at least 1.0.
2. Positive in both halves and in both core and expansion names.
3. Deciles 8, 9 and 10 are in rising order.
4. It **beats the existing flame rules**: on the same test months, the top decile's d3 average is at least equal to the flame cohort's, or matches it within 0.10% while producing at least 3 times as many trades.

**If it fails, the flame stays as the fast lane signal,** and the new features are logged forward only.

## 7. Stage 3: new setup families (price only, 10 years)

Each family is tested on price data alone over three eras: 2016 to 2019, 2020 to 2022, and 2023 to Sep 2026. A ticker can trigger the same setup at most once per 10 trading days.

* **PB, pullback in an uptrend:** close above the 200 day average, 50 day above 200 day, and either 3 or more consecutive down closes or a close in the bottom 20% of the 10 day range, with a 5 day return of 3% or worse.
* **BO, breakout continuation:** a close at a new 52 week high on volume at least 1.5 times its 50 day average.
* **SQ, volatility squeeze release:** 5 day ATR at most 0.6 times the 50 day ATR, then an up close with a range at least 1.5 times the 20 day average range.
* **PEAD, post earnings drift:** a gap up of at least 4% on the first session after earnings, closing in the top half of the day's range. Tested only on names with reliable earnings dates.
* **GAP, non earnings gap and hold:** a gap up of at least 3% with no earnings within 2 days, closing at or above the open.
* **WB, washout bounce:** a 5 day return of 12% or worse (or 2 day RSI at 5 or below), then the first up close.
* **SQZ, short squeeze candidate:** short interest at least 15% of float (with lag), days to cover at least 5, then an up day of at least 3% on volume at least 2 times average. Tested 2021 onward only.

**A family PASSES if:** its d3 average excess is at least +0.30% after costs in at least 2 of the 3 eras, with a win rate of at least 53%, a win/loss ratio of at least 1.0, and at least 300 episodes.

**Options overlay (Window A, passing families only):** within the family, split trades into thirds by fast score. The overlay adds value if the top third beats the bottom third by at least 0.30% at d3, in both halves.

## 8. Small studies

* **Strike magnet:** on the 2,341 flame days with strike data, does price reach the strike with the heaviest ask side call volume within 5 days more often than an equally distant strike on the opposite side? Pass: at least 8 points higher hit rate. The strike anatomy null lowers expectations here.
* **Gamma flip (17 watchlist names only):** is the d3 excess return different above vs below the flip level? Descriptive only; the sample is too small to pass or fail.
* **B2 expansion timing (forward tag):** log d2 and d5 returns for core and expansion B2 flames separately in fast_lane_log.csv. Review after 30 live expansion flames.

## 9. Output form (decided by rule, not by preference)

* If the fast score passes and rises steadily across deciles: publish it as **2 or 3 tiers**, with cut points set on training data only and then checked out of sample.
* If only one family or one interaction carries the edge: it becomes a **signal**, like the flame.
* If nothing passes: **the flame remains** the fast lane, and the new features are logged forward.

## 10. House rules that apply throughout

* Anything found after looking at the data is a **tag to forward test, never a filter.**
* Pass/fail bars are never adjusted after results are seen.
* Nested cells (for example 1 flat day includes 2 flat days) are never read as independent evidence.
* Every table carries win rate, average, median, average win, average loss and ratio, d1 to d5.
* Every result is a ceiling (survivorship, current constituents, no delisted names).

## 11. Known gaps and forward collection

* **Sweep urgency and sweep cluster count** cannot be backtested (flow alerts are snapshot depth only). They need the $150 personal API plan to log nightly, starting when that plan is active. They become testable after 3 to 6 months.
* **Net Drift by expiry bucket** is too costly to backfill. It is forward only, on the same plan.
* **Strike level GEX and flip levels** for more than the 17 watchlist names are forward only.

## Amendment log

*(empty; dated entries only, added after approval)*
