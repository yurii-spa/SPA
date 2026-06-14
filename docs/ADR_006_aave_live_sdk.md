# ADR-006: Aave V3 Live SDK Adapter — Migration Plan (FEAT-004)

Date: 2026-05-27
Status: Proposed (Phase 1 Scaffold implemented)
Supersedes: nothing
Related: FEAT-004 (v2.0 backlog), ADR-005 (BL-008 dual-driver pattern),
         FEAT-006 phased rollout (price_feeds.py)

## Context

SPA today executes every supply / withdraw decision through the
paper-trading engine: the orchestrator logs an intended trade, the
position book updates in `data/status.json`, and no on-chain transaction
is ever broadcast. To reach the v2.0 go-live milestone we need a live
execution path against Aave V3 — the largest stablecoin money market on
Ethereum, Arbitrum and Base.

Replacing the paper path in a single drop would freeze feature work for
the duration of the integration, risk subtle accounting drift between
mock balances and on-chain aToken balances, and force every developer to
hold a funded test wallet. We need a path from "paper everywhere" to
"Aave V3 live behind a feature flag" that:

* Lets the rest of the codebase keep landing strategies and risk fixes
  without waiting for a wallet integration.
* Keeps the pytest suite deterministic and offline (no Sepolia, no
  testnet flakiness).
* Mirrors a pattern the team has already shipped twice — FEAT-006
  (price feeds) and BL-008 (Postgres dual-driver).

## Decision

Adopt a **three-phase rollout** with a thin adapter
(`spa_core/execution/aave_v3_adapter.py`) sitting between the engine
and any future web3.py call. The adapter is dry-run by default; live
execution is opt-in via a constructor flag and gated by a separate
go-live activation step.

### Phasing

* **Phase 1 — Scaffold (this sprint).** Land `AaveV3Adapter` with
  `supply`, `withdraw`, `get_supply_balance`, `get_supply_apy`,
  `health_check` and `_validate_inputs`. Every state-changing call
  returns a deterministic `DRY_RUN` payload; the same calls with
  `dry_run=False` return `NOT_IMPLEMENTED` instead of raising, so the
  engine can wire the adapter today without crashing on flag flips.
  Record real Aave V3 Pool contract addresses for Ethereum, Arbitrum
  and Base, plus three RPC endpoints per chain — the same 3-RPC
  fallback shape we already use in `price_feeds.py`. Tests stay 100%
  offline (12+ deterministic cases) and run in <0.1s.

* **Phase 2 — Real on-chain execution (~12h).** Add `web3.py` and
  `eth_account` as deps. Implement Pool.supply / Pool.withdraw with
  EIP-1559 fee estimation, the 3-RPC fallback for read calls,
  aToken.balanceOf for `get_supply_balance`, and RAY-scaled
  `getReserveData(asset).liquidityRate` for `get_supply_apy`. Sign with
  a key loaded from the secrets manager (NOT from the repo). Gate
  every live call behind `safety_checks.py`. Keep all Phase 1 tests
  green; add a separate `-m live` test marker for Tenderly-fork checks
  that runs out-of-band.

* **Phase 3 — Engine cutover (~6h).** Replace the
  `engine.py` paper-trade dispatcher with a switch on
  `SPA_EXECUTION_MODE`: `paper` (default) → existing path,
  `dry_run` → `AaveV3Adapter(dry_run=True)`, `live` →
  `AaveV3Adapter(dry_run=False)` plus the 11 go-live gates from
  `spa_core/golive/activate.py`. Decommission the paper dispatcher
  once a full week of live operation has produced clean reconciliation
  reports.

## Alternatives considered

* **Use a vendor SDK (e.g. @aave/contract-helpers).** Node-only,
  requires running a sidecar process from Python, adds a 30+ MB
  dependency. Rejected — keeps the runtime pure-Python and stdlib-first
  as everywhere else in `spa_core`.
* **Skip the adapter, call web3.py directly from `engine.py`.**
  Conflates orchestration with chain semantics; makes the engine
  impossible to unit-test offline. Rejected.
* **Build a generic "lending protocol" adapter abstraction now.** Aave
  V3 and Compound V3 are similar but not identical (Compound V3 is
  single-asset per Comet, has no aTokens). We will revisit a shared
  interface only after Compound V3 (FEAT-005) ships — premature
  abstraction would lock us into the wrong shape.

## Consequences

* **Positive.** Strategy code can begin importing `AaveV3Adapter` and
  exercising the dry-run path immediately, with no risk of accidental
  on-chain calls. The contract addresses and RPC fallback registry
  live in one auditable file. Phase 2 lands behind a flag, so a single
  env var rolls back to paper trading in seconds.
* **Negative.** Until Phase 2 lands the live path is a stub; any code
  that flips `dry_run=False` will observe `NOT_IMPLEMENTED` payloads
  rather than real transactions. The engine integration layer must
  treat `NOT_IMPLEMENTED` as a hard error in pre-go-live tests.
* **Neutral.** Real wallet key custody, gas oracle integration, and
  multisig routing (Gnosis Safe) remain owned by `wallet.py` /
  `safety_checks.py`. The adapter does not duplicate them.

## Rollback

Phase 1 is additive only — deleting `spa_core/execution/aave_v3_adapter.py`
and its tests restores pre-FEAT-004 behaviour byte-for-byte. Phase 2 and
Phase 3 are flag-guarded; `unset SPA_EXECUTION_MODE` (or set to `paper`)
returns the engine to paper trading without code changes.

## Out of scope (for now)

Compound V3 integration (FEAT-005, separate ADR), cross-chain capital
rotation, MEV protection (covered by `wallet.py` Flashbots wiring),
Gnosis Safe routing for amounts >$500 (already specified in
`wallet.py`), borrowing / leverage on Aave V3.
