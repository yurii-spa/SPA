# ADR-008 — Execution Router (cross-protocol APY arbitration)

**Status:** ACCEPTED (2026-05-27, sprint v3.4)
**Owners:** claude-agent (Dispatch sprint v3.4, SPA-V34-001)
**Related:** FEAT-004 (Aave V3 Live SDK), FEAT-005 (Compound V3 Live SDK), FEAT-006 (Real-Time Price Feeds), BL-008 (PostgreSQL Migration), ADR-006, ADR-007

## Context

The two execution adapters scaffolded in v3.2 (`AaveV3Adapter`,
SPA-V32-001) and v3.3 (`CompoundV3Adapter`, SPA-V33-001) each speak to
a single protocol. The remaining unanswered question — explicitly
called out in `FEAT-005` description — is **"Rate comparison vs Aave on
every cycle; auto-route to highest net APY within risk limits."**

Without an arbitration layer:

1. `engine.py` would need to hard-code per-protocol branching.
2. Adding a third / fourth adapter (Morpho, Yearn) requires editing
   the engine every time.
3. Risk policy gates (`min_apy`, `allowed_protocols`, blacklists) would
   have to live in the engine alongside accounting logic.

This is exactly the kind of dispatch concern that wants its own module.

## Decision

Introduce **`spa_core/execution/router.py`** — a pure-Python
`ExecutionRouter` class that wraps an arbitrary iterable of adapter
instances, dispatches `supply` / `withdraw` based on registered
`(protocol, chain)` keys, and ranks adapters by supply APY for the
auto-route decision.

Key design points:

* **Structural typing, no concrete imports.** The router doesn't
  import `AaveV3Adapter` / `CompoundV3Adapter` at module top-level —
  it relies on `Protocol`-style duck typing. A new adapter (e.g.
  `MorphoBlueAdapter`) plugs in without touching `router.py`.
* **Protocol name = `snake_case(ClassName.removesuffix("Adapter"))`.**
  `AaveV3Adapter → aave_v3`, `CompoundV3Adapter → compound_v3`. The
  router refuses to register two adapters with the same
  `(protocol, chain)` key — silent overwrite is too dangerous.
* **Risk gates are exclusionary only.** `min_apy`, `allowed_protocols`,
  `blacklisted_protocols`, `allowed_chains` all filter the candidate
  set. If no adapter survives the filter, the router returns a
  `NO_ROUTE` envelope rather than picking a degraded fallback.
  Silent fallback to a worse rate is a go-live anti-pattern.
* **Deterministic tie-breaking.** When two protocols return identical
  APYs, the alphabetically-earlier protocol wins. Required for stable
  Sharpe regression tests.
* **No mode flag of its own.** The router does not introduce
  `dry_run` — whoever constructs the router decides the mode on each
  adapter. This mirrors the BL-008 dual-driver pattern (the
  abstraction is mode-agnostic; mode lives at the leaf).
* **Withdrawals are NOT APY-routed.** Engine is responsible for
  tracking *where* a position lives in SQLite. The router exposes
  `route_withdraw(..., protocol=...)` requiring the caller to name
  the protocol. Routing a withdraw by APY would silently rebalance
  positions, which is an accounting hazard.

## Alternatives considered

1. **Inline routing in `engine.py`.** Rejected: leaks adapter
   knowledge into accounting logic, hard to test in isolation,
   slow to extend.

2. **Per-chain router instances.** Rejected: many engine call-sites
   already know the target chain, so registering all
   `(protocol, chain)` pairs in one router is no worse and avoids
   `Dict[str, ExecutionRouter]` plumbing.

3. **Async router with concurrent APY fetches.** Deferred to Phase 2.
   Dry-run APYs are constants; live mode (post-Phase 2 of
   FEAT-004 / FEAT-005) can add `concurrent.futures` parallelism
   if rate-comparison latency becomes a bottleneck.

4. **Auto-routed withdrawals (sweep best APY back to current
   destination).** Rejected — see decision section.

## Rollout (phased)

* **Phase 1 (this sprint, v3.4):** Router lives in
  `spa_core/execution/`. Tests cover registry, APY comparison,
  best-protocol selection, supply routing with all four gate flavours,
  named withdraw routing, aggregate balances, health check (36 tests).
  No engine wiring yet — every existing call-site keeps its current
  adapter-direct calls.

* **Phase 2 (future sprint):** Swap
  `paper_trading/engine.py` direct adapter calls for
  `ExecutionRouter.route_supply()`. Engine becomes adapter-agnostic.
  Required before live capital cutover (FEAT-004 Phase 3 /
  FEAT-005 Phase 3).

* **Phase 3 (post go-live):** Add per-protocol *net* APY (gross APY
  minus gas amortisation estimate) using `data/gas_price_estimates.json`.
  Today the router picks on gross APY only.

## Rollback

Phase 1 is purely additive — no existing module imports
`router.py` yet. Reverting Phase 1 is a no-op deletion of three
files (`router.py`, `test_execution_router.py`, this ADR).

Phase 2 rollback (when wired): the engine will read the cutover
behaviour from `SPA_EXECUTION_ROUTING_MODE` env var:

* `direct` (default during Phase 2 rollout) — engine bypasses router,
  hits adapters directly. Same path as today.
* `router` — engine routes through `ExecutionRouter`. Default once
  router stability is confirmed.

This mirrors the BL-008 `SPA_DATABASE_URL` and FEAT-006
`SPA_PRICE_FEED_MODE` toggles.

## Verification

* `spa_core/tests/test_execution_router.py` — 36 deterministic tests,
  zero network, zero DB. All PASS in 0.05s.
* Cross-suite regression: `test_aave_v3_adapter.py` (14),
  `test_compound_v3_adapter.py` (14), `test_price_feeds.py` (13),
  `test_execution_router.py` (36) — total 79/79 PASS.

## References

* `spa_core/execution/router.py`
* `spa_core/execution/aave_v3_adapter.py`
* `spa_core/execution/compound_v3_adapter.py`
* `docs/ADR_006_aave_live_sdk.md`
* `docs/ADR_007_compound_v3_live_sdk.md`
* KANBAN: FEAT-005 description ("Rate comparison vs Aave …")
