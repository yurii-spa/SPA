import sqlite3, json, math, sys, glob
sys.path.insert(0,'/Users/yuriikulieshov/Documents/SPA_Claude')
from spa_core.trading_research import market_data as md, regime as rg, metrics as mt, research_quality as rq
S='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/trading_research'
E=sqlite3.connect(f'file:{S}/evidence.db?mode=ro',uri=True); M=sqlite3.connect(f'file:{S}/market.db?mode=ro',uri=True)
fwd=[r[0] for r in E.execute("select candidate_id from lifecycle_events where to_stage='FORWARD_PAPER'")]
print("code versions in fwd obs", list(E.execute("select code_version,count(*),datetime(min(signal_ts_ms)/1000,'unixepoch') from observations where candidate_id in (%s) group by 1 order by 3"%",".join("?"*5),fwd)))
print("ticks", E.execute("select count(*),sum(ok),sum(ok=0),datetime(min(started_ms)/1000,'unixepoch'),datetime(max(started_ms)/1000,'unixepoch') from ticks").fetchone())
ts=[r[0] for r in E.execute("select started_ms from ticks order by started_ms")]
gaps=sorted(((ts[i]-ts[i-1])/60000,ts[i-1]) for i in range(1,len(ts)))[-3:]; print("largest tick gaps min",gaps)
print("failed ticks detail", list(E.execute("select datetime(started_ms/1000,'unixepoch'),substr(detail,1,120) from ticks where ok=0 limit 5")))
b1h=md.load_1h(M,'BTCUSDT'); days=md.aggregate(b1h,'1D')
def dstats(eq_by_day):
    ks=sorted(eq_by_day); e=[1.0]+[eq_by_day[k] for k in ks]
    r=[e[i]/e[i-1]-1 for i in range(1,len(e))]; mu=sum(r)/len(r); sd=math.sqrt(sum((x-mu)**2 for x in r)/(len(r)-1))
    return dict(n=len(r),net=e[-1]-1,mdd=mt.max_drawdown(e),vol_d=sd,sharpe_ann=mu/sd*math.sqrt(365) if sd else None, sharpe_d=mu/sd if sd else None)
for c in fwd:
    rows=list(E.execute("select bar_close_time,equity from observations where candidate_id=? order by bar_open_time",(c,)))
    byday={}
    for t,e in rows: byday[(t-1)//86400000]=e   # equity at last bar close in UTC day
    print("FWD",c[:26],{k:(round(v,5) if isinstance(v,float) else v) for k,v in dstats(byday).items()}, "window",rows[0][0],rows[-1][0])
    print("   vs_hold",rq.forward_vs_hold(E,c,c.split(':')[2]))
# BTC hold same 1D window: open Oct1 -> close Nov3 + entry cost 15bps
w=[d for d in days if 1790812800000<=d.open_time<=1793664000000]
hold={ (d.open_time)//86400000: d.close/w[0].open*(1-0.0015) for d in w}
print("HOLD 1D window",w[0].open,w[-1].close,{k:(round(v,5) if isinstance(v,float) else v) for k,v in dstats(hold).items()})
# regime
idx=rg.RegimeIndex(days)
from collections import Counter
print("regime fwd days",Counter((lambda r:(r['trend'],r['vol'],r['stress']))(idx.at(d.open_time)) for d in w))
lab=idx.at(1790812800000); print("regime at start",lab, "at end", idx.at(w[-1].open_time))
st=json.load(open(f'{S}/status.json'))
print("STATUS keys",list(st.keys()))
print(json.dumps(st.get("research_quality"),ensure_ascii=False)[:2500])
print("fc",json.dumps(st.get("forward_candidates"),ensure_ascii=False)[:1500])
print("data",st.get("data"),st.get("forward_since_ms"),st.get("evidence_verified"),st.get("generated_at_ms"))
h=glob.glob('/Users/yuriikulieshov/Documents/SPA_Claude/data/trading_research/backtest_history/*.json')
r=rq.closed_window_stability(h); print("STAB",{k:r[k] for k in r if k!='changed'}, r['changed'][:3])
