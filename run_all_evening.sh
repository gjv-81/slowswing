#!/bin/zsh
# STS master evening runner — ONE scheduled job, correct order, no overlap.
# -----------------------------------------------------------------------------
# Why this exists: v2 and the live run BOTH start with `rm -rf ~/.cache/py-yfinance`.
# If they ever overlap, one wipes the cache while the other is mid-download —
# the "unable to open database file" failure. Running them in sequence makes
# that impossible, and the live run starts the instant v2 finishes rather than
# waiting out a fixed gap.
#
# v2 first (so v2_new_today.txt is ready for the combined Telegram), then the
# live run — which builds the board AND publishes board.json to Cloudflare.
#
# Scheduled by launchd at 17:00 via ~/Library/LaunchAgents/com.gagan.sts.evening.plist
# (launchd, not cron, so a run missed while the Mac is asleep fires on wake).
# -----------------------------------------------------------------------------
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/evening.log"

echo "===== MASTER START $(/bin/date) =====" >> "$LOG" 2>&1

/bin/zsh "$DIR/run_v2_evening.sh"
echo "----- v2 finished, starting live run $(/bin/date) -----" >> "$LOG" 2>&1

/bin/zsh "$DIR/run_evening.sh"

echo "===== MASTER END $(/bin/date) =====" >> "$LOG" 2>&1
