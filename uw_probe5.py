#!/usr/bin/env python3.12
"""uw_probe5.py : probe history depth of the literature driven endpoints (about 14 requests)."""
import json, requests, uw_harvest3 as h
def show(name, path, params=None):
    r=requests.get(h.BASE+path,params=params or {},headers={"Authorization":f"Bearer {h.TOK}"},timeout=60)
    print(f"\n== {name}  {path} {params or ''}  status {r.status_code}")
    try: b=r.json()
    except Exception: print("   not json:", r.text[:200]); return
    d=b.get("data",b) if isinstance(b,dict) else b
    if isinstance(d,dict):
        print("   dict keys:", list(d)[:15])
        for k,v in d.items():
            if isinstance(v,list) and v: d=v; print(f"   using list under '{k}'"); break
    if isinstance(d,list) and d:
        keys=list(d[0].keys()) if isinstance(d[0],dict) else []
        dk=[k for k in keys if 'date' in k or k in ('timestamp','time','report_date')]
        ds=sorted(str(x.get(dk[0]))[:10] for x in d if isinstance(x,dict) and x.get(dk[0])) if dk else []
        print(f"   rows {len(d)} | date field {dk[:2]} | span {ds[0] if ds else None} to {ds[-1] if ds else None}")
        print("   columns:", keys[:25])
    else: print("   raw:", str(b)[:300])
show("realized vol + IV","/api/stock/NVDA/volatility/realized",{"timeframe":"2Y"})
show("realized vol + IV","/api/stock/NVDA/volatility/realized",{"timeframe":"3Y"})
show("variance risk premium","/api/stock/NVDA/volatility/variance-risk-premium")
show("option sentiment (AVAR)","/api/stock/NVDA/volatility/option-sentiment")
show("option sentiment (AVAR) past date","/api/stock/NVDA/volatility/option-sentiment",{"date":"2025-03-03"})
show("vol anomaly","/api/stock/NVDA/volatility/anomaly")
show("RR skew expired expiry","/api/stock/NVDA/historical-risk-reversal-skew",{"expiry":"2025-06-20","delta":"25","timeframe":"1Y"})
show("RR skew live expiry","/api/stock/NVDA/historical-risk-reversal-skew",{"expiry":"2026-11-20","delta":"25","timeframe":"1Y"})
show("earnings history","/api/earnings/NVDA")
show("earnings (stock)","/api/stock/NVDA/earnings")
show("shorts data (borrow fee)","/api/shorts/NVDA/data")
show("shorts data older","/api/shorts/NVDA/data",{"older_than":"2025-01-01"})
