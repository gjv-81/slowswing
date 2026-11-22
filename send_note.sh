#!/bin/zsh
# send_note.sh — email an announcement that is NOT a journal post (a new page, a notice).
#
#   ./send_note.sh announcements/market-health.json --test          only to you, with the Publish button
#   ./send_note.sh announcements/market-health.json --test you@x.y  only to that address
#   ./send_note.sh announcements/market-health.json                 real send (asks you to type SEND)
#
# Same rails as send_post.sh: the worker's /api/announce, one send per slug, every
# signup who has not opted out. The JSON holds slug, title, intro (HTML), excerpt (plain
# text), and optionally kicker, path (page to link to), cta (button text), date.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
FILE="$1"; MODE="$2"; TO="$3"
[ -f "$FILE" ] || { echo "usage: $0 <announcement.json> [--test [email]]"; exit 1; }
[ -f "$DIR/.announce_key" ] || { echo "missing $DIR/.announce_key"; exit 1; }
KEY="$(cat "$DIR/.announce_key")"
BODY="$(node -e '
  const o=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));
  if(!o.slug||!o.title||!o.intro){ console.error("slug, title and intro are required"); process.exit(2); }
  if(process.argv[2]==="--test"){ o.test=true; if(process.argv[3]) o.to=process.argv[3]; }
  process.stdout.write(JSON.stringify(o));
' "$FILE" "$MODE" "$TO")"
printf '%s' "$BODY" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const o=JSON.parse(s);console.log((o.test?"TEST → "+(o.to||"NOTIFY_EMAIL"):"REAL SEND to all signups")+"\n  "+o.title+"\n  links to: #"+(o.path||"post/"+o.slug))})'
if [ "$MODE" != "--test" ]; then
  printf "Type SEND to confirm: "; read ans; [ "$ans" = "SEND" ] || { echo "aborted"; exit 1; }
fi
curl -sS -X POST "https://theslowswing.com/api/announce" \
  -H "authorization: Bearer $KEY" -H "content-type: application/json" \
  --data "$BODY"
echo
