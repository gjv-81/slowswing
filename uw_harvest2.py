#!/usr/bin/env python3.12
"""
uw_harvest2.py — PHASE 2 UW archive (personal research only; no redistribution).
Jobs, in order:
  1. flow_per_strike : strike-level ask/bid flow for every QUIET-FLAME day
                       (both years, in/out-of-sample) -> uw_archive/flow_per_strike/
  2. shorts          : short interest/float, short volume ratio, FTDs, all tickers
  3. darkpool        : every dark-pool print for each signal's life (+40td),
                       all signals Nov-2024..now  [THE BULK JOB, ~2 quota-days]
  4. gex             : gex-levels snapshot (all tickers) + per-day spot exposures
                       for the personal watchlist
Everything is resumable (one file per unit of work, skipped if present) and
budget-capped: stops cleanly at 35k requests; rerun next day to continue.

RUN:  cd ~/STS/15min && caffeinate -i python3.12 uw_harvest2.py
(caffeinate stops idle sleep; a closed lid still pauses the Mac — that only
 pauses this script, never loses data. Reopen or rerun and it continues.)
"""
import glob, os, sys, time, json
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE=Path(__file__).resolve().parent
ARCH=HERE/"uw_archive"
BASE="https://api.unusualwhales.com"
BUDGET=35000
PAUSE=0.30
WATCH=["VEEV","SNOW","TTD","ARM","ASML","SE","RKLB","CRWV","HOOD","COIN","PLTR",
       "NBIS","ALAB","SNDK","MU","MRVL","WDC"]

def token():
    for ln in (HERE/".env_uw").read_text().splitlines():
        if "UW_TOKEN" in ln: return ln.split("=",1)[1].strip().strip('"').strip("'")
    sys.exit("UW_TOKEN missing")
TOK=token(); NREQ=0
def get(path,params=None):
    global NREQ
    import requests
    if NREQ>=BUDGET:
        print(f"\n== request budget {BUDGET} reached — rerun tomorrow, it resumes =="); sys.exit(0)
    NREQ+=1
    for a in range(3):
        try:
            r=requests.get(BASE+path,params=params or {},timeout=60,
                headers={"Authorization":f"Bearer {TOK}","Accept":"application/json"})
            time.sleep(PAUSE)
            if r.status_code==200: return r.json()
            if r.status_code==429: time.sleep(30); continue
            return None
        except Exception: time.sleep(5*(a+1))
    return None
def rows(b):
    if b is None: return []
    d=b.get("data",b) if isinstance(b,dict) else b
    return d if isinstance(d,list) else ([d] if isinstance(d,dict) else [])

# ---- signal + quiet-flame regeneration (shared with the studies) ----------
ZC={"high52":(-0.149772,0.156737),"dist200":(1.681650,6.240695),"mom6":(0.086250,0.361377),
    "qqe":(0.044473,0.194268),"hull":(0.027496,0.303103),"mom40":(0.020000,0.155298)}
WT={"high52":-2.20,"dist200":1.35,"mom6":1.08,"qqe":-0.99,"mom40":0.63,"hull":0.60}
z=lambda v,k:np.clip((v-ZC[k][0])/ZC[k][1],-3,3)
def wma(s,n):
    w=np.arange(1,n+1,dtype=float); return s.rolling(n).apply(lambda x:np.dot(x,w)/w.sum(),raw=True)
def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def signals_and_flames():
    """returns (signal list [(t,date)], quiet-flame ticker-days [(t,date)])"""
    LO=pd.Timestamp("2024-11-01")
    sigs=[]; flames=[]
    for fp in sorted(glob.glob(str(ARCH/"options_volume"/"*.csv"))):
        t=os.path.splitext(os.path.basename(fp))[0].upper()
        pxf=HERE/"daily_data_v2"/f"{t}.csv"
        if not pxf.exists(): continue
        try:
            px=pd.read_csv(pxf,index_col=0,parse_dates=True).sort_index()
            if len(px)<600: continue
            o=pd.read_csv(fp,parse_dates=["date"]).set_index("date").sort_index()
            if "call_volume_ask_side" not in o.columns: continue
            C,H=px["Close"],px["High"];pc=C.shift(1)
            tr=pd.concat([H-px["Low"],(H-pc).abs(),(px["Low"]-pc).abs()],axis=1).max(axis=1)
            atr=tr.ewm(alpha=1/14,adjust=False).mean()
            f={}
            f["high52"]=C/H.rolling(252).max()-1
            f["dist200"]=(C-C.rolling(200).mean())/atr
            f["mom6"]=C.shift(10)/C.shift(126)-1
            f["qqe"]=(rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50
            hma=wma(2*wma(C,10)-wma(C,20),4); f["hull"]=(hma-hma.shift(1))/atr
            f["mom40"]=C/C.shift(40)-1
            score=sum(WT[k]*z(f[k],k) for k in WT)
            mask=(score>=2)
            m=mask&~mask.shift(1,fill_value=False)
            idxs=np.where(m&(C>=10))[0]
            med=o["call_volume_ask_side"].rolling(21,min_periods=10).median().shift(1)
            ratio=o["call_volume_ask_side"]/med.replace(0,np.nan)
            dayret=C.pct_change()*100
            last=-99
            for i0 in idxs:
                if i0-last<20: continue
                last=i0
                sd=C.index[i0]
                if sd<LO: continue
                sigs.append((t,sd))
                for dt in C.index[i0+1:i0+42]:
                    if dt not in o.index: continue
                    r=ratio.get(dt,np.nan)
                    if not np.isfinite(r) or r<3: continue
                    if o.loc[dt,"call_volume_ask_side"]<=o.loc[dt,"put_volume_ask_side"]: continue
                    if abs(dayret.loc[dt])>1: continue        # quiet flame only
                    flames.append((t,dt))
        except Exception: continue
    return sigs,flames

def save_df(dirname,fname,recs):
    if not recs: return
    d=ARCH/dirname; d.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(recs).to_csv(d/fname,index=False)

def main():
    cache=ARCH/"_phase2_targets.json"
    if cache.exists():
        j=json.loads(cache.read_text())
        sigs=[(t,pd.Timestamp(d)) for t,d in j["sigs"]]
        flames=[(t,pd.Timestamp(d)) for t,d in j["flames"]]
        print(f"targets loaded: {len(sigs)} signals, {len(flames)} quiet-flame days")
    else:
        print("regenerating signals + quiet-flame days (few minutes, one-time) ...")
        sigs,flames=signals_and_flames()
        cache.write_text(json.dumps({"sigs":[(t,str(d.date())) for t,d in sigs],
                                     "flames":[(t,str(d.date())) for t,d in flames]}))
        print(f"targets: {len(sigs)} signals, {len(flames)} quiet-flame days (cached)")

    # ---- JOB 1: flow-per-strike on quiet-flame days ----
    print("\nJOB 1: flow-per-strike on flame days")
    done=0
    for t,d in flames:
        fn=f"{t}_{d.date()}.csv"
        if (ARCH/"flow_per_strike"/fn).exists(): done+=1; continue
        save_df("flow_per_strike",fn,rows(get(f"/api/stock/{t}/flow-per-strike",{"date":str(d.date())})))
        done+=1
        if done%100==0: print(f"  {done}/{len(flames)} | req {NREQ}")
    print(f"  job1 complete ({done})")

    # ---- JOB 2: shorts, all tickers ----
    print("\nJOB 2: shorts data")
    tickers=sorted({os.path.splitext(os.path.basename(f))[0] for f in glob.glob(str(ARCH/'options_volume'/'*.csv'))})
    for i,t in enumerate(tickers,1):
        if (ARCH/"shorts_interest"/f"{t}.csv").exists(): continue
        save_df("shorts_interest",f"{t}.csv",rows(get(f"/api/shorts/{t}/interest-float/v2")))
        save_df("shorts_volume",f"{t}.csv",rows(get(f"/api/shorts/{t}/volume-and-ratio",{"limit":500})))
        save_df("shorts_ftds",f"{t}.csv",rows(get(f"/api/shorts/{t}/ftds")))
        if i%100==0: print(f"  [{i}/{len(tickers)}] req {NREQ}")
    print("  job2 complete")

    # ---- JOB 3: darkpool prints over each signal's life (BULK) ----
    print("\nJOB 3: darkpool prints (bulk — may take 2 quota-days)")
    units=[]
    for t,sd in sigs:
        pxf=HERE/"daily_data_v2"/f"{t}.csv"
        try: idx=pd.read_csv(pxf,usecols=[0],parse_dates=[0]).iloc[:,0]
        except Exception: continue
        life=idx[idx>sd][:40]
        units += [(t,str(d.date())) for d in life if d<=pd.Timestamp.today()]
    units=sorted(set(units))
    print(f"  ticker-days to fetch: {len(units)}")
    done=0
    for t,d in units:
        fn=f"{t}_{d}.csv"
        if (ARCH/"darkpool"/fn).exists(): done+=1; continue
        save_df("darkpool",fn,rows(get(f"/api/darkpool/{t}",{"date":d,"limit":500})))
        done+=1
        if done%500==0: print(f"  {done}/{len(units)} | req {NREQ}")
    print(f"  job3 complete ({done})")

    # ---- JOB 4: GEX levels snapshot (all) + per-day spot exposures (watchlist) ----
    print("\nJOB 4: GEX")
    for t in tickers:
        if (ARCH/"gex_levels"/f"{t}.csv").exists(): continue
        save_df("gex_levels",f"{t}.csv",rows(get(f"/api/stock/{t}/gex-levels")))
    for t in WATCH:
        pxf=HERE/"daily_data_v2"/f"{t}.csv"
        if not pxf.exists(): continue
        idx=pd.read_csv(pxf,usecols=[0],parse_dates=[0]).iloc[:,0]
        days=[d for d in idx if d>=pd.Timestamp("2024-11-01")]
        for d in days:
            fn=f"{t}_{d.date()}.csv"
            if (ARCH/"spot_exposures"/fn).exists(): continue
            save_df("spot_exposures",fn,rows(get(f"/api/stock/{t}/spot-exposures",{"date":str(d.date())})))
    print("  job4 complete")
    print(f"\nPHASE 2 DONE | total requests this run: {NREQ}")

if __name__=="__main__":
    main()
