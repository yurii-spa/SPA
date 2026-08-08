# Capital-Efficiency Guard — backlog spec (owner-flagged 2026-07-12)

> **Status: BACKLOG / think-through-first.** Owner flagged this after we found the live book sitting
> at ~20% idle cash (deployable T1 headroom left unused) — and, worse, **no check anywhere caught it.**
> "Меня сильно смущает что стратегия не доработала сама, что у нас нет проверки" — write it up, think
> it through separately, and fix EVERYWHERE. This is a governance gap, not a one-off bug.

## 1. The honest problem

The desk measures **risk** world-class (RiskPolicy caps, tier limits, kill-switch, RTMR, refusal
engine, drawdown ladder) — but has **zero** measurement of **capital efficiency**. The allocator can
silently leave deployable capital idle at 0% and nothing flags it:

- **Observed (2026-07-12):** live book = 80% deployed / **~20% cash** while the RiskPolicy min-cash is
  only **5%**. That's ~15% of the book earning 0% with qualifying T1 headroom available (`compound_v3`,
  `spark_susds`, Aave on OP/Poly/Arb — each 40% cap, 0% weight). Cost: ~+1pp of forgone yield
  (~4.4% realized vs ~5.4% achievable by deploying the idle cash).
- **Root mechanism:** raw `allocator.allocate()` wants ~24 protocols fully deployed (0% cash), but the
  **ALLOC-002 ≤8-protocol collapse** (`cycle_runner._compliant_target`) trims to 8 and its
  redistribution does **not** re-fill the freed weight into the survivor book → the dropped protocols'
  weight silently becomes cash.
- **The real failure:** it took the *owner asking* to surface it. No agent, monitor, health-check, or
  test watches "are we actually deploying the capital we safely can?"

## 2. Fix EVERYWHERE (owner's ask) — three layers

**A. Fix the allocator redistribution (the actual leak).**
After the ≤8 collapse, water-fill freed capital into the survivor-8 up to caps (T1 40% / T2 20% each /
T2-total 50% / T3 15%), APY-descending, T1-first — leaving only `min_cash_pct` (5%) as cash. The
`_fill_remainder` mechanism already exists (SPA-V405) but runs BEFORE the total-tier caps and/or on a
narrow universe; the ≤8 path (`_compliant_target`) needs the same honest re-fill. Deterministic,
RiskPolicy UNTOUCHED, respects grade-D exclusions (never re-fund a refused protocol).

**B. Add a Capital-Efficiency GUARD (the missing check — the point of this ticket).**
A deterministic monitor that flags silent under-deployment, mirroring how `agent_health` /
`cycle_health` already flag other regressions:
- Compute `idle_excess = cash_pct − min_cash_pct`. If `idle_excess > tolerance` (e.g. >3pp) **AND**
  qualifying deployable headroom exists (a whitelisted protocol under its cap, passing TVL/APY floors,
  not grade-D) → **WARNING**: "capital-efficiency: X% deployable capital idle at 0%."
- Emit into `agent_health` / `cycle_health` (same escalation path as Q1-10 resilience). Write a status
  JSON (`data/capital_efficiency.json`): `cash_pct`, `min_cash_pct`, `idle_excess`, `deployable_headroom_pct`,
  `forgone_yield_bps_est`, `verdict OK/WARNING`. Fail-CLOSED (unknown → WARNING, never a false OK).
- **Honesty:** distinguish STRUCTURAL cash (caps genuinely exhausted → OK, not a fault) from LAZY cash
  (headroom exists but unused → WARNING). The guard must not cry wolf when the caps really do force cash.

**C. Test + surface.**
- Unit test: given a target with headroom, assert deployed ≥ `1 − min_cash − eps` and every cap held.
- Regression test: the observed 20%-cash scenario must trip the guard.
- Surface a "capital efficiency %" (deployed / deployable) on `/readiness` or the dashboard system panel
  — so it's publicly visible, like the other honesty metrics.

## 3. Why this matters beyond the +1pp

The number (+1pp) is small; the **principle** is not. A desk whose pitch is "we measure what others
don't" cannot silently leave money idle with no alarm. This guard turns "capital efficiency" into a
first-class, monitored, publishable invariant — same class as the drawdown ladder and the refusal log.

## 4. Constraints (hard)

Deterministic + stdlib-only + fail-CLOSED. **No LLM.** RiskPolicy v1.0 **untouched** (the guard reads
`min_cash_pct` etc., never changes them). `atomic_save` for the status JSON. The allocator fix is
money-path on the **go-live track** → sandbox-validate + show owner before it hits a live cycle
(owner decides A: now / B: after go-live). The guard itself (B) is read-only/advisory → safe to ship
independently of the allocator fix.

## 5. Suggested sequencing
1. **B first (guard) — safe, ship independently:** it's read-only, catches the class of bug going
   forward, and needs no live-track change. Highest value-per-risk.
2. **A (allocator re-fill)** — money-path, owner-timed (now vs post-go-live).
3. **C (test + surface).**

---

## 6. Что такое «пригодная комната» (уточнено 2026-08-08, цикл #165)

До 08.08 сторож считал комнату пригодной, спросив только про **тир** и **доходность**. Он не
спрашивал ни про **происхождение** размера пула, ни про сам **размер** — и печатал как пригодное
то, что аллокатору финансировать запрещено:

- `aerodrome_usdc_lp(+20% @ 8.5%)` при `live_apy = null`, `tvl_usd = 0.0` — фид мёртв целиком,
  а 8.5 % это литерал `fallback_apy`;
- `moonwell_base` при TVL $1.41M против порога RiskPolicy $5M — пул, отфильтрованный
  аллокатором (`_filter_by_tvl`, MP-011).

Теперь порог живёт в ОДНОМ месте — `spa_core/risk/tvl_floor.py` (значение приходит из
`RiskConfig.min_tvl_usd`, литералов в правиле нет), и его же зовёт атрибуция кэша
(`attribute_cash`). Конформанс-тест сверяет общее правило с `allocator._filter_by_tvl`
пул-за-пулом и краснеет при любом расхождении.

Новые поля артефакта `data/capital_efficiency.json`:

| поле | смысл |
|---|---|
| `headroom_excluded` | комнаты, которым НЕЛЬЗЯ давать деньги, с причиной (`tvl_unmeasured` / `tvl_below_floor:$X<$Y`) |
| `headroom_size_unmeasured` | пулы, чей размер вообще не наблюдался |
| `min_tvl_usd` | порог, который применялся (None ⇒ вердикт `UNKNOWN`) |

Два fail-CLOSED, добавленных ПРОТИВ самой этой починки — она ведь убирает строки из тревоги:

1. **порог не разрешён** ⇒ `UNKNOWN`, не `OK`;
2. **комната осталась только у пулов с ненаблюдённым размером** ⇒ `UNKNOWN`, не `OK`.
   «Не измерено» ≠ «структурно»; иначе дыра в наблюдении выдавалась бы за правильное решение
   держать кэш. Контроль в обратную сторону: измеренный маленький пул даёт честный `OK`.

Тревога при этом НЕ гасится: на живом срезе 08.08 вердикт остался `WARNING`, изменился только
список — из него ушли ложные строки, а `best_qualifying_apy_pct` упал с 8.5 % (мёртвый литерал)
до 7.5 % (живой `frax`, TVL $100M).
