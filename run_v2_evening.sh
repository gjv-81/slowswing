#!/bin/zsh
# STS v2 evening runner — cron 5:30pm weekdays (BEFORE the 6:30pm live run, so
# v2_new_today.txt is ready for the combined Telegram). Location-independent.
#   crontab line:  30 17 * * 1-5  ~/STS/15min/run_v2_evening.sh
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/v2_evening.log"
PY="/usr/local/bin/python3.12"

echo "===== v2 cron START $(/bin/date) =====" >> "$LOG" 2>&1
cd "$DIR" || { echo "cd failed" >> "$LOG"; exit 1; }
rm -rf "$HOME/.cache/py-yfinance" 2>/dev/null

n=0
while [ $n -lt 3 ]; do
  /usr/bin/caffeinate -i "$PY" "$DIR/refresh_v2.py" >> "$LOG" 2>&1 \
    && /usr/bin/caffeinate -i "$PY" "$DIR/eval_universe_v2.py" >> "$LOG" 2>&1
  rc=$?
  if [ $rc -eq 0 ]; then break; fi
  n=$((n+1))
  echo "----- v2 retry $n, waiting 90s -----" >> "$LOG" 2>&1
  sleep 90
done
echo "===== v2 cron END $(/bin/date) rc=$rc after $((n+1)) attempt(s) =====" >> "$LOG" 2>&1
