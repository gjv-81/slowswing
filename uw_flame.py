#!/usr/bin/env python3.12
"""
uw_flame.py — STAGE-2 flame study on Unusual Whales classified flow.
Pre-registration: STS_FLAME_UW_PREREG.md (written before any UW data was seen).

MODES
  python3.12 uw_flame.py --probe      # hit candidate endpoints for 1 ticker,
                                      # incl. a Sep-2025 date (verify lookback);
                                      # prints JSON keys + sample rows
  python3.12 uw_flame.py --download   # pull daily side-classified option data
                                      # for all stage-1 B2/S2 tickers -> uw_flow/
  (backtest runs separately once we see the field names)

Token: reads UW_TOKEN from ~/STS/15min/.env_uw
Rate care: API Basic = 40k req/day; we stay far under with polite pacing.
"""
import argparse, os, sys, time, json, glob
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
ENV=HERE/".env_uw"
OUT=HERE/"uw_flow"
BASE="https://api.unusualwhales.com"

def token():
    if not ENV.exists():
        sys.exit(f"missing {ENV} — create it:  echo 'UW_TOKEN=\"...\"' > {ENV}")
    for ln in ENV.read_text().splitlines():
        if "UW_TOKEN" in ln:
            return ln.split("=",1)[1].strip().strip('"').strip("'")
    sys.exit("UW_TOKEN not found in .env_uw")

def get(path, params=None, tok=None):
    import requests
    r=requests.get(BASE+path, params=params or {},
                   headers={"Authorization":f"Bearer {tok}","Accept":"application/json"},
                   timeout=60)
    time.sleep(0.35)
    try: body=r.json()
    except Exception: body=r.text[:400]
    return r.status_code, body

def describe(body, depth=0):
    """print structure: keys and one sample row"""
    if isinstance(body,dict):
        for k,v in body.items():
            if isinstance(v,list) and v:
                print(f"  key '{k}': list[{len(v)}]; first row keys/sample:")
                if isinstance(v[0],dict):
                    for kk,vv in list(v[0].items())[:30]:
                        print(f"      {kk}: {vv}")
                else: print(f"      {v[0]}")
            else:
                print(f"  key '{k}': {str(v)[:120]}")
    else:
        print(f"  {str(body)[:400]}")

def probe():
    tok=token()
    t="ZS"                       # liquid, in our signal set
    old="2025-10-01"; recent="2026-09-18"
    candidates=[
        ("/api/stock/{t}/options-volume",  {"limit":5}),
        ("/api/stock/{t}/options-volume",  {"limit":500}),      # how far back does it page?
        ("/api/stock/{t}/flow-alerts",     {"limit":5}),
        ("/api/stock/{t}/flow-per-strike", {"date":old}),       # 2yr-lookback check
        ("/api/stock/{t}/greek-exposure",  {"date":recent}),
        ("/api/stock/{t}/greek-exposure",  {"date":old}),       # lookback check #2
        ("/api/stock/{t}/oi-change",       {"date":recent}),
        ("/api/stock/{t}/iv-rank",         {"limit":5}),
        ("/api/darkpool/{t}",              {"date":recent,"limit":5}),
        ("/api/stock/{t}/net-prem-ticks",  {"date":recent}),
        ("/api/stock/{t}/unusualness",     {}),
        ("/api/stock/{t}/option-stance",   {}),
    ]
    for path,params in candidates:
        p=path.format(t=t)
        code,body=get(p,params,tok)
        print(f"\n=== GET {p} {params} -> HTTP {code} ===")
        if code==200: describe(body)
        else: print(f"  {str(body)[:200]}")
    print("\nPaste this output back — the download step gets built from whichever "
          "endpoint returns daily SIDE-CLASSIFIED (ask/bid) call & put volume/premium, "
          "and from whether the Sep-2025 request returned data (2yr lookback check).")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--probe",action="store_true")
    ap.add_argument("--download",action="store_true")
    a=ap.parse_args()
    if a.probe: probe()
    elif a.download:
        sys.exit("download mode gets finalized after the probe confirms the endpoint/fields")
    else:
        print(__doc__)

if __name__=="__main__":
    main()
