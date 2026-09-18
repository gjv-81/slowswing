#!/bin/zsh
# Publish the current board.json to Cloudflare (theslowswing.com).
# Called at the end of run_evening.sh; also safe to run by hand to force a refresh.
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/evening.log"
SITE="$DIR/site"
WRANGLER="$DIR/node_modules/.bin/wrangler"

# make sure node is on PATH (cron uses a minimal PATH); .node_path is written during setup
[ -f "$DIR/.node_path" ] && source "$DIR/.node_path"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Cloudflare auth token (chmod 600). Never echoed.
[ -f "$DIR/.cf_token" ] && export CLOUDFLARE_API_TOKEN="$(cat "$DIR/.cf_token")"
if [ -z "$CLOUDFLARE_API_TOKEN" ]; then
  echo "!! deploy skipped: missing $DIR/.cf_token" >> "$LOG"; exit 1
fi
if [ ! -x "$WRANGLER" ]; then
  echo "!! deploy skipped: wrangler not installed (run: cd $DIR && npm install wrangler)" >> "$LOG"; exit 1
fi

# refresh the board the site serves, then deploy the assets folder
[ -f "$DIR/board.json" ] || { echo "!! no board.json to publish" >> "$LOG"; exit 1; }

# The full board is GATED. It must NEVER sit in site/ — anything in there is a
# public asset, and one fetch of /board.json would walk straight around the paywall.
rm -f "$SITE/board.json"

# Public feed for signed-out visitors: all retired names (the Track Record) plus
# exactly one current name as the home-page hook.
PY312="/usr/local/bin/python3.12"
[ -x "$PY312" ] || PY312="$(command -v python3)"
"$PY312" "$DIR/build_teaser.py" >> "$LOG" 2>&1 || echo "!! build_teaser failed" >> "$LOG"
cd "$DIR" || exit 1
# Version stamp. The live page fetches this (no-cache) on every navigation and
# reloads itself when the value changes — Cloudflare sends no ETag on these
# responses, so this is what "is there a newer deploy?" compares against.
printf '{"v":"%s"}\n' "$(/bin/date -u +%Y%m%dT%H%M%SZ)" > "$SITE/version.json"
echo "----- cloudflare deploy $(/bin/date) version=$(cat "$SITE/version.json") -----" >> "$LOG"
"$WRANGLER" deploy >> "$LOG" 2>&1
rc=$?
if [ $rc -eq 0 ]; then echo "----- deploy OK -----" >> "$LOG"; else echo "----- deploy FAILED rc=$rc -----" >> "$LOG"; fi

# --- also publish the board into KV, where the gated /api/board reads it ---
# (site/board.json stays for now so the ungated site keeps working; delete it
#  from site/ once the front-end gate is switched on, or the paywall leaks.)
echo "----- kv put board:current -----" >> "$LOG" 2>&1
"$WRANGLER" kv key put "board:current" --path="$DIR/board.json" --binding=STORE --remote >> "$LOG" 2>&1 \
  && echo "----- kv OK -----" >> "$LOG" || echo "!! kv put failed" >> "$LOG"

exit $rc
