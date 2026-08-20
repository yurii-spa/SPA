"""v0.2: trend-gate on risk-up moves + crash lockout.
Registered changes (results-v01 doc, BEFORE this run):
1. Allocations above 50% BTC require weekly trend confirmation (close > 20W SMA).
   While cheap-but-falling: capped at 50%.
2. Crash override replaced: after 7d return < -20%, risk-up moves are BLOCKED for 28 days
   (no forced step-down).
3. New bear criterion: model MaxDD <= 45% of BTC MaxDD in same window.
All other rules/params identical to v0.1. Calibration window only for any tuning.
"""
import pandas as pd, numpy as np
import backtest as v1  # reuse signals, simulate, benchmarks, metrics

CRASH_LOCK = 28

def run_ladder_v2(sig):
    cur = "neutral"; cand, cand_days = None, 0
    prev_regime, switch_day = None, None
    lock_until = -1
    targets, regimes = [], []
    p1a = sig["p1"].values; brp = sig["below_rp"].values
    tr7 = sig["ret7"].values; trend = sig["trend"].values; m2u = sig["m2_up"].values
    # weekly trend-gate: price above 20W SMA (recomputed here, past-only, same as v1 wk data)
    px = sig["price"]
    wk = px.resample("W-SUN").last()
    above20 = (wk.shift(1) > wk.rolling(20).mean().shift(1)).reindex(px.index, method="ffill").fillna(False).values
    for i in range(len(sig)):
        raw = v1.raw_regime(p1a[i], brp[i])
        crash_now = not np.isnan(tr7[i]) and tr7[i] < v1.CRASH_7D
        crash_prev = i > 0 and not np.isnan(tr7[i-1]) and tr7[i-1] < v1.CRASH_7D
        if crash_now and not crash_prev:
            lock_until = i + CRASH_LOCK
        if raw != cur:
            risk_up = v1.BASE_W[raw] > v1.BASE_W[cur]
            blocked = (raw == prev_regime and switch_day is not None
                       and (i - switch_day) < v1.COOLDOWN)
            if risk_up and i < lock_until:
                blocked = True
            if not blocked:
                if raw == cand: cand_days += 1
                else: cand, cand_days = raw, 1
                need = v1.CONFIRM_RISK_UP if risk_up else v1.CONFIRM_RISK_DN
                if cand_days >= need:
                    prev_regime, switch_day = cur, i
                    cur = raw; cand, cand_days = None, 0
            else:
                cand, cand_days = None, 0
        else:
            cand, cand_days = None, 0
        w = v1.BASE_W[cur] + 0.10*trend[i] + (0.05 if m2u[i] else -0.05)
        # TREND GATE: cheap-but-falling capped at 50%
        if w > 0.50 and not above20[i]:
            w = 0.50
        targets.append(min(0.90, max(0.10, w)))
        regimes.append(cur)
    return pd.Series(targets, index=sig.index), pd.Series(regimes, index=sig.index)

def compare(df, t1, t2, start, end, label):
    price = df["price"]
    n1,_ = v1.simulate(price, t1, start, end)
    n2,tr = v1.simulate(price, t2, start, end)
    px = price.loc[start:end]
    res = {"v0.1": v1.metrics(n1), "v0.2": v1.metrics(n2, tr),
           "50/50 quarterly": v1.metrics(v1.bench_5050_q(price, start, end)),
           "HODL BTC": v1.metrics(px/px.iloc[0])}
    print(f"\n=== {label}: {start} -> {end} ===")
    print(pd.DataFrame(res).T.to_string())
    btc_dd = (px/px.cummax()-1).min()
    m_dd = (n2/n2.cummax()-1).min()
    print(f"bear criterion: model DD = {round(m_dd/btc_dd*100)}% of BTC DD (pass if <=45%)")

if __name__ == "__main__":
    df = pd.read_csv("btc_dataset.csv", parse_dates=["date"], index_col="date")
    m2 = pd.read_csv("m2.csv", parse_dates=["date"], index_col="date")
    sig = v1.build_signals(df, m2)
    t1,_ = v1.run_ladder(sig)
    t2, reg2 = run_ladder_v2(sig)
    pd.DataFrame({"target": t2, "regime": reg2}).to_csv("ladder_state_v02.csv")
    compare(df, t1, t2, "2015-01-01","2019-12-31","CALIBRATION 2015-2019")
    compare(df, t1, t2, "2020-01-01","2022-12-31","TEST-1 2020-2022")
    compare(df, t1, t2, "2023-01-01","2026-08-20","TEST-2 2023-2026")
    compare(df, t1, t2, "2015-01-01","2026-08-20","FULL 2015-2026")
    for s,e,l in [("2018-01-01","2018-12-31","BEAR 2018"),
                  ("2022-01-01","2022-12-31","BEAR 2022"),
                  ("2025-10-01","2026-08-20","BEAR 2025-26")]:
        n2,_ = v1.simulate(df["price"], t2, s, e)
        px = df["price"].loc[s:e]
        print(f"{l}: v0.2 {round((n2.iloc[-1]-1)*100,1)}% | BTC {round((px.iloc[-1]/px.iloc[0]-1)*100,1)}%")
    print("\nCurrent v0.2 state:", reg2.iloc[-1], "| target:", round(t2.iloc[-1]*100), "% BTC")
