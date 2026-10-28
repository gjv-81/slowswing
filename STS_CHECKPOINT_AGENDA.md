# OCTOBER CHECKPOINT REVIEW — agenda (locked 2026-09-29, review when 12-wk locks land)
First locks ~Oct 15; ~100+ checkpoints by ~Oct 20. All decisions on LOCKED
12-week data, all changes prospective + dated. Pre-registered questions:

1. UNIVERSE MERGE — does v2 join the live pipeline?
   Bar: new-name DLB 12-wk results >= live-universe DLB. (Evidence so far:
   new-name DLB as good or better at wk4; new-name D200G worse.)

2. NEAR-LINE D200G FILTER — make dist200 <= +10% an entry rule for D200G?
   Bar: stretched D200G (>+10%) 12-wk results confirm the wk4 pattern
   (25-47% win, −20% dips) in both books.

3. FAIL/SPEC RE-ADMISSION to the website (GJ decision 2026-09-29: intended,
   pending confirmation). Bar: FAIL/SPEC cohort's locked 12-wk results look
   like PASS/WATCH, not like FAIL/LEV/GS. If passed: dated methodology note,
   SPEC becomes a visible "Speculative" tier on the board, PROSPECTIVE only
   (names added from the change date; no retroactive insertion). RKLB re-enters
   via this door or not at all.

4. HOLD-DOCTRINE STRESS TEST — the Aug-Sep give-back: did positions that were
   +wk4 recover by wk12 (as the 10-yr studies claim) or did the mid-hold bleed
   persist? This is the referee for the 12-24 week hold rule itself.

5. QUIET-TAPE TAG (dark pool) — begin tagging new DLB/D200G entries loud/quiet
   when live UW data exists; evaluate after its own forward sample. (Finding:
   quiet dark-pool tape in days 1-10 -> 57%/+4.3% vs loud 49%/−0.7%.)

6. PRICE/RING FLOOR for the INTERNAL book? The site now enforces $50+PASS/WATCH;
   decide whether the internal tracker keeps logging everything (recommended —
   research value) or adopts floors too.

7. WR cohort formalization — WR20/30/40 remains the best small cohort
   (wk4 ~70-80% win). Enough locked data yet to make WR a headline setup?

Also due mid-Oct: fast-lane forward-test interim look (fast_lane_log.csv),
UW personal account go/no-go for live flame trading.

8. X200 / X200-G — plain X200 tested 2026-09-30 and RETIRED (4,326 signals:
   12-wk excess +0.05%, 2-wk excess −0.03% — market-performing at every
   horizon). X200-G (gap >= 5% within 10 bars of the cross) discovered
   post-hoc same day: in-sample wk12 win 65%, excess ~+3%, positive 8/10
   years (prereg: STS_X200G_PREREG.md). STATUS: observation logging LIVE as of
   2026-09-30 (x200g_observe.py in run_evening.sh; first signal: COIN); promotion decided ~Q1 2027 on >= 20 live
   12-week outcomes (bars: win >= 55%, excess >= +2%).

9. SLOW-LANE UNIVERSE EXPANSION — slow_expand.py screens quality mid/large
   caps ($50+, cap >= $2B, 3yr+, $10M/day) from the ext pool into
   daily_data_slow_ext/. Fold into the merged universe HERE as part of the
   single dated universe change (items 1 + 9 together).


10. LATE-ENTRY FORMALIZATION (added 2026-10-18) — candidate study, pre-register
    before running: "entering an Active name at day N (5/10/15) that is down
    >X% (5/10/15) since signal — forward 4/8/12-week returns vs day-one entry."
    Motivation: user question "is -13% at day 10 still a good time to enter?"
    Existing evidence (cohort-level, not cell-specific): wk4 Active-state late
    entries +6.2% fwd 8wk; down>10% at wk4 the best (+8.0%); post-touch fwd
    +7.3%/57.6%/+4.5% excess (STS_LINETOUCH_EXIT_PREREG.md). If a cell
    validates on locked data AND survives forward paper-testing, it may become
    an Evidence-page cohort statistic — NEVER a star/badge on a live board name
    (entry recommendation; compliance bright line). Related new evidence for
    item 2 (near-line entry filter): ATR-distance taxonomy 2026-10-18 —
    stretched entries (>=1.5 ATR above 200d) breach the line in 33-65% of
    cases within 12wk; every post-entry line-based exit tested FAILED
    (12th & 13th consecutive exit-aid failures; breach day ~= local bottom).

11. RS-AT-ENTRY FLOOR (added 2026-10-26, from the MTZ post-mortem) — candidate
    filter, pre-register before testing further: block (or downweight) entries
    whose 40-day relative strength vs the market is below a floor (e.g. -15).
    First look, locked published cohort (n=63): RS<-15 at entry -> 50% win,
    +1.4% avg; -15..0 -> 56%, +9.8%; 0..15 -> 53%, +8.8%; >15 -> 67%, +18.0%.
    Both MTZ entries had RS -20.6 and -23.8. Needs: full 10-year backtest with
    pre-set pass/fail bars, plus check it doesn't just re-discover the momentum
    features already in the score.

BUG TO FIX (qualgate.py, found 2026-10-22/26): old companies (TER, MTZ) are
being labeled NEW-IPO / "<3yr public history" because yfinance returned
truncated fundamentals. Their gate scores are computed on a sliver of data and
their IPO flavor tag is wrong — this pollutes the IPO-cohort stats (WATCH/IPO
was the worst locked cell). Fix: when price history shows 3yr+ but fundamentals
history is short, flag as DATA-THIN instead of NEW-IPO and re-pull before
scoring.

ITEM 11 RESOLVED (2026-10-26): RS-at-entry floor backtested same day
(STS_RS_FLOOR_PREREG.md) and REJECTED — over 10 years the RS<-15 bucket is the
best performer by average excess (+14.2 pts), with ordinary medians and the
biggest winners. The live-cohort weakness was one choppy window. RS stays
display-only.

12. GATE RE-WEIGHTING VIA REGRESSION (added 2026-10-26) — DO NOT RUN BEFORE
    ~500 locked 12-week outcomes (expected roughly mid-2027). Idea: learn the
    six gate-component weights from outcomes (like the STS ML score), instead
    of the current hand-set research weights (F 24 / GP 22 / Z 16 / FCF 14 /
    Solv 14 / Trend 10; PASS 65 / WATCH 50 set by calibration).
    Why wait: (a) no historical point-in-time fundamentals (yfinance = today's
    statements, ~4yr) — training on them is hindsight; the tracker's nightly
    logs are accumulating clean, look-ahead-free training data instead;
    (b) 124 locked outcomes from one market stretch would overfit (see the
    rejected RS floor, item 11, for how convincing that mistake looks).
    Method when triggered: pre-register; train on first half of locked data,
    test on second half; adopt ONLY if it beats the hand weights out of sample.
    Until then the gate stays as-is (live spread: PASS +12.8% vs FAIL -4.9%
    at wk12 — working).

13. RE-ENTRY DOORS TOO NARROW (added 2026-10-26, STS_THIRD_ENTRY_PREREG.md) —
    backtest: signals refused re-entry (no premium door) beat SPY by +8.3 pts
    at wk12, better than allowed re-entries (+4.2), both eras. Decide in
    November: add a "deeper markdown" third door (re-entry if >=10 pts deeper
    off the 52wk high than previous entry), weigh board clutter + repeat-loser
    optics (MTZ would re-enter under this door too). LRCX (Oct 2026) is the
    live example the current rules refuse.
