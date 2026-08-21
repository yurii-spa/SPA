"""v0.3: trend as HARD cap/floor, not +-10% tilt.
Registered before run; evaluated on CALIBRATION first, tests reported as contaminated.
- Confirmed bear trend: weight capped at 0.35 (0.50 if capitulation & price<realized = deep value).
- Confirmed bull trend: weight floored at 0.55 unless regime is distribution/euphoria.
- Crash lockout 28d on risk-up (from v0.2). Cooldown/confirm days from v0.1.
"""
import pandas as pd, numpy as np
import backtest as v1
from backtest_v02 import run_ladder_v2
CRASH_LOCK = 28

def run_ladder_v3(sig):
    cur="neutral"; cand,cand_days=None,0; prev_regime,switch_day=None,None; lock_until=-1
    targets,regimes=[],[]
    p1a=sig["p1"].values; brp=sig["below_rp"].values; tr7=sig["ret7"].values
    trend=sig["trend"].values; m2u=sig["m2_up"].values
    for i in range(len(sig)):
        raw=v1.raw_regime(p1a[i],brp[i])
        crash_now=not np.isnan(tr7[i]) and tr7[i]<v1.CRASH_7D
        crash_prev=i>0 and not np.isnan(tr7[i-1]) and tr7[i-1]<v1.CRASH_7D
        if crash_now and not crash_prev: lock_until=i+CRASH_LOCK
        if raw!=cur:
            risk_up=v1.BASE_W[raw]>v1.BASE_W[cur]
            blocked=(raw==prev_regime and switch_day is not None and (i-switch_day)<v1.COOLDOWN)
            if risk_up and i<lock_until: blocked=True
            if not blocked:
                if raw==cand: cand_days+=1
                else: cand,cand_days=raw,1
                need=v1.CONFIRM_RISK_UP if risk_up else v1.CONFIRM_RISK_DN
                if cand_days>=need:
                    prev_regime,switch_day=cur,i; cur=raw; cand,cand_days=None,0
            else: cand,cand_days=None,0
        else: cand,cand_days=None,0
        w=v1.BASE_W[cur]+(0.05 if m2u[i] else -0.05)
        if trend[i]<0:  # confirmed bear
            cap=0.50 if (cur=="capitulation" and brp[i]) else 0.35
            w=min(w,cap)
        elif trend[i]>0:  # confirmed bull
            if cur not in ("distribution","euphoria"): w=max(w,0.55)
        targets.append(min(0.90,max(0.10,w))); regimes.append(cur)
    return pd.Series(targets,index=sig.index), pd.Series(regimes,index=sig.index)

if __name__=="__main__":
    df=pd.read_csv("btc_dataset.csv",parse_dates=["date"],index_col="date")
    m2=pd.read_csv("m2.csv",parse_dates=["date"],index_col="date")
    sig=v1.build_signals(df,m2)
    t1,_=v1.run_ladder(sig); t3,reg3=run_ladder_v3(sig)
    price=df["price"]
    print("=== CALIBRATION ONLY FIRST ===")
    for lbl,t in [("v0.1",t1),("v0.3",t3)]:
        n,tr=v1.simulate(price,t,"2015-01-01","2019-12-31")
        print(lbl, v1.metrics(n,tr))
    px=price.loc["2015-01-01":"2019-12-31"]
    print("50/50q", v1.metrics(v1.bench_5050_q(price,"2015-01-01","2019-12-31")))
    ans=input if False else None
    print("\n=== TESTS (contaminated, informational) ===")
    for s,e,l in [("2020-01-01","2022-12-31","TEST-1"),("2023-01-01","2026-08-20","TEST-2"),
                  ("2015-01-01","2026-08-20","FULL")]:
        n1,_=v1.simulate(price,t1,s,e); n3,tr=v1.simulate(price,t3,s,e)
        pxw=price.loc[s:e]
        print(f"\n{l} {s}->{e}")
        print(" v0.1  ",v1.metrics(n1)); print(" v0.3  ",v1.metrics(n3,tr))
        print(" 50/50q",v1.metrics(v1.bench_5050_q(price,s,e)))
        print(" HODL  ",v1.metrics(pxw/pxw.iloc[0]))
        bdd=(pxw/pxw.cummax()-1).min(); mdd=(n3/n3.cummax()-1).min()
        print(f" bear-criterion: {round(mdd/bdd*100)}% of BTC DD (<=45% pass)")
    for s,e,l in [("2018-01-01","2018-12-31","BEAR 2018"),("2022-01-01","2022-12-31","BEAR 2022"),
                  ("2025-10-01","2026-08-20","BEAR 25-26")]:
        n3,_=v1.simulate(price,t3,s,e); pxw=price.loc[s:e]
        print(f"{l}: v0.3 {round((n3.iloc[-1]-1)*100,1)}% | BTC {round((pxw.iloc[-1]/pxw.iloc[0]-1)*100,1)}%")
    pd.DataFrame({"target":t3,"regime":reg3}).to_csv("ladder_state_v03.csv")
    print("\nCurrent v0.3:",reg3.iloc[-1],"| target:",round(t3.iloc[-1]*100),"% BTC")
