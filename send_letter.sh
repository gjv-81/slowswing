#!/bin/zsh
# send_letter.sh — send ONE personal note from The Slow Swing to ONE address.
#   ./send_letter.sh letters/<file>.json            (asks you to type SEND)
#   ./send_letter.sh letters/<file>.json --to-me    sends it to you instead, to check how it looks
# JSON: to, subject, html, text. Goes out from hello@theslowswing.com; replies reach support@.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"; FILE="$1"; MODE="$2"
[ -f "$FILE" ] || { echo "usage: $0 <letter.json> [--to-me]"; exit 1; }
KEY="$(cat "$DIR/.announce_key")"
BODY="$(node -e '
  const o=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));
  if(process.argv[2]==="--to-me"){ o.subject="[check] "+o.subject; o.to=process.argv[3]; }
  process.stdout.write(JSON.stringify(o));' "$FILE" "$MODE" "$(git -C "$DIR" config user.email 2>/dev/null || echo gjv1000@gmail.com)")"
printf '%s' "$BODY" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const o=JSON.parse(s);console.log("TO: "+o.to+"\nSUBJECT: "+o.subject)})'
if [ "$MODE" != "--to-me" ]; then printf "Type SEND to confirm: "; read ans; [ "$ans" = "SEND" ] || { echo "aborted"; exit 1; }; fi
curl -sS -X POST "https://theslowswing.com/api/letter" -H "authorization: Bearer $KEY" -H "content-type: application/json" --data "$BODY"; echo
