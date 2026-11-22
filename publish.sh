#!/bin/zsh
# publish.sh — one run: send whatever is committed to GitHub (site deploys itself),
# and, if a post slug is given, email YOU the owner preview with the Publish button.
#
#   ./publish.sh                         push only (site / data / worker changes)
#   ./publish.sh this-looks-like-2022    push, wait for the deploy, then the preview email
#
# Nothing here approves anything: a post goes live only if the website chat already
# committed it with published:true after your go-ahead, and members are emailed only
# when you press the button in the preview email.
set -e
cd "$(cd "$(dirname "$0")" && pwd)"
rm -f .git/index.lock .git/HEAD.lock .git/ORIG_HEAD.lock .git/objects/maintenance.lock .git/refs/remotes/origin/main.lock 2>/dev/null || true
git pull --rebase --autostash origin main
git push origin main
echo "✔ pushed: $(git log --oneline -1)"
if [ -n "$1" ]; then
  echo "waiting 90s for the site to deploy…"; sleep 90
  ./send_post.sh "$1" --test
  echo "✔ preview email sent to you — press 'Publish to members' in it to send to everyone"
fi
