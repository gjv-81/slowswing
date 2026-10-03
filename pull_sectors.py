#!/usr/bin/env python3.12
"""pull_sectors.py : GICS sector per ticker from yfinance, for STS_CORNERS_PREREG.md Corner 2.
Output: sectors.csv (ticker, sector, industry). Resumable. About 900 to 1,800 names, a few minutes."""
import glob, os, time, pandas as pd, yfinance as yf
from pathlib import Path
HERE=Path(__file__).resolve().parent; OUT=HERE/"sectors.csv"
tk=sorted({os.path.basename(f)[:-4] for f in glob.glob(str(HERE/"daily_data_v2"/"*.csv"))+glob.glob(str(HERE/"daily_data_ext"/"*.csv"))}-{"SPY","QQQ","IWM","RSP"})
done=set(pd.read_csv(OUT).ticker) if OUT.exists() else set()
rows=[]
for i,t in enumerate(tk,1):
    if t in done: continue
    try:
        info=yf.Ticker(t).info or {}
        rows.append({"ticker":t,"sector":info.get("sector"),"industry":info.get("industry")})
    except Exception as e:
        rows.append({"ticker":t,"sector":None,"industry":None})
    if len(rows)>=50:
        pd.DataFrame(rows).to_csv(OUT,mode="a",header=not OUT.exists(),index=False); rows=[]
        print(f"  {i}/{len(tk)}",flush=True)
    time.sleep(0.15)
if rows: pd.DataFrame(rows).to_csv(OUT,mode="a",header=not OUT.exists(),index=False)
d=pd.read_csv(OUT); print(f"done: {len(d)} tickers, {d.sector.notna().sum()} with a sector"); print(d.sector.value_counts())
