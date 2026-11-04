import json
D='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/'
cp=json.load(open(D+'current_positions.json')); hy=json.load(open(D+'hy_paper_trading.json')); lp=json.load(open(D+'lp_paper_trading.json'))
C=dict(cp['positions']); C['cash']=cp['cash_usd']; navC=cp['current_equity_usd']
B={p['protocol']:p['notional_usd'] for p in hy['positions']}; B['pendle_pt_susds']=hy['daily_history'][-1]['fixed_carry_value_usd']; navB=hy['equity']
A={p['protocol']:p['notional_usd'] for p in lp['positions']}; lv=lp['loop']['last_valuation']; A['loop_equity']=lv['equity']; navA=lp['equity']
print('sumB',sum(B.values()),navB,'sumA',sum(A.values()),navA)
def pc(x,n): return f"{x:,.0f} ({x/n*100:.2f}%)"
books={'C':(C,navC),'B':(B,navB),'A':(A,navA)}
groups={'maple':['maple'],'fluid':['fluid_fusdc'],'morpho':['morpho_blue_base','morpho_steakhouse','loop_equity'],'ethena':['susde','loop_equity'],'compound':['compound_v3'],'aave':['aave_v3'],'pendle/sky':['pendle_pt_susds'],'base_chain':['morpho_blue_base'],'maple+fluid':['maple','fluid_fusdc'],'ethena+morpho':['susde','morpho_steakhouse','morpho_blue_base','loop_equity']}
tot=navA+navB+navC; print('tot',tot)
for g,ks in groups.items():
  row=[];s=0
  for b,(P,n) in books.items():
    x=sum(P.get(k,0) for k in ks); s+=x; row.append(f"{b}:{pc(x,n)}")
  print(g,row,'ALL',pc(s,tot))
usdc={'C':navC,'B':sum(B[k] for k in ['maple','fluid_fusdc','morpho_steakhouse']),'A':A['maple']+A['fluid_fusdc']}
for b,x in usdc.items():
  n=books[b][1]; print('USDC',b,pc(x,n),'-1%',pc(x*.01,n),'-5%',pc(x*.05,n))
coll,debt=lv['collateral_value'],lv['debt_value']; print('loop coll',coll,'debt',debt,'gross USDe %A',coll/navA)
for m in [.05,.30]:
  b=B['susde']*m; print('USDe B',m,pc(b,navB))
  c2=coll*(1-m); hf=c2*0.915/debt; eq=max(0,c2-debt)
  loss=lv['equity']-eq
  print(' A jump',m,'hf',round(hf,4),'loss',pc(loss,navA), 'with stress unwind slip', pc(loss+c2*0.0015+12 if hf>1 else lv['equity'],navA))
# gradual: unwind at oracle 0.97 (−3%)
g=coll*0.03+coll*0.97*0.0015+12; print('A gradual unwind at 0.97',pc(g,navA))
# carry
h=lp['loop']['share_price_history']; y=((h[-1][1]/h[0][1])**(365/33)-1)*100
b0=((debt/lp['loop']['entry']['debt_usd'])**(365/33.92)-1)*100
lev=coll/lv['equity']; print('y',y,'b',b0,'lev',lev)
for dpp in [0,5,15]:
  b=b0+dpp; carry=y*lev-b*(lev-1); extra_day=debt*dpp/100/365
  d30=debt*(1+b/100)**(30/365); c30=coll*(1+y/100)**(30/365); hf30=c30*0.915/d30
  exit_cost=3*extra_day+coll*0.0005+12
  print(f"+{dpp}pp carry {carry:.2f}% loopEq; extra/day ${extra_day:.1f}; 30d extra {pc(extra_day*30,navA)}; hf30 {hf30:.4f}; 3d-exit cost {pc(exit_cost,navA)}")
print('hf now',lv['hf'],'oracle drop to liq',1-1/lv['hf'])
fc=hy['fixed_carry']['legs'][0]; print('PT units',fc['units'],'mark',fc['mark'],'pull to par',fc['units']-B['pendle_pt_susds'])
for b,(P,n) in books.items(): print(b,{k:round(v/n*100,2) for k,v in P.items()})
