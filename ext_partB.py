"""Part B: bearish warning inside the setups, and the avoid rule."""
import numpy as np, pandas as pd
from stage1_screen import nw_t
COST=0.001
df=pd.read_parquet("ext_rows.parquet")
df=df[(df.close>=10)&(df.dollar_vol_med20>=20e6)&(df.opt_vol_med21>=1000)].copy()
df["W2"]=((df.M2_put_surge>=3)&(df.ask_put_gt_call==1)).astype(float).where(df.M2_put_surge.notna())
df["W1"]=(df.W2*df.quiet).where(df.W2.notna())
df=df.sort_values(["ticker","date"])
for w in ("W1","W2"):
    df[w+"_recent5"]=df.groupby("ticker")[w].transform(lambda s:s.rolling(5,min_periods=1).max().shift(1))   # fired in the prior 5 sessions (not today)
    df[w+"_recent5_incl"]=df.groupby("ticker")[w].transform(lambda s:s.rolling(5,min_periods=1).max())      # prior 5 or today
H={"d3":"xs3","d5":"xs5","wk2":"xs10","wk4":"xs20"}
REC=(df.act_DLB==1)|(df.act_D200==1)|(df.act_D200G==1); MOM=(df.act_S2==1)|(df.act_B2==1)
df["grp"]=np.where(REC,"recovery",np.where(MOM,"s2b2",None))
ins=df[df.grp.notna()].copy()
def st(x):
    x=x.dropna()-COST; w=x[x>0]; l=x[x<=0]
    return dict(n=int(len(x)),avg=x.mean()*100,win=(x>0).mean()*100,med=x.median()*100,avg_win=w.mean()*100 if len(w) else np.nan,avg_loss=l.mean()*100 if len(l) else np.nan,ratio=(w.mean()/abs(l.mean())) if len(l) and len(w) else np.nan)
rows=[]
# Q1: warning days vs matched (same day) setup days without
for w in ("W1","W2"):
    for gname,g in (("all",ins),("recovery",ins[ins.grp=="recovery"]),("s2b2",ins[ins.grp=="s2b2"])):
        on=g[g[w]==1]; off=g[g[w]==0]
        row={"flag":w,"group":gname,"n_warning_days":len(on),"tickers":on.ticker.nunique(),"days":on.date.nunique()}
        for h,c in H.items():
            row[f"{h}_warn_avg"]=st(on[c])["avg"]; row[f"{h}_other_avg"]=st(off[c])["avg"]; row[f"{h}_warn_win"]=st(on[c])["win"]
            e=on.groupby("date")[c].mean(); m=off.groupby("date")[c].mean(); d=(e-m).dropna()
            row[f"{h}_matched_diff"]=d.mean()*100
            if h=="wk2":
                t,_=nw_t(d.values,10); row["wk2_t"]=t; dates=d.index; mid=dates[len(dates)//2]
                row["wk2_diff_h1"]=d[dates<mid].mean()*100; row["wk2_diff_h2"]=d[dates>=mid].mean()*100
        rows.append(row)
Q1=pd.DataFrame(rows)
# Q2: avoid rule. (a) signal day entries: did W1 fire in the 5 sessions before or on the signal day?
sig=[]
for s,col in (("S2","act_S2"),("B2","act_B2"),("DLB","act_DLB"),("D200","act_D200"),("D200G","act_D200G")):
    first=(df[col]==1)&(df.groupby("ticker")[col].shift(1).fillna(0)==0)
    e=df[first&df.W1_recent5_incl.notna()]
    a=e[e.W1_recent5_incl==1]; b=e[e.W1_recent5_incl==0]
    sig.append({"setup":s,"signals":len(e),"with_warning":len(a),"share_flagged":len(a)/max(len(e),1)*100,
                "wk4_with_warning":st(a.xs20)["avg"],"wk4_without":st(b.xs20)["avg"],"wk4_win_with":st(a.xs20)["win"],"wk4_win_without":st(b.xs20)["win"],
                "wk2_with_warning":st(a.xs10)["avg"],"wk2_without":st(b.xs10)["avg"]})
e=df[df.groupby("ticker")[["act_S2","act_B2","act_DLB","act_D200","act_D200G"]].shift(1).fillna(0).sum(axis=1).eq(0)&(df.in_setup==1)&df.W1_recent5_incl.notna()]
a=e[e.W1_recent5_incl==1]; b=e[e.W1_recent5_incl==0]
sig.append({"setup":"ALL","signals":len(e),"with_warning":len(a),"share_flagged":len(a)/max(len(e),1)*100,"wk4_with_warning":st(a.xs20)["avg"],"wk4_without":st(b.xs20)["avg"],"wk4_win_with":st(a.xs20)["win"],"wk4_win_without":st(b.xs20)["win"],"wk2_with_warning":st(a.xs10)["avg"],"wk2_without":st(b.xs10)["avg"]})
Q2a=pd.DataFrame(sig)
# (b) forward version: all entries in windows, skip those with W1 in the prior 5 sessions
rule=[]
for gname,g in (("all",ins),("recovery",ins[ins.grp=="recovery"]),("s2b2",ins[ins.grp=="s2b2"])):
    g=g[g.W1_recent5.notna()]
    keep=g[g.W1_recent5==0]; skip=g[g.W1_recent5==1]
    rule.append({"group":gname,"entries":len(g),"skipped":len(skip),"share_skipped":len(skip)/max(len(g),1)*100,
                 "wk4_all":st(g.xs20)["avg"],"wk4_kept":st(keep.xs20)["avg"],"wk4_skipped":st(skip.xs20)["avg"],"improvement_kept_minus_all":st(keep.xs20)["avg"]-st(g.xs20)["avg"],
                 "wk2_all":st(g.xs10)["avg"],"wk2_kept":st(keep.xs10)["avg"],"wk2_skipped":st(skip.xs10)["avg"]})
Q2b=pd.DataFrame(rule)
# pass evaluation on W1
r=Q1[(Q1.flag=="W1")]
allr=r[r.group=="all"].iloc[0]; rec=r[r.group=="recovery"].iloc[0]; mom=r[r.group=="s2b2"].iloc[0]
checks={"W1 trails matched by >= 0.75% at wk2":allr.wk2_matched_diff<=-0.75,"|t| >= 2.5":abs(allr.wk2_t)>=2.5,
        "same sign both halves":(allr.wk2_diff_h1<0) and (allr.wk2_diff_h2<0),"both groups trail by >= 0.75%":(rec.wk2_matched_diff<=-0.75) and (mom.wk2_matched_diff<=-0.75),
        "avoid rule removes >= 5% of entries":Q2b[Q2b.group=="all"].share_skipped.iloc[0]>=5}
P=pd.DataFrame([{"check":k,"result":v} for k,v in checks.items()]+[{"check":"PASS","result":all(checks.values())}])
for n,o in (("extB_q1",Q1),("extB_q2a",Q2a),("extB_q2b",Q2b),("extB_pass",P)): o.to_csv(n+".csv",index=False)
pd.set_option("display.width",260); pd.set_option("display.max_columns",40)
print(Q1[["flag","group","n_warning_days","d3_matched_diff","d5_matched_diff","wk2_matched_diff","wk2_t","wk2_diff_h1","wk2_diff_h2","wk4_matched_diff","wk2_warn_avg","wk2_other_avg"]].round(3).to_string())
print(Q2a.round(2).to_string()); print(Q2b.round(3).to_string()); print(P.to_string())
