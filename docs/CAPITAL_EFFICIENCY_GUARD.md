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
