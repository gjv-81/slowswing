"""
vol_setup_model.py : walk forward ridge per STS_VOL_SETUP_PREREG.md (approved Oct 3 2026).
Model 1: V1..V4 + setup flags, data from Jan 2024.   Model 2: V1..V6 + flags, data from Sep 16 2024.
Analysis A: signal day rows only.   Analysis B: all rows in the first 40 days.
Horizons d1..d5 (purge 5), wk2 (purge 10), wk4 (purge 20). Pass judged at d3 on the top decile.
"""
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
COST=0.001
SETUPS=["S2","B2","D200G","X200G"]
HORIZ={"d1":5,"d2":5,"d3":5,"d4":5,"d5":5,"wk2":10,"wk4":20}
MODELS={"M1":(["V1_iv","V2_ivrank6m","V3_iv_minus_rv","V4_iv_chg5"],"2024-01-02"),
        "M2":(["V1_iv","V2_ivrank6m","V3_iv_minus_rv","V4_iv_chg5","V5_smirk","V6_smirk_chg5"],"2024-09-16"),
        "M1_12m":(["V1_iv","V2b_ivrank12m","V3_iv_minus_rv","V4_iv_chg5"],"2024-07-15")}

def stats(x):
    x=x.dropna()-COST; w=x[x>0]; l=x[x<=0]
    return dict(n=int(len(x)),avg=x.mean()*100,win=(x>0).mean()*100,med=x.median()*100,
                avg_win=w.mean()*100 if len(w) else np.nan,avg_loss=l.mean()*100 if len(l) else np.nan,
                ratio=(w.mean()/abs(l.mean())) if len(l) and len(w) else np.nan)

def walk_forward(df, feats, horizon, purge):
    """returns df of test rows with out of sample score, and the list of monthly coefficient rows"""
    d=df.dropna(subset=feats+[horizon]).copy()
    for s in SETUPS: d["f_"+s]=(d.setup==s).astype(float)
    X=feats+["f_"+s for s in SETUPS[1:]]   # S2 is the reference setup
    months=sorted(d.date.dt.to_period("M").unique()); first=months[0]
    preds=[]; coefs=[]
    for m in months:
        if (m-first).n<9: continue
        start=m.start_time
        tr=d[d.date<start-pd.tseries.offsets.BDay(purge)]
        te=d[d.date.dt.to_period("M")==m]
        if len(tr)<200 or te.empty: continue
        mu=tr[feats].mean(); sd=tr[feats].std().replace(0,np.nan)
        Ztr=tr.copy(); Zte=te.copy()
        for f in feats: Ztr[f]=((tr[f]-mu[f])/sd[f]).clip(-3,3); Zte[f]=((te[f]-mu[f])/sd[f]).clip(-3,3)
        lo,hi=tr[horizon].quantile([.01,.99]); y=tr[horizon].clip(lo,hi)
        mdl=Ridge(alpha=1.0).fit(Ztr[X].fillna(0),y)
        coefs.append({"month":str(m),"n_train":len(tr),**dict(zip(X,mdl.coef_))})
        preds.append(te.assign(score=mdl.predict(Zte[X].fillna(0))))
    if not preds: return None,None
    oos=pd.concat(preds)
    oos["dec"]=oos.groupby(oos.date.dt.to_period("M")).score.transform(lambda s:np.ceil(s.rank(method="first",pct=True)*10)).astype(int)
    return oos,pd.DataFrame(coefs)

def grade(oos, horizon="d3"):
    top=oos[oos.dec==10]; allr=oos
    t=stats(top[horizon]); a=stats(allr[horizon])
    dec=oos.groupby("dec")[horizon].apply(lambda x:(x.dropna()-COST).mean()*100)
    mid=oos.date.sort_values().iloc[len(oos)//2]
    h1=stats(top[top.date<mid][horizon])["avg"]; h2=stats(top[top.date>=mid][horizon])["avg"]
    checks={"1 avg d3 >= +0.40%":t["avg"]>=0.40,"2 win >= 54%":t["win"]>=54,"3 ratio >= 1.0":t["ratio"]>=1.0,
            "4 positive both halves":(h1>0) and (h2>0),"5 deciles 8<9<10":dec.loc[8]<dec.loc[9]<dec.loc[10],
            "6 beats all signals by 0.30%":(t["avg"]-a["avg"])>=0.30}
    return t,a,dec,h1,h2,checks

def main():
    df=pd.read_parquet("vol_setup_rows.parquet")
    df=df[df.d3.notna()]
    cut=df.groupby("date")["borrow_fee"].transform(lambda s:s.quantile(0.90))
    df["easy"]=(df.borrow_fee<=cut)|df.borrow_fee.isna()
    summary=[]; horizons=[]; weights=[]; deciles=[]; persetup=[]; top_oos={}
    for mname,(feats,start) in MODELS.items():
        for an,sub in (("A signal day",df[df.is_signal_day==1]),("B any day in 40",df)):
            sub=sub[sub.date>=start]
            key=f"{mname} {an}"
            for hz,purge in HORIZ.items():
                oos,co=walk_forward(sub,feats,hz,purge)
                if oos is None: continue
                t=stats(oos[oos.dec==10][hz]); a=stats(oos[hz])
                horizons.append({"model":mname,"analysis":an,"horizon":hz,"test_from":oos.date.min().strftime("%b %d %Y"),"test_to":oos.date.max().strftime("%b %d %Y"),
                                 "episodes_top":int(oos[oos.dec==10].drop_duplicates(["ticker","signal_date"]).shape[0]),
                                 **{"top_"+k:v for k,v in t.items()},**{"all_"+k:v for k,v in a.items()},"top_minus_all":t["avg"]-a["avg"]})
                if hz=="d3":
                    top_oos[key]=oos
                    tt,aa,dec,h1,h2,checks=grade(oos)
                    row={"model":mname,"analysis":an,"test_from":oos.date.min().strftime("%b %d %Y"),"test_to":oos.date.max().strftime("%b %d %Y"),
                         "rows_tested":len(oos),"episodes_tested":int(oos.drop_duplicates(["ticker","signal_date"]).shape[0]),
                         **{"top_"+k:v for k,v in tt.items()},"all_avg":aa["avg"],"all_win":aa["win"],"top_h1":h1,"top_h2":h2,
                         **checks,"PASS":all(checks.values()),"graded":mname in ("M1","M2")}
                    # robustness: easy to borrow only, core vs ext
                    e=oos[oos.easy]; row["top_avg_easy_borrow"]=stats(e[e.dec==10]["d3"])["avg"]
                    row["top_avg_core"]=stats(oos[(oos.dec==10)&(oos.core==1)]["d3"])["avg"]; row["top_avg_ext"]=stats(oos[(oos.dec==10)&(oos.core==0)]["d3"])["avg"]
                    summary.append(row)
                    for dk,dv in dec.items(): deciles.append({"model":mname,"analysis":an,"decile":dk,"avg_d3_after_cost":dv,"n":int((oos.dec==dk).sum())})
                    mean=co.drop(columns=["month","n_train"]).mean(); sdv=co.drop(columns=["month","n_train"]).std()
                    for f in mean.index: weights.append({"model":mname,"analysis":an,"input":f,"avg_weight_oos":mean[f]*100,"sd_across_refits":sdv[f]*100,"share_refits_same_sign":(np.sign(co[f])==np.sign(mean[f])).mean()*100})
                    for s in SETUPS:
                        o=oos[oos.setup==s]
                        if len(o)<30: continue
                        ts=stats(o[o.dec==10]["d3"]); as_=stats(o["d3"])
                        persetup.append({"model":mname,"analysis":an,"setup":s,"rows":len(o),"episodes":int(o.drop_duplicates(["ticker","signal_date"]).shape[0]),
                                         **{"top_"+k:v for k,v in ts.items()},"all_avg":as_["avg"],"all_win":as_["win"],"top_minus_all":ts["avg"]-as_["avg"],
                                         "note":"descriptive only" if s=="X200G" else ""})
                print(f"{key} {hz}: top10 avg {t['avg']:+.3f} win {t['win']:.1f} | all {a['avg']:+.3f} | n {t['n']}",flush=True)
    S=pd.DataFrame(summary)
    # smirk question: M2 top vs M1 top on M2's months
    smirk=[]
    for an in ("A signal day","B any day in 40"):
        m2=top_oos.get(f"M2 {an}"); m1=top_oos.get(f"M1 {an}")
        if m2 is None or m1 is None: continue
        m1c=m1[m1.date>=m2.date.min()]
        a2=stats(m2[m2.dec==10]["d3"])["avg"]; a1=stats(m1c[m1c.dec==10]["d3"])["avg"]
        p2=bool(S[(S.model=="M2")&(S.analysis==an)].PASS.iloc[0])
        smirk.append({"analysis":an,"M2_top_avg_d3":a2,"M1_top_avg_d3_same_months":a1,"difference":a2-a1,"M2_passed":p2,"smirk_adds_value":p2 and (a2-a1)>=0.20})
    # descriptive full sample per setup weights (M2 inputs where available, else M1)
    desc=[]
    for s in SETUPS:
        for mname in ("M1","M2"):
            feats,start=MODELS[mname]
            d=df[(df.setup==s)&(df.date>=start)].dropna(subset=feats+["d3"])
            for an,dd in (("A signal day",d[d.is_signal_day==1]),("B any day in 40",d)):
                if len(dd)<60: continue
                Z=(dd[feats]-dd[feats].mean())/dd[feats].std().replace(0,np.nan); Z=Z.clip(-3,3).fillna(0)
                lo,hi=dd.d3.quantile([.01,.99]); mdl=Ridge(alpha=1.0).fit(Z,dd.d3.clip(lo,hi))
                for f,c in zip(feats,mdl.coef_): desc.append({"setup":s,"model":mname,"analysis":an,"n":len(dd),"input":f,"weight_full_sample":c*100})
    # single input sorts inside setups (top third vs bottom third, d3)
    single=[]
    for f in ["V1_iv","V2_ivrank6m","V3_iv_minus_rv","V4_iv_chg5","V5_smirk","V6_smirk_chg5"]:
        for an,dd in (("A signal day",df[df.is_signal_day==1]),("B any day in 40",df)):
            d=dd.dropna(subset=[f,"d3"])
            if len(d)<90: continue
            q=d.groupby(d.date.dt.to_period("M"))[f].transform(lambda s:s.rank(pct=True))
            top=stats(d[q>=2/3]["d3"]); bot=stats(d[q<=1/3]["d3"])
            single.append({"input":f,"analysis":an,"n_top":top["n"],"top_third_avg_d3":top["avg"],"top_third_win":top["win"],"bottom_third_avg_d3":bot["avg"],"bottom_third_win":bot["win"],"spread":top["avg"]-bot["avg"]})
    for name,obj in [("summary",S),("horizons",pd.DataFrame(horizons)),("weights",pd.DataFrame(weights)),("deciles",pd.DataFrame(deciles)),
                     ("persetup",pd.DataFrame(persetup)),("smirk",pd.DataFrame(smirk)),("descweights",pd.DataFrame(desc)),("single",pd.DataFrame(single))]:
        obj.to_csv(f"vs_{name}.csv",index=False)
    pd.set_option("display.width",250); pd.set_option("display.max_columns",40)
    print(S[["model","analysis","test_from","test_to","top_n","top_avg","top_win","top_ratio","all_avg","top_h1","top_h2","PASS"]].round(3).to_string())
    print(pd.DataFrame(smirk).round(3).to_string())

if __name__=="__main__": main()
