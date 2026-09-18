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
"$PY" "$DIR/build_board.py" >> "$LOG" 2>&1
brc=$?
if [ $brc -ne 0 ]; then
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
if [ "$BOARD" != "none" ] && [ $brc -eq 0 ]; then
  echo "----- publish to cloudflare -----" >> "$LOG" 2>&1
  /bin/zsh "$DIR/deploy_site.sh" >> "$LOG" 2>&1
else
  echo "----- publish SKIPPED (board=$BOARD rc=$brc) -----" >> "$LOG" 2>&1
fi

# --- positive failure alert (added 2026-09-16) ---
# The summary Telegram only goes out on success, so silence was the only alarm.
# Now a failed scan, a failed board build or a skipped publish each say so.
if [ $SCAN_OK -eq 0 ] || [ "$BOARD" = "none" ] || [ $brc -ne 0 ]; then
  MSG="❌ STS evening run problem $(/bin/date '+%a %b %d')"
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

echo "===== cron END $(/bin/date) rc=$rc after $((n+1)) attempt(s) board=$BOARD =====" >> "$LOG" 2>&1
