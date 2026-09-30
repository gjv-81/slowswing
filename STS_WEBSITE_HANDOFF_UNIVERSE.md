# STS → WEBSITE HANDOFF #4 — Published-universe spec enforced (2026-09-29)
*Paste into the website chat. Backend changes are DONE; this handoff covers the
site-copy changes that must follow, and the facts behind them.*

## What happened
The original product spec (handoff #1: board "filtered to PASS-gate") was never
implemented — build_board.py shipped with INCLUDE_QUALGATES = {PASS, WATCH, FAIL},
so FAIL-gate and sub-$15 names (FMC, TRIP, XPEV, OWL, MARA, CLSK, AI, ...) were
being published. GJ has also been telling prospects the site "ignores small caps
and anything under $50." The code now enforces that promise.

## Backend changes already made (backups: *.bak.20260929)
- **build_board.py**: INCLUDE_QUALGATES = {PASS, WATCH} (FAILs tracked internally,
  never published) + new MIN_ENTRY_PRICE = 50.0 gate (entry price at signal).
  Logs excluded rows ("# price gate: ...") each run.
- **build_stats.py**: identical filters mirrored (PUBLISHED_GATES, MIN_ENTRY_PRICE),
  so board and track record share one universe definition.
- **site/stats_history.json REGENERATED**: the Aug 2026 snapshot was recomputed
  point-in-time (--asof 2026-08-31) on the corrected universe. Old file kept at
  site/stats_history.json.old-universe.bak. This was done BEFORE the first
  September month-end lock, so the published series is consistent from birth.
  Rationale: spec correction to match the publicly stated universe, made while
  the audience was 1–2 close friends; a mechanical rule applied to all names,
  not per-name deletion of losers.

## The corrected Aug 2026 numbers (site will show these)
- Cumulative n=66 (was 140): touched +5% = 89.4% (was 89.3) · +10% = 71.2%
  (was 72.1) — the BALLOONS BARELY MOVE.
- Achievable stats IMPROVE: avg 4-wk return +10.4% (was +8.9) · positive at
  4 wks 71.2% (was 66.4) · avg max dip −12.0%.
- By setup: Phoenix n=51 (+5% 86.3, +10% 72.5, avg wk4 +11.7, pos4 76.5%);
  Cruise n=15 (+5% 100.0, +10% 66.7, avg wk4 +6.2, pos4 53.3%).

## SITE COPY CHANGES NEEDED (this chat's job)
1. **Remove the "△ Higher-risk" quality tier everywhere** — board legend, filters,
   How-It-Works, tour. Only 💎 High-Quality (PASS) and ◆ Watch (WATCH) remain.
   No FAIL names will ever appear in board.json again.
2. **Add a universe sentence** to How-It-Works / About / methodology, matching
   what GJ tells people, e.g.: "Our universe is mid- and large-cap US stocks
   (S&P 500/400 constituents), priced $50 and above at signal, screened by our
   fundamental quality gate. We deliberately skip small caps and low-priced
   stocks." Keep it descriptive — no mechanics beyond this.
3. **Cohort size**: anywhere n is displayed (balloon fine print, track record),
   it will now be smaller (66 as of Aug). Don't hide it; it's the honest size
   of the promised universe.
4. If the tour or psychology pages reference the higher-risk tier, update.
5. NOTE: FAIL-tier data may still exist in the current inline board.json in
   sts_site_live.html — republish after tonight's pipeline run so the live
   board matches (run_evening.sh regenerates + deploys).

## Guardrails (unchanged, binding)
- The universe rule is MECHANICAL and dated. Never remove individual names
  because they lost; never tighten rules silently after outcomes. Any future
  universe change = dated methodology note on the site.
- Balloons stay labeled hypothetical peak/MFE, monthly snapshot, never restated
  (the series is now born clean — protect that).
- No entry/exit language, impersonal content, all prior compliance rules.
