# STS → WEBSITE HANDOFF
*Paste this into the website/subscription chat. It updates the "subscription product"
appendix in STS_README.md with the new lifecycle + short-term scorecard, which reshape
the product. Read alongside STS_README.md (the full system) — this is the product layer.*

---

## What this system is (one paragraph for the web chat)
A daily stock-selection model (ML-derived 6-feature score, ridge regression, 10yr / ~600
stocks) that surfaces **marked-down stocks near their 200-day trend line** — "buy the markdown,
not the extension." It ranks candidates nightly, tags each with a setup code, an evidence
"ring," a market-regime "dial," and a fundamental PASS/WATCH/FAIL gate. Currently in live
paper-validation (started 2026-07-20). All files in /Users/Gagan/STS/15min; nightly pipeline
outputs STS_holy_grail.xlsx. See STS_README.md for the model, setup codes, and 11 studies.

---

## NEW since the README: the lifecycle (this is the core of the product)
Every position now carries a **phase** — an *actionability* signal answering "can I still
take this trade today?":

- **ACTIVE** — held < 4 weeks AND up less than 5% from the signal price. *Still a valid entry.*
  Includes names that are DOWN (cheaper near the line = arguably better). **This is the
  "buy list" — what a subscriber can act on today.**
- **EXTENDED** — held < 4 weeks but already ran UP 5%+. *The move happened — don't chase.*
  Show as "wait for a pullback," not as a buy.
- **RETIRED** — held >= 4 weeks. The short-term trade is "done." Feeds the honest track record.

## NEW: the short-term scorecard (realistic, honest metrics)
Because most people don't hold 12–24 weeks, RETIRED positions are scored on a **short horizon**:
- **wk2_ret** — actual close-to-close return 2 weeks after entry (achievable)
- **wk4_ret** — actual return 4 weeks after entry (achievable)
- **maxdip_4wk** — worst intraday drawdown in the first 4 weeks (the pain to expect)
- **NO peak / max-gain / MFE anywhere.** We never show "you could have made X if you sold the
  top" — it's unachievable and, for a paid service, a compliance/credibility red flag.

## The data-backed selling point (from the live paper book, day 26 — still small sample)
- Retired book: **wk4 avg ~+8%, 62% win**, vs ~+4.9% full 12-week hold — i.e. **most of the
  gain lands by week 4**, with a *smaller* max dip than the full hold. A 4-week trade is viable.
- Best setup short-term: **DLB +11.8% at 4 weeks, 65% win**; the edge shows up FAST, not only
  at 12 weeks. Worst: S2 (near-high momentum) negative even at 4 weeks — de-prioritize.
- Regime lever (from 10yr study): these setups average **+8.6%/12wk when entered post-correction
  (RED regime) vs +1.7% when extended (YELLOW)** — ~5x. The dial should headline the market
  context on the site.

## Product surfaces this enables
1. **Daily "Active" buy list** — Active names near their 200-day, filtered to PASS-gate, ranked
   by setup (D200G/DLB/washout first). "Here's what you can still enter today."
2. **"Extended" watch list** — ran already; wait for pullback.
3. **Honest track record page** — Retired scorecard: real wk2/wk4 returns, win rates, avg max
   dip, per setup. Clearly labeled paper/hypothetical until live.
4. **Market dial header** — GREEN/YELLOW/RED regime = how aggressive to be (and the ~5x context).

## Metrics rules for the site (non-negotiable for honesty + compliance)
- Show **actual returns** at real horizons (wk2, wk4, wk12) + **max dip**. Never the peak.
- Label all figures **paper / hypothetical**, subject to **survivorship bias** (dead stocks
  absent → figures are ceilings) and no transaction costs. Feature the *live paper* numbers,
  not the idealized backtest, once ≥100 twelve-week checkpoints exist (~mid-Oct 2026).
- Never cherry-pick winners (e.g. "MRNA +117%") without the full distribution.

## Compliance (carry forward from README appendix — resolve BEFORE building)
- Design as **impersonal research / educational newsletter** (publisher's-exemption path),
  NOT personalized advice (which likely triggers RIA registration). Talk to a securities
  attorney first.
- **yfinance is NOT licensed for commercial redistribution** — a paid product needs a licensed
  data feed (Polygon / Nasdaq / IEX / broker commercial terms). Hard requirement.
- Disclaimers everywhere; no performance-based fees; no guarantees.

## Sequence for the website chat
1. Confirm legal framing (attorney) + product definition (impersonal research).
2. Sort commercial market-data licensing.
3. Wrap the existing nightly pipeline output (scores, setups, phase, gate) into a DB/API.
4. Build: login-gated dashboard = Active buy list + Extended watch + regime header + track
   record page; Stripe subscription; standard auth.

The model + pipeline already exist (STS_README.md). The new phase/short-term scorecard makes
the product genuinely useful to short-term traders — the honest, achievable version.
