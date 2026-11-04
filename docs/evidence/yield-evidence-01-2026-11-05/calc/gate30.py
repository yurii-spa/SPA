import json, sys, datetime as dt, statistics as st
SNAP='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/'
def D(s): return dt.date.fromisoformat(s[:10])
out={}
for book,f in (('balanced','hy_paper_trading.json'),('aggressive','lp_paper_trading.json')):
    d=json.load(open(SNAP+f)); H=d['daily_history']; exp=[e for e in d['experiments'] if e.get('status')!='closed'][-1]
    eid=exp['experiment_id']; v2=[r for r in H if r.get('experiment_id')==eid]
    prev=[r for r in H if D(r['date'])<D(v2[0]['date'])]
    start_nav=prev[-1]['equity'] if prev else d['seed_equity']
    dates=[D(r['date']) for r in v2]; first,last=dates[0],dates[-1]
    cal=(last-first).days+1; allday={first+dt.timedelta(i) for i in range(cal)}; missing=sorted(allday-set(dates))
    dup=len(dates)-len(set(dates))
    nav_end=v2[-1]['equity']
    gross=sum((r.get('daily_yield_usd') or 0) for r in v2); cost=sum((r.get('cost_usd') or 0) for r in v2)
    mtm=sum((r.get('mtm_pnl_usd') or 0) for r in v2); net=sum((r.get('net_pnl_usd') or 0) for r in v2)
    fc_mark=sum((r.get('fixed_carry_mark_pnl_usd') or 0) for r in v2); fc_cost=sum((r.get('fixed_carry_trade_cost_usd') or 0) for r in v2)
    peak=start_nav; mdd=0; mdd_day=None
    for r in v2:
        peak=max(peak,r['equity']); ddv=r['equity']/peak-1
        if ddv<mdd: mdd, mdd_day=ddv, r['date']
    ret=nav_end/start_nav-1; n_int=(last-first).days+1
    ann=(1+ret)**(365/n_int)-1
    apys=[r['apy_pct'] for r in v2 if r.get('apy_pct') is not None]
    first30=[r for r in v2 if (D(r['date'])-first).days<30]; nav30=first30[-1]['equity']; ret30=nav30/start_nav-1
    dep=[(r.get('deployed_usd') or 0)/r['equity'] for r in v2 if r.get('equity')]
    mtmcov=[r.get('mtm_coverage_pct') for r in v2]
    chg=[(r['date'],r.get('opened'),r.get('closed')) for r in v2 if r.get('opened') or r.get('closed')]
    o={'experiment':eid,'start_date':str(first),'last_date':str(last),'calendar_days':cal,'observed_rows':len(v2),'missing_dates':[str(x) for x in missing],'duplicate_rows':dup,
       'start_nav':round(start_nav,2),'nav_day30':round(nav30,2),'return_30d_pct':round(ret30*100,4),'nav_end':round(nav_end,2),'return_period_pct':round(ret*100,4),'annualized_ACT365_pct':round(ann*100,3),
       'sum_daily_yield_usd':round(gross,2),'sum_costs_usd':round(cost,2),'sum_mtm_usd':round(mtm,2),'sum_net_pnl_usd':round(net,2),'nav_delta_usd':round(nav_end-start_nav,2),
       'fixed_carry_mark_usd':round(fc_mark,2),'fixed_carry_trade_cost_usd':round(fc_cost,2),
       'mdd_pct':round(mdd*100,4),'mdd_day':mdd_day,'apy_observed_mean_pct':round(st.mean(apys),3) if apys else None,'apy_observed_min_max':[min(apys),max(apys)] if apys else None,
       'deployed_share_mean_pct':round(st.mean(dep)*100,2) if dep else None,'deployed_share_min_pct':round(min(dep)*100,2) if dep else None,
       'mtm_coverage_values':sorted(set(map(str,mtmcov))),'composition_changes':chg[:10],'n_changes':len(chg),
       'accrual_basis':sorted(set(str(r.get('accrual_basis')) for r in v2)),'economics_model':sorted(set(str(r.get('economics_model')) for r in v2))}
    if book=='aggressive':
        hf=[r.get('loop_hf') for r in v2 if r.get('loop_hf') is not None]; ltv=[r.get('loop_ltv') for r in v2 if r.get('loop_ltv') is not None]
        o.update(loop_hf_min=min(hf) if hf else None, loop_hf_last=hf[-1] if hf else None, loop_ltv_max=max(ltv) if ltv else None,
                 loop_measured=sorted(set(str(r.get('loop_measured')) for r in v2)), loop_status=sorted(set(str(r.get('loop_status')) for r in v2)),
                 loop_economics_last=v2[-1].get('loop_economics'), loop_cfg={k:d['loop'].get(k) for k in list(d['loop'])[:25]} if isinstance(d.get('loop'),dict) else None)
    else:
        o.update(fixed_carry=d.get('fixed_carry'))
    o['positions_now']=d['positions']; o['stop_reference']=d.get('stop_reference')
    out[book]=o
json.dump(out,open('/private/tmp/claude-501/yield_p1/gate30.json','w'),ensure_ascii=False,indent=1,default=str)
for b,o in out.items():
    print('==',b); [print(' ',k,':',json.dumps(o[k],ensure_ascii=False,default=str)[:260]) for k in o if k not in ('positions_now','loop_cfg','fixed_carry','loop_economics_last')]
