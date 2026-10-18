# PRE-REGISTRATION — post-touch exit test for stretched entries (2026-10-18)
Frozen BEFORE looking at post-touch returns.

## Hypothesis
For signals that entered >=1.5 ATR ABOVE the 200-day SMA and later TOUCH the
line (Low <= that day's 200-SMA) within 60td, the remaining trade (from the
touch-day CLOSE to the original 12-week mark) is negative enough that exiting
at the touch beats the no-exit doctrine.

## Definitions (frozen)
- Cohort: full signal family (score>=2, >=10% below 52wk high), all
  daily_data_v2 tickers, next-open entry, 20td refractory, signal day
  dist = (close - sma200)/ATR14 >= 1.5 (also report >= 2.0).
- Touch day T: first day after entry with Low <= sma200(that day), T <= 60.
- Post-touch return: close(entry_day+60td)/close(T) - 1 (what holding keeps
  vs exiting at the touch close). Also report fwd d5/d10/d20 from T, median,
  avgWin/avgLoss, and the same measure for SPY over identical windows (excess).
- Split: touch in first 20td vs touch in 21-60td; era split 2017-2021 vs
  2022-2026.

## Pass/fail bar (frozen)
ADOPT as an exit-rule candidate (promote to forward tagging) ONLY if, at BOTH
1.5 and 2.0 ATR thresholds: post-touch-to-wk12 avg <= -2%, median < 0,
win% < 45%, and SPY-excess negative; and the direction holds in both eras.
Otherwise: the touch stays a descriptive tag, no exit rule (doctrine stands).

## RESULT (2026-10-18, same day — bar FAILED, hypothesis rejected)
Post-touch -> wk12: >=1.5 ATR: n=2402, avg +7.30%, med +3.04%, win 57.6%,
SPY-excess +4.50%; >=2.0 ATR: n=2053, avg +6.91%, win 57.7%, excess +4.35%.
Early touches (first 20td) are the STRONGEST post-touch: +11.8%, 61% win,
+7.3% excess. Positive in both eras, at d5/d10/d20.
VERDICT: no exit rule. All damage occurs BEFORE the touch; exiting at the
touch sells the statistical bottom. 12th consecutive exit-aid failure.
Touch remains a descriptive tag only. Entry-side implication (stretched vs
near-line entries) feeds checkpoint agenda item 2.
