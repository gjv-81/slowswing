#!/usr/bin/env python3
"""
backtest_uts_exit_sweep.py
==========================
Diagnoses WHY the UTS daily model backtested at PF 0.88:
was the ENTRY wrong, or was the EXIT killing good signals?

Same entries as backtest_uts_daily.py (fresh-cross of core_ok, enter
next bar's open, one position per ticker) — but sweeps NINE exits:

  TIME exits    : hold 2 / 4 / 6 / 8 / 12 weeks (10/20/30/40/60 bars),
                  exit at the close of the final bar. No judgment, pure clock.
  STRUCT exits  : first daily close below EMA21  -> exit next bar OPEN
                  first daily close below SMA50  -> exit next bar OPEN
  ATR trail     : 3 x ATR(14) trailing stop on highest close since entry
                  -> exit next bar OPEN
  UTS baseline  : the original uts_exit (imported from uts_exit.py)
                  so the PF 0.88 result is reproduced inside this run.

Every trade is tagged at ENTRY with:
  - RVOL20        : signal-day volume / 20-day average volume
  - V3_V5         : mean volume last 3 bars / mean volume prior 5 bars
  - OBV_SLOPE10   : 10-day OBV change, normalised by avg volume
  - CAP_TIER      : MEGA >=200B / LARGE 10-200B / MID 2-10B / SMALL <2B
                    (yfinance, cached to cap_cache.json after first run)
  - SPY_REGIME    : SPY close above/below its 200-SMA on entry day
                    (needs daily_data/SPY.csv)

HONESTY RULES
  - Signal on bar i close -> enter bar i+1 OPEN (no lookahead)
  - Structure/trail condition seen at close of bar j -> exit bar j+1 OPEN
  - Costs: 0.05% per side (0.10% round trip)
  - CENSORING: trades that cannot complete their horizon (or whose
    structure exit never fires) before data end are EXCLUDED from that
    strategy's stats and counted separately. Force-closing them at data
    end would bias exactly the long horizons we care about.
  - One open position per ticker per strategy.

RUN
  cd ~/Documents/STS/15min && python3.12 backtest_uts_exit_sweep.py

OUTPUT (same folder)
  uts_exit_sweep.xlsx        SUMMARY / CAP_TIERS / REGIME / VOLUME tabs
  uts_exit_sweep_trades.csv  full per-trade log, every strategy
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ─── CONFIG ──────────────────────────────────────────────────────────────────

HERE        = Path(__file__).resolve().parent
# optional CLI arg selects the data folder:
#   python3.12 backtest_uts_exit_sweep.py                -> daily_data/
#   python3.12 backtest_uts_exit_sweep.py daily_data_10y -> 10-year files
_arg        = sys.argv[1] if len(sys.argv) > 1 else 'daily_data'
DATA_DIR    = HERE / _arg
OUT_XLSX    = HERE / f'uts_exit_sweep{"" if _arg == "daily_data" else "_10y"}.xlsx'
OUT_CSV     = HERE / f'uts_exit_sweep_trades{"" if _arg == "daily_data" else "_10y"}.csv'
CAP_CACHE   = HERE / 'cap_cache.json'

ENGINE_MODULE = ''          # leave '' to auto-locate the file that defines
                            # compute_uts_daily_buy; or set e.g. 'uts_daily'

COST_PER_SIDE = 0.0005      # 0.05% each way
MIN_BARS      = 260         # ~1yr minimum history per ticker
TRADE_SIZE    = 10_000      # $ per trade for total-P&L illustration

TIME_HORIZONS = {           # label -> trading bars held
    'TIME_2W' : 10,
    'TIME_4W' : 20,
    'TIME_6W' : 30,
    'TIME_8W' : 40,
    'TIME_12W': 60,
}
STRUCT_EXITS = ['EMA21_BREAK', 'SMA50_BREAK', 'ATR3_TRAIL']
BASELINE     = 'UTS_EXIT'   # included only if uts_exit.py imports cleanly

CAP_TIERS = [               # (floor $, label) — checked in order
    (200e9, 'MEGA'),
    (10e9,  'LARGE'),
    (2e9,   'MID'),
    (0,     'SMALL'),
]

# ─── ENGINE / EXIT IMPORT ────────────────────────────────────────────────────

sys.path.insert(0, str(HERE))

def find_engine():
    """Import the module that defines compute_uts_daily_buy."""
    import importlib
    if ENGINE_MODULE:
        return importlib.import_module(ENGINE_MODULE)
    me = Path(__file__).name
    for p in sorted(HERE.glob('*.py')):
        if p.name == me:
            continue
        try:
            if 'def compute_uts_daily_buy' in p.read_text(errors='ignore'):
                print(f'  engine found: {p.name}')
                return importlib.import_module(p.stem)
        except Exception:
            continue
    raise SystemExit(
        'Could not locate compute_uts_daily_buy in any .py file here.\n'
        'Set ENGINE_MODULE at the top of this script to the module name.')

def find_uts_exit():
    try:
        import uts_exit
        print('  uts_exit.py found — UTS baseline included')
        return uts_exit
    except Exception as e:
        print(f'  uts_exit.py not importable ({e}) — baseline skipped')
        return None

# ─── DATA ────────────────────────────────────────────────────────────────────

COLMAP = {'open': 'Open', 'high': 'High', 'low': 'Low',
          'close': 'Close', 'volume': 'Volume',
          'adj close': 'Close', 'adj_close': 'Close'}

def load_daily(path):
    df = pd.read_csv(path)
    # normalise column names
    ren = {}
    for c in df.columns:
        key = str(c).strip().lower()
        if key in COLMAP:
            ren[c] = COLMAP[key]
        elif key in ('date', 'datetime', 'timestamp'):
            ren[c] = 'Date'
    df = df.rename(columns=ren)
    if 'Date' not in df.columns:
        df = df.rename(columns={df.columns[0]: 'Date'})
    df['Date'] = pd.to_datetime(df['Date'], utc=True, errors='coerce')
    df = df.dropna(subset=['Date']).set_index('Date').sort_index()
    df.index = df.index.tz_convert(None).normalize()
    need = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not all(c in df.columns for c in need):
        return None
    return df[need].dropna()

# ─── INDICATORS ──────────────────────────────────────────────────────────────

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def atr_wilder(df, n=14):
    h, l, c = df['High'], df['Low'], df['Close']
    tr = pd.concat([h - l, (h - c.shift()).abs(),
                    (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def obv(df):
    direction = np.sign(df['Close'].diff()).fillna(0)
    return (direction * df['Volume']).cumsum()

# ─── VOLUME TAGS AT SIGNAL BAR ───────────────────────────────────────────────

def volume_tags(df, sp):
    v = df['Volume'].values
    out = {'rvol20': np.nan, 'v3_v5': np.nan, 'obv_slope10': np.nan}
    if sp >= 20:
        base = v[sp - 20:sp].mean()
        if base > 0:
            out['rvol20'] = v[sp] / base
    if sp >= 8:
        last3  = v[sp - 2:sp + 1].mean()
        prior5 = v[sp - 7:sp - 2].mean()
        if prior5 > 0:
            out['v3_v5'] = last3 / prior5
    if sp >= 10:
        ob = obv(df).values
        avgv = v[max(0, sp - 20):sp].mean()
        if avgv > 0:
            out['obv_slope10'] = (ob[sp] - ob[sp - 10]) / (avgv * 10)
    return out

# ─── MARKET CAP ──────────────────────────────────────────────────────────────

def cap_tier(mc):
    if mc is None or (isinstance(mc, float) and np.isnan(mc)):
        return 'UNKNOWN'
    for floor, label in CAP_TIERS:
        if mc >= floor:
            return label
    return 'UNKNOWN'

def load_caps(tickers):
    caps = {}
    if CAP_CACHE.exists():
        try:
            caps = json.loads(CAP_CACHE.read_text())
        except Exception:
            caps = {}
    missing = [t for t in tickers if t not in caps]
    if missing:
        try:
            import yfinance as yf
            print(f'  fetching market cap for {len(missing)} tickers '
                  f'(one-time, cached to {CAP_CACHE.name})...')
            for i, t in enumerate(missing, 1):
                mc = None
                try:
                    fi = yf.Ticker(t).fast_info
                    mc = (fi.get('marketCap') if hasattr(fi, 'get') else None) \
                        or getattr(fi, 'market_cap', None)
                except Exception:
                    mc = None
                caps[t] = mc
                if i % 50 == 0:
                    print(f'    {i}/{len(missing)}')
                    CAP_CACHE.write_text(json.dumps(caps))
            CAP_CACHE.write_text(json.dumps(caps))
        except ImportError:
            print('  yfinance not installed for python3.12 — cap tiers '
                  'will show UNKNOWN. (pip3.12 install yfinance to enable)')
    return caps

# ─── SPY REGIME ──────────────────────────────────────────────────────────────

def load_spy_regime():
    """date -> 'SPY>200SMA' / 'SPY<200SMA'; empty dict if SPY.csv missing."""
    for name in ('SPY.csv', 'spy.csv'):
        p = DATA_DIR / name
        if p.exists():
            spy = load_daily(p)
            if spy is None or len(spy) < 200:
                break
            sma = spy['Close'].rolling(200).mean()
            flags = np.where(spy['Close'] > sma, 'SPY>200SMA', 'SPY<200SMA')
            ser = pd.Series(flags, index=spy.index)
            ser[sma.isna()] = 'UNKNOWN'
            return ser
    print('  daily_data/SPY.csv missing or short — regime tags = UNKNOWN')
    return pd.Series(dtype=object)

def load_spy_close():
    """SPY daily closes for relative-strength tagging."""
    for name in ('SPY.csv', 'spy.csv'):
        p = DATA_DIR / name
        if p.exists():
            spy = load_daily(p)
            if spy is not None and len(spy):
                return spy['Close']
    print('  daily_data/SPY.csv missing — RS tags will be blank')
    return pd.Series(dtype=float)

def regime_at(ser, date):
    if ser.empty:
        return 'UNKNOWN'
    try:
        sub = ser.loc[:date]
        return sub.iloc[-1] if len(sub) else 'UNKNOWN'
    except Exception:
        return 'UNKNOWN'

# ─── EXIT ENGINES ────────────────────────────────────────────────────────────
# Each returns (exit_pos, exit_price) or None if censored (can't complete).

def exit_time(df, ep, hold_bars):
    xp = ep + hold_bars - 1
    if xp >= len(df):
        return None
    return xp, float(df['Close'].iloc[xp])

def exit_close_below(df, ep, line):
    """First close below `line` after entry -> exit NEXT bar's open."""
    close = df['Close'].values
    ln = line.values
    for j in range(ep, len(df)):
        if not np.isnan(ln[j]) and close[j] < ln[j]:
            if j + 1 < len(df):
                return j + 1, float(df['Open'].iloc[j + 1])
            return None          # condition fired on last bar — censored
    return None                  # never fired — censored

def exit_atr_trail(df, ep, atr, mult=3.0):
    close = df['Close'].values
    a = atr.values
    hi = close[ep]
    for j in range(ep, len(df)):
        hi = max(hi, close[j])
        trail = hi - mult * a[j]
        if close[j] < trail:
            if j + 1 < len(df):
                return j + 1, float(df['Open'].iloc[j + 1])
            return None
    return None

def exit_uts(df, ep, uts_exit_mod, exit_series):
    try:
        res = uts_exit_mod.uts_exit_bar(df, ep, exit_series)
    except Exception:
        return None
    if res is None:
        return None
    # accept either an int position or a (pos, ...) tuple
    xp = res[0] if isinstance(res, (tuple, list)) else int(res)
    if xp is None or xp >= len(df):
        return None
    return xp, float(df['Close'].iloc[xp])

# ─── SIMULATION ──────────────────────────────────────────────────────────────

def run_strategy(df, sig_positions, exit_fn):
    """One ticker, one exit strategy. Returns (trades, n_censored)."""
    trades, censored = [], 0
    last_exit = -1
    lows = df['Low'].values
    highs = df['High'].values
    for sp in sig_positions:
        ep = sp + 1
        if ep >= len(df) or ep <= last_exit:
            continue
        entry = float(df['Open'].iloc[ep])
        if entry <= 0:
            continue
        res = exit_fn(df, ep)
        if res is None:
            censored += 1
            last_exit = len(df)      # position occupies ticker to data end
            continue
        xp, exit_px = res
        last_exit = xp
        eff_in  = entry  * (1 + COST_PER_SIDE)
        eff_out = exit_px * (1 - COST_PER_SIDE)
        ret = eff_out / eff_in - 1
        seg_lo = lows[ep:xp + 1].min()
        seg_hi = highs[ep:xp + 1].max()
        trades.append({
            'signal_date': df.index[sp].date(),
            'entry_date':  df.index[ep].date(),
            'exit_date':   df.index[xp].date(),
            'entry': round(entry, 2),
            'exit':  round(exit_px, 2),
            'ret_pct': round(ret * 100, 3),
            'hold_bars': xp - ep + 1,
            'mae_pct': round((seg_lo / entry - 1) * 100, 3),
            'mfe_pct': round((seg_hi / entry - 1) * 100, 3),
            'sig_pos': sp,
        })
    return trades, censored

# ─── METRICS ─────────────────────────────────────────────────────────────────

def metrics(rets):
    rets = np.asarray(rets, dtype=float)
    if len(rets) == 0:
        return dict(Trades=0, WinRate=None, PF=None, AvgRet=None,
                    MedRet=None, TotPnL=None)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    gross_w = wins.sum()
    gross_l = abs(losses.sum())
    pf = round(gross_w / gross_l, 3) if gross_l > 0 else float('inf')
    return dict(
        Trades=len(rets),
        WinRate=round(len(wins) / len(rets) * 100, 1),
        PF=pf,
        AvgRet=round(rets.mean(), 3),
        MedRet=round(float(np.median(rets)), 3),
        TotPnL=round(float(rets.sum() / 100 * TRADE_SIZE), 0),
    )

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print('=' * 64)
    print('  UTS Daily — Exit Sweep Backtest')
    print('=' * 64)

    if not DATA_DIR.exists():
        raise SystemExit(f'{DATA_DIR} not found — run from ~/Documents/STS/15min')

    engine = find_engine()
    uts_x = find_uts_exit()

    files = sorted(DATA_DIR.glob('*.csv'))
    tickers = [f.stem.upper() for f in files]
    print(f'  {len(files)} daily files in {DATA_DIR.name}/')

    caps = load_caps(tickers)
    spy_regime = load_spy_regime()
    spy_close = load_spy_close()

    strategies = list(TIME_HORIZONS) + STRUCT_EXITS + \
        ([BASELINE] if uts_x else [])

    all_trades = []
    censor_counts = {s: 0 for s in strategies}
    skipped = 0

    for n, f in enumerate(files, 1):
        tk = f.stem.upper()
        df = load_daily(f)
        if df is None or len(df) < MIN_BARS:
            skipped += 1
            continue

        # entry signal — fresh cross of core_ok
        try:
            sig_df = engine.compute_uts_daily_buy(df.copy())
            core = sig_df['core_ok'].astype(bool).values
        except Exception as e:
            print(f'  {tk}: engine error ({e}) — skipped')
            skipped += 1
            continue
        fresh = core & ~np.roll(core, 1)
        fresh[0] = False
        sig_positions = np.where(fresh)[0].tolist()
        if not sig_positions:
            continue

        # per-ticker precomputes
        ema21 = ema(df['Close'], 21)
        sma50 = df['Close'].rolling(50).mean()
        atr14 = atr_wilder(df, 14)
        uts_series = None
        if uts_x:
            try:
                uts_series = uts_x.compute_uts_exit_series(df.copy())
            except Exception:
                uts_series = None

        exit_fns = {}
        for label, bars in TIME_HORIZONS.items():
            exit_fns[label] = (lambda d, e, b=bars: exit_time(d, e, b))
        exit_fns['EMA21_BREAK'] = (lambda d, e: exit_close_below(d, e, ema21))
        exit_fns['SMA50_BREAK'] = (lambda d, e: exit_close_below(d, e, sma50))
        exit_fns['ATR3_TRAIL']  = (lambda d, e: exit_atr_trail(d, e, atr14))
        if uts_x and uts_series is not None:
            exit_fns[BASELINE] = (
                lambda d, e: exit_uts(d, e, uts_x, uts_series))

        tier = cap_tier(caps.get(tk))

        # relative strength vs SPY at the signal bar
        spy_al = (spy_close.reindex(df.index, method='ffill').values
                  if len(spy_close) else None)
        cl = df['Close'].values

        def rs_at(sp, bars):
            """Trailing `bars`-day stock return minus SPY return, in % pts."""
            if spy_al is None or sp < bars:
                return None
            s_now, s_then = spy_al[sp], spy_al[sp - bars]
            if (np.isnan(s_now) or np.isnan(s_then) or s_then <= 0
                    or cl[sp - bars] <= 0):
                return None
            stock_ret = cl[sp] / cl[sp - bars] - 1
            spy_ret = s_now / s_then - 1
            return round((stock_ret - spy_ret) * 100, 2)

        for strat, fn in exit_fns.items():
            trades, cens = run_strategy(df, sig_positions, fn)
            censor_counts[strat] += cens
            for t in trades:
                sp = t.pop('sig_pos')
                vt = volume_tags(df, sp)
                t.update({
                    'ticker': tk,
                    'strategy': strat,
                    'cap_tier': tier,
                    'regime': regime_at(spy_regime,
                                        pd.Timestamp(t['entry_date'])),
                    'rvol20': round(vt['rvol20'], 2)
                        if not np.isnan(vt['rvol20']) else None,
                    'v3_v5': round(vt['v3_v5'], 2)
                        if not np.isnan(vt['v3_v5']) else None,
                    'obv_slope10': round(vt['obv_slope10'], 3)
                        if not np.isnan(vt['obv_slope10']) else None,
                    'rs_4w': rs_at(sp, 20),
                    'rs_8w': rs_at(sp, 40),
                })
                all_trades.append(t)

        if n % 50 == 0:
            print(f'  [{n}/{len(files)}] processed...')

    if not all_trades:
        raise SystemExit('No trades produced — check engine output.')

    tr = pd.DataFrame(all_trades)
    tr.to_csv(OUT_CSV, index=False)
    print(f'\n  {len(tr)} completed trades logged '
          f'({skipped} tickers skipped)')

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    rows = []
    for s in strategies:
        sub = tr[tr.strategy == s]
        m = metrics(sub.ret_pct.values)
        m.update(Strategy=s,
                 Censored=censor_counts[s],
                 AvgHold=round(sub.hold_bars.mean(), 1) if len(sub) else None,
                 AvgMAE=round(sub.mae_pct.mean(), 2) if len(sub) else None,
                 AvgMFE=round(sub.mfe_pct.mean(), 2) if len(sub) else None)
        rows.append(m)
    summary = pd.DataFrame(rows)[
        ['Strategy', 'Trades', 'Censored', 'WinRate', 'PF', 'AvgRet',
         'MedRet', 'AvgHold', 'AvgMAE', 'AvgMFE', 'TotPnL']]

    # ── CAP TIERS ────────────────────────────────────────────────────────────
    rows = []
    for s in strategies:
        for tier in ['MEGA', 'LARGE', 'MID', 'SMALL', 'UNKNOWN']:
            sub = tr[(tr.strategy == s) & (tr.cap_tier == tier)]
            if len(sub) == 0:
                continue
            m = metrics(sub.ret_pct.values)
            m.update(Strategy=s, CapTier=tier)
            rows.append(m)
    cap_tab = pd.DataFrame(rows)[
        ['Strategy', 'CapTier', 'Trades', 'WinRate', 'PF',
         'AvgRet', 'MedRet', 'TotPnL']]

    # ── REGIME ───────────────────────────────────────────────────────────────
    rows = []
    for s in strategies:
        for reg in ['SPY>200SMA', 'SPY<200SMA', 'UNKNOWN']:
            sub = tr[(tr.strategy == s) & (tr.regime == reg)]
            if len(sub) == 0:
                continue
            m = metrics(sub.ret_pct.values)
            m.update(Strategy=s, Regime=reg)
            rows.append(m)
    reg_tab = pd.DataFrame(rows)[
        ['Strategy', 'Regime', 'Trades', 'WinRate', 'PF',
         'AvgRet', 'MedRet', 'TotPnL']]

    # ── VOLUME: winners vs losers + RVOL quartiles ───────────────────────────
    rows = []
    for s in strategies:
        sub = tr[(tr.strategy == s) & tr.rvol20.notna()]
        if len(sub) < 40:
            continue
        w = sub[sub.ret_pct > 0]
        l = sub[sub.ret_pct <= 0]
        rows.append({
            'Strategy': s, 'Slice': 'WINNERS',
            'Trades': len(w),
            'MeanRVOL': round(w.rvol20.mean(), 2),
            'MedRVOL': round(w.rvol20.median(), 2),
            'MeanV3V5': round(w.v3_v5.mean(), 2),
            'MeanOBVslope': round(w.obv_slope10.mean(), 3),
            'WinRate': None, 'PF': None})
        rows.append({
            'Strategy': s, 'Slice': 'LOSERS',
            'Trades': len(l),
            'MeanRVOL': round(l.rvol20.mean(), 2),
            'MedRVOL': round(l.rvol20.median(), 2),
            'MeanV3V5': round(l.v3_v5.mean(), 2),
            'MeanOBVslope': round(l.obv_slope10.mean(), 3),
            'WinRate': None, 'PF': None})
        # quartiles of RVOL within this strategy
        try:
            sub = sub.copy()
            sub['q'] = pd.qcut(sub.rvol20, 4,
                               labels=['Q1_low', 'Q2', 'Q3', 'Q4_high'])
            for q in ['Q1_low', 'Q2', 'Q3', 'Q4_high']:
                qq = sub[sub.q == q]
                m = metrics(qq.ret_pct.values)
                rows.append({
                    'Strategy': s, 'Slice': f'RVOL {q}',
                    'Trades': m['Trades'],
                    'MeanRVOL': round(qq.rvol20.mean(), 2),
                    'MedRVOL': round(qq.rvol20.median(), 2),
                    'MeanV3V5': round(qq.v3_v5.mean(), 2),
                    'MeanOBVslope': round(qq.obv_slope10.mean(), 3),
                    'WinRate': m['WinRate'], 'PF': m['PF']})
        except Exception:
            pass
    vol_tab = pd.DataFrame(rows)

    # ── RELATIVE STRENGTH: Gate 3's other half on trial ──────────────────────
    rows = []
    for s in strategies:
        sub = tr[(tr.strategy == s) & tr.rs_8w.notna()]
        if len(sub) < 40:
            continue
        for label, grp in [('RS8w > 0 (confirmed)', sub[sub.rs_8w > 0]),
                           ('RS8w <= 0 (knife)',    sub[sub.rs_8w <= 0])]:
            m = metrics(grp.ret_pct.values)
            m.update(Strategy=s, Slice=label,
                     MeanRS8=round(grp.rs_8w.mean(), 2))
            rows.append(m)
        try:
            sub = sub.copy()
            sub['q'] = pd.qcut(sub.rs_8w, 4,
                               labels=['Q1_weak', 'Q2', 'Q3', 'Q4_strong'])
            for q in ['Q1_weak', 'Q2', 'Q3', 'Q4_strong']:
                qq = sub[sub.q == q]
                m = metrics(qq.ret_pct.values)
                m.update(Strategy=s, Slice=f'RS8 {q}',
                         MeanRS8=round(qq.rs_8w.mean(), 2))
                rows.append(m)
        except Exception:
            pass
    rs_tab = pd.DataFrame(rows)
    if len(rs_tab):
        rs_tab = rs_tab[['Strategy', 'Slice', 'MeanRS8', 'Trades',
                         'WinRate', 'PF', 'AvgRet', 'MedRet', 'TotPnL']]

    # ── WRITE EXCEL ──────────────────────────────────────────────────────────
    with pd.ExcelWriter(OUT_XLSX, engine='openpyxl') as xw:
        summary.to_excel(xw, sheet_name='SUMMARY', index=False)
        cap_tab.to_excel(xw, sheet_name='CAP_TIERS', index=False)
        reg_tab.to_excel(xw, sheet_name='REGIME', index=False)
        vol_tab.to_excel(xw, sheet_name='VOLUME', index=False)
        if len(rs_tab):
            rs_tab.to_excel(xw, sheet_name='RS', index=False)

    if len(rs_tab):
        show = rs_tab[rs_tab.Strategy == 'TIME_12W']
        if len(show):
            print('\n  RS AUDITION — TIME_12W (full table in RS tab):')
            print(show.to_string(index=False))

    print(f'\n  Saved: {OUT_XLSX.name}  (+ {OUT_CSV.name})')
    print('\n' + '=' * 64)
    print('  SUMMARY — how to read it')
    print('=' * 64)
    print(summary.to_string(index=False))
    print("""
  READ:
  - If PF rises with the TIME horizon (2W -> 12W) and crosses 1.0,
    the entry was fine and the exit was the problem. Build on it.
  - If PF is flat/underwater at every horizon, the entry has no edge
    at swing timescales. Lean on SSI2 + confirmation instead.
  - CAP_TIERS: check whether any edge concentrates in MEGA/LARGE.
  - REGIME: check whether it only works when SPY > 200SMA (that is
    Gate 3 earning its place).
  - VOLUME: if WINNERS' MeanRVOL > LOSERS' and PF climbs Q1 -> Q4,
    the volume gate is real. If flat, drop the volume gate.
  - RS: Gate 3's relative-strength audition. If PF for 'RS8w > 0'
    beats 'RS8w <= 0' and climbs Q1_weak -> Q4_strong, entering
    with confirmation is real and the gate earns its slot. If flat
    or inverted (dip-buying wins), the confirmation gate is out.

  GLOSSARY
  PF          Profit Factor = sum of wins / sum of losses.
              1.0 breakeven; 1.5 = $1.50 won per $1.00 lost.
  WinRate     % of trades ending positive (size-blind; PF has size).
  AvgRet/MedRet  Mean / median % return per trade. Avg >> Med means
              a right tail of big winners is doing the lifting.
  AvgHold     Average bars held (daily data: bars = trading days).
  AvgMAE      Avg of each trade's Maximum Adverse Excursion — the
              DEEPEST it went against you before exit. Pain number.
  AvgMFE      Avg Maximum Favorable Excursion — the best each trade
              ever looked. What was available to capture.
  Censored    Trades excluded because data ended before their exit
              could complete (kept out so long horizons aren't
              biased by force-closing).
  TotPnL      Illustrative $ total at $10,000 per trade.
  RVOL20      Signal-day volume / its own 20-day average.
  V3_V5       Mean volume last 3 days / mean of prior 5 days
              (volume acceleration).
  OBV_SLOPE10 10-day On-Balance-Volume change, normalised by avg
              volume. Positive = quiet accumulation.
  Regime      SPY above/below its 200-day SMA on entry day.
  Fresh-cross Entry fires only the FIRST day core_ok turns true
              after being false — one entry per qualifying episode.
  RS_4W/RS_8W Relative strength: stock's trailing 20-/40-bar return
              MINUS SPY's return over the same window, in % points.
              Positive = already outperforming the market at entry
              (confirmed); negative = entering a laggard (knife).
""")

if __name__ == '__main__':
    main()
