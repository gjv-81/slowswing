#!/usr/bin/env python3
"""Does our Marketstack plan include the dividends + splits endpoints?
Prints the answer without ever printing the key."""
import os, json, urllib.parse
import requests   # bundles its own CA certs; python.org builds of Python on macOS ship none
key = None
for line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    if line.startswith("MARKETSTACK_API_KEY"):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
assert key, "no MARKETSTACK_API_KEY in .env"

def hit(path, **q):
    q["access_key"] = key
    url = f"https://api.marketstack.com/{path}?" + urllib.parse.urlencode(q)
    r = requests.get(url, timeout=30)
    try: return r.status_code, r.json()
    except Exception: return r.status_code, {}

for label, path, q in [
    ("v2 dividends KO", "v2/dividends", dict(symbols="KO", limit=4)),
    ("v1 dividends KO", "v1/dividends", dict(symbols="KO", limit=4)),
    ("v2 splits NVDA",  "v2/splits",    dict(symbols="NVDA", limit=3)),
    ("v1 splits NVDA",  "v1/splits",    dict(symbols="NVDA", limit=3)),
]:
    code, body = hit(path, **q)
    if "error" in body:
        print(f"{label:<18} HTTP {code}  {body['error'].get('code')}: {body['error'].get('message','')[:110]}")
    else:
        rows = body.get("data") or []
        print(f"{label:<18} HTTP {code}  {len(rows)} rows")
        for r in rows[:4]:
            print("     ", {k: r.get(k) for k in ("date", "dividend", "split_factor", "symbol") if k in r})
