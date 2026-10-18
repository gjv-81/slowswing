#!/usr/bin/env python3
"""
atr_line_study.py — GJ's question (2026-10-18):
Of signals that fired while ABOVE the 200-day SMA by >=1.5 (and >=2.0) ATR,
how many came back to TOUCH/BREACH the 200-SMA before "moving upward"
(first touching +5% above entry), how many moved up without ever
approaching the line, and how did each path end at week 12?

Cohort: full signal family (score>=2, >=10% below 52wk high = DLB/D200G/B2),
all daily_data_v2 tickers, next-open entry, 20td refractory, 60td window.
Race: which happens first after entry — Low <= that day's 200-SMA ("touch")
or High >= entry*1.05 ("up first"). "Approached" = came within 0.5 ATR of
the line without touching.
"""
import glob, os
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")
HERE=os.path.dirname(os.path.abspath(__file__))
ZC={"high52":(-0.149772,0.156737),"dist200":(1.681650,6.240695),
    "mom6":(0.086250,0.361377),"qqe":(0.044473,0.194268),
    "hull":(0.027496,0.303103),"mom40":(0.020000,0.155298)}
W={"high52":-2.20,"dist200":1.35,"mom6":1.08,"qqe":-0.99,"mom40":0.63,"hull":0.60}
def zclip(s,k):
    m,sd=ZC[k]; return ((s-m)/sd).clip(-3,3)
def wilders(s,n): return s.ewm(alpha=1/n,adjust=False).mean()
def rsi_w(s,n=20):
    d=s.diff(); up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+wilders(up,n)/wilders(dn,n).replace(0,1e-10))
def wma(s,n):
    w=np.arange(1,n+1,dtype=float)
    return s.rolling(n).apply(lambda x:np.dot(x,w)/w.sum(),raw=True)
rows=[]
for fp in sorted(glob.glob(os.path.join(HERE,"daily_data_v2","*.csv"))):
    t=os.path.splitext(os.path.basename(fp))[0].upper()
    if t in {"SPY","QQQ","RSP"}: continue
    try: d=pd.read_csv(fp,index_col=0,parse_dates=True).sort_index()
    except Exception: continue
    if len(d)<320: continue
    C,H,L,O=d["Close"],d["High"],d["Low"],d["Open"]
    pc=C.shift(1)
    tr=pd.concat([H-L,(H-pc).abs(),(L-pc).abs()],axis=1).max(axis=1)
    atr=wilders(tr,14)
    sma=C.rolling(200).mean()
    high52=C/H.rolling(252).max()-1
    dist200=(C-sma)/atr
    mom6=C.shift(10)/C.shift(126)-1
    qqe=(rsi_w(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50
    hma=wma(2*wma(C,10)-wma(C,20),4)
    hull=(hma-hma.shift(1))/atr
    mom40=C/C.shift(40)-1
    score=(W["high52"]*zclip(high52,"high52")+W["dist200"]*zclip(dist200,"dist200")
           +W["mom6"]*zclip(mom6,"mom6")+W["qqe"]*zclip(qqe,"qqe")
           +W["hull"]*zclip(hull,"hull")+W["mom40"]*zclip(mom40,"mom40"))
    sig=((score>=2.0)&(high52<=-0.10)).fillna(False).values
    Ov,Hv,Lv,Cv=O.values,H.values,L.values,C.values
    smav,atrv=sma.values,atr.values
    idx=np.where(sig)[0]; last=-10**9
    for i in idx:
        if i-last<20: continue
        if i+1>=len(d)-61: continue
        last=i
        e=i+1; entry=Ov[e]
        if not np.isfinite(entry) or entry<=0: continue
        datr=(Cv[i]-smav[i])/atrv[i] if atrv[i]>0 else np.nan
        if not np.isfinite(datr): continue
        # race over next 60 td
        touch_day=up_day=None; min_gap=1e9
        for k in range(e,e+61):
            if Lv[k]<=smav[k] and touch_day is None: touch_day=k-e
            gap=(Lv[k]-smav[k])/atrv[k] if atrv[k]>0 else 9e9
            min_gap=min(min_gap,gap)
            if Hv[k]>=entry*1.05 and up_day is None: up_day=k-e
            if touch_day is not None and up_day is not None: break
        if touch_day is None: t_first=False
        elif up_day is None: t_first=True
        else: t_first=touch_day<up_day
        ret12=(Cv[e+60]/entry-1)*100
        rows.append((datr,t_first,touch_day,up_day,min_gap,ret12))
df=pd.DataFrame(rows,columns=["datr","touch_first","touch_day","up_day","min_gap","ret12"])
print(f"total signals: {len(df)}")
def bucket(d):
    if d<0: return "below line"
    if d<1.5: return "0-1.5 ATR"
    if d<2.0: return "1.5-2 ATR"
    return ">=2 ATR"
df["b"]=df.datr.map(bucket)
print("\n=== signals by distance above/below 200-SMA at signal ===")
print(df.b.value_counts().to_string())
for thr,name in [(1.5,">=1.5 ATR above line"),(2.0,">=2.0 ATR above line")]:
    s=df[df.datr>=thr]
    touched=s[s.touch_day.notna()]
    tf=s[s.touch_first]                       # came to the line before +5%
    uf=s[(~s.touch_first)&s.up_day.notna()]   # hit +5% first
    never=s[s.touch_day.isna()]
    near=never[never.min_gap<=0.5]            # approached within 0.5 ATR, no touch
    clean=never[never.min_gap>0.5]            # never came near the line
    print(f"\n=== {name}: n={len(s)} ===")
    def line(lbl,g):
        if not len(g): print(f"{lbl:>34}: 0"); return
        print(f"{lbl:>34}: {len(g):>5} ({100*len(g)/len(s):4.1f}%)  wk12 avg {g.ret12.mean():+6.2f}%  win {100*(g.ret12>0).mean():4.1f}%")
    line("touched/breached line BEFORE +5%",tf)
    line("hit +5% first, touched line later",s[(~s.touch_first)&s.touch_day.notna()])
    line("ANY touch of line within 60td",touched)
    line("never touched, but came <=0.5 ATR",near)
    line("never came near line (clean up)",clean)
