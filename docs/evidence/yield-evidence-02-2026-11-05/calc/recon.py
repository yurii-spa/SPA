"""YIELD-EVIDENCE-02 · сверка NAV↔P&L Aggressive на снимке (только чтение)."""
import json, sys
SNAP='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/lp_paper_trading.json'
d=json.load(open(SNAP)); H=d['daily_history']
EID='aggressive-susde-loop-v1@2026-10-02'
idx=[i for i,h in enumerate(H) if h.get('experiment_id')==EID]
prev=H[idx[0]-1]
rows=[]; tot={'d_equity':0,'net_pnl':0,'dy':0,'cost':0,'mtm':0,'d_floating_unexplained':0,'d_loop':0}
pf, pl, pe = prev['equity'], 0.0, prev['equity']   # до входа вся книга — плавающая
for i in idx:
    h=H[i]; f=h['floating_equity_usd']; l=h['loop_equity_usd'] or 0.0; e=h['equity']
    de=e-pe; dfl=f-pf; dlo=l-pl; npl=h['net_pnl_usd']
    transfer=dfl-npl            # изменение плавающей части, НЕ объяснённое её P&L = перевод в/из петли
    rows.append(dict(date=h['date'],equity=e,floating=f,loop=l,d_equity=round(de,2),net_pnl=round(npl,4),
                     d_floating=round(dfl,2),transfer_floating=round(transfer,2),d_loop=round(dlo,2),
                     check=round(de-(npl+transfer+dlo),4),loop_measured=h.get('loop_measured'),
                     rounding=round(e-(f+l),4)))
    for k,v in (('d_equity',de),('net_pnl',npl),('dy',h['daily_yield_usd']),('cost',h['cost_usd']),('mtm',h['mtm_pnl_usd']),('d_loop',dlo)): tot[k]+=v
    pf,pl,pe=f,l,e
tr=sum(r['transfer_floating'] for r in rows)
out={'source':SNAP,'experiment':EID,'start':{'date':prev['date'],'equity':prev['equity']},'end':{'date':rows[-1]['date'],'equity':rows[-1]['equity']},
     'totals':{k:round(v,2) for k,v in tot.items()},'sum_transfer_floating':round(tr,2),
     'identity':'Δequity = Σnet_pnl(floating) + Σtransfer(floating↔loop) + Σ(Δloop)',
     'identity_residual':round(tot['d_equity']-(tot['net_pnl']+tr+tot['d_loop']),4),
     'rows':rows,'loop_keys':sorted(d['loop'].keys())}
json.dump(out,open('/private/tmp/claude-501/yield_e2/recon.json','w'),ensure_ascii=False,indent=1)
print(json.dumps({k:out[k] for k in ('start','end','totals','sum_transfer_floating','identity_residual')},ensure_ascii=False))
for r in rows[:3]+rows[-2:]: print(r)
nz=[r for r in rows if abs(r['transfer_floating'])>0.01]; print('days with transfers:',[(r['date'],r['transfer_floating']) for r in nz])
print('rounding max', max(abs(r['rounding']) for r in rows)); print('loop keys', out['loop_keys'])

# ── петля: разложение результата после входа ──
L=d['loop']; en=L['entry']; lv=L['last_valuation']
units=float(L['collateral_units']); p0=float(en['price']); coll0=en['collateral_value_usd']; debt0=en['debt_usd']
p1=lv['collateral_value']/units
sp=dict((a,b) for a,b in L['share_price_history']); sp0=sp['2026-10-02']; sp1=sp[sorted(sp)[-1]]
row_end=[r for r in rows if r['date']=='2026-11-04'][0]
print('\nLOOP: units',round(units,4),'oracle price sUSDe/PYUSD',round(p0,6),'->',round(p1,6),'(%+.4f%%)'%((p1/p0-1)*100))
print('      sUSDe share price (USDe/share)',round(sp0,6),'->',round(sp1,6),'(%+.4f%%)'%((sp1/sp0-1)*100), 'dates', '2026-10-02 ->', sorted(sp)[-1])
print('      implied USDe in PYUSD: entry %.6f  last %.6f'%(p0/sp0, p1/sp1))
print('      collateral %.2f -> %.2f (%+.2f) | debt %.2f -> %.2f (%+.2f) | equity %.2f -> %.2f (%+.2f)'%(coll0,lv['collateral_value'],lv['collateral_value']-coll0,debt0,lv['debt_value'],lv['debt_value']-debt0,en['equity_in_usd'],lv['equity'],lv['equity']-en['equity_in_usd']))
yield_part=units*p0*(sp1/sp0-1); oracle_part=lv['collateral_value']-coll0-yield_part
print('      collateral growth split: sUSDe accrual %.2f · USDe/PYUSD oracle deviation %.2f'%(yield_part,oracle_part))
days=(__import__('datetime').datetime.fromisoformat(lv['at'][:19])-__import__('datetime').datetime.fromisoformat(en['at'][:19])).total_seconds()/86400
print('      debt growth %.2f over %.2f d = %.3f%% annual (entry borrow APY %.3f%%)'%(lv['debt_value']-debt0,days,((lv['debt_value']/debt0)**(365/days)-1)*100,en['borrow_apy_pct']))
print('      header equity %.2f = floating %.2f + loop(last_valuation %s) %.2f ; daily row 11-04 loop %.2f'%(d['equity'],row_end['floating'],lv['at'],lv['equity'],row_end['loop']))
r30=[r for r in rows if r['date']=='2026-10-31'][0]
print('\n30d (01.10→31.10): equity %.2f→%.2f = %+.2f ; floating %.2f loop %.2f'%(100260.76,r30['equity'],r30['equity']-100260.76,r30['floating'],r30['loop']))
