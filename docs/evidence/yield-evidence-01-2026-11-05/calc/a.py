import sqlite3, json, math, sys, hashlib
sys.path.insert(0,'/Users/yuriikulieshov/Documents/SPA_Claude')
from spa_core.trading_research import evidence as ev, market_data as md, regime as rg, metrics as mt
S='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/trading_research'
E=sqlite3.connect(f'file:{S}/evidence.db?mode=ro',uri=True); M=sqlite3.connect(f'file:{S}/market.db?mode=ro',uri=True)
H=3600000; D=86400000
REG=E.execute("select min(registered_at_ms) from candidates").fetchone()[0]
fwd=[r[0] for r in E.execute("select candidate_id from lifecycle_events where to_stage='FORWARD_PAPER'")]
# 1. 1h completeness
ots=[r[0] for r in M.execute("select open_time from candles where symbol='BTCUSDT' and tf='1h' order by open_time")]
s=set(ots); start=(REG//H+1)*H; last=ots[-1]
exp=list(range(start,last+H,H)); miss=[t for t in exp if t not in s]
print("1h since",start,"expected",len(exp),"present",len(exp)-len(miss),"missing",len(miss),miss[:5])
allgaps=[(ots[i-1],ots[i]) for i in range(1,len(ots)) if ots[i]-ots[i-1]!=H]
print("all 1h gaps",len(allgaps),"last gap end",allgaps[-1] if allgaps else None, "missing hours total", sum((b-a)//H-1 for a,b in allgaps))
print("fetched_at range fwd", M.execute("select min(fetched_at),max(fetched_at), sum(fetched_at - (open_time+3600000) > 7200000) from candles where tf='1h' and open_time>=?",(start,)).fetchone())
b1h=md.load_1h(M,'BTCUSDT')
for tf in ('4h','1D'):
    ag=[b for b in md.aggregate(b1h,tf) if b.open_time>=REG]
    print(tf,"agg bars since reg",len(ag), ag[0].open_time if ag else None, ag[-1].open_time if ag else None)
# 2. late
for r in E.execute("select candidate_id,bar_open_time,bar_close_time,signal_ts_ms,(signal_ts_ms-bar_close_time)/60000.0 from observations where late=1 and candidate_id in (%s)"%",".join("?"*len(fwd)),fwd): print("LATE",r)
for c in fwd:
    lags=[r[0] for r in E.execute("select (signal_ts_ms-bar_close_time)/60000.0 from observations where candidate_id=?",(c,))]
    lags.sort(); print("lag min",c[:22],"median",lags[len(lags)//2],"p95",lags[int(.95*len(lags))],"max",lags[-1])
# 8. fills
for c in fwd:
    rows=list(E.execute("select bar_open_time,bar_close_time,bar_open,bar_close,position_before,fill_price,target,action,position_held,closed_trade,fill_cost,equity from observations where candidate_id=? order by bar_open_time",(c,)))
    bad=0; same=0
    for i,r in enumerate(rows):
        if r[5] is not None:
            if r[5]!=r[2]: bad+=1
            if i==0 or rows[i-1][6]!=r[8] : same+=1   # fill not explained by previous target
            # previous row target == position held now
    acts=[(i,r[7]) for i,r in enumerate(rows) if r[7]!='HOLD']
    fills=[i for i,r in enumerate(rows) if r[5] is not None]
    print("FILL",c[:24],"fill!=bar_open",bad,"fill w/o prior-bar signal",same,"signal idx",acts,"fill idx",fills)
    for r in rows:
        if r[9]: print("  trade",r[9])
        if r[5] is not None: print("  fill at",r[0],"px",r[5],"cost",round(r[10],6))
