"""Part A: extremes across all stocks."""
import numpy as np, pandas as pd
from stage1_screen import nw_t
COST=0.001
df=pd.read_parquet("ext_rows.parquet")
df=df[(df.close>=10)&(df.dollar_vol_med20>=20e6)&(df.opt_vol_med21>=1000)&df.xs3.notna()].copy()
H={"d1":"xs1","d3":"xs3","d5":"xs5","wk2":"xs10"}
# declared direction of the predicted effect for each (measure, side): +1 extreme beats middle, -1 trails
DECL={("M1_call_surge","top"):+1,("M2_put_surge","top"):-1,("M3_net_prem","top"):+1,("M3_net_prem","bottom"):-1,("M4_vega","top"):+1,("M5_delta","top"):+1,
      ("M1_call_surge","bottom"):0,("M2_put_surge","bottom"):0,("M4_vega","bottom"):0,("M5_delta","bottom"):0}
def run(d,feat,cut,split=None):
    d=d.dropna(subset=[feat]).copy()
    cnt=d.groupby("date")[feat].transform("size"); d=d[cnt>=100]
    r=d.groupby("date")[feat].rank(method="first",pct=True)
    d["grp"]=np.where(r>1-cut,"top",np.where(r<=cut,"bottom","middle"))
    rows=[]
    for side in ("top","bottom"):
        ext=d[d.grp==side]; mid=d[d.grp=="middle"]
        if split is not None:
            ext=ext[ext[split[0]]==split[1]]; mid=mid[mid[split[0]]==split[1]]
        if len(ext)<30: continue
        row={"measure":feat,"side":side,"cut":f"{cut*100:g}%","split":"all" if split is None else f"{split[0]}={split[1]:g}","n_ext":len(ext),"tickers_ext":ext.ticker.nunique(),"days":ext.date.nunique()}
        for h,c in H.items():
            e=ext.groupby("date")[c].mean(); m=mid.groupby("date")[c].mean(); diff=(e-m).dropna()
            row[f"{h}_ext_avg"]=(ext[c]-COST).mean()*100; row[f"{h}_mid_avg"]=(mid[c]-COST).mean()*100
            row[f"{h}_diff"]=diff.mean()*100; row[f"{h}_ext_win"]=((ext[c]-COST)>0).mean()*100; row[f"{h}_ext_med"]=(ext[c]-COST).median()*100
            if h=="d3":
                t,n=nw_t(diff.values,3); row["d3_t"]=t
                dates=diff.index; midd=dates[len(dates)//2]
                row["d3_diff_h1"]=diff[dates<midd].mean()*100; row["d3_diff_h2"]=diff[dates>=midd].mean()*100
        decl=DECL.get((feat,side),0)
        if decl and split is None and cut==0.01:
            ok=(decl*row["d3_diff"]>=0.40) and (np.sign(row["d3_diff_h1"])==np.sign(row["d3_diff_h2"])==decl) and abs(row["d3_t"])>=2.5 and row["days"]>=40 and row["n_ext"]>=150
            row["declared_sign"]="beats" if decl>0 else "trails"; row["PASS"]=bool(ok)
        else:
            row["declared_sign"]="(not graded)"; row["PASS"]=None
        rows.append(row)
    return rows
res=[]
for feat in ["M1_call_surge","M2_put_surge","M3_net_prem","M4_vega","M5_delta"]:
    for cut in (0.01,0.02,0.005): res+=run(df,feat,cut)
    res+=run(df,feat,0.01,("quiet",1.0)); res+=run(df,feat,0.01,("in_setup",1.0)); res+=run(df,feat,0.01,("in_setup",0.0))
R=pd.DataFrame(res); R.to_csv("extA_results.csv",index=False)
pd.set_option("display.width",260); pd.set_option("display.max_columns",40)
print(R[R.split=="all"][["measure","side","cut","n_ext","days","d3_ext_avg","d3_mid_avg","d3_diff","d3_t","d3_diff_h1","d3_diff_h2","wk2_diff","declared_sign","PASS"]].round(3).to_string())
print(R[R.split!="all"][["measure","side","split","n_ext","d3_ext_avg","d3_diff","d3_t","wk2_diff"]].round(3).to_string())
