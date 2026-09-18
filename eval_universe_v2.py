#!/usr/bin/env python3.12
"""
eval_universe_v2.py — APPLES-TO-APPLES replay of the paper book on the SEPARATE
expanded universe (daily_data_v2/), starting the SAME date as the live book
(2026-07-20), so the ONLY variable is the universe. Does NOT touch the live
pipeline. Reads price history straight from the daily_data_v2/ CSVs (no yfinance).

WHAT IT DOES
  - Replays every trading day from START_DATE to the latest bar. On each day it
    scores every ticker (history up to that day) and logs a NEW entry the first
    time a ticker's score >= 2 (same first-appearance rule as the live scan;
    re-qualification is omitted so the comparison isolates the universe effect).
  - For each entry, computes the same outcome metrics as the live tracker:
    setup, dist200_pct, wr, ret%, wk2/wk4/wk12 return, max dip, excess vs SPY,
    and the Active/Extended/Retired phase.
  - Writes STS_holy_grail_v2.xlsx with the same fan-out tables + a NEW_vs_EXISTING
    breakdown (how the newly-added names, e.g. VEEV, performed vs names already
    in the live universe).

RUN (after build_universe.py):  cd ~/STS/15min && python3.12 eval_universe_v2.py
Compare its tables to the live STS_holy_grail.xlsx (same 7/20 start).
"""
import os, glob
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
DATA = HERE / "daily_data_v2"
LIVE = HERE / "daily_data_10y"
OUT  = HERE / "STS_holy_grail_v2.xlsx"
START_DATE = pd.Timestamp("2026-07-20")     # same as the live paper book
ETF  = {"SPY","QQQ","IWM","DIA","GLD","SLV","USO","SOXX","SMH","RSP","TLT","HYG",
        "ARKK","VOO","VTI","XLB","XLE","XLF","XLI","XLK","XLU","XLV","XLY","UNG","UUP","FXI","KWEB"}
MIN_PRICE=10.0; W2,W4,W12=10,20,60
ZC={"high52":(-0.149772,0.156737),"dist200":(1.681650,6.240695),"mom6":(0.086250,0.361377),
    "qqe":(0.044473,0.194268),"hull":(0.027496,0.303103),"mom40":(0.020000,0.155298)}
W={"high52":-2.20,"dist200":1.35,"mom6":1.08,"qqe":-0.99,"mom40":0.63,"hull":0.60}
z=lambda v,k:np.clip((v-ZC[k][0])/ZC[k][1],-3,3)
def wma(s,n):
    w=np.arange(1,n+1,dtype=float); return s.rolling(n).apply(lambda x:np.dot(x,w)/w.sum(),raw=True)
def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def feats(d):
    C,H,L=d["Close"],d["High"],d["Low"];pc=C.shift(1)
    tr=pd.concat([H-L,(H-pc).abs(),(L-pc).abs()],axis=1).max(axis=1);atr=tr.ewm(alpha=1/14,adjust=False).mean()
    sma=C.rolling(200).mean()
    f=pd.DataFrame(index=d.index)
    f["high52"]=C/H.rolling(252).max()-1; f["dist200"]=(C-sma)/atr
    f["mom6"]=C.shift(10)/C.shift(126)-1
    f["qqe"]=(rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50
    hma=wma(2*wma(C,10)-wma(C,20),4); f["hull"]=(hma-hma.shift(1))/atr
    f["mom40"]=C/C.shift(40)-1
    f["score"]=sum(W[k]*z(f[k],k) for k in W)
    f["dist200_pct"]=(C/sma-1)*100; f["off_high"]=f["high52"]*100
    f["wash_min8w"]=f["dist200_pct"].rolling(40).min()
    return f

def classify(score,oh,d,wm):
    above=d>0; deep=oh<=-25; mid=-25<oh<=-10
    if deep and above: setup="D200G" if score>=2 else "D200"
    elif score>=2: setup="B2" if mid else ("S2" if oh>-10 else "DLB")
    else: setup="-"
    wr=""
    if wm==wm and -10<=d<=0:
        wr="WR40" if wm<=-40 else ("WR30" if wm<=-30 else ("WR20" if wm<=-20 else ""))
    return setup,wr

def main():
    src=DATA if DATA.exists() and any(DATA.glob("*.csv")) else LIVE
    if src is LIVE: print("NOTE: daily_data_v2/ not found — running on live universe as a smoke test.")
    print(f"Replaying paper book from {START_DATE.date()} on {src.name}/ ...")
    live_set={os.path.splitext(os.path.basename(f))[0].upper() for f in glob.glob(str(LIVE/'*.csv'))}
    spy=pd.read_csv((src/"SPY.csv") if (src/"SPY.csv").exists() else (LIVE/"SPY.csv"),index_col=0,parse_dates=True).sort_index()
    rows=[]; pending=[]
    for fp in glob.glob(str(src/"*.csv")):
        t=os.path.splitext(os.path.basename(fp))[0].upper()
        if t in ETF: continue
        d=pd.read_csv(fp,index_col=0,parse_dates=True).sort_index()
        if len(d)<260: continue
        f=feats(d)
        fw=f[(f.index>=START_DATE)]            # window from the paper-book start
        fw=fw.dropna(subset=["score","dist200_pct"])
        qual=fw[fw["score"]>=2]
        if len(qual)==0: continue
        sig_date=qual.index[0]                  # bar whose CLOSE generated the signal
        r0=qual.iloc[0]                          # features AT the signal bar (point-in-time)
        setup,wr=classify(r0["score"],r0["off_high"],r0["dist200_pct"],r0["wash_min8w"])
        # POINT-IN-TIME: the signal is only known at sig_date's close, so we ENTER
        # at the NEXT session's open (never the same bar) — no look-ahead.
        after=d[d.index>sig_date]
        if len(after)==0:
            # signal fired at the LATEST bar — entry is tomorrow. Not in the stats
            # yet, but it IS tonight's news: export for the Telegram summary.
            if sig_date==d.index[-1] and float(d["Close"].iloc[-1])>=MIN_PRICE:
                pending.append(dict(ticker=t,setup=setup,wr=wr,
                                    score=round(float(r0["score"]),1),sig_date=sig_date))
            continue
        if float(after["Close"].iloc[0])<MIN_PRICE: continue
        e_date=after.index[0]                   # actual entry bar (next session)
        e_px=float(after["Open"].iloc[0]) if "Open" in after else float(after["Close"].iloc[0])
        last=float(after["Close"].iloc[-1]); ret=(last/e_px-1)*100
        def chk(n): return (float(after["Close"].iloc[n])/e_px-1)*100 if len(after)>n else np.nan
        w2,w4,w12=chk(W2),chk(W4),chk(W12)
        first4=after.iloc[:W4+1]; maxdip4=(float(first4["Low"].min())/e_px-1)*100 if len(first4) else np.nan
        dh=len(after)
        phase="Retired" if dh>=W4 else ("Extended" if ret>=5 else "Active")
        sp=spy[spy.index>=e_date]; sp_e=float(sp["Open"].iloc[0]) if len(sp) else np.nan
        sp_ret=(float(sp["Close"].iloc[min(dh-1,len(sp)-1)])/sp_e-1)*100 if len(sp) else np.nan
        rows.append(dict(entry_date=e_date.date(),ticker=t,setup=setup,phase=phase,wr=wr,
            score=round(float(r0["score"]),1),dist200_pct=round(float(r0["dist200_pct"]),1),
            ret_pct=round(ret,2),wk2=round(w2,2) if w2==w2 else np.nan,
            wk4=round(w4,2) if w4==w4 else np.nan,wk12=round(w12,2) if w12==w12 else np.nan,
            maxdip4=round(maxdip4,2) if maxdip4==maxdip4 else np.nan,
            excess=round(ret-sp_ret,2) if sp_ret==sp_ret else np.nan,
            new=(t not in live_set)))
    df=pd.DataFrame(rows)
    print(f"v2 book: {len(df)} positions ({int(df['new'].sum())} NEW names not in live universe)")

    # ── export tonight's NEW v2 signals for the combined Telegram ───────────
    # "new today" = signal fired at the latest bar (pending, enters tomorrow)
    # PLUS entries whose entry bar IS the latest session (entered at today's open).
    last_bar=spy.index.max()
    newly_entered=[r for r in rows if pd.Timestamp(r["entry_date"])>=last_bar.normalize()]
    with open(HERE/"v2_new_today.txt","w") as fh:
        fh.write(f"asof={last_bar.date()}\n")
        for p in pending:
            fh.write(f"{p['ticker']},{p['setup']}{('/'+p['wr']) if p['wr'] else ''},{p['score']},signal-tonight\n")
        for r in newly_entered:
            fh.write(f"{r['ticker']},{r['setup']}{('/'+r['wr']) if r['wr'] else ''},{r['score']},entered-today\n")
    if pending or newly_entered:
        print(f"v2 NEW today: signals {', '.join(p['ticker'] for p in pending) or 'none'}"
              f" | entered {', '.join(r['ticker'] for r in newly_entered) or 'none'}")
    else:
        print("v2 NEW today: none")

    def fan(g,label):
        return g.groupby(label).agg(n=("ret_pct","size"),avg=("ret_pct","mean"),
            win=("ret_pct",lambda s:100*(s>0).mean()),excess=("excess","mean")).round(2).reset_index()
    setup_t=fan(df[df["setup"]!="-"],"setup")
    df["band"]=pd.cut(df["dist200_pct"],[-100,-10,0,10,20,300],labels=["<-10","-10..0","0..10","10..20",">20"])
    band_t=fan(df,"band")
    newcmp=df.groupby("new").agg(n=("ret_pct","size"),avg=("ret_pct","mean"),
        win=("ret_pct",lambda s:100*(s>0).mean()),excess=("excess","mean")).round(2).reset_index()
    newcmp["new"]=newcmp["new"].map({True:"NEW names",False:"existing"})
    wrdf=df[df["wr"].astype(str).str.startswith("WR")]
    wr_t=fan(wrdf,"wr") if len(wrdf) else pd.DataFrame([{"wr":"none","n":0}])

    with pd.ExcelWriter(OUT,engine="openpyxl") as xw:
        summary=pd.DataFrame([("positions",len(df)),("NEW names",int(df["new"].sum())),
            ("book avg ret %",round(df["ret_pct"].mean(),2)),("excess vs SPY %",round(df["excess"].mean(),2)),
            ("win %",round(100*(df["ret_pct"]>0).mean(),1))],columns=["metric","value"])
        summary.to_excel(xw,sheet_name="v2_Book",index=False); r=len(summary)+2
        for nm,tb in [("SETUP fan-out",setup_t),("DISTANCE from 200dma",band_t),
                      ("WASHOUT-RECOVERY (WR20/30/40)",wr_t),("NEW vs EXISTING",newcmp)]:
            pd.DataFrame([{"":nm}]).to_excel(xw,sheet_name="v2_Book",index=False,header=False,startrow=r);r+=1
            tb.to_excel(xw,sheet_name="v2_Book",index=False,startrow=r);r+=len(tb)+2
        # NEWEST entries on top (score desc within a day)
        df.sort_values(["entry_date","score"],ascending=False).to_excel(xw,sheet_name="Positions",index=False)
        df[df["new"]].sort_values(["entry_date","score"],ascending=False).to_excel(xw,sheet_name="New_Names",index=False)
        # widen the entry_date column so dates are fully visible
        for sh,w in [("Positions",13),("New_Names",13),("v2_Book",24)]:
            xw.sheets[sh].column_dimensions["A"].width=w
    print(f"\nwrote {OUT}")
    print("\n=== SETUP fan-out (v2, from 7/20) ==="); print(setup_t.to_string(index=False))
    print("\n=== NEW vs EXISTING ==="); print(newcmp.to_string(index=False))
    print("\n=== top NEW-name performers ===")
    print(df[df["new"]].nlargest(12,"ret_pct")[["ticker","setup","score","dist200_pct","ret_pct","wk4"]].to_string(index=False))

if __name__ == "__main__":
    main()
