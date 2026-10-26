#!/bin/zsh
# STS evening runner — called by cron. Location-independent: uses its own folder,
# so it works wherever this folder lives (no hardcoded ~/Documents path).
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/evening.log"
PY="/usr/local/bin/python3.12"

echo "===== cron START $(/bin/date) =====" >> "$LOG" 2>&1
cd "$DIR" || { echo "cd failed" >> "$LOG"; exit 1; }
# wipe the yfinance HTTP/tz cache first — it corrupts on dropped connections
# (common while travelling), which was causing "unable to open database file"
rm -rf "$HOME/.cache/py-yfinance" 2>/dev/null

# retry the run up to 3 times, 90s apart, so a brief loss of connection
# self-heals instead of failing the whole evening
# --- X200-G observation scan FIRST (logs tonight's signals; main message reads the log) ---
echo "----- x200g observation -----" >> "$LOG" 2>&1
"$PY" "$DIR/x200g_observe.py" >> "$LOG" 2>&1

n=0
while [ $n -lt 3 ]; do
  /usr/bin/caffeinate -i "$PY" "$DIR/sts_ml_evening.py" >> "$LOG" 2>&1
  rc=$?
  if [ $rc -eq 0 ] && ! tail -20 "$LOG" | grep -q "download failed"; then
    break
  fi
  n=$((n+1))
  echo "----- retry $n (download failed or error), waiting 90s -----" >> "$LOG" 2>&1
  sleep 90
done
# Did the scan actually succeed? (rc from the last attempt, plus the log check
# the retry loop uses.) A failed scan means NO new names tonight, and the
# workbook still holds yesterday's prices — so it must not be used as a
# price source tonight either.
SCAN_OK=1
if [ $rc -ne 0 ] || tail -20 "$LOG" | grep -q "download failed"; then SCAN_OK=0; fi

# --- website refresh: 4-zone regime dial + board.json (added 2026-08-30) ---
echo "----- build_regime + build_board -----" >> "$LOG" 2>&1
/usr/bin/caffeinate -i "$PY" "$DIR/build_regime.py" >> "$LOG" 2>&1

# Board prices come from MARKETSTACK for the ~64 live names (licensed feed,
# ~1,400 requests/month). build_board's freshness guard exits non-zero if the
# vendor hasn't posted today's bar or the pull failed; then, ONLY if tonight's
# scan succeeded (so the workbook is fresh), fall back to the workbook's own
# prices. If both the scan and the vendor failed, publish nothing: yesterday's
# board stays live rather than yesterday's prices wearing today's date.
BOARD="marketstack"
if [ "${STS_FORCE_YAHOO:-0}" = "1" ]; then
  # TEMP 2026-10-22: everything on Yahoo until Marketstack billing is settled —
  # the board takes the workbook's (tracker/Yahoo) closes, zero vendor calls.
  echo "----- STS_FORCE_YAHOO=1: board from workbook prices, no Marketstack call -----" >> "$LOG" 2>&1
  PC_SOURCE=workbook "$PY" "$DIR/build_board.py" >> "$LOG" 2>&1
  brc=$?; BOARD="workbook"
else
"$PY" "$DIR/build_board.py" >> "$LOG" 2>&1
brc=$?
fi
if [ $brc -ne 0 ] && [ "$BOARD" = "marketstack" ]; then
  if [ $SCAN_OK -eq 1 ]; then
    echo "----- marketstack board rc=$brc -> falling back to workbook prices -----" >> "$LOG" 2>&1
    PC_SOURCE=workbook "$PY" "$DIR/build_board.py" >> "$LOG" 2>&1
    brc=$?; BOARD="workbook"
  else
    echo "----- marketstack board rc=$brc AND scan failed -> NOT publishing -----" >> "$LOG" 2>&1
    BOARD="none"
  fi
fi

# --- month-end track-record snapshot for the home-page headline (added 2026-09-18) ---
# No-op except on the last trading day of the month; writes site/stats_history.json.
"$PY" "$DIR/build_stats.py" >> "$LOG" 2>&1

# --- publish board.json to Cloudflare / theslowswing.com (added 2026-09-06) ---
DEPLOY_OK=1
if [ "$BOARD" != "none" ] && [ $brc -eq 0 ]; then
  echo "----- publish to cloudflare -----" >> "$LOG" 2>&1
  # 2026-10-13: a single transient "fetch failed" from wrangler left the public
  # site a day stale while the run reported success. Retry with a pause, and
  # treat a final failure as a failure (alert below).
  d=0; DEPLOY_OK=0
  while [ $d -lt 3 ]; do
    /bin/zsh "$DIR/deploy_site.sh" >> "$LOG" 2>&1 && { DEPLOY_OK=1; break; }
    d=$((d+1)); echo "----- deploy attempt $d failed, waiting 120s -----" >> "$LOG" 2>&1; sleep 120
  done
else
  echo "----- publish SKIPPED (board=$BOARD rc=$brc) -----" >> "$LOG" 2>&1
fi

# --- positive failure alert (added 2026-09-16) ---
# The summary Telegram only goes out on success, so silence was the only alarm.
# Now a failed scan, a failed board build or a skipped publish each say so.
if [ $SCAN_OK -eq 0 ] || [ "$BOARD" = "none" ] || [ $brc -ne 0 ] || [ $DEPLOY_OK -eq 0 ]; then
  MSG="❌ STS evening run problem $(/bin/date '+%a %b %d')"
  [ $DEPLOY_OK -eq 0 ] && MSG="$MSG
• Cloudflare publish FAILED 3x (network?) — public site still shows the previous session; member board in KV may be current. Fix: zsh ~/STS/15min/deploy_site.sh"
  [ $SCAN_OK -eq 0 ] && MSG="$MSG
• scan FAILED after 3 attempts (Yahoo/yfinance down?) — no new names tonight"
  case "$BOARD" in
    marketstack) MSG="$MSG
• board prices refreshed from Marketstack, site is current" ;;
    workbook)    MSG="$MSG
• Marketstack had no fresh bar, board used workbook prices" ;;
    none)        MSG="$MSG
• board NOT republished — site still shows the previous session" ;;
  esac
  MSG="$MSG
Fix: pip3.12 install -U yfinance  then  zsh ~/STS/15min/run_evening.sh"
  # cwd is $DIR (cd at the top), and `python -` puts cwd on sys.path
  "$PY" - "$MSG" <<'PYEOF' >> "$LOG" 2>&1
import sys
from sts_ml_evening import send_telegram
send_telegram(sys.argv[1])
PYEOF
fi

# --- fast-lane flame scan (added 2026-09-27) ---
# Fully automated ask-side flame check on tonight's quiet S2/B2 candidates.
# Exits quietly if no UW token file exists (.env_uw_live / .env_uw), so this
# line is safe to keep here before the personal API account is active.
echo "----- fast-lane flame scan -----" >> "$LOG" 2>&1
"$PY" "$DIR/uw_flame_live.py" >> "$LOG" 2>&1

# --- nightly push to GitHub (added 2026-09-18) ---
# The cloud copy (github.com/gjv-81/slowswing, private) is never more than a
# day old, so troubleshooting can happen without the laptop. .gitignore keeps
# secrets and the big data folders out. Failures are logged, never fatal.
if [ -d "$DIR/.git" ]; then
  echo "----- git push -----" >> "$LOG" 2>&1
  ( cd "$DIR" && /usr/bin/git add -A >> "$LOG" 2>&1 \
    && /usr/bin/git -c user.name="STS nightly" -c user.email="gjv1000@gmail.com" commit -q -m "nightly $(/bin/date '+%Y-%m-%d %H:%M')" >> "$LOG" 2>&1 \
    ; /usr/bin/git push -q origin main >> "$LOG" 2>&1 && echo "----- git push OK -----" >> "$LOG" || echo "!! git push failed (see above)" >> "$LOG" )
fi

# --- keep the Cloudflare R2 state bucket current (shadow period of the GitHub
#     migration; the CI reads its starting state from r2:sts-state/live/).
#     No-op until .r2_env exists. See r2_sync_mac.sh.
# After the GitHub cutover the CLOUD owns the state. A manual Mac run must not
# push its (possibly older) state over the cloud's unless explicitly asked:
#   STS_PRIMARY=1 zsh run_all_evening.sh     (fallback night only, after r2_pull_if_new.sh --force)
if [ "${STS_PRIMARY:-0}" = "1" ] && [ -f "$DIR/.r2_env" ] && command -v rclone >/dev/null 2>&1; then
  echo "----- R2 sync up (STS_PRIMARY=1) -----" >> "$LOG" 2>&1
  /bin/zsh "$DIR/r2_sync_mac.sh" up >> "$LOG" 2>&1 || echo "!! R2 sync failed (non-fatal)" >> "$LOG"
fi

echo "===== cron END $(/bin/date) rc=$rc after $((n+1)) attempt(s) board=$BOARD =====" >> "$LOG" 2>&1
