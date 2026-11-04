import json,sys
sys.path.insert(0,'/Users/yuriikulieshov/Documents/SPA_Claude')
from spa_core.trading_research import market_data as md, strategies as stg, execution as ex, metrics as mt
import sqlite3
S='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/trading_research'
d=json.load(open(f'{S}/backtest.json')); m=d['manifest']
print({k:m.get(k) for k in ('generated_at_ms','code_version','data_to_ms','oos_start_ms','oos_end_ms','bars_1h','gaps_1h')})
M=sqlite3.connect(f'file:{S}/market.db?mode=ro',uri=True); b1h=md.load_1h(M,'BTCUSDT'); reg=stg.by_id()
OE=m['oos_end_ms']
for r in d['results']:
    if r['id'] in reg and r['id'].split(':')[0] in ('donchian@v1','supertrend@v1','supertrend_and_ma@v1') and r['id'].endswith(('0facf75089','8f4bfc1d5a','cb4ee7a5a5','7a05f87bf7','2be6f365aa')):
        p=r['post_registration']; print(r['id'][:26],{k:p.get(k) for k in ('bars','net_return','trades','win_rate','sharpe','max_drawdown','exposure')}, "gating trades",r['gating'].get('trades'),"oos",round(r['out_of_sample']['sharpe'],3),"is",round(r['in_sample']['sharpe'],3))
        c=reg[r['id']]; bars=md.aggregate(b1h,c.timeframe); t=c.signal(bars)
        sim=ex.simulate(bars,t,ex.EXEC_MODELS[c.exec_model],tf_ms=md.TF_MS[c.timeframe])
        idx=[i for i,b in enumerate(bars) if b.open_time>=OE]; a=idx[0]
        print("   bt position at first post-reg bar",sim.position[a-1],sim.position[a], "trades exiting post-reg:",[ (tr['entry_px'],tr['exit_px'],round(tr['ret'],4),tr['exit_time']) for tr in sim.trades if tr['exit_time']>=bars[a].open_time])
        # entry time of those trades: find
