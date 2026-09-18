#!/usr/bin/env python3
"""
analyze_dead_trades.py
======================
Reads uts_exit_sweep_trades.csv (already on disk from the exit sweep)
and answers three questions with the system's own excursion history:

  1. RECOVERY CURVE — of trades that at some point were down X%,
     what fraction still finished positive? Where does recovery
     probability collapse? That collapse point IS the statistical
     "this trade is dead" line you asked for.

  2. STOP SWEEP — re-simulates the trades with a hard stop at each
     candidate depth (any trade whose MAE breached the stop exits at
     the stop instead of its real outcome). Shows PF / win rate /
     worst-trade impact at every stop level, so the stop is chosen
     by data, not by feel.

  3. PROFIT-CAP TEST — the other half of the bell-curve idea:
     re-simulates with a take-profit cap at each level (any trade
     whose MFE reached the cap exits there). Shows exactly how much
     PF the upside truncation costs. This is the honest test of
     "exit when price is far above the mean."

Approximations (stated, not hidden):
  - Stop fills AT the stop level — real fills gap slightly worse.
    Results are therefore mildly optimistic for tight stops.
  - Stop-only and cap-only re-simulations are each order-independent
    and exact given MAE/MFE. A COMBINED stop+cap cannot be simulated
    from this log (we don't know whether the high or the low came
    first inside each trade), so it is deliberately not shown.

Run:  cd ~/Documents/STS/15min && python3.12 analyze_dead_trades.py
Out:  prints tables + saves dead_trade_analysis.xlsx
"""

from pathlib import Path

import numpy as np
import pandas as pd

HERE      = Path(__file__).resolve().parent
TRADES    = HERE / 'uts_exit_sweep_trades.csv'
OUT_XLSX  = HERE / 'dead_trade_analysis.xlsx'

STRATEGY  = 'TIME_12W'          # the winning exit from the sweep
ALSO      = ['TIME_8W']         # secondary check, same tables

DD_GRID   = [-3, -5, -7, -9, -11, -13, -15, -18, -21, -25, -30]   # drawdown depths (%)
STOP_GRID = [5, 7, 9, 11, 13, 15, 18, 21, 25]                     # stop levels (%)
CAP_GRID  = [5, 8, 10, 12, 15, 20, 25, 30]                        # profit caps (%)


def metrics(rets):
    rets = np.asarray(rets, dtype=float)
    if len(rets) == 0:
        return dict(Trades=0, WinRate=None, PF=None, AvgRet=None, MedRet=None)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    gl = abs(losses.sum())
    pf = round(wins.sum() / gl, 3) if gl > 0 else float('inf')
    return dict(Trades=len(rets),
                WinRate=round(len(wins) / len(rets) * 100, 1),
                PF=pf,
                AvgRet=round(rets.mean(), 3),
                MedRet=round(float(np.median(rets)), 3))


def recovery_curve(df):
    """P(final win | trade was at some point down at least X%)."""
    rows = []
    for depth in DD_GRID:
        hit = df[df.mae_pct <= depth]
        if len(hit) < 20:
            continue
        finished_pos = (hit.ret_pct > 0).mean() * 100
        rows.append({
            'ReachedDrawdown': f'{depth}% or worse',
            'Trades': len(hit),
            'PctOfAll': round(len(hit) / len(df) * 100, 1),
            'StillWon%': round(finished_pos, 1),
            'AvgFinalRet%': round(hit.ret_pct.mean(), 2),
            'MedFinalRet%': round(hit.ret_pct.median(), 2),
        })
    return pd.DataFrame(rows)


def excursion_percentiles(df):
    """How deep do WINNERS actually dip vs LOSERS — the stop's raw material."""
    rows = []
    for label, grp in [('WINNERS', df[df.ret_pct > 0]),
                       ('LOSERS',  df[df.ret_pct <= 0])]:
        p = grp.mae_pct
        rows.append({
            'Group': label, 'Trades': len(grp),
            'MedianMAE%': round(p.median(), 2),
            'P75_MAE%':  round(p.quantile(0.25), 2),   # deeper quartile
            'P90_MAE%':  round(p.quantile(0.10), 2),
            'P95_MAE%':  round(p.quantile(0.05), 2),
            'WorstMAE%': round(p.min(), 2),
        })
    return pd.DataFrame(rows)


def stop_sweep(df):
    """Hard stop at -S%: any trade whose MAE breached it exits at -S%."""
    base = metrics(df.ret_pct.values)
    rows = [dict(Stop='NONE (baseline)', Stopped=0, StoppedPct=0.0, **base,
                 WorstTrade=round(df.ret_pct.min(), 1))]
    for s in STOP_GRID:
        stopped = df.mae_pct <= -s
        rets = np.where(stopped, -float(s), df.ret_pct.values)
        m = metrics(rets)
        rows.append(dict(Stop=f'-{s}%',
                         Stopped=int(stopped.sum()),
                         StoppedPct=round(stopped.mean() * 100, 1),
                         **m,
                         WorstTrade=round(float(rets.min()), 1)))
    return pd.DataFrame(rows)


def cap_sweep(df):
    """Take-profit at +C%: any trade whose MFE reached it exits at +C%."""
    base = metrics(df.ret_pct.values)
    rows = [dict(Cap='NONE (baseline)', Capped=0, CappedPct=0.0, **base)]
    for c in CAP_GRID:
        capped = df.mfe_pct >= c
        rets = np.where(capped, float(c), df.ret_pct.values)
        m = metrics(rets)
        rows.append(dict(Cap=f'+{c}%',
                         Capped=int(capped.sum()),
                         CappedPct=round(capped.mean() * 100, 1),
                         **m))
    return pd.DataFrame(rows)


def main():
    if not TRADES.exists():
        raise SystemExit(f'{TRADES.name} not found — run the exit sweep first.')
    tr = pd.read_csv(TRADES)
    need = {'strategy', 'ret_pct', 'mae_pct', 'mfe_pct'}
    if not need.issubset(tr.columns):
        raise SystemExit(f'Trade log missing columns {need - set(tr.columns)}')

    sheets = {}
    for strat in [STRATEGY] + ALSO:
        df = tr[tr.strategy == strat].dropna(subset=['ret_pct', 'mae_pct'])
        if len(df) < 100:
            print(f'  {strat}: only {len(df)} trades — skipped')
            continue

        rec  = recovery_curve(df)
        exc  = excursion_percentiles(df)
        stop = stop_sweep(df)
        cap  = cap_sweep(df)

        print('\n' + '=' * 66)
        print(f'  {strat}  ({len(df)} trades — ALL TIERS POOLED)')
        print('=' * 66)
        print('\n-- RECOVERY: if a trade got down to X, did it still win? --')
        print(rec.to_string(index=False))
        print('\n-- EXCURSION: how deep do winners actually dip? --')
        print(exc.to_string(index=False))
        print('\n-- STOP SWEEP: PF if a hard stop had been applied --')
        print(stop.to_string(index=False))
        print('\n-- PROFIT-CAP TEST: PF if gains were taken at +C% --')
        print(cap.to_string(index=False))

        sheets[f'{strat}_RECOVERY'] = rec
        sheets[f'{strat}_EXCURSION'] = exc
        sheets[f'{strat}_STOPS'] = stop
        sheets[f'{strat}_CAPS'] = cap

        # ── PER-CAP-TIER BREAKDOWN (primary strategy only) ──────────────────
        # One stop cannot fit MEGA and SMALL alike: the same -15% dip is a
        # crisis in a mega-cap and a normal week in a small-cap. These tables
        # let each tier earn its own stop from its own excursion history.
        if strat == STRATEGY and 'cap_tier' in df.columns:
            MIN_TIER_TRADES = 150
            for tier in ['MEGA', 'LARGE', 'MID', 'SMALL']:
                sub = df[df.cap_tier == tier]
                if len(sub) < MIN_TIER_TRADES:
                    if len(sub) > 0:
                        print(f'\n  [{tier}: only {len(sub)} trades — '
                              f'below {MIN_TIER_TRADES}, skipped]')
                    continue
                t_rec  = recovery_curve(sub)
                t_exc  = excursion_percentiles(sub)
                t_stop = stop_sweep(sub)

                print('\n' + '-' * 66)
                print(f'  {strat} | {tier} ONLY  ({len(sub)} trades)')
                print('-' * 66)
                print('\n-- RECOVERY --')
                print(t_rec.to_string(index=False))
                print('\n-- EXCURSION --')
                print(t_exc.to_string(index=False))
                print('\n-- STOP SWEEP --')
                print(t_stop.to_string(index=False))

                sheets[f'{tier}_RECOVERY'] = t_rec
                sheets[f'{tier}_EXCURSION'] = t_exc
                sheets[f'{tier}_STOPS'] = t_stop

            unk = (df.cap_tier == 'UNKNOWN').sum()
            if unk:
                print(f'\n  [{unk} trades have cap_tier UNKNOWN — '
                      f'pip3.12 install yfinance, delete cap_cache.json, '
                      f're-run the sweep to classify them]')

    if sheets:
        with pd.ExcelWriter(OUT_XLSX, engine='openpyxl') as xw:
            for name, df in sheets.items():
                df.to_excel(xw, sheet_name=name[:31], index=False)
        print(f'\n  Saved: {OUT_XLSX.name}')

    print("""
  HOW TO READ
  - PER-TIER TABLES: read each tier's EXCURSION winners' P90/P95 as
    that tier's natural noise floor. Expect MEGA/LARGE to earn a
    tighter stop (winners dip less) and SMALL to need a wider one.
    Set each tier's stop just past its winners' P90-P95, then check
    the tier's STOP SWEEP to confirm PF holds there. Conviction
    sizes the position; the tier's volatility places the stop.
  - RECOVERY: find the depth where StillWon% collapses (e.g. drops
    under ~25-30%). Below that depth you are statistically holding
    a dead trade. That depth is your stop candidate.
  - EXCURSION: sanity-check it — the stop should sit deeper than
    where most WINNERS dip (P90/P95), or you'll stop out trades
    that were about to work.
  - STOPS: the sweep shows the trade-off. The right stop keeps PF
    close to baseline while chopping WorstTrade and tail risk.
    If EVERY stop level lowers PF materially, the honest reading is
    that this signal's winners routinely dip deep, and the stop is
    a survivability tax you pay for holdability — choose the
    cheapest one, not none.
  - CAPS: expect PF to fall as the cap tightens. That fall is the
    price of 'take profit when extended' — the upper half of the
    bell-curve idea. If PF at +10% cap is much lower than baseline,
    the right tail is the edge and upside must stay uncapped.

  GLOSSARY
  MAE        Maximum Adverse Excursion — the DEEPEST a trade went
             against you between entry and exit (% of entry). The
             'pain' number. (Maximum, not mean — tables show the
             average of each trade's worst point.)
  MFE        Maximum Favorable Excursion — the BEST the trade ever
             looked before exit. The 'what was available' number.
  PF         Profit Factor = sum of wins / sum of losses.
             1.0 breakeven; 1.5 = $1.50 won per $1.00 lost.
  WinRate    % of trades ending positive (size-blind; PF has size).
  AvgRet     Mean % return per trade.  MedRet: median — when Avg is
             well above Med, a right tail of big winners is at work.
  StillWon%  Of trades that were AT SOME POINT down X% or worse,
             the share that still finished positive. Where this
             collapses = the statistical 'trade is dead' line.
  P90_MAE%   (winners) 90% of winning trades never dipped deeper
             than this — a stop tighter than this kills winners.
  Stopped    Trades a given stop level would have force-exited.
  Capped     Trades whose MFE reached the take-profit cap.
  WorstTrade Single worst final return in the set — the tail-risk
             number a stop exists to shrink.
""")


if __name__ == '__main__':
    main()
