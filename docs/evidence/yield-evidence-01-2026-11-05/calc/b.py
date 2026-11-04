import sqlite3, json, math, sys
sys.path.insert(0,'/Users/yuriikulieshov/Documents/SPA_Claude')
from spa_core.trading_research import evidence as ev, market_data as md, regime as rg, metrics as mt, strategies as stg, backtest as bt
S='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/trading_research'
E=sqlite3.connect(f'file:{S}/evidence.db?mode=ro',uri=True); M=sqlite3.connect(f'file:{S}/market.db?mode=ro',uri=True)
fwd=[r[0] for r in E.execute("select candidate_id from lifecycle_events where to_stage='FORWARD_PAPER'")]
reg=stg.by_id(); print("current code_version",bt.code_version())
b1h=md.load_1h(M,'BTCUSDT')
REG=E.execute("select min(registered_at_ms) from candidates").fetchone()[0]
for c in fwd:
    dh,df=E.execute("select def_hash,definition from candidates where candidate_id=?",(c,)).fetchone()
    k=reg.get(c); print("DEF",c[:26],"in registry",k is not None,"hash match",k and k.def_hash==dh, "def", df)
    bars=md.aggregate(b1h,k.timeframe); full=k.signal(bars)
    idx=[i for i,b in enumerate(bars) if b.open_time>=REG-40*86400000]
    bad=sum(1 for i in idx if k.signal(bars[:i+1])[i]!=full[i])
    # stored targets vs recomputed
    st={r[0]:r[1] for r in E.execute("select bar_open_time,target from observations where candidate_id=?",(c,))}
    mism=sum(1 for i,b in enumerate(bars) if b.open_time in st and st[b.open_time]!=max(0,full[i]))
    print("   causality violations (truncated vs full)",bad,"of",len(idx),"; stored target != recompute",mism,"of",len(st))
print(ev.verify(E))
