#!/bin/zsh
# r2_sync_mac.sh — keep the Cloudflare R2 state bucket in step with this Mac.
#
#   zsh r2_sync_mac.sh up      Mac → R2 live/   (first-time seed, and the end of
#                              every Mac nightly while CI runs in shadow mode)
#   zsh r2_sync_mac.sh down    R2 live/ → Mac   (after cutover, to pull the
#                              CI's state back onto the laptop for a manual run)
#   zsh r2_sync_mac.sh diff    compare R2 shadow/ (the CI's outputs) with the
#                              Mac's own files — the shadow-night check
#
# Needs: brew install rclone, and ~/STS/15min/.r2_env (git-ignored, chmod 600):
#   R2_ACCOUNT_ID=...
#   R2_ACCESS_KEY_ID=...
#   R2_SECRET_ACCESS_KEY=...
#   R2_BUCKET=sts-state
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
[ -f "$DIR/.r2_env" ] || { echo "missing $DIR/.r2_env"; exit 1; }
command -v rclone >/dev/null 2>&1 || { echo "rclone is not installed. Run:  curl -fsSL https://rclone.org/install.sh | sudo bash"; exit 1; }
set -a; source "$DIR/.r2_env"; set +a
export RCLONE_CONFIG=/dev/null RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_REGION=auto RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true RCLONE_CONFIG_R2_ACL=private
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
B="${R2_BUCKET:-sts-state}"
RC=(rclone --fast-list --transfers 32 --checkers 32 --checksum --stats-one-line --stats 30s)

DIRS=(daily_data_10y daily_data_v2 daily_data_ext daily_data_slow_ext daily_data_10y_retired uw_archive/earnings_hist holy_grail_archive)
FILES=(sts_ml_paper_trades.csv sts_ml_paper_tracker.xlsx STS_holy_grail.xlsx STS_holy_grail_v2.xlsx
       v2_alerted_history.csv v2_new_today.txt x200g_log.csv qualgate_cache.csv cap_cache.json names.json
       regime.json board.json site/stats_history.json site/teaser.json)

case "$1" in
  up)
    for d in $DIRS; do [ -d "$d" ] && { echo "== $d"; $RC sync "$d" "r2:$B/live/$d"; }; done
    for f in $FILES; do [ -f "$f" ] && $RC copyto "$f" "r2:$B/live/$f"; done
    echo "R2 live/ is current ($(date))";;
  down)
    for d in $DIRS; do echo "== $d"; $RC sync "r2:$B/live/$d" "$d"; done
    for f in $FILES; do $RC copyto "r2:$B/live/$f" "$f" 2>/dev/null; done
    echo "Mac matches R2 live/ ($(date))";;
  diff)
    echo "== book (CI shadow vs Mac):"
    rclone cat "r2:$B/shadow/sts_ml_paper_trades.csv" | diff - sts_ml_paper_trades.csv && echo "   identical"
    echo "== board.json names (CI shadow vs Mac):"
    python3 - <<'EOF'
import json, subprocess, os
b = os.environ.get("R2_BUCKET", "sts-state")
ci = json.loads(subprocess.check_output(["rclone", "cat", f"r2:{b}/shadow/board.json"]))
mac = json.load(open("board.json"))
key = lambda d: {r["t"]: (r.get("setup"), r.get("phase"), round(r.get("chg") or 0, 1)) for r in d.get("names", [])}
a, m = key(ci), key(mac)
only_ci, only_mac = sorted(set(a) - set(m)), sorted(set(m) - set(a))
diffs = [t for t in set(a) & set(m) if a[t] != m[t]]
print(f"   CI {len(a)} names, Mac {len(m)} names; only-CI {only_ci[:10]}; only-Mac {only_mac[:10]}; differing {sorted(diffs)[:15]}")
EOF
    echo "== CI shadow session + log tail:"; rclone cat "r2:$B/shadow/ci_last_session.txt" 2>/dev/null
    L="$(rclone lsf "r2:$B/shadow/logs/" 2>/dev/null | grep '^evening_' | sort | tail -1)"
    [ -n "$L" ] && rclone cat "r2:$B/shadow/logs/$L" | grep "CI START\|Data source\|Scored\|wrote board\|CI END" | tail -6;;
  *) echo "usage: $0 up|down|diff"; exit 1;;
esac
