# STS — Signal Trading System

*A machine-learning–driven swing/position selection system for U.S. equities.*

---

## Overview

I built a stock-selection system using a machine-learning model (regularized linear
regression) trained on 10 years of daily data across ~600 U.S. stocks. It learned which
price-behavior combinations — deep pullbacks in intact long-term uptrends, momentum, and
relative strength — best predicted 12-to-24-week outperformance, validated walk-forward on
data the model never saw. From that research I distilled two custom thinkorswim indicators
and a scanner that score the entire market daily and surface marked-down market leaders for
fundamental review. The system's job is simple: rank stocks with the statistical profile of
past winners and hand me a short list to vet. In backtests the top-ranked setups materially
outperformed the average stock (roughly 13–16% vs ~4% per 12 weeks), though those figures
are idealized — no transaction costs, and subject to survivorship bias — which is exactly
why I am forward-testing the system live with a 120+ position paper portfolio before
committing real capital.

> **On "machine learning":** the model is regularized linear regression (ridge). That is
> genuinely supervised machine learning — trained on labeled data, validated out-of-sample —
> just the simple, interpretable end of the spectrum, which is a feature, not a bug: linear
> models are far harder to overfit than neural networks on noisy market data.

---

## How it works, end to end

1. **Nightly scan** (`sts_ml_evening.py`) — computes a learned-weight **score** for every
   stock in the universe after the close, using six price features (below).
2. **Rank & flag** — everything scoring ≥ 2.0 is a candidate; each name is also tagged with
   a **setup code**, a **ring** (evidence zone), and the **SPY regime dial**.
3. **Fundamental gate** (`qualgate.py`) — a research-backed PASS/WATCH/FAIL quality screen is
   applied to filter out balance-sheet blow-up risk.
4. **Tracker** (`sts_ml_paper_tracker.py` → `build_holy_grail.py`) — every qualifier is logged
   to a paper portfolio and scored forward at 12 and 24 weeks. Output: `STS_holy_grail.xlsx`.
5. **Telegram digest** — a nightly summary (regime, new qualifiers, setup fan-out) is pushed
   to my phone. The whole pipeline runs automatically each evening.

The human still makes the final call: the scanner produces the *short list*; fundamental
review (SSI2 / QualGate) and position sizing are mine.

---

## The score (what the model learned)

Each stock's score is a weighted sum of six **z-scored** price features (weights learned via
ridge regression, clipped at ±3σ so extreme outliers can't blow up the score):

| Feature | Weight | Meaning |
|---|---|---|
| Distance below 52-week high | −2.20 | further below the high → higher score (buy the markdown) |
| Distance above 200-day SMA (ATR-normalized) | +1.35 | further above the long-term trend → higher (trend intact) |
| 6-month momentum | +1.08 | stronger 6-month return → higher |
| QQE (smoothed RSI vs 50) | −0.99 | more washed-out oscillator → higher (contrarian) |
| 40-day momentum | +0.63 | medium-term strength → higher |
| Hull MA slope | +0.60 | turning up → higher |

The plain-English profile the score rewards: **a marked-down stock whose long-term uptrend is
still intact, with cooled-off short-term momentum.** The 200-day is a *simple* moving average,
no displacement.

---

## Setup codes — the recovery ladder

The codes describe *where a stock sits in its recovery*, weakest evidence to strongest:

> **LB → DLB → X200 → D200 → D200G**

| Code | Definition | Backtest (12wk, no-stop) | How to trade |
|---|---|---|---|
| **D200G** | Deep + above the 200-day SMA + score ≥ 2. (Deep = 25%+ below the 52-week high.) The best cell. | **+16.2% avg** | Trade FIRST — front of the review queue. |
| **D200** | Deep + above the 200-day SMA (score not required). Recovery structurally confirmed; catches sprint-recoveries the score misses. | **+14.0% avg** | Trade second. |
| **B2** | **Breather** — score ≥ 2 + 10–25% below the high. The "up 8 weeks, soft 4 weeks" pullback, measured by depth. | **+14.1% avg** (best excess) | Trade. Best form: RS+ green but cooling. |
| **G2** | The whole score ≥ 2 green bucket, any depth (the nightly candidate list). | **+13.1% avg** | The candidate universe. |
| **S2** | **Sprinter** — score ≥ 2 + within 10% of the high (momentum type, hasn't pulled back yet). | **+11.3% avg** | Valid, but last in line. |
| **X200** | Day one of D200: a deep stock *freshly* crossing above its 200-day SMA. | **+10.5% avg** (weaker than the settled state) | No urgency — it ripens into D200. Never chase the cross. |
| **DLB** | **D**eep + **L**ane **B** (below the 200-day) + score ≥ 2. The "score-qualified crash" — model likes it, but the trend isn't reclaimed yet. Riskiest score ≥ 2 cell. | **+12.2% avg** (broken-trend risk) | Only with a PASS gate, small size. Never FAIL/SPEC. |
| **LB** | **Lane B** — crashed AND below the 200-day, score gray (< 2). No systematic signal — technicals proven useless here. | n/a (thesis only) | Fundamental thesis ONLY. Small size. |

Each rung up the ladder = one more piece of evidence that the recovery is real (below the
200-day → crossing it → established above it → confirmed by the score).

---

## Modifiers (describe a name alongside its code)

| Modifier | Meaning |
|---|---|
| **RS+** | Relative-strength column green = leading the market. NOT an entry rule (tested: adds nothing) — it's a tie-break between similar scores and the leader-picker within a sector cluster. |
| **RING** | Evidence zone. **GREEN** = cap ≥ $10B, price ≥ $15, $70M/day volume, listed 3yr+ (full trust). **AMBER** = $3–10B or 1–3yr (half size, heavier fundamental review). **RED** = below that (formula only, no evidence). |
| **DIAL** | SPY stretch **percentile** vs its own trailing 3-year distribution (replaced the ATR dial 2026-08-26 — the ATR version sat in YELLOW 54% of all days and stopped discriminating; see spy_regime_study.py / STS_spy_regime_study.xlsx). **RED** = below the 200-day · **GREEN** = above + <50th pctile (recently reset — historically the best entries) · **YELLOW** = 50–90th pctile (extended but ordinary, ~40% of days) · **ORANGE** = >90th pctile (over-extended: median outcomes are fine, but this is the ONLY zone where the bad-tail 4-week drawdowns exceeded −8% and 12-week drawdowns reached −33% — where bear markets began). Informational market context, never a veto. |
| **QUALGATE** | Fundamental safety gate (PASS / WATCH / FAIL). Not a return booster — it thins the value-trap / blow-up tail. Matters most inside DLB. |

**Say a stock in one breath:** *"MU = D200G, RS+, green ring, orange dial."*

---

## Trading rules (apply to all codes)

- **Position size:** 4–5% equal weight, ~15–20 names. This — not stops — is the risk control.
- **No stop-loss.** Every stop tested (fixed, ATR-scaled, breakeven) reduced returns; at a
  12-week horizon on volatile names, any stop sits inside the noise and sells recoveries at
  their lows. Only a **catastrophe line** (≈ −40% or thesis broken) applies.
- **No profit targets.** The big winners fund the strategy; capping them destroys expectancy.
- **Hold 12–24 weeks.** Returns roughly double from 12 to 24 weeks at equal per-week
  efficiency — momentum persists. Score *decay while a position is winning is a success
  signal* (the setup being consumed), never an exit trigger.
- **Sector cap:** max 3–5 positions per sector/theme. A cluster of 20 qualifying chips is
  ONE bet at 20× size.
- **Regime dial** sets aggressiveness (size / number of new entries), never blocks a trade.

---

## The fundamental gate (QualGate)

A research-backed **quality/safety** screen — its job is NOT to predict returns (fundamentals
are weak at swing horizons) but to decide whether a name is a sound-enough business to be
*eligible* for the technical model. It screens out junk and blow-up risk.

| Factor | What it measures | Source |
|---|---|---|
| Gross profitability | gross profit / total assets | Novy-Marx (2013) |
| Piotroski F-score | 9 accounting-health checks | Piotroski (2000) |
| Altman Z-score | distress / bankruptcy risk (**hard veto** below 1.81) | Altman (1968) |
| Accruals (OCF > NI) | earnings quality | Sloan (1996) |
| FCF yield + trend | self-funding quality | Asness et al. (QMJ) |
| Solvency | interest coverage, leverage, liquidity | balance-sheet gate |

**Output tags:** PASS / WATCH / FAIL, plus a **profile** (CORE = mature/stable, GROWTH,
DECLINING, SPECULATIVE, NEW-IPO, LEVERAGED) and any veto reasons. Data via yfinance
(annual + quarterly, ~4yr), cached and refreshed monthly.

---

## Scorecard metrics (the tracker's live report card)

The tracker groups every paper position and reports, per bucket (setup code, score band, or
qualgate tier):

| Metric | Meaning |
|---|---|
| **n** | number of positions in the bucket |
| **avg_ret%** | average return so far (live P&L) |
| **med_ret%** | median return (the typical position) |
| **win%** | share of positions currently positive |
| **avg_excess%** | average return minus SPY over the same holding window — the honest scoreboard |
| **avg_MAE%** | average Maximum Adverse Excursion (worst intraday dip vs entry). −10 to −15% on eventual winners is the researched, normal path |
| **worst_MAE%** | the single deepest drawdown in the bucket |
| **deep_DD%** | share of positions that dipped ≤ −20% (tail-risk gauge) |
| **avg_MFE%** | average Maximum Favorable Excursion (best gain vs entry) |
| **wk12_ret% / wk24_ret%** | return frozen at 60 / 120 trading days — the primary validation numbers |
| **days_held** | trading days since entry (60 = 12-week mark, 120 = 24-week) |
| **flag** | "dipping" (MAE past −13%, normal) or "CATASTROPHE" (below −40%, demands a decision) |

**What the gate is expected to do:** not raise win rate or returns (it's a safety filter), but
**thin the tail** — fewer deep drawdowns and permanent value traps among PASS names than FAIL
names, measured over 12 weeks. Win-rate parity in the short term is expected and not a failure.

---

## The research (what was and wasn't found)

Eleven walk-forward studies on the 10-year, ~600-stock panel. Headline findings:

**What works**
- The learned score bucket (≥ 2) beats the market out-of-sample; the edge is *monotonic*
  across score deciles.
- The strongest cell is **D200G** (deep discount + intact 200-day trend + green score): +16.2%.
- Edges live in **states** (being in the right bucket), and returns compound best when
  positions are **held** (12–24 weeks) with **no stops** and risk controlled by **sizing**.

**What was tested and rejected** (kept here so they're never re-added)
- The original hand-weighted 18-point indicator score (inversely predictive at 12 weeks).
- All 16 legacy technical indicators, at original *and* 5×-slowed settings (redundant).
- Every *timing trigger*: RS crossing zero, 200-day reclaim, "RS rising" — all added nothing
  or subtracted. **States beat moments, every time.**
- Every stop-loss (fixed, ATR, breakeven) — all reduced returns.
- Profit targets — all cut expectancy.
- Small/micro-caps — the edge disappears below large-cap.

---

## Honest caveats

- **Survivorship bias:** the universe is today's ~600 tickers backfilled 10 years; dead
  companies are invisible. All absolute backtest returns are *ceilings*. Relative comparisons
  (bucket vs bucket) are more robust.
- **Idealized execution:** entries at the open, no costs/slippage, stops assumed to fill at
  the level. Real results will be lower.
- **Regime concentration:** much of the measured edge came from strong-recovery years;
  choppy years (e.g. 2021) hurt every configuration.
- **The forward test is the real verdict.** No conclusions are drawn until 100 twelve-week
  checkpoints accumulate in the live paper portfolio (~mid-October 2026 for the first cohort).
  Everything before that is a snapshot, not a result.

---

## Operational stack

- **Universe:** ~600 U.S. equities, 10 years of daily bars (yfinance).
- **Scanner/indicators:** live in thinkorswim (STS_ML score column + chart study, RS-vs-market,
  SPY regime label, setup arrows, GOLD flag).
- **Nightly pipeline:** `run_evening.sh` → `sts_ml_evening.py` (scan + score) →
  `sts_ml_paper_tracker.py` (forward tracking) → `build_holy_grail.py` (consolidated workbook
  with Legend, Tracker, Scorecard, QualGate, Trades sheets) → Telegram digest.
- **Scheduling:** runs automatically each evening from a non-protected home folder (`~/STS`),
  no elevated permissions required.
- **Deliverable:** `STS_holy_grail.xlsx` — one workbook with the setup-code legend, the live
  tracker, the scorecard, per-ticker fundamentals, and the trade log.

---

*This is a personal research project and forward test. Nothing here is investment advice.
Figures are backtested and subject to the caveats above; the system is being validated on
paper before any real capital is committed.*

---

## Appendix — turning this into a subscription product (scoping notes)

*Notes for a future build. Not legal advice — consult a securities attorney before launch.*

### The core product question (decide this first)
There are two very different products, and they carry very different legal exposure:

1. **Impersonal research / educational newsletter** — the same ranked list, scores, and
   commentary sent to *all* subscribers, not tailored to any individual, presented as
   research/education. In the U.S. this may fall under the **"publisher's exemption"** to the
   Investment Advisers Act (the same basis newsletters like Value Line operate under) — but the
   exemption is fact-specific (must be impersonal, regular/bona-fide publication, not tailored
   advice). Lower regulatory burden, but strict on *how* it's framed.
2. **Personalized advice / managed signals** — recommendations tailored to a subscriber's
   situation, portfolio, or risk. This is much more likely to require **SEC or state
   Investment Adviser (RIA) registration**, with the attendant compliance, disclosures, ADV
   filings, fiduciary duty, and record-keeping.

**Design the site around #1 (impersonal research) unless/until you deliberately register.**
Every product decision below flows from that choice.

### Compliance guardrails to build in from day one
- **Disclaimers everywhere:** "not investment advice," "for educational/informational purposes,"
  "past performance ≠ future results," "you are responsible for your own trades."
- **Performance-claim rules are strict.** If you show returns you must show them honestly and
  completely — the backtest figures here are *idealized and survivorship-biased* (see caveats)
  and must be presented as such, never as "returns subscribers earned." The live paper-tracker
  results (once ≥100 checkpoints) are the honest number to feature, clearly labeled as paper/
  hypothetical. Cherry-picking winners (e.g. "U +52%!") without the full distribution is exactly
  what regulators penalize.
- **No performance-based fees** in the impersonal model; flat subscription only.
- **Testimonials, refunds, "guarantees":** all regulated — keep them clean or absent.
- Consider a formal **Terms of Service + Privacy Policy** and an explicit **risk disclosure**
  gate at signup.

### What subscribers would actually receive (product surface)
- The nightly **ranked candidate list** with setup codes, ring, dial, and gate tags.
- The **score** per name (or a simplified tier) and the **setup-code legend**.
- The **SPY regime dial** as a market-context header.
- Optionally: the educational layer — *why* a name qualifies (the "buy the markdown near its
  200-day" thesis), which strengthens the "educational publisher" positioning.
- **Not** individualized "buy X with your money" instructions — that's the line to stay behind.

### Technical build (high level)
- **Backend:** the existing nightly Python pipeline already produces the data; wrap its output
  (scores, setups, gate) into a small database/API instead of just Excel + Telegram.
- **Data licensing:** yfinance is fine for personal use but **not licensed for commercial
  redistribution** — a paid product needs a properly licensed market-data feed
  (e.g. Polygon, Nasdaq, IEX, or the broker API's commercial terms). This is a real cost and a
  hard requirement, not optional.
- **Frontend:** a login-gated dashboard (the ranked list + legend + regime), subscription via
  Stripe, auth via a standard provider.
- **Delivery cadence:** nightly refresh after close, matching the current pipeline.

### Sequence before writing any site code
1. Talk to a **securities attorney** — confirm the publisher-exemption path and the exact
   framing/disclaimers for your jurisdiction.
2. Lock the **product definition** (impersonal research, what's shown, what's not).
3. Sort **commercial market-data licensing** (blocks everything downstream).
4. *Then* design the dashboard, auth, and billing.

The order matters: the legal framing and data licensing shape the product, so resolve those
before investing in UI. The model and pipeline (this document) are the easy part — they already
exist. The product, compliance, and licensing are the new work.
