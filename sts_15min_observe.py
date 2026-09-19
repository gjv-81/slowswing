#!/usr/bin/env python3
"""
STS 15-Minute OBSERVE Scanner
==============================
A LIVE scanner for the 15-minute variant of the v3.2 strategy — running in
OBSERVE-ONLY mode. It detects triggers in real time, logs every one to a
file, and sends an OBSERVE-tagged Telegram message. It opens NO positions,
tracks NO P&L, and takes NO trades. Its only job is to build a forward
dataset of live 15-min triggers while the chunked backtest validation is
still in progress.

WHY OBSERVE-ONLY:
  The 15-min strategy is still being validated chunk by chunk. Chunk 2
  (Feb-Mar) lost money on every exit rule — the strategy is regime-
  dependent and NOT yet cleared for live trading. This scanner exists to
  collect live triggers for later comparison against the backtest, NOT to
  trade them. Every Telegram message says so explicitly.

WHAT IT IS NOT:
  Not sts_universe_scanner.py. That is the deployed 5-min trading scanner
  with a position tracker, exits, and EOD P&L. This file is a pared-down
  observer: no PositionTracker, no exits, no EOD results, no order logic.

ENGINE:
  Imports evaluate_ticker from sts_signal_engine_15m.py (the 15-min lift).
  Schwab serves 5-min bars; this scanner resamples them to 15-min before
  calling the engine — the same path timeframe_test.py uses, so live
  triggers are directly comparable to the backtest.

CADENCE:
  Scans every 15 minutes, aligned to 15-min candle closes with a 2-minute
  buffer: 9:47, 10:02, 10:17 ... 15:47 ET. (The v3.2 5-min scanner scans
  every 5 min; this is its 15-min equivalent.)

OPENING-BAR FLAG:
  The engine's cross logic has a known, unfixed bug — the EMAs compute
  across the overnight gap, so the first 15-min bar of the day can produce
  gap-artifact crosses. Triggers on the first bar are TAGGED suspect in
  both the log and the Telegram message so the forward dataset is not
  silently polluted.

Files (all in ~/Documents/STS/15min/):
  sts_15min_observe.py        — this file
  sts_signal_engine_15m.py    — the 15-min engine
  sts_indicators.py           — indicator math
  sts_universe_list.py        — ticker universe (read from parent STS/ or here)
  observe_triggers_YYYY-MM-DD.csv — the forward trigger log (auto-written)
  sts_15min_observe.log       — run log

Run:  caffeinate -i python3.12 ~/Documents/STS/15min/sts_15min_observe.py
"""

import os, sys, ssl, time, csv, re, logging, warnings
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pytz
import requests
import schedule

SCRIPT_DIR = Path(__file__).resolve().parent          # ~/Documents/STS/15min
STS_DIR    = SCRIPT_DIR.parent                        # ~/Documents/STS
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(STS_DIR))

# ─── IMPORT THE 15-MIN ENGINE ────────────────────────────────────────────────

try:
    from sts_signal_engine_15m import evaluate_ticker, resample_tf, \
                                       MIN_BARS_BASE, MIN_BARS_DAILY
except ImportError as e:
    print(f"ERROR: could not import sts_signal_engine_15m.py from {SCRIPT_DIR}")
    print(f"  {e}")
    print(f"  sts_signal_engine_15m.py and sts_indicators.py must be in {SCRIPT_DIR}")
    sys.exit(1)

try:
    from sts_universe_list import UNIVERSE_TICKERS
except ImportError:
    print(f"ERROR: sts_universe_list.py not found in {STS_DIR} or {SCRIPT_DIR}")
    sys.exit(1)

warnings.filterwarnings('ignore')
ssl._create_default_https_context = ssl._create_unverified_context

# ─── CONFIG ──────────────────────────────────────────────────────────────────

API_KEY    = 'rvtokLB0MCZNlXfY3QqY251qeXR8rCyQs8zBYzAp3w6m30Ek'
APP_SECRET = 'hjJ3ErG8mF7gyxk74ws6ujphCwr9CGlyen4rN7XlrqmJlqoRmqqrmSnX9Qpfjv3P'
# token lives on the Desktop (confirmed working path)
TOKEN_PATH = '/Users/Gagan/Desktop/schwab_token.json'

TELEGRAM_TOKEN   = 'REVOKED-see-.env'
TELEGRAM_CHAT_ID = '6499078442'

LOG_FILE   = SCRIPT_DIR / 'sts_15min_observe.log'
# OptionDrift sweep paste file — lives in the parent STS folder, same file
# the deployed 5-min scanner reads. If absent, sweep tagging is simply skipped.
SWEEP_FILE = STS_DIR / 'optiondrift_paste.txt'

ET = pytz.timezone('US/Eastern')

# ─── GAMMA FLIP — market-regime context for the Telegram message ─────────────
# Static dict, updated MANUALLY each morning from OptionDrift Net Drift
# (or FlashAlpha GEX). Only SPY and QQQ are needed here: the observe
# scanner watches the whole universe, so per-ticker gamma lines would not
# make sense — but the SPY/QQQ regime applies market-wide to every
# trigger. If a level is missing the regime block simply says 'no γ'.
#
#   >> UPDATE THESE TWO NUMBERS EACH MORNING <<
GAMMA_FLIP = {
    'SPY': 733.00,
    'QQQ': 702.00,
}

# Pre-filter — cheap quote screen before the expensive multi-TF fetch.
PREFILTER_MIN_PRICE = 100.0
PREFILTER_MIN_VOL   = 100_000
PRE_FILTER_MAX_QTY  = 500
MAX_WORKERS         = 8

DAILY_LOOKBACK_DAYS = 180
# The engine builds a 15/30/60-min ladder. The 60-min rung needs
# MIN_BARS_T3 (85) sixty-minute bars — and 60-min bars accrue slowly
# (~6-7 per trading day), so the lookback must be wide enough that even
# the SLOWEST rung has enough history. 30 days gave only ~55 sixty-min
# bars (too few). 120 calendar days yields ~80 trading days -> ~520+
# sixty-min bars, comfortably above the 85 minimum. The bare 5-min fetch
# returns full history regardless, so a wide trim window costs nothing.
FIVE_MIN_LOOKBACK_DAYS = 120

SCAN_START = dt_time(9, 30)
SCAN_END   = dt_time(16, 0)

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, mode='a')],
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('schwab.client').setLevel(logging.WARNING)
log = logging.getLogger(__name__)

# ─── SCHWAB ──────────────────────────────────────────────────────────────────

schwab_client = None

def init_schwab():
    global schwab_client
    try:
        import schwab
        schwab_client = schwab.auth.client_from_token_file(
            token_path=TOKEN_PATH, api_key=API_KEY, app_secret=APP_SECRET)
        log.info("Schwab client ready")
        return True
    except Exception as e:
        log.error(f"Schwab init failed: {e}")
        return False

# ─── SWEEP TICKER PARSING (ported verbatim from sts_universe_scanner.py) ──────
#
# Reads the OptionDrift paste file and extracts ticker symbols, so each logged
# trigger can be tagged with whether that ticker had a sweep that day. This is
# the SAME logic the deployed 5-min scanner uses — ticker presence in the file
# is the flag. Empty set on any error (sweep tagging just turns off).

SKIP_WORDS = {
    'A','I','CALL','PUT','BUY','SELL','FOR','AT','IS','TO','BE','BY','UP','DOWN',
    'ETF','OTC','IPO','PE','EPS','PT','PM','AM','ET','EST','PST','UTC','USD','OPEX',
    'OI','IV','HV','MM','AH','PH','GEX','DEX','FOMC','CPI','PMI','GDP','NFP','PPI',
    'COMP','TWO','ALL','ONE','NEW','OLD','MAY','JUN','JUL','AUG','SEP','OCT',
    'NOV','DEC','JAN','FEB','MAR','APR','MON','TUE','WED','THU','FRI','SAT','SUN',
    'OF','OR','IN','ON','AS','IT','SO','NO','YES','BIG','PRO','THE','AND',
    'BID','ASK','VOL','OPEN','HIGH','LOW','CLOSE','LAST','CHG','PCT',
    'FLOW','SWEEP','BLOCK','WHALE','BULL','BEAR','LONG','SHORT','TYPE','SIDE',
    'EXP','STRIKE','DAYS','DAY','HOUR','MIN','SEC','MARK','SPREAD','SPOT','STS',
}

def load_sweep_tickers():
    """Read the OptionDrift paste file, extract ticker symbols. Empty set on
    any error or if the file is missing/too short."""
    if not SWEEP_FILE.exists():
        return set()
    try:
        text = SWEEP_FILE.read_text()
        if len(text) < 100:
            return set()
        raw = set(re.findall(r'\b[A-Z]{1,5}\b', text))
        return raw - SKIP_WORDS
    except Exception as e:
        log.warning(f"Sweep file read failed: {e}")
        return set()

# ─── DATA FETCH ──────────────────────────────────────────────────────────────

def fetch_bulk_quotes(tickers):
    if not schwab_client:
        return {}
    quotes = {}
    for i in range(0, len(tickers), 200):
        try:
            resp = schwab_client.get_quotes(tickers[i:i+200])
            if resp.status_code == 200:
                quotes.update(resp.json())
        except Exception as e:
            log.warning(f"Bulk quote chunk {i} failed: {e}")
    return quotes

def fetch_daily_history(ticker):
    """Daily bars. Called BARE then trimmed — same reasoning as the 5-min
    fetch: explicit start_datetime can make the endpoint return a short
    slice. Bare call is reliable."""
    if not schwab_client:
        return None
    try:
        resp = schwab_client.get_price_history_every_day(ticker)
        if resp.status_code != 200:
            return None
        candles = resp.json().get('candles', [])
        if not candles:
            return None
        df = pd.DataFrame(candles)
        df['datetime'] = pd.to_datetime(df['datetime'], unit='ms', utc=True)
        df = df.set_index('datetime').rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'})
        df.index = df.index.tz_convert(ET)
        cutoff = pd.Timestamp.now(tz=ET) - timedelta(days=DAILY_LOOKBACK_DAYS)
        df = df[df.index >= cutoff]
        return df.dropna()
    except Exception:
        return None

def fetch_5m_history(ticker):
    """5-minute regular-session bars. Resampled to 15-min by the caller.

    NOTE: the Schwab 5-min endpoint is called BARE (no start_datetime) —
    passing start_datetime makes it return a tiny broken slice (~600 bars
    instead of ~17k). download_market_data.py calls it bare and works; this
    matches that. We trim to the lookback window AFTER fetching."""
    if not schwab_client:
        return None
    try:
        resp = schwab_client.get_price_history_every_five_minutes(ticker)
        if resp.status_code != 200:
            return None
        candles = resp.json().get('candles', [])
        if not candles:
            return None
        df = pd.DataFrame(candles)
        df['datetime'] = pd.to_datetime(df['datetime'], unit='ms', utc=True)
        df = df.set_index('datetime').rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'})
        df.index = df.index.tz_convert(ET)
        # regular session only
        df = df[((df.index.hour > 9) | ((df.index.hour == 9) & (df.index.minute >= 30)))
                & (df.index.hour < 16)]
        # trim to the lookback window (endpoint returns full history)
        cutoff = pd.Timestamp.now(tz=ET) - timedelta(days=FIVE_MIN_LOOKBACK_DAYS)
        df = df[df.index >= cutoff]
        return df.dropna()
    except Exception:
        return None

def to_15min(df_5m):
    """Resample 5-min OHLCV to 15-min, grouped per trading day so no candle
    spans the overnight gap. Matches the path used by timeframe_test.py."""
    if df_5m is None or len(df_5m) == 0:
        return None
    agg = {'Open': 'first', 'High': 'max', 'Low': 'min',
           'Close': 'last', 'Volume': 'sum'}
    parts = []
    for _, day in df_5m.groupby(df_5m.index.date):
        r = day.resample('15min', label='right', closed='right').agg(agg).dropna()
        parts.append(r)
    return pd.concat(parts) if parts else None

def fetch_ticker_bundle(ticker):
    """Fetch daily + 15-min (resampled from 5-min) for one ticker."""
    df_d  = fetch_daily_history(ticker)
    df_5m = fetch_5m_history(ticker)
    df_15 = to_15min(df_5m)
    return ticker, df_d, df_15

# ─── TELEGRAM ────────────────────────────────────────────────────────────────

def send_telegram(message):
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'},
            timeout=10)
        return resp.json().get('ok', False)
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False

def _levels_for(r):
    """Reference entry / stop / target from an evaluate_ticker() result.
    These are REFERENCE values for outcome comparison — not trade levels."""
    entry = r['price']
    atr_v = r.get('atr') or 0.0
    if r['signal'] == 'BUY':
        stop   = r.get('recent_low_5m') or (entry - atr_v)
        target = entry + 2 * atr_v
    else:
        stop   = r.get('recent_high_5m') or (entry + atr_v)
        target = entry - 2 * atr_v
    return round(entry, 2), round(stop, 2), round(target, 2)

def is_opening_bar(now_et):
    """First scan of the day = the 9:47 scan, evaluating the first 15-min
    candle (09:30-09:45). Triggers there are gap-bug suspect."""
    return now_et.time() < dt_time(10, 0)

def build_regime_block(quotes):
    """Build the MARKET REGIME lines for the Telegram message.

    Reads SPY and QQQ last price from the universe `quotes` dict already
    fetched by scan(). If either index is not in the universe (and so
    not in `quotes`), it is fetched directly — a tiny 2-symbol call.
    Each price is compared to its GAMMA_FLIP level. If a quote or a
    flip level is missing, that index shows 'no γ' rather than guessing.
    """
    # SPY/QQQ may not be in UNIVERSE_TICKERS — fetch any that are missing
    need = [s for s in ('SPY', 'QQQ')
            if not quotes.get(s, {}).get('quote', {}).get('lastPrice')]
    idx_quotes = dict(quotes)
    if need and schwab_client:
        try:
            extra = fetch_bulk_quotes(need)
            idx_quotes.update(extra)
        except Exception as e:
            log.warning(f"Regime index quote fetch failed: {e}")

    def idx_price(sym):
        q = idx_quotes.get(sym, {}).get('quote', {})
        p = q.get('lastPrice', 0) or 0
        return float(p) if p else None

    def idx_line(sym):
        price = idx_price(sym)
        flip = GAMMA_FLIP.get(sym)
        if price is None:
            return f"{sym}  no quote", None
        if flip is None:
            return f"{sym}  ${price:.0f}  no γ level set", None
        diff = price - flip
        ok = diff > 0
        regime = '+gamma ✅' if ok else '-gamma ⚠️'
        sign = '+' if diff >= 0 else ''
        return (f"{sym}  ${price:.0f}  γ${flip:.0f}  "
                f"{regime} ({sign}{diff:.1f})"), ok

    spy_line, spy_ok = idx_line('SPY')
    qqq_line, qqq_ok = idx_line('QQQ')

    if spy_ok and qqq_ok:
        verdict = '✅ GREEN LIGHT — both indices positive gamma'
    elif spy_ok is None or qqq_ok is None:
        verdict = 'ℹ️ regime partial — missing index data'
    elif spy_ok or qqq_ok:
        verdict = '⚠️ CAUTION — mixed regime'
    else:
        verdict = '🔴 WAIT — both indices below gamma flip'

    return ['<b>MARKET REGIME</b>', spy_line, qqq_line, verdict]


def build_observe_message(now_et, triggers, opening_flag, quotes=None):
    """Composite-table message, matching the 5-min scanner's format.
    Header says OBSERVE so the two scanners are distinguishable in Telegram.
    Columns: Time | Sym★ | Dir | Entry | Stop | Target — same layout the
    5-min scanner uses. GAP tag is a tiny marker on opening-bar triggers."""
    time_str = now_et.strftime('%I:%M %p ET')
    lines = [
        f"<b>📊 STS SCAN — OBSERVE — {time_str}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    # market regime block — shown every scan, triggers or not
    if quotes is not None:
        lines += build_regime_block(quotes)
        lines.append("━━━━━━━━━━━━━━━━━━━━")

    if not triggers:
        lines.append("No changes — scanner running normally.")
        return '\n'.join(lines)

    lines.append(f"<b>NEW ENTRIES ({len(triggers)})</b>")
    lines.append("<code>Time   Sym     Dir  Entry    Stop     Target</code>")
    for r in triggers:
        entry, stop, target = _levels_for(r)
        sym  = r['ticker']
        star = '★' if r.get('in_sweep') else ' '
        icon = '🟢' if r['signal'] == 'BUY' else '🔴'
        gap  = '·' if opening_flag else ' '   # tiny opening-bar marker
        t = now_et.strftime('%H:%M')
        lines.append(
            f"<code>{t}  {sym:<5}{star} {icon}  "
            f"{entry:<8.2f} {stop:<8.2f} {target:<8.2f}{gap}</code>"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    legend = "★ = in OptionDrift sweep file   🟢 BUY  🔴 SELL"
    if opening_flag:
        legend += "   · = opening bar (gap-cross suspect)"
    lines.append(legend)
    lines.append("<i>OBSERVE feed — logged for comparison, not trade signals.</i>")
    return '\n'.join(lines)

# ─── TRIGGER LOG (the forward dataset) ───────────────────────────────────────

LOG_COLUMNS = [
    'scan_time_et', 'ticker', 'signal', 'ref_entry', 'ref_stop',
    'ref_target', 'atr', 'score', 'in_sweep', 'opening_bar_suspect', 'reason',
]

def log_path_for(now_et):
    return SCRIPT_DIR / f"observe_triggers_{now_et.date().isoformat()}.csv"

def append_triggers(now_et, triggers, opening_flag):
    """Append this scan's triggers to today's CSV — the forward dataset."""
    if not triggers:
        return
    path = log_path_for(now_et)
    new_file = not path.exists()
    try:
        with open(path, 'a', newline='') as f:
            w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
            if new_file:
                w.writeheader()
            for r in triggers:
                entry, stop, target = _levels_for(r)
                w.writerow({
                    'scan_time_et': now_et.strftime('%Y-%m-%d %H:%M:%S'),
                    'ticker': r['ticker'],
                    'signal': r['signal'],
                    'ref_entry': entry,
                    'ref_stop': stop,
                    'ref_target': target,
                    'atr': round(r.get('atr') or 0.0, 4),
                    'score': r.get('score', ''),
                    'in_sweep': 'YES' if r.get('in_sweep') else 'no',
                    'opening_bar_suspect': 'YES' if opening_flag else 'no',
                    'reason': r.get('reason', ''),
                })
        log.info(f"  Logged {len(triggers)} trigger(s) -> {path.name}")
    except Exception as e:
        log.error(f"  Trigger log write failed: {e}")

# ─── SCAN ────────────────────────────────────────────────────────────────────

def is_scan_window(now_et):
    if now_et.weekday() >= 5:
        return False
    return SCAN_START <= now_et.time() <= SCAN_END

def run_scan():
    now_et = datetime.now(ET)
    if not is_scan_window(now_et):
        return

    opening_flag = is_opening_bar(now_et)
    log.info("=" * 60)
    log.info(f"  STS 15-min OBSERVE scan @ {now_et.strftime('%H:%M ET')}"
             f"{'  [OPENING BAR — gap-bug suspect]' if opening_flag else ''}")
    log.info("=" * 60)

    # ── Stage 1: bulk quotes -> cheap pre-filter ─────────────────────────────
    t0 = time.time()
    quotes = fetch_bulk_quotes(UNIVERSE_TICKERS)
    log.info(f"Stage 1: {len(quotes)} quotes in {time.time()-t0:.1f}s")

    sweep_tickers = load_sweep_tickers()
    log.info(f"Sweep file: {len(sweep_tickers)} tickers loaded")

    pre = []
    for tk in UNIVERSE_TICKERS:
        q = quotes.get(tk, {}).get('quote', {})
        px  = q.get('lastPrice', 0) or 0
        vol = q.get('totalVolume', 0) or 0
        if px >= PREFILTER_MIN_PRICE and vol >= PREFILTER_MIN_VOL:
            pre.append((tk, vol))
    pre.sort(key=lambda x: x[1], reverse=True)
    candidates = [tk for tk, _ in pre[:PRE_FILTER_MAX_QTY]]
    log.info(f"Stage 2: {len(candidates)} candidates after pre-filter")

    # ── Stage 3: parallel fetch + evaluate on 15-min bars ────────────────────
    log.info(f"Stage 3: parallel 15-min scan ({MAX_WORKERS} workers)...")
    scan_start = time.time()
    triggers = []
    fail_reasons = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_ticker_bundle, tk): tk for tk in candidates}
        for future in as_completed(futures):
            try:
                ticker, df_d, df_15 = future.result()
            except Exception:
                continue
            if df_d is None or len(df_d) < MIN_BARS_DAILY:
                fail_reasons['daily fetch'] = fail_reasons.get('daily fetch', 0) + 1
                continue
            if df_15 is None or len(df_15) < MIN_BARS_BASE:
                fail_reasons['15m fetch'] = fail_reasons.get('15m fetch', 0) + 1
                continue
            try:
                result = evaluate_ticker(ticker, df_d, df_15)
            except Exception as e:
                fail_reasons['engine error'] = fail_reasons.get('engine error', 0) + 1
                continue
            if result['signal'] in ('BUY', 'SELL'):
                result['in_sweep'] = ticker in sweep_tickers
                triggers.append(result)
                star = '★' if result['in_sweep'] else ' '
                tag = ' [GAP?]' if opening_flag else ''
                log.info(f"  {ticker:<6}{star} {result['signal']:<4} "
                         f"${result['price']:.2f}{tag}")
            else:
                cat = (result['reason'] or 'no signal').split(':')[0].split('—')[0].strip()
                fail_reasons[cat] = fail_reasons.get(cat, 0) + 1

    log.info(f"Scan complete in {time.time()-scan_start:.0f}s")
    log.info(f"  Triggers: {[r['ticker'] for r in triggers] or '(none)'}")
    if fail_reasons:
        top = sorted(fail_reasons.items(), key=lambda x: -x[1])[:6]
        log.info(f"  Top non-trigger reasons: {top}")

    # ── Log + notify ─────────────────────────────────────────────────────────
    append_triggers(now_et, triggers, opening_flag)
    msg = build_observe_message(now_et, triggers, opening_flag, quotes)
    if send_telegram(msg):
        log.info("  -> OBSERVE message sent")
    else:
        log.warning("  -> OBSERVE message FAILED to send")
    log.info("=" * 60 + "\n")

# ─── SCHEDULE ────────────────────────────────────────────────────────────────

def schedule_15min_aligned():
    """15-min candle closes at :45,:00,:15,:30 from 9:30. Scan 2 min after
    each: 9:47, 10:02, 10:17 ... 15:47 ET."""
    times = []
    t = 9 * 60 + 47
    end = 15 * 60 + 47
    while t <= end:
        times.append(f"{t // 60:02d}:{t % 60:02d}")
        t += 15
    for st in times:
        schedule.every().day.at(st, "America/New_York").do(run_scan)
    log.info(f"Scheduled {len(times)} scans: {times[0]} -> {times[-1]} ET")
    return times

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("  STS 15-Minute OBSERVE Scanner")
    log.info(f"  Universe: {len(UNIVERSE_TICKERS)} tickers")
    log.info(f"  Mode: OBSERVE ONLY — logs triggers, sends alerts, no trades")
    log.info(f"  Engine: sts_signal_engine_15m.py (15-min base, ladder 15/30/60)")
    log.info("=" * 60)

    if not init_schwab():
        sys.exit(1)

    scan_times = schedule_15min_aligned()

    send_telegram(
        "<b>👁 STS 15-Min OBSERVE Scanner Started</b>\n"
        f"Universe: {len(UNIVERSE_TICKERS)} tickers\n"
        f"Scans: every 15 min, {scan_times[0]}–{scan_times[-1]} ET\n"
        "\n"
        "<b>MODE: OBSERVE ONLY.</b> This scanner logs live 15-min triggers "
        "to build a forward dataset for comparison against the backtest. "
        "It opens no positions and takes no trades.\n"
        "\n"
        "<i>The 15-min strategy is still being validated chunk by chunk — "
        "chunk 2 (Feb-Mar) lost on every exit rule. These alerts are data, "
        "not trade signals. Opening-bar (9:47) triggers carry a small · "
        "marker — the overnight-gap-cross bug can mis-fire there. ★ marks tickers in the "
        "OptionDrift sweep file, so the sweep edge can be checked later.</i>\n"
        "\n"
        f"Triggers logged to: observe_triggers_{datetime.now(ET).date()}.csv"
    )

    now_et = datetime.now(ET)
    if is_scan_window(now_et):
        log.info("In scan window — running one scan now")
        run_scan()

    log.info("Scheduler running. Ctrl+C to stop.")
    while True:
        try:
            schedule.run_pending()
            time.sleep(15)
        except KeyboardInterrupt:
            log.info("Stopped by user")
            break
        except Exception as e:
            log.error(f"Loop error: {e}")
            time.sleep(30)

if __name__ == '__main__':
    main()
