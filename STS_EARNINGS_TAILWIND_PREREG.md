# PRE-REGISTRATION — "Earnings tailwind" (post-earnings setups)
*Written 2026-10-09, BEFORE results are seen. Prompted by ACN (Oct 2026): beat → +18% gap →
3-day fade → D200G re-qualified → +6.6% in two sessions. Do not edit after results.*

## Hypothesis
A Phoenix/Cruise signal that fires shortly AFTER an earnings report with a positive
reaction (post-earnings-announcement drift) goes on to do better over the next 4 and
12 weeks than signals with no recent earnings. The ACN state — beat, gap-up ≥ 4%, then
price has faded off the reaction-day close by the time the signal fires — is the primary cell.

## Data
- Signals: exh_build.score_and_signals on daily_data_v2 (1,025 tickers, 2016–2026),
  setups S2 / B2 / DLB / D200G; entry = next session's open (no lookahead).
- Earnings: uw_archive/earnings_hist/{t}.csv rows with source == "company":
  report_date, report_time (premarket → that day is the reaction session; postmarket/unknown
  → next session), street_mean_est, actual_eps.
- Outcomes: excess return vs SPY, entry open → close at +20 sessions (xs20, PRIMARY) and
  +60 sessions (xs60); raw return r20; peak (max high / entry − 1) within 20 sessions.

## Tags (computed at the signal close, nothing after it)
- recent_earn: a reaction session within the prior 10 sessions (inclusive of signal day).
- react: reaction-session close / prior close − 1.  gap4 = react ≥ +4%; gapdn4 = react ≤ −4%.
- beat: actual_eps > street_mean_est (NaN when estimate missing → "unknown").
- faded: signal close < reaction-session close (price has given back part of the gap).
- Cells: CONTROL (no reaction session in prior 10 sessions);
  E_UP_FADED (recent_earn & gap4 & faded)  ← PRIMARY (the ACN state);
  E_UP_HELD (recent_earn & gap4 & not faded); E_FLAT (recent_earn, |react| < 4%);
  E_DOWN (recent_earn & gapdn4).

## Pass / fail (declared in advance)
- PASS: E_UP_FADED, pooled over DLB+D200G+B2, has n ≥ 60 AND mean xs20 ≥ CONTROL + 2.0 pts
  AND win(r20>0) ≥ CONTROL + 5 pts, AND the sign holds at xs60 (≥ CONTROL + 0 pts) AND
  E_UP_HELD is not worse than CONTROL (graceful degradation, not an isolated spike).
- Also report by setup and by year (2016–2020 vs 2021–2026) — a pass that lives in one
  year is reported as such and does not count.
- FAIL: anything else. Then the idea is closed; no badge; no forward test.
- PASS → 3-month forward check on the live book (pending rows get the tag in the
  tracker), THEN a "⚡ Earnings tailwind" badge on the board. Never before.

## Not tested here (declared)
Analyst price targets — no free history exists, so it cannot be backtested; if ever
tested it will be a forward test, declared separately.
