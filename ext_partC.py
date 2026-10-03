"""Part C: unusual call or put surge in the 5 sessions before earnings, and the reaction."""
import glob, os, numpy as np, pandas as pd
from scipy import stats as sps
A="uw_archive"; COST=0.001
df=pd.read_parquet("ext_rows.parquet")
df=df[(df.close>=10)&(df.dollar_vol_med20>=20e6)&(df.opt_vol_med21>=1000)]
SPY=pd.read_csv("daily_data_v2/SPY.csv",index_col=0,parse_dates=True).sort_index(); SPY=SPY[~SPY.index.duplicated()]
from exh_build import load
ev=[]
for t,g in df.groupby("ticker"):
    f=f"{A}/earnings_hist/{t}.csv"
    if not os.path.exists(f): continue
    e=pd.read_csv(f)
    if "report_date" not in e: continue
    e=e[(e.get("source")=="company")&(e.report_time.isin(["premarket","postmarket"]))]
    px,_=load(t)
    if px is None: continue
    idx=px.index; O,C=px.Open,px.Close; sc=SPY.Close.reindex(idx); so=SPY.Open.reindex(idx)
    g=g.set_index("date")
    m1=g.M1_call_surge; m2=g.M2_put_surge
    hist=[]  # prior pre earnings maxima for "own history" comparison
    for _,r in e.sort_values("report_date").iterrows():
        d=pd.Timestamp(r.report_date); pos=idx.searchsorted(d)
        if pos>=len(idx) or idx[pos]!=d: continue
        rd=pos if r.report_time=="premarket" else pos+1
        if rd>=len(idx) or rd<6: continue
        pre=idx[rd-5:rd]
        c=m1.reindex(pre); p=m2.reindex(pre)
        if c.notna().sum()<3:
            continue
        cmax,pmax=c.max(),p.max()
        row={"ticker":t,"report_date":d,"reaction_date":idx[rd],"call_max":cmax,"put_max":pmax,
             "prior_call_max_med":np.nanmedian([h[0] for h in hist[-4:]]) if hist else np.nan,
             "prior_put_max_med":np.nanmedian([h[1] for h in hist[-4:]]) if hist else np.nan}
        if rd+3<len(idx):
            row["react_oc"]=(C.iloc[rd]/O.iloc[rd]-1)-(sc.iloc[rd]/so.iloc[rd]-1)
            row["react_cc"]=(C.iloc[rd]/C.iloc[rd-1]-1)-(sc.iloc[rd]/sc.iloc[rd-1]-1)
            row["d3_after"]=(C.iloc[rd+3]/O.iloc[rd+1]-1)-(sc.iloc[rd+3]/so.iloc[rd+1]-1)
        hist.append((cmax,pmax)); ev.append(row)
E=pd.DataFrame(ev); E=E[E.react_cc.notna()]
E["call_surge_raw"]=E.call_max>=3; E["put_surge_raw"]=E.put_max>=3
E["call_surge_own"]=E.call_surge_raw&(E.call_max>E.prior_call_max_med); E["put_surge_own"]=E.put_surge_raw&(E.put_max>E.prior_put_max_med)
E.to_parquet("extC_events.parquet",index=False)
def st(x):
    x=x.dropna(); return dict(n=int(len(x)),avg=x.mean()*100,share_pos=(x>0).mean()*100,med=x.median()*100)
rows=[]
for flavour in ("raw","own"):
    cs=E[E[f"call_surge_{flavour}"]&~E[f"put_surge_{flavour}"]]; ps=E[E[f"put_surge_{flavour}"]&~E[f"call_surge_{flavour}"]]
    both=E[E[f"call_surge_{flavour}"]&E[f"put_surge_{flavour}"]]; base=E[~E[f"call_surge_{flavour}"]&~E[f"put_surge_{flavour}"]]
    if flavour=="own": base=base[base.prior_call_max_med.notna()]
    for name,g in (("call surge only",cs),("put surge only",ps),("both",both),("neither (base)",base)):
        row={"flavour":flavour,"group":name,"events":len(g),"tickers":g.ticker.nunique()}
        for out in ("react_cc","react_oc","d3_after"):
            s=st(g[out]); row[f"{out}_avg"]=s["avg"]; row[f"{out}_share_pos"]=s["share_pos"]; row[f"{out}_med"]=s["med"]
        if name!="neither (base)" and len(g)>10:
            t,pv=sps.ttest_ind(g.react_cc.dropna(),base.react_cc.dropna(),equal_var=False); row["react_cc_t_vs_base"]=t
            row["react_cc_diff_vs_base"]=(g.react_cc.mean()-base.react_cc.mean())*100
            dates=g.sort_values("report_date").report_date; mid=dates.iloc[len(dates)//2]
            row["diff_h1"]=(g[g.report_date<mid].react_cc.mean()-base[base.report_date<mid].react_cc.mean())*100
            row["diff_h2"]=(g[g.report_date>=mid].react_cc.mean()-base[base.report_date>=mid].react_cc.mean())*100
        rows.append(row)
R=pd.DataFrame(rows)
def ok(flavour,side,sign):
    r=R[(R.flavour==flavour)&(R.group==f"{side} surge only")].iloc[0]
    return bool(sign*r.react_cc_diff_vs_base>=1.0 and abs(r.react_cc_t_vs_base)>=2.5 and np.sign(r.diff_h1)==np.sign(r.diff_h2)==sign and r.events>=150), r
P=[]
for flavour in ("raw","own"):
    c,rc=ok(flavour,"call",+1); p,rp=ok(flavour,"put",-1)
    P.append({"flavour":flavour,"call side pass":c,"call diff vs base":rc.react_cc_diff_vs_base,"call t":rc.react_cc_t_vs_base,"call events":rc.events,
              "put side pass":p,"put diff vs base":rp.react_cc_diff_vs_base,"put t":rp.react_cc_t_vs_base,"put events":rp.events,
              "verdict":"PASS" if (c and p) else ("partial (one side)" if (c or p) else "fail")})
P=pd.DataFrame(P)
R.to_csv("extC_results.csv",index=False); P.to_csv("extC_pass.csv",index=False)
pd.set_option("display.width",260); pd.set_option("display.max_columns",40)
print("events",len(E),"tickers",E.ticker.nunique(),E.report_date.min().date(),E.report_date.max().date())
print(R.round(3).to_string()); print(P.round(3).to_string())
