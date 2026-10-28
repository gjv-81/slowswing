#!/bin/zsh
# send_post.sh — email a journal post to members.
#
#   ./send_post.sh <slug> --test          send ONLY to NOTIFY_EMAIL (you), records nothing
#   ./send_post.sh <slug> --test you@x.y  send only to that address
#   ./send_post.sh <slug>                 real send: every account that can open the board
#                                         today and has not opted out. Safe to re-run — a
#                                         (slug, email) pair is never sent twice.
#
# Reads the post from site/posts.js (title, date, read time, excerpt, first
# paragraph of the body) and hands it to the worker's /api/announce, which
# renders the email and sends through Resend. The key lives in ~/STS/15min/.announce_key
# (created once with:  wrangler secret put ANNOUNCE_KEY  — same value in both places).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
SLUG="$1"; MODE="$2"; TO="$3"
[ -z "$SLUG" ] && { echo "usage: $0 <slug> [--test [email]]"; exit 1; }
[ -f "$DIR/.announce_key" ] || { echo "missing $DIR/.announce_key"; exit 1; }
KEY="$(cat "$DIR/.announce_key")"

BODY="$(node -e '
  const vm=require("vm"), fs=require("fs");
  const c={}; vm.runInNewContext(fs.readFileSync(process.argv[1],"utf8")+";this.P=POSTS", c);
  const p=c.P.find(x=>x.slug===process.argv[2]);
  if(!p){ console.error("no post with slug "+process.argv[2]); process.exit(2); }
  if(p.sample){ console.error("refusing: post is marked sample:true"); process.exit(3); }
  if(p.published!==true){ console.error("refusing: post is not published (needs `published: true` in posts.js — GJ approves, then the blog chat sets it)"); process.exit(4); }
  // first paragraph of the body = the teaser
  const m=p.body.match(/<p[\s\S]*?<\/p>/i);
  const intro=m?m[0]:("<p>"+p.excerpt+"</p>");
  const out={slug:p.slug,title:p.title,excerpt:p.excerpt,intro,date:p.date,read:p.read};
  if(process.argv[3]==="--test"){ out.test=true; if(process.argv[4]) out.to=process.argv[4]; }
  process.stdout.write(JSON.stringify(out));
' "$DIR/site/posts.js" "$SLUG" "$MODE" "$TO")"

echo "$BODY" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const o=JSON.parse(s);console.log((o.test?"TEST → "+(o.to||"NOTIFY_EMAIL"):"REAL SEND to all entitled members")+"\n  "+o.title+"\n  "+o.intro.replace(/<[^>]+>/g,"").slice(0,160)+"…")})'
if [ "$MODE" != "--test" ]; then
  printf "Type SEND to confirm: "; read ans; [ "$ans" = "SEND" ] || { echo "aborted"; exit 1; }
fi

curl -sS -X POST "https://theslowswing.com/api/announce" \
  -H "authorization: Bearer $KEY" -H "content-type: application/json" \
  --data "$BODY"
echo
