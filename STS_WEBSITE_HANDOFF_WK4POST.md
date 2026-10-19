# STS → WEBSITE HANDOFF #7 — Blog post: "Red at the checkpoint" + animated cohort chart (2026-10-19)
*Paste into the website chat (the posts chat — edits go in `site/posts.js` per the one-chat-per-file rule).
The approved chart mockup is `wk4_losers_spaghetti.html` in ~/STS/15min — self-contained
(inline SVG/JS, no external deps). All numbers are real, from the first locked 12-week cohort.*

---

## 1. WHAT THIS IS
First blog post built on LOCKED live data: the 15 published signals that were below their
signal price at week 4, tracked to their 12-week grades. Approved final post text is in §4
(verbatim — user has proofread it; do not reword). The animated chart in §3 is approved and
final; lift its SVG/JS module into the post unchanged except for integration plumbing.

## 2. COHORT DEFINITIONS (already enforced — do not recompute differently)
- "Published" = QualGate PASS/WATCH + setup in {DLB, D200G, B2} + entry price >= $50.
  (S2 is NOT published; FTNT/DDOG/CROX were S2 and are excluded. AEO/PINS/BBWI/ENPH
  excluded by the $50 floor. User caught an early version that wrongly included these.)
- Locked cohort = all published signals with a completed 12-week (60 trading day) window:
  n=55, entries Jul 20 – Jul 23 2026 era, win 58.2%, avg +9.76%, excess vs SPY +5.42%,
  touched +5%: 92.7%, touched +10%: 78.2%.  ← these supersede the earlier n=69 numbers
  anywhere they appear.
- The post's cohort = the 15 of those 55 with wk4 return < 0.
- Key chart values (must match post text): basket of 15: wk4 −4.8% → wk12 −5.5%;
  S&P 500 same windows: +3.4% → +4.4%; avg best-moment (running peak) of the 15:
  wk4 +4.6% → wk12 +13.4%; ALL 55 published: wk4 +11.1% → wk12 +9.8%.
- Individual endings (chart legend): OKTA +47.6 (pk +64), AMD +17.1 (pk +26),
  COIN +14.9 (pk +27), DUOL +5.6 (pk +20), QCOM +1.3 (pk +16), CSCO −1.5 (pk +11),
  ARM −6.1 (pk +23), CAT −13.2 (pk +1), WING −14.1 (pk −4), ON −14.7 (pk +3),
  AMAT −14.8 (pk +4), KLAC −15.3 (pk +1), VRT −19.5 (pk +3), BLDR −30.6 (pk +2),
  MTZ −38.9 (pk +6).

## 3. THE CHART (wk4_losers_spaghetti.html) — behavior spec
Animated sequence (~20s, Replay button re-runs it):
1. 15 real price paths draw one by one (5s each, 0.55s stagger) from day 0;
   teal = finished positive, orange-red = finished negative.
2. Numbered endpoint labels land per line; peak values in parentheses are color-coded:
   dark green pk > +5%, light green 0..+5%, gray never-green (WING only).
3. Amber dashed vertical at week 4 ("week 4 — all 15 in the red").
4. Faint density bell of the 15 endpoints at the right edge.
5. At ~14s the background fades (spaghetti to 15% opacity, labels 35%) and FOUR summary
   lines sweep in left→right together (shared clip animation):
   thick teal = ALL 55 published avg; thick black = the 15 held together;
   gray dashed = S&P 500 same period; violet dotted = avg best-moment of the 15.
6. A white legend box (top-left) appears with all four lines' style swatches and
   "wk4 X% → 12wk Y%" values; wk-4 dots and endpoint dots mark each line.
Integration notes: number-to-ticker legend grid sits below the SVG; footnote defines
"peak = level touched, not a return earned". Keep the Replay button (matches the
explainer's replay pattern). Mobile: replay button goes static above the badge <760px.

## 4. FINAL POST TEXT (approved verbatim; apply tklink treatment to tickers)
Title: Red at the checkpoint: what happened to the 15 signals that were losing at week 4

[Body — use exactly the approved draft from the working chat, reproduced here:]

Our first batch of signals just finished its full 12-week window. That gives us something
we didn't have before: real endings, not predictions.

Today we want to show you the scariest-looking group — every published signal that was
below its signal price at the four-week mark. All 15 of them.

Look at the chart. Every line starts at the same place: the signal day, at zero. By week 4,
all 15 are under water — held together as one basket, they're down 4.8%.

Here's the twist: by that same week-4 mark, these struggling names had already touched
+4.6% at their average best moment — more than the S&P 500 gained in the whole four weeks.
Eleven of the 15 had been green at some point. Red at the checkpoint almost never means it
was never working — it means it didn't hold.

Then watch the next eight weeks. The lines scatter in every direction.

Five of the 15 recovered. OKTA didn't just recover — it finished up 47.6%, the best name
in our whole book. AMD +17.1%. COIN +14.9%. If you had given up at week 4, you would have
sold each of them near its low.

Ten never came back. MTZ finished down 38.9%. BLDR down 30.6%. Holding them did not save
them.

Held together, the basket ended at −5.5% — while the S&P 500 gained 4.4% over the same
twelve weeks. One big winner softened what ten losers did. That's why we hold the basket,
not a favorite.

Now look at the top line on the chart: all 55 published signals from this same period —
winners and losers together — finished at +9.8%, with 58% winners. The group that looked
broken at week 4 still couldn't drag the book down.

Timing mattered here too. These 15 lived their weeks 4 through 12 in August and September —
historically the choppiest, weakest stretch of the market year. Our signals are recovery
stocks, and recovery stocks move harder than the market in both directions. In a rising
tape that extra motion works for us; in a sideways, nervous tape it shows up as exactly
what you see in this chart. That's context, not an excuse — we show the batch as it
happened and let the next batches speak for themselves.

That's the honest shape of this group: some healed, most didn't, and at week 4 you could
not tell which was which. Our ten years of research says a group like this usually ends
better. This batch didn't. One batch in one choppy stretch doesn't overturn ten years —
but we're not going to hide it either. We log it, and we watch the next batches.

How to read this as a subscriber: the board tracks every signal for 12 weeks, because
that's the horizon the system was built on. A name down at week 4 is not a failed signal —
and not a guaranteed comeback either. It's an unfinished one. The grade comes at week 12.

*All figures are from our live record of published signals, measured at closing prices,
no stop-losses, no targets, dividends excluded. "Touched" and "best moment" refer to the
highest closing gain reached at any point — levels touched, not returns earned. Past
results don't predict any single name. This is education, not advice.*

## 5. COMPLIANCE CHECKLIST
- This is the LIVE record (post-launch signals), so no "hypothetical backtest" label —
  but keep the footnote exactly as written (touched-not-earned, no-stops, not advice).
- No entry language anywhere ("still enterable", "good time to buy" etc. must not appear).
- Peak/best-moment values always carry the "touched, not earned" qualifier.
- Ticker symbols: bold teal tklink treatment, every mention, linked per blog convention.
- Do not add a comments section or reply mechanisms.

## 6. SITE-WIDE NUMBER CORRECTIONS RIDING ALONG
Wherever the site or earlier handoffs quote the locked first-cohort stats, use the
corrected published-universe figures: n=55, win 58.2%, avg +9.76%, excess +5.42%,
touched +5% 92.7% / +10% 78.2%. (Supersedes the n=69 / 60.9% / +10.46% figures from the
first checkpoint pass, which accidentally included S2 and sub-$50 names.)
