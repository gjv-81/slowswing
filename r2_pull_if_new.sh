#!/bin/zsh
# r2_pull_if_new.sh — keep the laptop's copy of the nightly outputs current.
#
# After the cutover (2026-10-27) the nightly runs on GitHub and writes its results
# to the R2 bucket (sts-state/live/). This script runs on the Mac every hour via
# launchd (com.slowswing.r2pull) and, ONLY if the cloud has a newer session than
# the one on disk, pulls everything down: STS_holy_grail.xlsx, the tracker, the
# live book, board/regime JSON and the price-history folders. One tiny request
# per hour when nothing is new; a ~30-second sync when there is.
#
# Manual:  zsh ~/STS/15min/r2_pull_if_new.sh        (add --force to pull regardless)
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
LOG="$DIR/r2_pull.log"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
[ -f "$DIR/.r2_env" ] || { echo "$(date) missing .r2_env" >> "$LOG"; exit 1; }
command -v rclone >/dev/null 2>&1 || { echo "$(date) rclone missing" >> "$LOG"; exit 1; }
set -a; source "$DIR/.r2_env"; set +a
export RCLONE_CONFIG=/dev/null RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_REGION=auto RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true RCLONE_CONFIG_R2_ACL=private
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
B="${R2_BUCKET:-sts-state}"

remote="$(rclone cat "r2:$B/live/ci_last_session.txt" 2>/dev/null | tr -d '[:space:]')"
local_="$(cat "$DIR/ci_last_session.txt" 2>/dev/null | tr -d '[:space:]')"
if [ -z "$remote" ]; then echo "$(date) cloud has no session marker yet (CI not live?)" >> "$LOG"; exit 0; fi
if [ "$remote" = "$local_" ] && [ "$1" != "--force" ]; then exit 0; fi

echo "===== $(date) pulling session $remote (laptop had ${local_:-none}) =====" >> "$LOG"
zsh "$DIR/r2_sync_mac.sh" down >> "$LOG" 2>&1 && echo "$remote" > "$DIR/ci_last_session.txt"
# keep the laptop's git in step with the cloud's nightly "(CI)" commits so a later
# site push is never rejected as out of date; local edits are auto-stashed/restored
( cd "$DIR" && /usr/bin/git pull -q --rebase --autostash origin main >> "$LOG" 2>&1 && echo "git: in step with origin/main" >> "$LOG" || echo "git: pull --rebase needs attention (see above)" >> "$LOG" )
echo "----- done $(date): STS_holy_grail.xlsx $(stat -f '%Sm' STS_holy_grail.xlsx 2>/dev/null) -----" >> "$LOG"
# tell the phone, so a missing message is itself a signal
TG="$(grep '^TG_TOKEN=' "$DIR/.env" | cut -d= -f2- | tr -d '"'"'"' )"; CH="$(grep '^TG_CHAT=' "$DIR/.env" | cut -d= -f2- | tr -d '"'"'"' )"
[ -n "$TG" ] && curl -sS -m 15 -X POST "https://api.telegram.org/bot${TG}/sendMessage" --data-urlencode "chat_id=${CH:-6499078442}" --data-urlencode "text=💻 laptop synced session $remote from the cloud (workbook updated)" >/dev/null 2>&1 || true
