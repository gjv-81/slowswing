"""screener_compare_study.py — do ordinary screeners find what our setups find?
Same universe (daily_data_v2, price >= $50), same years (2016-2026), same measure
(entry at next open; touched +5% / +10% within 20 sessions on the High; r20; excess vs SPY).
Screens: RSI(14) < 30 cross (classic oversold); MACD(12,26,9) bullish cross; Bollinger(20,2)
close below lower band; RANDOM day (baseline). 20-session refractory per ticker, like our signals.
Ours: exh_build.score_and_signals, DLB+D200G+B2 (published setups)."""
import os, glob, numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
from exh_build import load, score_and_signals, rsi
SPY=pd.read_csv("daily_data_v2/SPY.csv",index_col=0,parse_dates=True).sort_index(); SPY=SPY[~SPY.index.duplicated()]
rng=np.random.default_rng(7); rows=[]
def ema(s,n): return s.ewm(span=n,adjust=False).mean()
for f in sorted(glob.glob("daily_data_v2/*.csv")):
    t=os.path.basename(f)[:-4]
    if t in ("SPY","RSP"): continue
    px,_=load(t)
    if px is None or len(px)<300: continue
    idx=px.index; O,H,C=px.Open,px.High,px.Close
    so=SPY.Open.reindex(idx).values; sc=SPY.Close.reindex(idx).values
    r=rsi(C,14); m=ema(C,12)-ema(C,26); sig=ema(m,9)
    bb=C.rolling(20).mean()-2*C.rolling(20).std()
    screens={
      "RSI<30":  (r<30)&(r.shift(1)>=30),
      "MACD cross": (m>sig)&(m.shift(1)<=sig.shift(1)),
      "Bollinger low": (C<bb)&(C.shift(1)>=bb.shift(1)),
    }
    def emit(name,i):
        if i+21>=len(idx) or C.iloc[i]<50: return
        e=O.iloc[i+1]
        if not np.isfinite(e) or not np.isfinite(so[i+1]) or not np.isfinite(sc[i+20]): return
        hi=H.iloc[i+1:i+21].values/e-1
        rows.append(dict(screen=name,t=t,date=idx[i],year=idx[i].year,t5=float(hi.max()>=0.05),t10=float(hi.max()>=0.10),
                         r20=(C.iloc[i+20]/e-1)*100, xs20=((C.iloc[i+20]/e-1)-(sc[i+20]/so[i+1]-1))*100))
    for name,mask in screens.items():
        last=-99
        for i in np.where(mask.fillna(False).values)[0]:
            if i-last<20: continue
            last=i; emit(name,i)
    # random days: ~ one per 60 sessions
    for i in rng.choice(np.arange(260,len(idx)-22), size=max(1,(len(idx)-282)//60), replace=False): emit("Random day",int(i))
    _,sg=score_and_signals(px)
    for s in ("DLB","D200G","B2"):
        for i in sg[s]: emit("Our setups",i)
df=pd.DataFrame(rows); df.to_parquet("screener_compare_rows.parquet",index=False)
def tab(g):
    return g.groupby("screen").agg(n=("t","size"),touched5=("t5",lambda s:s.mean()*100),touched10=("t10",lambda s:s.mean()*100),
        win20=("r20",lambda s:(s>0).mean()*100),avg_r20=("r20","mean"),excess=("xs20","mean")).round(1).sort_values("touched5",ascending=False)
T=tab(df); print("=== ALL YEARS, price >= $50, 20 sessions ===\n",T.to_string())
E=tab(df[df.year>=2021]); print("\n=== 2021-2026 ===\n",E.to_string())
with pd.ExcelWriter("screener_compare_results.xlsx") as w: T.to_excel(w,sheet_name="all years"); E.to_excel(w,sheet_name="2021-2026")
