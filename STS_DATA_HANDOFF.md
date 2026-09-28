# STS DATA HANDOFF — every dataset we hold, and the next research mission
*Paste into a new chat. Written 2026-09-28. All paths are on GJ's Mac under
`~/STS/15min/` unless noted. Companion docs: STS_README.md (the slow-lane model),
STS_FLAME_UW_PREREG.md + STS_flame_final.xlsx + STS_flame_expansion.xlsx (the
flame studies), STS_PROJECT_INSTRUCTIONS.md (project conventions).*

---

## 1. THE UNUSUAL WHALES ARCHIVE — `uw_archive/` (~2.2 GB)

Harvested Sep 26–28, 2026 during a 7-day API-Basic trial (cancel by ~Oct 2).
**LICENSE: strictly personal research. Never feeds theslowswing.com, never
redistributed, derived badges on any commercial surface need a commercial
license (UW enterprise ~$750/mo, or Intrinio Startup $333→$999/mo phased).**

| Folder | Files | What it is |
|---|---|---|
| `options_volume/` | 1,033 | **The crown jewel.** ~2 years (Sep 2024→Sep 2026) of DAILY per-ticker option aggregates for the full v2 universe. Columns incl. `call_volume`, `put_volume`, **`call_volume_ask_side` / `bid_side`** (and put equivalents), `call_premium`, `bullish_premium` / `bearish_premium`, `net_call_premium`, call/put open interest, and UW's own `avg_3/7/30_day` volume baselines. Side-classification is what raw chain data (ThetaData/Schwab) cannot give. |
| `options_volume_ext/` | ~450 | Same schema for the FAST-LANE EXPANSION names (see §2) that had S2/B2 signals. |
| `greek_exposure/` | 1,026 | ~1 year daily per-ticker: call/put gamma, delta, charm, vanna (GEX/DEX). |
| `iv_rank/` | 1,025 | Daily close, volatility, `iv_rank_1y` history per ticker. |
| `flow_alerts/` | 1,021 | Recent UW-classified unusual alerts per ticker (sweep/floor flags, ask/bid premium per alert, `alert_rule`, vol/OI ratio). Snapshot-depth, not full history. |
| `shorts_interest/`, `shorts_volume/`, `shorts_ftds/` | ~1,030 ea | Short interest/float (v2), daily short volume & ratio (500d), fails-to-deliver. UNTOUCHED so far — no study has used these yet. |
| `flow_per_strike/` | 2,341 | STRIKE-level ask/bid call & put volume+premium for every quiet-flame day (both years). Used once (anatomy: flames are one-strike, near-money, ~$167k median; anatomy does NOT separate winners). |
| `darkpool/` | 85,771 | Every dark-pool print (size, price, premium, NBBO bid/ask at execution) for each score≥2 signal's first 40 trading days, Nov 2024→Sep 2026. **Pre-aggregated daily cache: `uw_archive/darkpool_daily_agg.csv`** (ticker, date, dp_prem, above_share, block_prem) — use the cache, not the 85k files. |
| `gex_levels/` | 1,033 | Current gamma-level snapshot per ticker (call/put walls). |
| `spot_exposures/` | 6,992 | PER-DAY spot GEX for the 17-name personal watchlist, ~1yr. |
| `market/` | 2 | Market tide + total options volume series. |
| `_phase2_targets.json` | — | Cached signal list (all score≥2 first-day signals, 20td refractory, Nov 2024→) and quiet-flame day list. Regenerate via `uw_harvest2.py` if stale. |

## 2. PRICE DATA (yfinance) — free, unlicensed for commercial use

- `daily_data_v2/` — ~1,026 tickers (S&P 500 + S&P 400 + watchlist), 10 years
  daily OHLCV, current through today (refreshed weekdays 5:00pm by `refresh_v2.py`).
- `daily_data_ext/` — 1,246 FAST-LANE EXPANSION names: every US common stock
  (Nasdaq Trader symbol directory, ETFs excluded) with price > $25 and 300+ bars;
  3 years daily; refreshed by the same 5pm job.
- `daily_data_10y/` — the original live-universe folder (~604 tickers, 10y),
  kept current by the write-back inside `sts_ml_evening.py` (5:30pm cron).
- **yfinance is NOT licensed for commercial redistribution** — fine for research
  and personal signals; the website cannot be built on it (compliance memo).

## 3. MARKETSTACK — the website's licensed price feed

- Paid/licensed feed used by `build_board.py` for the ~64 live board names
  (~1,400 requests/month budget). Purpose: theslowswing.com displays licensed
  prices, not yfinance. Freshness guard: if Marketstack lacks today's bar the
  board falls back to workbook prices only when tonight's scan succeeded,
  else the site is not republished (see run_evening.sh). Reference:
  "Marketstack email.pdf" in the folder. Not a research dataset — display feed.

## 4. WHAT THE OPTIONS DATA HAS ALREADY PROVEN (don't re-run these)

All studies: walk-forward, pre-registered where possible, controls matched,
win% AND avg-win/avg-loss split (medians too — averages alone lied twice).

- **FLAME (validated, live in `uw_flame_live.py`, nightly Telegram):** ask-side
  call vol ≥3× own 21d median + calls>puts, on a quiet day (±1%) with ≥1 flat
  prior day, inside an S2/B2 signal's first 40td. Payoff window days 3–5.
  Final rules: S2 = fresh only (run since signal <5%), 1-flat only, validated
  universe only (did NOT transfer to expansion — pop-and-fade). B2 = works
  everywhere incl. expansion (61–68% win d1–d4), best after a 10%+ run
  (continuation) and on deep-flat; expect chunkier losses on ext names, day-5
  winners ~+7%. Strike anatomy adds nothing. Forward log: `fast_lane_log.csv`.
- **DLB/D200G + dark pool (new, tag-worthy):** HEAVY dark-pool activity in a
  signal's first 10 days predicts a WORSE remaining trade (DLB: 48.6%/−0.7%
  loud vs 57.4%/+4.3% quiet; D200G same sign). Quiet tape = sellers done.
  Buy-tilt (above-mid) and block share add nothing. Direction was discovered
  post-hoc → forward-tag, don't filter yet.
- **GEX at entry: NULL** for DLB/D200G at wk4 (below-flip entries marginally
  better if anything). The intraday gamma-flip intuition does not port.
- **Raw (unclassified) option volume: NULL** — proven three ways before the
  ask-side data existed. Never build on volume without side classification.
- **Weather/"conditions changing" badges: NULL** (chop study, 8,974 signals).
- Earlier failures to remember: stop-losses, profit targets, mid-trade exit
  aids all reduced returns for the slow lane.

## 5. THE NEW RESEARCH MISSION for this chat

S2/B2 were designed for SWING trading and merely borrowed for the flame. The
options data likely has more to give if setups are designed FOR it, the way the
original 6-feature score was ML-trained for the slow lane. Directions:

1. **Options-native setup discovery.** Treat the flame ingredients (ask-side
   surge, quiet tape, run context) plus untouched inputs (net premium trends,
   bullish/bearish premium balance, OI changes, IV-rank percentile, short
   interest/FTDs, dark-pool quietness, GEX walls from gex_levels) as a FEATURE
   SET, and train weights against 1–5 day forward returns — a "fast score"
   analogous to the slow lane's ridge model. Universe: the ~1,480 tickers with
   options_volume coverage. Two years of daily rows ≈ 700k observations.
2. **Condition studies on cheap wins first:** shorts data vs washout-recovery
   (are WR winners squeezes?); IV-rank as flame context (do flames in low-IV
   names pay better — cheap options = smarter money?); dark-pool quiet-tape as
   an entry timing signal on its own.
3. **Setup families worth testing beyond S2/B2:** post-earnings drift with
   ask-side confirmation; 52-week-high breakout day with flame; quiet-tape DLB
   (dark-pool silence + near-line) as a new slow-lane entry refinement.

**Methodology requirements (non-negotiable house rules):**
- Pre-register definitions and pass/fail bars BEFORE looking (see
  STS_FLAME_UW_PREREG.md for the template). Post-hoc finds = tags to
  forward-test, never filters.
- Walk-forward only; baselines from trailing windows; entries at next session.
- Always report win% AND avg-win/avg-loss/ratio AND median, d1–d5 for short
  horizons. Nested cells (flat1⊇flat2⊇flat3) — never read subsets as
  independent. Check transfer: validated universe vs expansion separately.
- Survivorship: all universes are current constituents — results are ceilings.
- Sample honesty: overlapping windows; count episodes, not just rows.
- GJ's intuitions have repeatedly been right (exit timing, flat-then-flame,
  run-up exclusion for S2) — test pushback empirically, don't assert.

## 6. OPERATIONAL NOTES

- UW trial: ACTIVE until ~Oct 2 — CANCEL IT (business email reserved for a
  future commercial license). Live plan: separate personal email → $150/mo API
  Basic when ready to trade; 40k req/day, quota resets 8pm ET; max 1 concurrent
  on trial. `uw_flame_live.py` runs nightly from run_evening.sh, exits quietly
  without a token (`.env_uw_live` preferred, `.env_uw` fallback).
- Key scripts: `uw_harvest.py` / `uw_harvest2.py` (archive builders, resumable,
  35k budget/run), `uw_expand.py` (--list/--prices/--flow/--backtest),
  `uw_flame_live.py` (nightly scanner), `flame_download.py`+`flame_backtest.py`
  (ThetaData stage-1, superseded), ThetaTerminal in `~/STS/ThetaTerminal`
  (free tier: 1yr EOD stocks+options, no OI, 20 req/min).
- The slow lane's first 12-week checkpoints lock ~Oct 15 (100+ by ~Oct 20):
  the universe-merge decision and any new slow-lane tags (quiet-tape) ride
  on that review.
