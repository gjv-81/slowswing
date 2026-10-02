import numpy as np, pandas as pd
COST=0.001
ev=pd.read_parquet("stage3_events.parquet")
def st(x):
    x=x.dropna()-COST; w=x[x>0]; l=x[x<=0]
    return pd.Series(dict(n=len(x),avg=x.mean()*100,win=(x>0).mean()*100,med=x.median()*100,avg_win=w.mean()*100,avg_loss=l.mean()*100,ratio=(w.mean()/abs(l.mean())) if len(l) else np.nan))
fams=["PB","BO","SQ","PEAD","GAP","WB","SQZ"]
summary=[];detail=[]
for f in fams:
    e=ev[ev.family==f]
    pooled=st(e.xs3); eras=e.groupby("era").xs3.apply(lambda x:(x.dropna()-COST).mean()*100)
    era_n=e.groupby("era").size()
    avail=list(eras.index)
    need=2 if len(avail)==3 else len(avail)
    eras_ok=int((eras>=0.30).sum())
    checks={"eras_ok":eras_ok>=need,"win>=53":pooled.win>=53,"ratio>=1":pooled.ratio>=1,"episodes>=300":pooled.n>=300}
    row={"family":f,**{f"era {k[:2]} avg d3":v for k,v in eras.items()},**{f"era {k[:2]} n":v for k,v in era_n.items()},
         "eras at least +0.30%":f"{eras_ok} of {len(avail)} (need {need})",**{k:v for k,v in pooled.items()},
         "core avg d3":(e[e.core==1].xs3.dropna()-COST).mean()*100,"ext avg d3":(e[e.core==0].xs3.dropna()-COST).mean()*100,
         "PASS":all(checks.values()),"why":";".join(k for k,v in checks.items() if not v)}
    summary.append(row)
    for k in range(1,6):
        s=st(e[f"xs{k}"]); detail.append({"family":f,"horizon":f"d{k}",**s})
    for era,g in e.groupby("era"):
        s=st(g.xs3); detail.append({"family":f,"horizon":f"d3 {era}",**s})
S=pd.DataFrame(summary); D=pd.DataFrame(detail)
# gamma modifier (Amendment 1): all families reported; verdict counts only for passing families
decl={"BO":"neg","SQ":"neg","GAP":"neg","PEAD":"neg","PB":"pos","WB":"pos","SQZ":None}
gam=[]
for f in fams:
    e=ev[(ev.family==f)&ev.net_gex.notna()].sort_values("date")
    if len(e)<40: continue
    mid=e.date.iloc[len(e)//2]
    def diff(g):
        a=(g[g.net_gex<0].xs3.dropna()-COST).mean()*100; b=(g[g.net_gex>=0].xs3.dropna()-COST).mean()*100
        return a,b
    a,b=diff(e); a1,b1=diff(e[e.date<mid]); a2,b2=diff(e[e.date>=mid])
    want=decl[f]
    sgn=1 if want=="neg" else -1
    ok=want is not None and sgn*(a1-b1)>=0.30 and sgn*(a2-b2)>=0.30
    gam.append({"family":f,"declared better when":{"neg":"dealers short gamma","pos":"dealers long gamma",None:"not declared"}[want],
        "n short gamma":int((e.net_gex<0).sum()),"n long gamma":int((e.net_gex>=0).sum()),
        "avg d3 short gamma":a,"avg d3 long gamma":b,"difference (short minus long)":a-b,
        "first half diff":a1-b1,"second half diff":a2-b2,"supported (declared rule)":bool(ok),
        "counts for verdict":bool(S.loc[S.family==f,"PASS"].iloc[0])})
G=pd.DataFrame(gam)
# N7 inside PEAD
p=ev[(ev.family=="PEAD")&ev.n7_surge.notna()]
N7=pd.DataFrame([{"group":"PEAD with pre earnings call surge",**st(p[p.n7_surge==1].xs3)},{"group":"PEAD without",**st(p[p.n7_surge==0].xs3)}])
for name,df in [("S",S),("D",D),("G",G),("N7",N7)]: df.to_csv(f"stage3_{name}.csv",index=False)
pd.set_option("display.width",250); pd.set_option("display.max_columns",30)
print(S.round(3).to_string()); print(G.round(3).to_string()); print(N7.round(3).to_string())
