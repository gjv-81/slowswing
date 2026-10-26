#!/usr/bin/env bash
# =============================================================================
# run_nightly_ci.sh — The Slow Swing nightly, GitHub Actions edition.
#
# Mirrors run_v2_evening.sh + run_evening.sh step for step, on Linux, with the
# state (price history, the live book, the workbook, archives) kept in a
# Cloudflare R2 bucket instead of on the laptop:
#
#   sync DOWN from R2  →  v2 scan  →  X200-G  →  live scan + tracker + workbook
#   →  regime + board + stats  →  [publish: teaser, wrangler deploy, KV]
#   →  sync UP to R2  →  [publish: commit state files back to the repo]
#   →  Telegram ❌ on any failure (plus a one-line ✅/shadow summary)
#
# MODES  (env PUBLISH)
#   PUBLISH=0  shadow — runs everything, publishes NOTHING (no Cloudflare, no
#              KV, no git push, no member Telegram). Outputs go to R2 under
#              shadow/ so they can be diffed against the Mac's real run.
#   PUBLISH=1  live — the Mac's job, done here.
#
# ENV (GitHub secrets / variables → see .github/workflows/nightly.yml)
#   MARKETSTACK_API_KEY  EOD_PROVIDER=marketstack  STS_FORCE_YAHOO (0/1)
#   TG_TOKEN TG_CHAT     CLOUDFLARE_API_TOKEN
#   R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY  R2_BUCKET (default sts-state)
#
# Everything is relative to the repo root (this file's folder). No zsh, no
# caffeinate, no /usr/local paths, TZ pinned to New York so every date in the
# Python matches what the Mac would have computed.
# =============================================================================
set -u
export TZ=America/New_York
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
PY="${PYTHON:-python3}"
LOG="$DIR/evening.log"
V2LOG="$DIR/v2_evening.log"
PUBLISH="${PUBLISH:-0}"
R2_BUCKET="${R2_BUCKET:-sts-state}"
PREFIX_DOWN="live"                                   # state always comes from the real run
PREFIX_UP=$([ "$PUBLISH" = "1" ] && echo "live" || echo "shadow")
export EOD_PROVIDER="${EOD_PROVIDER:-marketstack}"
export PYTHONUNBUFFERED=1

log()  { echo "$*" | tee -a "$LOG"; }
stamp(){ date '+%a %b %d %H:%M:%S %Z %Y'; }

# ---- Telegram straight from bash (python's send_telegram is used by the scan;
#      this one is for the runner's own alerts, and works even if python died)
tg() {
  [ -n "${TG_TOKEN:-}" ] && [ -n "${TG_CHAT:-}" ] || return 0
  curl -sS -m 20 -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
       --data-urlencode "chat_id=${TG_CHAT}" --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

# ---- rclone remote "r2" configured purely from env (no config file on disk)
export RCLONE_CONFIG=/dev/null
export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_REGION=auto
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true     # token is scoped to one bucket; never try to create it
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID:-}"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY:-}"
export RCLONE_CONFIG_R2_ENDPOINT="https://${R2_ACCOUNT_ID:-}.r2.cloudflarestorage.com"
export RCLONE_CONFIG_R2_ACL=private
RC="rclone --fast-list --transfers 32 --checkers 32 --checksum --stats-one-line --stats 30s -q"

# What lives in R2. Folders are synced whole; state files are copied by name.
STATE_DIRS="daily_data_10y daily_data_v2 daily_data_ext daily_data_slow_ext daily_data_10y_retired uw_archive/earnings_hist holy_grail_archive"
STATE_FILES="sts_ml_paper_trades.csv sts_ml_paper_tracker.xlsx STS_holy_grail.xlsx STS_holy_grail_v2.xlsx \
             v2_alerted_history.csv v2_new_today.txt x200g_log.csv qualgate_cache.csv cap_cache.json names.json \
             regime.json board.json site/stats_history.json site/teaser.json ci_last_session.txt"

# ---- the session this run is for (last closed session, ET) ----------------
SESSION="$($PY - <<'EOF'
import datetime as dt
from zoneinfo import ZoneInfo
now = dt.datetime.now(ZoneInfo("America/New_York")); d = now.date()
if (now.hour, now.minute) < (16, 0): d -= dt.timedelta(days=1)
while d.weekday() >= 5: d -= dt.timedelta(days=1)
print(d.isoformat())
EOF
)"

echo "===== CI START $(stamp) session=$SESSION publish=$PUBLISH provider=$EOD_PROVIDER force_yahoo=${STS_FORCE_YAHOO:-0} =====" | tee -a "$LOG" "$V2LOG"

# ---- 0. state down ---------------------------------------------------------
log "----- R2 sync down ($PREFIX_DOWN/) -----"
for d in $STATE_DIRS; do
  mkdir -p "$d"
  $RC sync "r2:$R2_BUCKET/$PREFIX_DOWN/$d" "$d" 2>>"$LOG" || log "!! sync down failed: $d"
done
for f in $STATE_FILES; do
  $RC copyto "r2:$R2_BUCKET/$PREFIX_DOWN/$f" "$f" 2>/dev/null || true
done
n10=$(ls daily_data_10y/*.csv 2>/dev/null | wc -l); nv2=$(ls daily_data_v2/*.csv 2>/dev/null | wc -l)
log "  state: $n10 files in daily_data_10y, $nv2 in daily_data_v2, book $(wc -l < sts_ml_paper_trades.csv 2>/dev/null || echo 0) lines"
if [ "$n10" -lt 500 ] || [ ! -s sts_ml_paper_trades.csv ]; then
  log "!! state looks EMPTY — refusing to run (seed R2 from the Mac first: r2_seed.sh)"
  tg "❌ CI nightly $SESSION: R2 state missing/empty — run r2_seed.sh on the Mac. Nothing was changed."
  exit 2
fi
# already done tonight? (second cron slot, or a manual re-run)
if [ "$(cat ci_last_session.txt 2>/dev/null)" = "$SESSION" ] && [ "${FORCE_RUN:-0}" != "1" ]; then
  log "----- session $SESSION already processed by CI — exiting -----"
  exit 0
fi
rm -rf "$HOME/.cache/py-yfinance" 2>/dev/null

# ---- 1. v2 research scan (its own log, like the Mac) ----------------------
echo "===== v2 CI START $(stamp) =====" >> "$V2LOG"
n=0; v2rc=1
while [ $n -lt 3 ]; do
  $PY refresh_v2.py >> "$V2LOG" 2>&1 && $PY eval_universe_v2.py >> "$V2LOG" 2>&1
  v2rc=$?; [ $v2rc -eq 0 ] && break
  n=$((n+1)); echo "----- v2 retry $n, waiting 90s -----" >> "$V2LOG"; sleep 90
done
echo "===== v2 CI END $(stamp) rc=$v2rc after $((n+1)) attempt(s) =====" >> "$V2LOG"

# ---- 2. X200-G observation --------------------------------------------------
log "----- x200g observation -----"
$PY x200g_observe.py >> "$LOG" 2>&1

# ---- 3. live scan + tracker + workbook (3 attempts) ------------------------
# In shadow mode the scan must not message members: blank the token for python only.
SCAN_TG="${TG_TOKEN:-}"; [ "$PUBLISH" = "1" ] || SCAN_TG=""
n=0; rc=1
while [ $n -lt 3 ]; do
  TG_TOKEN="$SCAN_TG" $PY sts_ml_evening.py >> "$LOG" 2>&1
  rc=$?
  if [ $rc -eq 0 ] && ! tail -20 "$LOG" | grep -q "download failed"; then break; fi
  n=$((n+1)); log "----- retry $n (download failed or error), waiting 90s -----"; sleep 90
done
SCAN_OK=1; { [ $rc -ne 0 ] || tail -20 "$LOG" | grep -q "download failed"; } && SCAN_OK=0

# ---- 4. regime + board + month-end stats -----------------------------------
log "----- build_regime + build_board -----"
$PY build_regime.py >> "$LOG" 2>&1
BOARD="marketstack"
if [ "${STS_FORCE_YAHOO:-0}" = "1" ]; then
  log "----- STS_FORCE_YAHOO=1: board from workbook prices, no Marketstack call -----"
  PC_SOURCE=workbook $PY build_board.py >> "$LOG" 2>&1; brc=$?; BOARD="workbook"
else
  $PY build_board.py >> "$LOG" 2>&1; brc=$?
fi
if [ $brc -ne 0 ] && [ "$BOARD" = "marketstack" ]; then
  if [ $SCAN_OK -eq 1 ]; then
    log "----- marketstack board rc=$brc -> falling back to workbook prices -----"
    PC_SOURCE=workbook $PY build_board.py >> "$LOG" 2>&1; brc=$?; BOARD="workbook"
  else
    log "----- marketstack board rc=$brc AND scan failed -> NOT publishing -----"; BOARD="none"
  fi
fi
$PY build_stats.py >> "$LOG" 2>&1

# ---- 5. publish (live mode only) -------------------------------------------
DEPLOY_OK=1
if [ "$PUBLISH" = "1" ]; then
  if [ "$BOARD" != "none" ] && [ $brc -eq 0 ]; then
    log "----- publish to cloudflare -----"
    d=0; DEPLOY_OK=0
    while [ $d -lt 3 ]; do
      bash deploy_site.sh >> "$LOG" 2>&1 && { DEPLOY_OK=1; break; }
      d=$((d+1)); log "----- deploy attempt $d failed, waiting 120s -----"; sleep 120
    done
  else
    log "----- publish SKIPPED (board=$BOARD rc=$brc) -----"
  fi
else
  log "----- SHADOW: publish skipped by design (board=$BOARD rc=$brc) -----"
  # shadow still builds the public teaser so it can be diffed; never deploys it
  $PY build_teaser.py >> "$LOG" 2>&1 || true
fi

# ---- 6. fast-lane flame scan (no-op without a UW token file) ---------------
$PY uw_flame_live.py >> "$LOG" 2>&1 || true

# ---- 7. state up ------------------------------------------------------------
echo "$SESSION" > ci_last_session.txt
log "----- R2 sync up ($PREFIX_UP/) -----"
UP_OK=1
for d in $STATE_DIRS; do
  [ -d "$d" ] || continue
  $RC sync "$d" "r2:$R2_BUCKET/$PREFIX_UP/$d" 2>>"$LOG" || { log "!! sync up failed: $d"; UP_OK=0; }
done
for f in $STATE_FILES; do
  [ -f "$f" ] && { $RC copyto "$f" "r2:$R2_BUCKET/$PREFIX_UP/$f" 2>>"$LOG" || UP_OK=0; }
done
$RC copyto "$LOG" "r2:$R2_BUCKET/$PREFIX_UP/logs/evening_$SESSION.log" 2>/dev/null || true
$RC copyto "$V2LOG" "r2:$R2_BUCKET/$PREFIX_UP/logs/v2_evening_$SESSION.log" 2>/dev/null || true

# ---- 8. commit state files back to the repo (live only; audit trail) --------
if [ "$PUBLISH" = "1" ] && [ -d .git ]; then
  log "----- git push-back -----"
  git add -A sts_ml_paper_trades.csv sts_ml_paper_tracker.xlsx STS_holy_grail.xlsx STS_holy_grail_v2.xlsx \
             v2_alerted_history.csv v2_new_today.txt x200g_log.csv qualgate_cache.csv cap_cache.json \
             regime.json board.json site/stats_history.json site/teaser.json site/version.json 2>/dev/null
  git -c user.name="STS nightly (CI)" -c user.email="gjv1000@gmail.com" commit -q -m "nightly $SESSION (CI)" >> "$LOG" 2>&1 || true
  git push -q origin HEAD:main >> "$LOG" 2>&1 && log "----- git push OK -----" || log "!! git push failed (non-fatal)"
fi

# ---- 9. verdict --------------------------------------------------------------
NEW="$(grep -m1 -o "Appended [0-9]* new\|No new qualifiers[^.]*" "$LOG" | tail -1)"
PROBLEM=0
[ $SCAN_OK -eq 0 ] || [ "$BOARD" = "none" ] || [ $brc -ne 0 ] || [ $DEPLOY_OK -eq 0 ] || [ $UP_OK -eq 0 ] || [ $v2rc -ne 0 ] && PROBLEM=1
if [ $PROBLEM -eq 1 ]; then
  MSG="❌ CI nightly $SESSION ($([ "$PUBLISH" = "1" ] && echo LIVE || echo shadow)) had a problem:"
  [ $v2rc -ne 0 ]       && MSG="$MSG
• v2 research scan failed (Yahoo from the runner?) — research only, nothing visible"
  [ $SCAN_OK -eq 0 ]    && MSG="$MSG
• live scan FAILED after 3 attempts — no new names tonight"
  [ "$BOARD" = "none" ] && MSG="$MSG
• board NOT rebuilt — site still shows the previous session"
  [ $brc -ne 0 ]        && MSG="$MSG
• build_board exited $brc"
  [ $DEPLOY_OK -eq 0 ]  && MSG="$MSG
• Cloudflare publish FAILED 3x — public site stale"
  [ $UP_OK -eq 0 ]      && MSG="$MSG
• R2 sync up incomplete — next run may start from older state"
  MSG="$MSG
Log: GitHub → Actions → nightly → this run (evening.log artifact)"
  tg "$MSG"
elif [ "$PUBLISH" != "1" ]; then
  tg "👻 CI shadow $SESSION OK · board=$BOARD · ${NEW:-scan ok} · outputs in r2:$R2_BUCKET/shadow/"
fi
echo "===== CI END $(stamp) rc=$rc scan_ok=$SCAN_OK board=$BOARD deploy_ok=$DEPLOY_OK up_ok=$UP_OK problem=$PROBLEM =====" | tee -a "$LOG"
exit $PROBLEM
