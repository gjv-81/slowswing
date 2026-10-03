"""exh_model.py : STS_EXHAUSTION_PREREG.md models. Logistic primary, XGBoost secondary, walk forward, block bootstrap."""
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
import xgboost as xgb
COST=0.001
E=["E1_short_vol_chg","E2_si_chg","E3_dp_vs_first5","E4_dp_vs_norm","E5_score_chg","E6_pulse_chg","C1_ret5"]
SETUPS=["S2","B2","DLB","D200","D200G","X200G"]
FLAGS=["f_"+s for s in SETUPS[1:]]
X=E+FLAGS+["day_in_window"]
REC={"DLB","D200","D200G"}; MOM={"S2","B2"}

def stats(x):
    x=x.dropna()-COST; w=x[x>0]; l=x[x<=0]
    return dict(n=int(len(x)),avg=x.mean()*100,win=(x>0).mean()*100,med=x.median()*100,
                avg_win=w.mean()*100 if len(w) else np.nan,avg_loss=l.mean()*100 if len(l) else np.nan,
                ratio=(w.mean()/abs(l.mean())) if len(l) and len(w) else np.nan)

def prep(df):
    d=df.copy()
    for s in SETUPS: d["f_"+s]=(d.setup==s).astype(float)
    return d

def first_day_entries(d):
    d=d.dropna(subset=["nflags"]).sort_values("date")
    return d.groupby(["ticker","setup","signal_date","nflags"],as_index=False).first()

def fit_logit(tr,te,target):
    mu=tr[E].mean(); sd=tr[E].std().replace(0,np.nan)
    Ztr=tr[X].copy(); Zte=te[X].copy()
    for f in E: Ztr[f]=((tr[f]-mu[f])/sd[f]).clip(-3,3); Zte[f]=((te[f]-mu[f])/sd[f]).clip(-3,3)
    Ztr["day_in_window"]=(tr.day_in_window-22)/10; Zte["day_in_window"]=(te.day_in_window-22)/10
    m=LogisticRegression(C=1.0,max_iter=2000).fit(Ztr.fillna(0),tr[target])
    return m.predict_proba(Zte.fillna(0))[:,1], dict(zip(X,m.coef_[0]))

def fit_xgb(tr,te,target):
    n=len(tr); cut=int(n*0.8); tr=tr.sort_values("date")
    a,b=tr.iloc[:cut],tr.iloc[cut:]
    m=xgb.XGBClassifier(max_depth=3,learning_rate=0.05,n_estimators=300,min_child_weight=50,subsample=0.8,colsample_bytree=0.8,
                        early_stopping_rounds=30,eval_metric="logloss",verbosity=0)
    m.fit(a[X],a[target],eval_set=[(b[X],b[target])],verbose=False)
    imp=dict(zip(X,m.feature_importances_))
    return m.predict_proba(te[X])[:,1], imp

def walk(d,horizon,purge,model="logit"):
    d=d.dropna(subset=E+[horizon]).copy(); d["y"]=(d[horizon]>0).astype(int)
    months=sorted(d.date.dt.to_period("M").unique()); first=months[0]
    preds=[]; coefs=[]
    for m in months:
        if (m-first).n<9: continue
        start=m.start_time
        tr=d[d.date<start-pd.tseries.offsets.BDay(purge)]; te=d[d.date.dt.to_period("M")==m]
        if len(tr)<300 or te.empty or tr.y.nunique()<2: continue
        p,c=(fit_logit if model=="logit" else fit_xgb)(tr,te,"y")
        preds.append(te.assign(p=p)); coefs.append({"month":str(m),**c})
    if not preds: return None,None
    oos=pd.concat(preds)
    oos["tert"]=oos.groupby(oos.date.dt.to_period("M")).p.transform(lambda s:np.ceil(s.rank(method="first",pct=True)*3)).astype(int)
    return oos,pd.DataFrame(coefs)

def grade(oos,horizon="wk4"):
    g=oos[oos.setup!="X200G"]
    auc=roc_auc_score(g.y,g.p)
    top=g[g.tert==3]; bot=g[g.tert==1]
    t=stats(top[horizon]); b=stats(bot[horizon]); a=stats(g[horizon])
    mid=g.date.sort_values().iloc[len(g)//2]
    def half(h):
        hh=g[h];
        if hh.y.nunique()<2 or len(hh)<50: return np.nan,np.nan
        return roc_auc_score(hh.y,hh.p), stats(hh[hh.tert==3][horizon])["avg"]-stats(hh[hh.tert==1][horizon])["avg"]
    a1,s1=half(g.date<mid); a2,s2=half(g.date>=mid)
    rec=g[g.setup.isin(REC)]; mom=g[g.setup.isin(MOM)]
    srec=stats(rec[rec.tert==3][horizon])["avg"]-stats(rec[rec.tert==1][horizon])["avg"]
    smom=stats(mom[mom.tert==3][horizon])["avg"]-stats(mom[mom.tert==1][horizon])["avg"]
    # condition 6: top third vs all entries matched on day in window (bucketed by 5 days)
    g=g.assign(dbin=(g.day_in_window//5))
    base=g.groupby("dbin")[horizon].mean(); matched=(top.day_in_window//5).map(base)
    c6=(top[horizon]-matched).mean()*100
    checks={"1 AUC >= 0.55":auc>=0.55,"2 top minus bottom third >= +1.5%":(t["avg"]-b["avg"])>=1.5,
            "3 top ratio >= 1.0 and win >= 52%":(t["ratio"]>=1.0) and (t["win"]>=52),
            "4 both halves (AUC>=0.55 and spread>=1.5)":(a1>=0.55 and a2>=0.55 and s1>=1.5 and s2>=1.5),
            "5 spread >= 1.5 in recovery group and in S2/B2":(srec>=1.5 and smom>=1.5),
            "6 top beats same day in window by >= 0.75%":c6>=0.75}
    return dict(auc=auc,top=t,bot=b,all=a,spread=t["avg"]-b["avg"],auc_h1=a1,auc_h2=a2,spread_h1=s1,spread_h2=s2,
                spread_recovery=srec,spread_s2b2=smom,c6=c6,checks=checks,PASS=all(checks.values()))

def block_bootstrap(d,horizon,n=1000,seed=0):
    """logistic on the full first day entry set, resampling whole signals"""
    d=d.dropna(subset=E+[horizon]).copy(); d["y"]=(d[horizon]>0).astype(int)
    d["sig"]=d.ticker+"|"+d.signal_date.astype(str)
    sigs=d.sig.unique(); rng=np.random.default_rng(seed); out=[]
    groups=d.groupby("sig").indices
    for _ in range(n):
        pick=rng.choice(sigs,len(sigs),replace=True)
        ix=np.concatenate([groups[s] for s in pick]); b=d.iloc[ix]
        if b.y.nunique()<2: continue
        _,c=fit_logit(b,b.iloc[:5],"y"); out.append(c)
    B=pd.DataFrame(out)
    return pd.DataFrame({"input":B.columns,"weight_median":B.median(),"p5":B.quantile(.05),"p95":B.quantile(.95),
                         "range_excludes_zero":((B.quantile(.05)>0)|(B.quantile(.95)<0)).values}).reset_index(drop=True)

def main():
    df=prep(pd.read_parquet("exh_rows.parquet"))
    df=df[df.wk4.notna()]
    core=df[df.core==1]
    A=first_day_entries(core); B=core.dropna(subset=["nflags"])
    print("first day entries:",len(A),"signals:",A.drop_duplicates(["ticker","signal_date"]).shape[0]); print(A.setup.value_counts().to_dict())
    res=[]; weights=[]; oos_store={}
    for an,dset in (("A first day entries",A),("B every day",B)):
        for hz,purge in (("wk4",20),("wk2",10),("d5",5)):
            for model in ("logit","xgb"):
                oos,co=walk(dset,hz,purge,model)
                if oos is None: continue
                g=grade(oos,hz); oos_store[(an,hz,model)]=oos
                row={"analysis":an,"horizon":hz,"model":model,"graded":(an.startswith("A") and hz=="wk4" and model=="logit"),
                     "test_from":oos.date.min().strftime("%b %d %Y"),"test_to":oos.date.max().strftime("%b %d %Y"),"rows":len(oos),
                     "signals":int(oos.drop_duplicates(["ticker","signal_date"]).shape[0]),"AUC":g["auc"],
                     **{"top_"+k:v for k,v in g["top"].items()},**{"bot_"+k:v for k,v in g["bot"].items()},"all_avg":g["all"]["avg"],"all_win":g["all"]["win"],
                     "spread":g["spread"],"AUC_h1":g["auc_h1"],"AUC_h2":g["auc_h2"],"spread_h1":g["spread_h1"],"spread_h2":g["spread_h2"],
                     "spread_recovery":g["spread_recovery"],"spread_s2b2":g["spread_s2b2"],"top_vs_same_day_in_window":g["c6"],**g["checks"],"PASS":g["PASS"]}
                res.append(row)
                if model=="logit":
                    mean=co.drop(columns="month").mean(); sd=co.drop(columns="month").std()
                    for f in mean.index: weights.append({"analysis":an,"horizon":hz,"input":f,"avg_coef_oos":mean[f],"sd_across_refits":sd[f],"share_same_sign":(np.sign(co[f])==np.sign(mean[f])).mean()*100})
                else:
                    mean=co.drop(columns="month").mean()
                    for f in mean.index: weights.append({"analysis":an,"horizon":hz,"input":f,"xgb_importance":mean[f]})
                print(f"{an} {hz} {model}: AUC {g['auc']:.3f} top {g['top']['avg']:+.2f} bot {g['bot']['avg']:+.2f} spread {g['spread']:+.2f} | {'PASS' if g['PASS'] else 'fail'}",flush=True)
    R=pd.DataFrame(res); R.to_csv("exh_results.csv",index=False); pd.DataFrame(weights).to_csv("exh_weights.csv",index=False)
    # bootstrap on A wk4
    print("bootstrapping ...",flush=True)
    bs=block_bootstrap(A[A.setup!="X200G"],"wk4",n=600); bs.to_csv("exh_bootstrap.csv",index=False); print(bs.round(3).to_string())
    # per setup, flag count staircase, single flags (A, wk4, out of sample rows of the graded model)
    oos=oos_store[("A first day entries","wk4","logit")]
    per=[]
    for s in SETUPS:
        o=oos[oos.setup==s]
        if len(o)<30: continue
        t=stats(o[o.tert==3].wk4); b=stats(o[o.tert==1].wk4); a=stats(o.wk4)
        per.append({"setup":s,"rows":len(o),"AUC":roc_auc_score(o.y,o.p) if o.y.nunique()>1 else np.nan,**{"top_"+k:v for k,v in t.items()},"bot_avg":b["avg"],"all_avg":a["avg"],"all_win":a["win"],"note":"descriptive only" if s=="X200G" else ""})
    pd.DataFrame(per).to_csv("exh_persetup.csv",index=False)
    st=[]
    for k in range(5):
        o=A[(A.nflags==k)&(A.setup!="X200G")]
        if len(o): st.append({"flags":k,**{"wk4_"+a:b for a,b in stats(o.wk4).items()},**{"wk2_"+a:b for a,b in stats(o.wk2).items()}})
    pd.DataFrame(st).to_csv("exh_staircase.csv",index=False)
    sf=[]
    for f,name in [("F1","short selling falling"),("F2","dark pool quiet"),("F3","score rising"),("F4","pulse rising")]:
        g=A[A.setup!="X200G"]
        on=stats(g[g[f]==1].wk4); off=stats(g[g[f]==0].wk4)
        sf.append({"flag":name,"n_on":on["n"],"wk4_avg_on":on["avg"],"wk4_win_on":on["win"],"n_off":off["n"],"wk4_avg_off":off["avg"],"wk4_win_off":off["win"],"difference":on["avg"]-off["avg"]})
    pd.DataFrame(sf).to_csv("exh_singleflags.csv",index=False)
    pd.set_option("display.width",250); pd.set_option("display.max_columns",40)
    print(R[["analysis","horizon","model","AUC","top_avg","bot_avg","spread","spread_h1","spread_h2","spread_recovery","spread_s2b2","top_vs_same_day_in_window","PASS"]].round(3).to_string())
    print(pd.DataFrame(st).round(2).to_string()); print(pd.DataFrame(sf).round(2).to_string())

if __name__=="__main__": main()
