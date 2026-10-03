# PREREGISTRATION: Seller exhaustion inside the slow lane setups

*STATUS: APPROVED by GJ on Oct 3 2026 and FROZEN. v2 written Oct 3 2026 (v1 omitted DLB and D200, added at GJ's request; pulse defined as the system's 40 day RS vs RSP after checking the code; both before any data was examined). No input below has been compared with forward returns in this form. Once approved the text is frozen; later changes go in a dated amendment at the bottom.*

## 1. The idea being tested

GJ's thesis: after a setup signal fires, the stock may keep sagging while sellers finish. When short selling fades and dark pool activity dries up, and the STS score and pulse then start to turn up, the stock has likely bottomed and the setup's bullish case can play out. The question is whether these four signs, read on days after the signal, predict better 2 and 4 week returns, and how much weight each one deserves.

Prior evidence: heavy dark pool activity in the first 10 days after a DLB or D200G signal predicted a worse remaining trade (DLB 48.6% win loud vs 57.4% quiet). That was found after the fact. This study is its first proper out of sample check.

## 2. Setups and rows

* **Setups:** S2, B2, DLB, D200, D200G (slow lane code: first day of score at least 2 for S2, B2, DLB, D200G; D200 = at least 25% below the 52 week high and above the 200 day, score not required, first day the condition appears, 20 day refractory) and X200G (frozen definition in STS_X200G_PREREG.md). DLB is the setup where seller exhaustion matters most (below the 200 day line), and it is half of the earlier dark pool evidence. X200G is included with a flag and its own results table; this study is descriptive for X200G and changes nothing in its observation plan.
* **Universe:** core (daily_data_v2) and expansion (daily_data_ext) names. Dark pool and shorts data exist for core names only, so the main model runs on core; expansion rows are reported where inputs exist.
* **Window:** for each signal, trading days 5 to 40 after the signal day (day 0). Days 0 to 4 are excluded because the fading measures need a base.
* **Entries (to avoid counting one situation many times):** for each signal and each flag count k (0 to 4), the FIRST day on which exactly k flags are present is an entry. One signal can therefore contribute at most 5 entries, one per count. All days are also kept as a secondary "every day" analysis.
* **Liquidity:** price at least $10, 20 day median dollar volume at least $20M.
* **Period:** signals from Nov 1 2024 (start of dark pool data) to Sep 2026.

## 3. Inputs, measured at the close of the entry day t (nothing later)

Continuous measures (used by the models):

* **E1 Short selling change:** average daily short volume ratio over days t minus 4 to t, divided by the average over days t minus 24 to t minus 5, minus 1. Negative = short selling fading. (shorts_volume)
* **E2 Short interest change:** latest published short interest as % of float, minus the value published before the signal, in percentage points. Uses only reports available 10 trading days after their settlement date. (shorts_interest)
* **E3 Dark pool change:** dark pool dollars over days t minus 4 to t, divided by dollars over signal days 0 to 4, minus 1. Negative = dark pool quieter than right after the signal. (darkpool_daily_agg)
* **E4 Dark pool vs norm:** dark pool dollars over days t minus 4 to t divided by the stock's median 5 day dollars over the prior 20 days, minus 1.
* **E5 Score change:** STS score at t minus STS score at t minus 5. (computed from prices, same formula as the slow lane)
* **E6 Pulse change:** the system's Pulse (relative strength) is 100 x (stock 40 day return minus RSP 40 day return), price only, RSP = equal weight S&P 500. E6 = Pulse at t minus Pulse at t minus 5, in points.
* **Control, C1:** stock return over days t minus 5 to t. Included so that E5 and E6 are judged on what they add beyond plain recent price movement.
* **Setup flags:** B2, DLB, D200, D200G, X200G (S2 is the reference). Also day in window (t) as a control.

Flags (yes/no, for the readable count and the single flag tables; thresholds fixed here):

* **F1 Short selling falling:** E1 at or below minus 0.15 AND the 5 day ratio is below the stock's 60 day median.
* **F2 Dark pool quiet:** E3 at or below minus 0.30 AND E4 at or below 0.
* **F3 Score rising:** E5 at least +0.30.
* **F4 Pulse rising:** E6 at least +1.0 point.

## 4. Outcomes

* Excess return = stock return minus SPY return from the open of day t plus 1 to the close of day t plus k, minus 0.10% round trip cost.
* **Primary horizon: wk4 (20 sessions). Secondary: wk2 (10 sessions). Reported, not graded: d5 and remaining return to day 60 after the signal.**
* **Classification target:** win = wk4 excess return greater than 0.
* Every table shows: n, average, win %, median, average win, average loss, win/loss ratio, and distinct signals.

## 5. Models

* **Primary: logistic regression** on E1 to E6, C1, setup flags and day in window, inputs standardized on the training window and clipped at 3 standard deviations, light L2 penalty (C = 1.0). Output: probability of a wk4 win.
* **Secondary: XGBoost**, constrained: max depth 3, learning rate 0.05, at most 300 trees with early stopping on the last 20% of the training window, minimum 50 rows per leaf. Same inputs.
* **Walk forward:** expanding training window of at least 9 months, retrained monthly, scoring only the next month, with a 20 session purge gap (the wk4 horizon) between training and test. Test window about Aug 2025 to Sep 2026. Only out of sample scores are graded.
* **Weights:** logistic coefficients averaged across the monthly refits, each with a **block bootstrap** range (resample whole signals with replacement, 1,000 draws, report the 5th to 95th percentile). A weight whose range includes zero is reported as "not distinguishable from zero."
* **Flag count:** the simple 0 to 4 count is reported alongside the models as the readable baseline.

## 6. Pass bar (judged on the primary model, first day entries, core universe, wk4)

All must hold:

1. Out of sample AUC at least **0.55**.
2. The model's **top third** of entries beats the **bottom third** by at least **+1.5%** excess at wk4.
3. Top third win/loss ratio at least 1.0 and win rate at least 52%.
4. Conditions 1 and 2 hold in **both halves** of the test window.
5. Condition 2 holds separately within the **recovery group (DLB, D200, D200G)** and within **S2/B2** (X200G excluded from grading).
6. The top third beats "all entries at the same day in window" by at least +0.75% at wk4 (so the result is not just the setup or the timing in the window).

**XGBoost comparison:** if its out of sample AUC exceeds logistic by 0.02 or more, the interaction it leans on is reported as a tag to forward test, never a rule. If not, the additive logistic weights are the answer.

**Dark pool check:** the sign of E3 and E4 weights is declared in advance as negative (quieter = better). Same sign with a bootstrap range excluding zero = the earlier finding is confirmed out of sample. Opposite sign or range including zero = not confirmed.

**Score and pulse check:** E5 and E6 are declared "carry information" only if their weights keep the same sign and a range excluding zero with C1 in the model.

## 7. Robustness (reported, not graded)

* "Every day" analysis instead of first day entries.
* Each flag alone: entries with the flag vs without, wk2 and wk4.
* Flag count staircase 0 to 4.
* Expansion universe rows where inputs exist.
* Excluding the top 10% of names by borrow fee each day.
* wk2 as the target instead of wk4.

## 8. What a result means

* **Pass:** the exhaustion score becomes a forward tag on the slow lane board for the next 12 week cycle (the Oct 15 checkpoint cohort is the natural live test). It becomes a sizing or timing rule only if the live cohort confirms. It never changes an entry signal or adds an exit.
* **Fail:** the four signs do not time the bottom inside these setups. The dark pool finding stays a forward tag only.
* House rules: nothing found after looking becomes a filter; bars and thresholds do not move; survivorship (current constituents) makes every result a ceiling.

## Amendment log

*(empty)*
