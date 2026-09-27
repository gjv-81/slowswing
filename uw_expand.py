#!/usr/bin/env python3.12
"""
uw_expand.py — expand the FAST-LANE (S2/B2) universe and backtest the flame on
the NEW names. Screen: optionable + price > $25 + avg option volume >= 1,000
contracts/day (liquidity floor, applied from the flow data itself).

STAGES (run in order; each is resumable):
  python3.12 uw_expand.py --list      # UW optionable tickers -> candidates (2 req)
  python3.12 uw_expand.py --prices    # yfinance 3y bars, price>$25 screen (NO UW quota)
                                      #   -> daily_data_ext/ (separate from v2)
  python3.12 uw_expand.py --flow      # UW options-volume history for survivors
                                      #   (~3-6k req — run AFTER the 8pm reset)
  python3.12 uw_expand.py --backtest  # flame grid on NEW names only -> console + xlsx
"""
import argparse, glob, os, sys, time, json
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE=Path(__file__).resolve().parent
EXTPX=HERE/"daily_data_ext"
EXTOV=HERE/"uw_archive"/"options_volume_ext"
CAND=HERE/"uw_archive"/"_expand_candidates.txt"
SURV=HERE/"uw_archive"/"_expand_survivors.txt"
BASE="https://api.unusualwhales.com"
BUDGET=30000; PAUSE=0.30
MIN_PRICE=25.0; MIN_OPT_VOL=1000     # avg daily contracts (calls+puts), ticker-level median

ETF_EXCL={"SPY","QQQ","IWM","DIA","GLD","SLV","USO","SOXX","SMH","RSP","TLT","HYG","ARKK",
 "VOO","VTI","XLB","XLE","XLF","XLI","XLK","XLU","XLV","XLY","UNG","UUP","FXI","KWEB","IBB",
 "XBI","IGV","ITB","KRE","XRT","XOP","GDX","JETS","VNQ","AGG","BND","LQD","SQQQ","TQQQ",
 "UVXY","VXX","BITO","EEM","EFA","EWZ","GDXJ","SLX","TAN","SOXL","SOXS","TZA","TNA","LABU",
 "SPXU","UPRO","SVXY","VIXY","QID","QLD","SSO","SDS","IEF","SHY","EMB","XME","OIH","KBE",
 "SMCX","MSTX","NVDL","TSLL","IWF","IWD","MDY","XLC","XLRE","GOVT","FXE","FXY","USMV"}

def token():
    for ln in (HERE/".env_uw").read_text().splitlines():
        if "UW_TOKEN" in ln: return ln.split("=",1)[1].strip().strip('"').strip("'")
    sys.exit("UW_TOKEN missing")
NREQ=0
def get(path,params=None):
    global NREQ
    import requests
    if NREQ>=BUDGET: sys.exit(f"budget {BUDGET} reached — resume after the 8pm reset")
    NREQ+=1
    for a in range(3):
        try:
            r=requests.get(BASE+path,params=params or {},timeout=60,
                headers={"Authorization":f"Bearer {token()}","Accept":"application/json"})
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

def stage_list():
    """Candidate universe from Nasdaq Trader's official symbol directories (free,
    no auth, includes an ETF flag). Optionability gets confirmed implicitly later:
    non-optionable names return no UW flow data and are skipped for ~1 request.
    (UW's optionable-tickers endpoint needs the Advanced tier — not the trial.)"""
    import requests as _rq
    have={os.path.splitext(os.path.basename(f))[0].upper()
          for f in glob.glob(str(HERE/"uw_archive"/"options_volume"/"*.csv"))}
    ticks=set()
    for url,symcol,etfcol in [
        ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt","Symbol","ETF"),
        ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt","ACT Symbol","ETF")]:
        txt=_rq.get(url,timeout=30,headers={"User-Agent":"Mozilla/5.0"}).text
        lines=[l for l in txt.splitlines() if "|" in l]
        hdr=lines[0].split("|")
        si,ei=hdr.index(symcol),hdr.index(etfcol)
        ti=hdr.index("Test Issue") if "Test Issue" in hdr else None
        n=0
        for l in lines[1:]:
            p=l.split("|")
            if len(p)<=max(si,ei): continue
            if p[ei].strip().upper()=="Y": continue            # ETF
            if ti is not None and p[ti].strip().upper()=="Y": continue
            s=p[si].strip().upper()
            if not s or len(s)>5: continue
            if not s.replace("-","").replace(".","").isalnum(): continue
            if any(c in s for c in "$^~+=#"): continue          # warrants/units/preferreds
            ticks.add(s.replace(".","-")); n+=1
        print(f"  {url.split('/')[-1]}: kept {n}")
    new=sorted(t for t in ticks if t not in have and t not in ETF_EXCL)
    CAND.write_text("\n".join(new)+"\n")
    print(f"US common stocks: {len(ticks)} | already archived: {len(have)} | NEW candidates: {len(new)} -> {CAND.name}")

def stage_prices():
    import yfinance as yf
    cands=[t.strip() for t in CAND.read_text().splitlines() if t.strip()]
    EXTPX.mkdir(exist_ok=True)
    print(f"downloading 3y bars for {len(cands)} candidates (batched) ...")
    keep=[]
    CH=100
    for i in range(0,len(cands),CH):
        chunk=cands[i:i+CH]
        try:
            raw=yf.download(chunk,period="3y",interval="1d",auto_adjust=True,
                            group_by="ticker",progress=False,threads=True)
        except Exception as e:
            print(f"  batch failed: {e}"); continue
        for t in chunk:
            try:
                d=(raw[t] if len(chunk)>1 else raw).dropna()
                if len(d)<300: continue
                if float(d["Close"].iloc[-1])<MIN_PRICE: continue
                d=d[["Open","High","Low","Close","Volume"]]
                d.index.name="Date"
                d.reset_index().to_csv(EXTPX/f"{t}.csv",index=False)
                keep.append(t)
            except Exception: pass
        print(f"  {min(i+CH,len(cands))}/{len(cands)} screened | kept {len(keep)}")
        time.sleep(1)
    SURV.write_text("\n".join(sorted(keep))+"\n")
    print(f"price screen (> ${MIN_PRICE:.0f}, 300+ bars): {len(keep)} survivors -> {SURV.name}")

def _has_signal(t):
    """does this ticker have >=1 S2/B2 signal since Nov 2024? (prices only, no UW)"""
    try:
        px=pd.read_csv(EXTPX/f"{t}.csv",index_col=0,parse_dates=True).sort_index()
        if len(px)<300: return False
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
        oh=f["high52"]*100
        mask=(score>=2)&(oh>-25)&(C>=MIN_PRICE)
        m=mask&~mask.shift(1,fill_value=False)
        m=m[m.index>=pd.Timestamp("2024-11-01")]
        return bool(m.any())
    except Exception:
        return False

def stage_flow():
    surv=[t.strip() for t in SURV.read_text().splitlines() if t.strip()]
    sigfile=HERE/"uw_archive"/"_expand_with_signals.txt"
    if sigfile.exists():
        surv=[t.strip() for t in sigfile.read_text().splitlines() if t.strip()]
        print(f"{len(surv)} tickers with S2/B2 signals (cached)")
    else:
        print(f"pre-screening {len(surv)} survivors for S2/B2 signals (local, no quota) ...")
        surv=[t for t in surv if _has_signal(t)]
        sigfile.write_text("\n".join(surv)+"\n")
        print(f"{len(surv)} tickers have >=1 signal since Nov 2024 — only these get UW flow")
    EXTOV.mkdir(parents=True,exist_ok=True)
    done=0
    for i,t in enumerate(surv,1):
        fp=EXTOV/f"{t}.csv"
        if fp.exists(): done+=1; continue
        out=[]; seen=set()
        for pg in range(4):
            rs=rows(get(f"/api/stock/{t}/options-volume",{"limit":500,"page":pg}))
            if not rs: break
            key=json.dumps(rs[0],sort_keys=True,default=str)
            if key in seen: break
            seen.add(key); out.extend(rs)
            if len(rs)<500: break
        if out:
            pd.DataFrame(out).to_csv(fp,index=False); done+=1
        if i%50==0: print(f"  [{i}/{len(surv)}] saved {done} | req {NREQ}")
    print(f"flow history: {done} tickers archived")

# ---------- backtest (same engine, NEW names only, liquidity floor) ----------
ZC={"high52":(-0.149772,0.156737),"dist200":(1.681650,6.240695),"mom6":(0.086250,0.361377),
    "qqe":(0.044473,0.194268),"hull":(0.027496,0.303103),"mom40":(0.020000,0.155298)}
WT={"high52":-2.20,"dist200":1.35,"mom6":1.08,"qqe":-0.99,"mom40":0.63,"hull":0.60}
z=lambda v,k:np.clip((v-ZC[k][0])/ZC[k][1],-3,3)
def wma(s,n):
    w=np.arange(1,n+1,dtype=float); return s.rolling(n).apply(lambda x:np.dot(x,w)/w.sum(),raw=True)
def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def stage_backtest():
    LO=pd.Timestamp("2024-11-01")
    rows_=[]; skipped_liq=0
    files=sorted(glob.glob(str(EXTOV/"*.csv")))
    print(f"backtesting {len(files)} NEW tickers ...")
    for fp in files:
        t=os.path.splitext(os.path.basename(fp))[0].upper()
        pxf=EXTPX/f"{t}.csv"
        if not pxf.exists(): continue
        try:
            o=pd.read_csv(fp,parse_dates=["date"]).set_index("date").sort_index()
            if "call_volume_ask_side" not in o.columns: continue
            if (o["call_volume"]+o["put_volume"]).median()<MIN_OPT_VOL:
                skipped_liq+=1; continue
            px=pd.read_csv(pxf,index_col=0,parse_dates=True).sort_index()
            if len(px)<300: continue
            C,H=px["Close"],px["High"];pc=C.shift(1)
            tr=pd.concat([H-px["Low"],(H-pc).abs(),(px["Low"]-pc).abs()],axis=1).max(axis=1)
            atr=tr.ewm(alpha=1/14,adjust=False).mean();sma=C.rolling(200).mean()
            f={}
            f["high52"]=C/H.rolling(252).max()-1; f["dist200"]=(C-sma)/atr
            f["mom6"]=C.shift(10)/C.shift(126)-1
            f["qqe"]=(rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50
            hma=wma(2*wma(C,10)-wma(C,20),4); f["hull"]=(hma-hma.shift(1))/atr
            f["mom40"]=C/C.shift(40)-1
            score=sum(WT[k]*z(f[k],k) for k in WT)
            oh=f["high52"]*100
            mask=(score>=2)&(oh>-25)                    # S2/B2 only (fast lane)
            m=mask&~mask.shift(1,fill_value=False)
            idxs=np.where(m&(C>=MIN_PRICE))[0]
            med=o["call_volume_ask_side"].rolling(21,min_periods=10).median().shift(1)
            ratio=o["call_volume_ask_side"]/med.replace(0,np.nan)
            dayret=C.pct_change()*100
            last=-99
            for i0 in idxs:
                if i0-last<20: continue
                last=i0
                sd=C.index[i0]
                if sd<LO: continue
                setup="B2" if oh.iloc[i0]<=-10 else "S2"
                for dt in C.index[i0+1:i0+42]:
                    if dt not in o.index: continue
                    r=ratio.get(dt,np.nan)
                    if not np.isfinite(r): continue
                    i=C.index.get_loc(dt)
                    if i<4 or i+5>=len(C): continue
                    prior=[abs(dayret.iloc[i-k]) for k in range(1,4)]
                    rows_.append(dict(setup=setup,
                        flame=(r>=3)&(o.loc[dt,"call_volume_ask_side"]>o.loc[dt,"put_volume_ask_side"]),
                        d0=dayret.iloc[i],flat1=prior[0]<=1,
                        flat2=prior[0]<=1 and prior[1]<=1,flat3=all(p<=1 for p in prior),
                        **{f"f{n}":(C.iloc[i+n]/C.iloc[i]-1)*100 for n in range(1,6)}))
        except Exception: continue
    ev=pd.DataFrame(rows_)
    print(f"(liquidity floor removed {skipped_liq} thin tickers)")
    print(f"NEW-NAMES sample: signal-days {len(ev)} | flames {int(ev.flame.sum())}")
    print("setups:",ev.groupby("setup").size().to_dict(),"\n")
    def wins(g): return "  ".join(f"d{n}:{100*(g[f'f{n}']>0).mean():5.1f}%" for n in range(1,6))
    def avgs(g): return "  ".join(f"d{n}:{g[f'f{n}'].mean():+5.2f}%" for n in range(1,6))
    out=[]
    quiet=ev[ev.d0.abs()<=1]
    for st in ["S2","B2"]:
        g=quiet[quiet.setup==st]
        for nm,mask in [("1flat",g.flat1),("2flat",g.flat2),("3flat",g.flat3)]:
            q=g[mask]; fl,nf=q[q.flame],q[~q.flame]
            if len(fl)<15: continue
            print(f"{st:4s} {nm:6s} FLAME n={len(fl):4d}  win  {wins(fl)}")
            print(f"{'':4s} {'':6s}              avg  {avgs(fl)}")
            print(f"{'':4s} {'':6s} ctrl  n={len(nf):5d} win  {wins(nf)}\n")
            for lab,gg in [("FLAME",fl),("control",nf)]:
                rec=dict(setup=st,flat=nm,cohort=lab,n=len(gg))
                for n in range(1,6):
                    rec[f"d{n}_win"]=round(100*(gg[f"f{n}"]>0).mean(),1)
                    rec[f"d{n}_avg"]=round(gg[f"f{n}"].mean(),2)
                out.append(rec)
    if out:
        pd.DataFrame(out).to_excel(HERE/"STS_flame_expansion.xlsx",sheet_name="NewNames",index=False)
        print("wrote STS_flame_expansion.xlsx")

def main():
    ap=argparse.ArgumentParser()
    for m in ("list","prices","flow","backtest"): ap.add_argument(f"--{m}",action="store_true")
    a=ap.parse_args()
    if a.list: stage_list()
    elif a.prices: stage_prices()
    elif a.flow: stage_flow()
    elif a.backtest: stage_backtest()
    else: print(__doc__)

if __name__=="__main__":
    main()
