"""Stage 2 per STS_FAST_PREREG.md, built from the features that passed Stage 1 (Amendment 1: N6 only)."""
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
COST=0.001; FEATS=["N6_borrow_fee"]
df=pd.read_parquet("fast_features.parquet").merge(pd.read_parquet("n_features.parquet"),on=["ticker","date"])
df=df[(df.close>=10)&(df.dollar_vol_med20>=20e6)&(df.opt_vol_med21>=1000)].dropna(subset=FEATS+["xs3"]).copy()
for f in FEATS:   # standardize across stocks each day, clip at 3 sd
    g=df.groupby("date")[f]; df[f+"_z"]=((df[f]-g.transform("mean"))/g.transform("std")).clip(-3,3)
lo,hi=df.xs3.quantile([.01,.99]); df["y"]=df.xs3.clip(lo,hi)
X=[f+"_z" for f in FEATS]
months=sorted(df.date.dt.to_period("M").unique()); first=months[0]
preds=[]; coefs=[]
for m in months:
    if (m-first).n<9: continue
    start=m.start_time
    tr=df[df.date<start-pd.tseries.offsets.BDay(5)]          # 5 day purge
    te=df[df.date.dt.to_period("M")==m]
    mdl=Ridge(alpha=1.0).fit(tr[X].fillna(0),tr.y)
    coefs.append((str(m),*mdl.coef_))
    preds.append(te.assign(score=mdl.predict(te[X].fillna(0))))
oos=pd.concat(preds)
oos["dec"]=oos.groupby("date").score.transform(lambda s:np.ceil(s.rank(method="first",pct=True)*10)).astype(int)
def stats(g,k=3):
    x=g[f"xs{k}"]-COST; w=x[x>0]; l=x[x<=0]
    return dict(n=len(x),avg=x.mean()*100,win=(x>0).mean()*100,med=x.median()*100,avg_win=w.mean()*100,avg_loss=l.mean()*100,ratio=w.mean()/abs(l.mean()) if len(l) else np.nan)
top=oos[oos.dec==10]
res={"top_d%d"%k:stats(top,k) for k in range(1,6)}
dec=oos.groupby("dec").apply(lambda g:(g.xs3-COST).mean()*100)
mid=oos.date.sort_values().iloc[len(oos)//2]
h1=stats(top[top.date<mid])["avg"]; h2=stats(top[top.date>=mid])["avg"]
core=stats(top[top.core==1])["avg"]; ext=stats(top[top.core==0])["avg"]
# flame benchmark on the same test months (quiet flame inside S2/B2, at least 1 prior flat day)
fl=oos[(oos.flame_raw==1)&(oos.day_ret.abs()<=0.01)&(oos.P1_prior_flat_days>=1)&((oos.act_S2==1)|(oos.act_B2==1))]
flame=stats(fl) if len(fl) else {"avg":np.nan,"n":0}
t3=res["top_d3"]
checks={"avg_d3>=0.40":t3["avg"]>=0.40,"win>=54":t3["win"]>=54,"ratio>=1":t3["ratio"]>=1,"both_halves_pos":h1>0 and h2>0,
 "core_and_ext_pos":core>0 and ext>0,"dec8<9<10":dec.loc[8]<dec.loc[9]<dec.loc[10],
 "beats_flame":(t3["avg"]>=flame["avg"]) or (abs(t3["avg"]-flame["avg"])<=0.10 and t3["n"]>=3*flame["n"])}
print("coef by month:",coefs[:2],"...",coefs[-1])
print("top decile d3:",{k:round(v,3) for k,v in t3.items()})
print("halves",round(h1,3),round(h2,3),"core",round(core,3),"ext",round(ext,3))
print("deciles d3 after cost:",dec.round(3).to_dict())
print("flame same months:",{k:round(v,3) for k,v in flame.items()})
print("checks:",checks,"PASS" if all(checks.values()) else "FAIL")
pd.DataFrame([{"horizon":k,**v} for k,v in res.items()]).to_csv("stage2_top.csv",index=False)
dec.rename("avg_d3_after_cost").to_csv("stage2_deciles.csv")
pd.DataFrame([{"check":k,"result":v} for k,v in checks.items()]+[{"check":"flame_avg_d3","result":flame["avg"]},{"check":"flame_n","result":flame["n"]},{"check":"top_h1","result":h1},{"check":"top_h2","result":h2},{"check":"top_core","result":core},{"check":"top_ext","result":ext}]).to_csv("stage2_checks.csv",index=False)
