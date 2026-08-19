"""
RS-volatile-clmm — расчётная часть (pure stdlib, детерминированно, seed фиксирован).

Шаг 1: валидация конц-ликвидности (Uniswap v3/v4 математика) на числах скриншота
Revert (ETH/USDG 0.05%, диапазон 1722.15–2112.48, цена 1922.26).
Шаг 2: divergence loss при движении к границам.
Шаг 3: Monte-Carlo GBM — время в диапазоне, частота ре-рейнджей, IL-драг.
Шаг 4: net-APY таблица по сценариям fee APR x волатильность.
Шаг 5: delta-neutral вариант (минус funding).
"""
import math
import random

# ── Скриншот (Revert, 2026-07-30) ────────────────────────────────────────────
P0   = 1922.26          # текущая цена ETH/USDG
PA   = 1722.15223       # нижняя граница
PB   = 2112.48418       # верхняя граница
ETH0 = 2.32680575       # ETH в позиции
USD0 = 5190.53617       # USDG в позиции
POS0 = 9663.27          # стоимость позиции $
FEE_APR_SHOWN = 0.7894  # заявленный fee APR
DL_SHOWN = 29.98        # divergence loss на скриншоте
INVESTED = 9663.64      # invested (2.42612148 ETH @входе + 5000 USDG)

sqrt = math.sqrt

def liquidity_from_amounts(P, pa, pb, x, y):
    """L из количеств x (ETH) и y (USD) при цене P внутри [pa,pb]."""
    Lx = x / (1/sqrt(P) - 1/sqrt(pb))
    Ly = y / (sqrt(P) - sqrt(pa))
    return Lx, Ly

def amounts(L, P, pa, pb):
    """Количества (x,y) позиции с ликвидностью L при цене P (клип к границам)."""
    Pc = min(max(P, pa), pb)
    x = L * (1/sqrt(Pc) - 1/sqrt(pb))
    y = L * (sqrt(Pc) - sqrt(pa))
    return x, y

def value(L, P, pa, pb):
    x, y = amounts(L, P, pa, pb)
    return x * P + y

# ── Шаг 1: валидация ─────────────────────────────────────────────────────────
Lx, Ly = liquidity_from_amounts(P0, PA, PB, ETH0, USD0)
print(f"[1] L по ETH-ноге = {Lx:.2f}, L по USD-ноге = {Ly:.2f}  (должны совпасть)")
L = (Lx + Ly) / 2
v_model = value(L, P0, PA, PB)
print(f"[1] стоимость по модели = ${v_model:.2f}  vs скриншот ${POS0:.2f}"
      f"  (расхождение {abs(v_model-POS0)/POS0*100:.3f}%)")

# entry: invested 2.42612148 ETH + 5000 USDG; цена входа из инвестиций
X_IN, Y_IN = 2.42612148, 5000.0
# HODL-стоимость входа при текущей цене:
hodl_now = X_IN * P0 + Y_IN
dl_model = hodl_now - v_model
print(f"[1] divergence loss по модели = ${dl_model:.2f} vs скриншот ${DL_SHOWN:.2f}")

# ── Шаг 2: DL на границах ────────────────────────────────────────────────────
print("\n[2] Divergence loss при движении цены (без комиссий):")
for P in (PA, P0*0.95, P0, P0*1.05, PB):
    v = value(L, P, PA, PB)
    hodl = X_IN * P + Y_IN
    dl = hodl - v
    print(f"    P={P:8.2f}  позиция=${v:9.2f}  HODL=${hodl:9.2f}"
          f"  DL=${dl:7.2f} ({dl/POS0*100:5.2f}% позиции)")

# DL за один «цикл ре-рейнджа»: вход в центре, выход на границе, ре-центр
v_at_edge_lo = value(L, PA, PA, PB)
hodl_at_lo   = X_IN * PA + Y_IN
dl_cycle_lo  = (hodl_at_lo - v_at_edge_lo) / POS0
v_at_edge_hi = value(L, PB, PA, PB)
hodl_at_hi   = X_IN * PB + Y_IN
dl_cycle_hi  = (hodl_at_hi - v_at_edge_hi) / POS0
print(f"[2] реализуемый IL за цикл: вниз {dl_cycle_lo*100:.2f}%, вверх {dl_cycle_hi*100:.2f}%")

# ── Шаг 3: Monte-Carlo GBM (seed фиксирован — воспроизводимо) ────────────────
def mc(sigma_annual, days=365, n_paths=4000, seed=42):
    """Симулируем год. Возврат: (time_in_range, reranges/год, IL-драг %/год).
    Политика: вышли из диапазона -> ре-рейндж в тот же относительный диапазон
    вокруг новой цены (реализуем IL цикла), газ игнорируем в этой функции."""
    rng = random.Random(seed)
    dt = 1/365
    sd = sigma_annual * sqrt(dt)
    lo_rel, hi_rel = PA/P0, PB/P0
    til_sum = 0.0; rr_sum = 0; il_sum = 0.0
    for _ in range(n_paths):
        p = 1.0; center = 1.0
        in_range_days = 0; reranges = 0; il_real = 0.0
        for _ in range(days):
            p *= math.exp(-0.5*sd*sd + sd*rng.gauss(0, 1))
            lo, hi = center*lo_rel, center*hi_rel
            if lo <= p <= hi:
                in_range_days += 1
            else:
                # реализованный IL цикла (какая граница пробита)
                il_real += (dl_cycle_lo if p < lo else dl_cycle_hi)
                center = p
                reranges += 1
        til_sum += in_range_days/days
        rr_sum  += reranges
        il_sum  += il_real
    n = n_paths
    return til_sum/n, rr_sum/n, il_sum/n

print("\n[3] Monte-Carlo, диапазон ±10% (как на скриншоте), 4000 путей, год:")
print(f"    {'vol ETH':>8} {'время в диапазоне':>18} {'ре-рейнджей/год':>16} {'IL-драг %/год':>14}")
MC = {}
for sig in (0.40, 0.55, 0.70):
    til, rr, il = mc(sig)
    MC[sig] = (til, rr, il)
    print(f"    {sig*100:6.0f}% {til*100:16.1f}% {rr:16.1f} {il*100:13.2f}%")

# ── Шаг 4: net-APY таблица ───────────────────────────────────────────────────
GAS_PER_RERANGE_USD = 2.0   # v4/L2 ~ $0.1-2; консервативно $2
print("\n[4] NET APY = fee_apr * время_в_диапазоне - IL-драг - газ:")
print(f"    {'fee APR':>8} | " + " | ".join(f"vol {s*100:.0f}%" for s in MC))
for fee in (0.79, 0.50, 0.30):
    row = []
    for sig, (til, rr, il) in MC.items():
        gas = rr * GAS_PER_RERANGE_USD / POS0
        net = fee * til - il - gas
        row.append(f"{net*100:6.1f}%")
    print(f"    {fee*100:6.0f}%  | " + " | ".join(row))

# ── Шаг 5: delta-neutral вариант ─────────────────────────────────────────────
print("\n[5] Delta-neutral (шорт ETH-ноги перпом). Хедж снимает НАПРАВЛЕНИЕ,")
print("    но НЕ IL (гамма-потеря остаётся). Минус funding за шорт:")
print(f"    {'fee APR':>8} | funding 5% | funding 10% | funding 15%   (vol 55%)")
til, rr, il = MC[0.55]
for fee in (0.79, 0.50, 0.30):
    gas = rr * GAS_PER_RERANGE_USD / POS0
    base = fee * til - il - gas
    # хеджируется только ETH-нога (~50% позиции) → funding на половину номинала
    row = [f"{(base - f*0.5)*100:6.1f}%" for f in (0.05, 0.10, 0.15)]
    print(f"    {fee*100:6.0f}%  | " + "  |  ".join(row))

# ── Fee-decay наблюдение со скриншота ────────────────────────────────────────
print("\n[6] Наблюдение: fee APR за неделю на скриншоте упал 100% -> 78.6%")
print("    (~-3%/день). Устойчивый уровень зрелых ETH/stable 0.05% пулов:")
print("    исторически 20-50% APR. Сценарий '79% навсегда' — нереалистичен.")
