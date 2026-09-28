#!/usr/bin/env python3.12
"""
uw_flame_live.py — nightly FAST-LANE flame scanner (fully automated, no manual work).

WHAT IT DOES each evening (after the price refresh):
  1. Scans daily_data_v2/ + daily_data_ext/ for ACTIVE S2/B2 signals
     (score >= 2, < 25% off 52wk high, first-day rule + 20td refractory,
      signal age <= 40 trading days, price >= $25).
  2. Keeps only candidates matching the VALIDATED pattern for tonight:
     TODAY within ±1% and the PRIOR day within ±1% (the "1-flat" cell —
     deep-flat variants are deliberately excluded: bad payoff ratios).
  3. For that shortlist only (usually < 15 names), one UW call each:
     ask-side call volume vs its own trailing-21d median.
     FLAME = ratio >= 3 AND ask-side calls > ask-side puts.
  4. Telegram alert with the flames (and the checked shortlist for context),
     and appends EVERYTHING to fast_lane_log.csv — the forward-test record.

TOKEN: reads .env_uw_live first (the personal $150 account), else .env_uw.
       If neither exists, exits quietly — safe to leave wired into run_evening.sh.

RUN:  python3.12 uw_flame_live.py            (or add to run_evening.sh)
Historical profile (STS_flame_final.xlsx): payoff window days 3-5;
S2 1-flat avg winner ~+4%, avg loser ~-3.5%, win ~53-58%. Personal use only.
"""
import glob, os, sys, time, datetime
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

HERE=Path(__file__).resolve().parent
LOG=HERE/"fast_lane_log.csv"
BASE="https://api.unusualwhales.com"
TG_TOKEN="8608595671:AAHwVnhGeP3iiX9jk9EV4CPGAmArrbT-DkI"
TG_CHAT="6499078442"
MIN_PRICE=25.0

def token():
    for name in (".env_uw_live",".env_uw"):
        p=HERE/name
        if p.exists():
            for ln in p.read_text().splitlines():
                if "UW_TOKEN" in ln:
                    return ln.split("=",1)[1].strip().strip('"').strip("'")
    return None

ZC={"high52":(-0.149772,0.156737),"dist200":(1.681650,6.240695),"mom6":(0.086250,0.361377),
    "qqe":(0.044473,0.194268),"hull":(0.027496,0.303103),"mom40":(0.020000,0.155298)}
W={"high52":-2.20,"dist200":1.35,"mom6":1.08,"qqe":-0.99,"mom40":0.63,"hull":0.60}
z=lambda v,k:np.clip((v-ZC[k][0])/ZC[k][1],-3,3)
def wma(s,n):
    w=np.arange(1,n+1,dtype=float); return s.rolling(n).apply(lambda x:np.dot(x,w)/w.sum(),raw=True)
def rsi(s,n=20):
    d=s.diff();up,dn=d.clip(lower=0),-d.clip(upper=0)
    return 100-100/(1+up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,1e-10))

def find_candidates():
    """active S2/B2 signals whose TODAY + prior day are both quiet (±1%)"""
    cands=[]
    files=[(f,"v2") for f in glob.glob(str(HERE/"daily_data_v2"/"*.csv"))] \
         +[(f,"ext") for f in glob.glob(str(HERE/"daily_data_ext"/"*.csv"))]
    seen=set()
    for fp,src in sorted(files):
        t=os.path.splitext(os.path.basename(fp))[0].upper()
        if t in seen: continue
        seen.add(t)
        try:
            px=pd.read_csv(fp,index_col=0,parse_dates=True).sort_index()
            if len(px)<300: continue
            C,H=px["Close"],px["High"]
            if float(C.iloc[-1])<MIN_PRICE: continue
            ret=C.pct_change()*100
            # tonight's pattern gate first (cheap): today and yesterday within ±1%
            if abs(ret.iloc[-1])>1 or abs(ret.iloc[-2])>1: continue
            # how many consecutive PRIOR days were quiet (max 10 counted)
            streak=0
            for k in range(2,12):
                if abs(ret.iloc[-k])<=1: streak+=1
                else: break
            pc=C.shift(1)
            tr=pd.concat([H-px["Low"],(H-pc).abs(),(px["Low"]-pc).abs()],axis=1).max(axis=1)
            atr=tr.ewm(alpha=1/14,adjust=False).mean();sma=C.rolling(200).mean()
            f={}
            f["high52"]=C/H.rolling(252).max()-1; f["dist200"]=(C-sma)/atr
            f["mom6"]=C.shift(10)/C.shift(126)-1
            f["qqe"]=(rsi(C,20).fillna(50).ewm(span=5,adjust=False).mean()-50)/50
            hma=wma(2*wma(C,10)-wma(C,20),4); f["hull"]=(hma-hma.shift(1))/atr
            f["mom40"]=C/C.shift(40)-1
            score=sum(W[k]*z(f[k],k) for k in W)
            oh=f["high52"]*100
            mask=(score>=2)&(oh>-25)
            m=mask&~mask.shift(1,fill_value=False)
            idxs=np.where(m&(C>=MIN_PRICE))[0]
            last=-99; sig_idx=None
            for i0 in idxs:
                if i0-last<20: continue
                last=i0; sig_idx=i0
            if sig_idx is None: continue
            age=len(C)-1-sig_idx
            if not (1<=age<=40): continue                      # active signal life
            setup="B2" if oh.iloc[sig_idx]<=-10 else "S2"
            run=round((float(C.iloc[-1])/float(C.iloc[sig_idx])-1)*100,1)
            cands.append(dict(ticker=t,setup=setup,univ=src,flat_streak=streak,run=run,
                              sig_date=str(C.index[sig_idx].date()),
                              age=age,close=round(float(C.iloc[-1]),2),
                              d0=round(float(ret.iloc[-1]),2)))
        except Exception: continue
    return cands

def check_flame(t,tok):
    import requests
    try:
        r=requests.get(f"{BASE}/api/stock/{t}/options-volume",params={"limit":30},
            headers={"Authorization":f"Bearer {tok}","Accept":"application/json"},timeout=30)
        time.sleep(0.4)
        if r.status_code!=200: return None
        d=pd.DataFrame(r.json().get("data",[]))
        if len(d)<15 or "call_volume_ask_side" not in d.columns: return None
        d["date"]=pd.to_datetime(d["date"]); d=d.sort_values("date")
        today=d.iloc[-1]
        med=float(d["call_volume_ask_side"].iloc[:-1].tail(21).median())
        if med<=0: return None
        ratio=float(today["call_volume_ask_side"])/med
        flame=(ratio>=3) and (float(today["call_volume_ask_side"])>float(today["put_volume_ask_side"]))
        def g(k):
            try: return float(today.get(k,np.nan))
            except Exception: return np.nan
        ask_call,ask_put=g("call_volume_ask_side"),g("put_volume_ask_side")
        prem=g("call_premium_ask_side")
        if not np.isfinite(prem): prem=g("bullish_premium")
        avg30=g("avg_30_day_call_volume")
        return dict(ratio=round(ratio,2),flame=flame,
                    ask_call=int(ask_call),ask_put=int(ask_put),
                    pc_ask=round(ask_put/ask_call,2) if ask_call>0 else np.nan,
                    call_prem=prem,
                    vol_vs_30d=round(g("call_volume")/avg30,2) if avg30 and avg30>0 else np.nan,
                    uw_date=str(today["date"].date()))
    except Exception:
        return None

def spy_dial():
    """same percentile dial as the evening script (RED/GREEN/YELLOW/ORANGE)"""
    try:
        spy=pd.read_csv(HERE/"daily_data_10y"/"SPY.csv",index_col=0,parse_dates=True).sort_index()["Close"]
        stretch=((spy/spy.rolling(200).mean()-1)*100).dropna()
        w=stretch.iloc[-757:]
        p=100*(w.iloc[:-1]<w.iloc[-1]).mean()
        s=float(stretch.iloc[-1])
        if s<0: return "🔴 SPY: RED (below 200-day)"
        if p>90: return f"🟠 SPY: ORANGE (over-extended, {p:.0f}th pctile of 3yr)"
        if p>=50: return f"🟡 SPY: YELLOW (extended, {p:.0f}th pctile of 3yr)"
        return f"🟢 SPY: GREEN (recently reset, {p:.0f}th pctile of 3yr)"
    except Exception:
        return "SPY dial unavailable"

def _money(x):
    if not np.isfinite(x): return "n/a"
    return f"${x/1e6:.1f}M" if x>=1e6 else f"${x/1e3:.0f}k"

def main():
    tok=token()
    if not tok:
        print("no UW token (.env_uw_live / .env_uw) — flame scan skipped"); return
    today=datetime.date.today().isoformat()
    cands=find_candidates()
    print(f"quiet S2/B2 candidates tonight: {len(cands)}")
    rows=[]; flames=[]
    for c in cands:
        r=check_flame(c["ticker"],tok)
        if r is None: continue
        rec={**c,**r,"scan_date":today}
        rows.append(rec)
        # EXPANSION RULE (backtested 2026-09-28): S2 flames did NOT transfer to
        # the ext universe (controls beat flames at d3-d5) — log them, never alert.
        # B2 transferred strongly (61-68% win d1-d4) — full universe allowed.
        if r["flame"] and not (c["setup"]=="S2" and c["univ"]=="ext"):
            flames.append(rec)
        print(f"  {c['ticker']:6s} {c['setup']} ratio {r['ratio']:5.2f} {'🔥' if r['flame'] else ''}")
    if rows:
        pd.DataFrame(rows).to_csv(LOG,mode="a",header=not LOG.exists(),index=False)
    # telegram — standalone FAST LANE message
    try:
        import requests
        dial=spy_dial()
        datestr=datetime.date.today().strftime("%a %b %d")
        if flames:
            lines=[]
            for f in flames:
                pc=f"{f['pc_ask']:.1f}" if np.isfinite(f.get("pc_ask",np.nan)) else "n/a"
                v30=f"{f['vol_vs_30d']:.1f}x" if np.isfinite(f.get("vol_vs_30d",np.nan)) else "n/a"
                warn=" ⚠️deep-flat" if (f['setup']=="S2" and f.get('flat_streak',1)>=2) else ""
                boost=" ✅deep-flat" if (f['setup']=="B2" and f.get('flat_streak',1)>=2) else ""
                rn=f.get('run',0)
                if f['setup']=="S2":
                    runtag=" ✅fresh" if rn<5 else " ⚠️ran"
                else:
                    runtag=" ✅continuation" if rn>=10 else (" ⚠️mid-run" if rn>=5 else "")
                lines.append(
                    f"🔥 <b>{f['ticker']}</b> — {f['setup']}/{f['univ']} · sig {f['sig_date']} (day {f['age']}) · "
                    f"run {f.get('run',0):+.1f}%{runtag} · flat x{f.get('flat_streak',1)}{warn}{boost} · ${f['close']} ({f['d0']:+.1f}%)\n"
                    f"     ask-calls <b>{f['ratio']}x</b> med ({f['ask_call']:,}) · {_money(f.get('call_prem',np.nan))} call prem · "
                    f"P/C ask {pc} · vol {v30} 30d")
            body="\n".join(lines)
            msg=(f"🔥 <b>FAST LANE</b> — {datestr}\n\n{dial}\n\n{body}\n\n"
                 f"<i>Playbook: window days 3–5 · S2 hist ~55% win, avg +4.1/−3.5 · B2 strength d4–d5</i>\n"
                 f"<i>(checked {len(rows)} quiet candidates · research, not advice)</i>")
        else:
            msg=(f"FAST LANE — {datestr}\n{dial}\n"
                 f"No flames tonight ({len(rows)} quiet S2/B2 candidates checked).")
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id":TG_CHAT,"text":msg,"parse_mode":"HTML"},timeout=15)
        print("telegram sent")
    except Exception as e:
        print(f"telegram failed: {e}")

if __name__=="__main__":
    main()
