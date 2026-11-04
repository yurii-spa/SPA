"""Свежесть и пропуски наблюдений рынка петли (копия журнала, только чтение)."""
import json, datetime as dt, collections
P='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/paper_observations_aggressive.jsonl'
rows=[json.loads(l) for l in open(P) if l.strip()]
rows=[r for r in rows if (r.get('experiment_id') or (r.get('observation') or {}).get('experiment_id'))]
def g(r,*k):
    o=r.get('observation',r)
    for x in k: o=(o or {}).get(x)
    return o
ts=[dt.datetime.fromisoformat(r['run_ts'][:19]) for r in rows]
print('runs',len(rows),'from',ts[0],'to',ts[-1])
ok=[g(r,'data','morpho_ok') for r in rows]; print('morpho_ok true',sum(1 for x in ok if x),'false',sum(1 for x in ok if x is False))
gaps=[(ts[i]-ts[i-1]).total_seconds()/3600 for i in range(1,len(ts))]
print('interval h: median %.2f max %.2f; gaps >2h: %d'%(sorted(gaps)[len(gaps)//2],max(gaps),sum(1 for x in gaps if x>2)))
miss=collections.Counter()
for r in rows:
    for m in (g(r,'data','missing') or []): miss[m.split(':')[0][:60]]+=1
print('missing reasons', miss.most_common(6))
iu=[g(r,'data','implied_usde') for r in rows if g(r,'data','implied_usde') is not None]
print('implied USDe/PYUSD: n=%d min %.6f max %.6f last %.6f'%(len(iu),min(iu),max(iu),iu[-1]))
acts=collections.Counter(str(g(r,'supervision_action'))[:40] for r in rows); print('actions',acts.most_common(5))
# longest consecutive unmeasured streak
s=b=0
for x in ok:
    s = s+1 if x is False else 0; b=max(b,s)
print('longest unmeasured streak (runs):',b)
print('keys sample', list(rows[-1].keys())[:10])
