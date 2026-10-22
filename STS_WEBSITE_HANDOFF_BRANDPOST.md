# STS → WEBSITE HANDOFF #8 — Blog post: Phoenix vs Cruise vs the S&P 500 + two dynamic charts (2026-10-20)
*Paste into the posts chat (edits go in `site/posts.js` only, per the one-chat-per-file rule).
The user-approved, pixel-final reference is `blog_preview_phoenix_cruise.html` in ~/STS/15min —
title, copy, both charts, tables, callout and colors are all final there. Reproduce it;
don't re-derive it. Standalone chart sources: `brand_spaghetti.html`, `brand_touch_live.html`
(data inlined; regenerators: brand_spaghetti.json / brand_touch_curves.json).*

## 1. TITLE + PLACEMENT
Title (as approved in the preview): "Two setups, one choppy market: Phoenix, Cruise, and
every S&P 500 stock — measured". (Alternative the user also liked: "Phoenix sprints, Cruise
simmers: our first 12-week report card" — use only if he asks.)
This is post #2 of the locked-cohort series; it follows handoff #7's "Red at the checkpoint"
post and references it in the intro ("Last week we dissected...") — publish in that order.

## 2. POST BODY
Take the copy VERBATIM from blog_preview_phoenix_cruise.html (user proofread it there).
Structure: intro → chart 1 → personality paragraph (contains the approved sentence
"Phoenix was 8.5 points ahead of the market at week 4 and kept 6.1 of them to the finish;
Cruise ran closer to the market early and edged away slowly") → Phoenix/Cruise table →
Cruise 100%-touched paragraph → skeptic transition → chart 2 → S&P comparison table →
"Read that bottom line twice" paragraph → small print (note: the line "one stock either
way moves its numbers" was REMOVED — keep it out). Tickers get tklink treatment.

## 3. CHART 1 — spaghetti with baskets (brand_spaghetti.html)
- 55 real signal paths (violet=Phoenix 41, blue=Cruise 14), day 0→60, thin strands fade in
  staggered (~0.12s apart, 2s fade).
- At t≈3.5s the thick lines start AND the strands dim to 8% opacity: Phoenix basket
  (violet, 4.5s draw), Cruise basket (blue, +0.8s), then the S&P line fades in —
  **S&P line is RED dashed (#dc2626)** incl. its labels and legend swatch.
- Amber dashed vertical at week 4. Week-4 labels are self-describing and bold with white
  halos: "Phoenix basket +12.6%", "Cruise basket +6.9%", "S&P basket +3.5%" (positions:
  Phoenix left-above, Cruise right-above, S&P right-below; 13.5px, weight 900).
- Subtitle ends: "the numbers on it are each basket's **average return** on that day" —
  the words "average return" bold + dark green (#166534).
- End labels (right, de-overlapped ≥16px, white halos): Phoenix +10.5% / Cruise +7.7% /
  S&P 500 +0.3%.
- Right-side performers panel (appears with final labels): TOP 5 (TEAM +128.6, PAYC +62.0,
  ANF +56.6, ZS +55.2, OKTA +47.6) upper-right; BOTTOM 5 (VRT −19.5, CAVA −22.4, WDC −22.5,
  BLDR −30.6, MTZ −38.9) lower-right, clear of the end-label band. Peak values in
  parentheses, color-coded: dark green >+5%, light green 0..+5%, red <0.
- "How to read the two kinds of numbers" callout box (blue left border) below the legend:
  definitions line (Winners = above signal price at that week's close, by any amount;
  Touched = got there at some point, not that it stayed), the Cruise line (all 14 touched
  +5%, only 8 green at wk4 — "gains offered, not yet kept"), and FOUR example pills:
  MTZ +8.6→wk4 −10.4 · CSCO +10.6→ended −1.5 · WDC green +9.1 at wk4→finished −22.5 ·
  OKTA +10→wk4 −0.04→finished +47.6.
- ↻ Replay button (top-right; static above badge <760px).

## 4. CHART 2 — interactive touch levels with auto-tour (brand_touch_live.html)
- Three lines: Phoenix violet, Cruise blue, S&P GRAY dashed (deliberately NOT red here).
- Level pills +5% / +10% / +20% + "↻ Replay tour" button at row end.
- AUTO-TOUR on load: +5% → (3.2s) +10% → (5.8s) +20%, then STAYS on +20% (so the resting
  state is the 63/36/20 stat). Any manual pill click cancels the tour. Lines morph (0.9s d
  transition) between levels; intro line-draw animation on first render.
- Week-4 markers per line: dots on the amber week-4 line + bold halo values that move with
  the level (de-overlapped ≥17px). End labels de-overlapped ≥16px.
- Data (weeks 0..12, % of group that had touched, intraday-high basis):
  phoenix +5:  [10.5?]—use brand_touch_curves.json verbatim; key endpoints:
  wk12 touch — Phoenix 90.2/78.0/63.4, Cruise 100.0/78.6/35.7, S&P 75.2/51.0/19.7 (5/10/20);
  wk4 touch — Phoenix 85.4/75.6/43.9*, Cruise 100.0/71.4/14.3*, S&P 69.7/41.3/9.8*
  (*read exact values from the JSON; the chart displays rounded).

## 5. TABLES (verbatim from preview)
Table 1 (Phoenix 41 / Cruise 14): winners wk4 78/57 · ahead of S&P wk4 +8.5/+2.8 pts ·
winners wk12 58/57 · avg wk12 +10.5/+7.6 · touched 5: 90/100 · 10: 78/79 · 20: 63/36 ·
ahead of S&P wk12 +6.1/+3.3 pts.
Table 2 (typical S&P stock vs published signals, same 12 weeks): touched 5: 75 vs 93 ·
10: 51 vs 78 · 20: 20 vs 56 · green wk12: 43 vs 58 · avg: +0.3 vs +9.8 · median: −2.2 vs
+5.2 (style: S&P median red, signal column green, as in preview).

## 6. COMPLIANCE
Live record (post-launch signals): no backtest label, but keep the footnotes exactly as in
the preview (touched ≠ earned; no stops/targets; dividends excluded; 492 current members,
survivorship both sides; not advice). No entry language. The definitions callout ships with
chart 1 wherever it's embedded. Cohort = PASS/WATCH + {DLB,D200G,B2} + $50 floor only
(S2 and sub-$50 names are not published — same rule as handoff #7).
