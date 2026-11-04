"""YIELD-EVIDENCE-02 · стресс петли Aggressive по формулам spa_core/paper_trading/loop_book.py (модель, не наблюдение).
Вход — последняя ИЗМЕРЕННАЯ оценка петли из снимка (loop.last_valuation, 2026-11-04T23:02:55Z)."""
import json
S='/Users/yuriikulieshov/Documents/SPA_worktrees/yield_snapshot_2026-11-05/data/lp_paper_trading.json'
d=json.load(open(S)); L=d['loop']; v=L['last_valuation']; NAV=d['equity']
# константы — дословно из loop_book.py
LLTV=0.915; SWAP_COST=0.0005; STRESS_MULT=3.0; GAS=12.0; EMERGENCY_HF=1.08; FLOOR=0.97; NEG_DAYS=3
LIF=min(1.15, 1/(1-0.3*(1-LLTV)))
coll,debt,eq=v['collateral_value'],v['debt_value'],v['equity']; implied0=0.999573   # последнее измеренное USDe/PYUSD (журнал наблюдений)
y=0.0494; b=0.04244    # реализованные: рост цены доли sUSDe 02.10→04.11; рост долга 33,9 дн.
def hf(c,dbt): return c*LLTV/dbt
def unwind(c,dbt,stress): s=SWAP_COST*(STRESS_MULT if stress else 1); g=c*(1-s); return max(0.0,g-dbt-2*GAS), g<dbt
def liquidate(c,dbt):
    seized=min(c, dbt*LIF); bad=max(0.0,dbt-seized/LIF); rest=c-seized; cash=max(0.0,rest*(1-SWAP_COST*STRESS_MULT)-GAS); return cash,bad
out=[]
def row(name,cash,extra=''):
    loss=eq-cash; out.append((name,round(loss,2),round(loss/NAV*100,2),extra))
for shock in (0.05,0.30):
    c=coll*(1-shock); h=hf(c,debt); impl=implied0*(1-shock)
    if h<=1.0: cash,bad=liquidate(c,debt); row(f'USDe −{int(shock*100)}% скачком',cash,f'HF {h:.3f} ≤ 1 ⇒ ликвидация; LIF {LIF:.5f}; плохой долг кредиторам {bad:,.0f}$')
    elif h<EMERGENCY_HF or impl<FLOOR: cash,_=unwind(c,debt,True); row(f'USDe −{int(shock*100)}% скачком',cash,f'HF {h:.3f}; оценка USDe {impl:.4f} < {FLOOR} ⇒ аварийный выход, проскальзывание {SWAP_COST*STRESS_MULT:.2%}')
# плавное падение: выход срабатывает на пороге 0,97 (если прогон измерен)
c=coll*(FLOOR/implied0); cash,_=unwind(c,debt,True); row('USDe плавно до порога 0,97',cash,'аварийный выход на пороге; предполагает измеренный прогон (самая длинная серия без замера — 11 ч)')
# ставка PYUSD +5 пп
b2=b+0.05; carry=(coll*y-debt*b2)/eq; daily=(coll*y-debt*b2)/365
cash,_=unwind(coll+daily*NEG_DAYS*0,debt,False); loss_exit=(eq-cash)+(-daily)*NEG_DAYS
out.append(('ставка PYUSD +5 пп',round(loss_exit,2),round(loss_exit/NAV*100,2),f'carry на капитал {carry*100:.2f}%/год ({daily:.2f}$/день); после {NEG_DAYS} дн. отрицательного carry — выход по обычному проскальзыванию'))
# пег PYUSD — модель принимает $1; арифметика чувствительности (вне модели)
for p in (0.01,0.03):
    out.append((f'PYUSD +{int(p*100)}% к $ (вне модели)',round(debt*p,2),round(debt*p/NAV*100,2),'модель считает PYUSD = $1; это арифметика чувствительности долга, не вывод модели'))
print(json.dumps({'input':{'at':v['at'],'collateral':coll,'debt':debt,'loop_equity':eq,'book_nav':NAV,'hf':round(hf(coll,debt),4),'LIF':LIF,'implied_usde':implied0,'collateral_yield':y,'borrow':b},
                  'rows':out},ensure_ascii=False,indent=1))
