# ADR-007: Compound V3 Live SDK Integration (Phased Rollout)

Date: 2026-05-27
Status: Proposed (Phase 1 Scaffold implemented)
Supersedes: nothing
Related: FEAT-005 (v2.0 backlog), ADR-006 (FEAT-004 — Aave V3 paired
         pattern), ADR-005 (BL-008 dual-driver pattern),
         FEAT-006 phased rollout (price_feeds.py)

## Context

SPA (Smart Passive Aggregator) today routes every supply / withdraw
decision through the paper-trading engine. The orchestrator logs an
intended trade, the position book updates in `data/status.json`, and no
on-chain transaction is ever broadcast. The v2.0 go-live milestone
requires that we move from this synthetic execution path to real
on-chain execution. Aave V3 is being integrated under FEAT-004 / ADR-006
in parallel; this ADR covers the companion adapter for **Compound V3**.

Compound V3 — known internally as **Comet** — is the third-generation
deployment of Compound. It differs from Aave V3 in three ways that
materially shape this ADR:

1. **Single-asset pools.** Each Comet is a separate contract scoped to
   exactly one base asset. The widely-deployed Comet on Ethereum,
   Arbitrum and Base is `cUSDCv3` (USDC base). The other base assets
   (`cWETHv3`, `cUSDTv3` on mainnet) are either out of SPA's strategy
   scope or not deployed on every chain we care about. As a result the
   Phase 1 adapter exposes **USDC only**.
2. **No aTokens.** Where Aave V3 mints an interest-bearing `aToken` per
   reserve, Compound V3 tracks principal + interest accrual on the
   Comet contract directly. `Comet.balanceOf(wallet)` returns the
   current base-asset balance (USDC denominated). The adapter therefore
   names the receipt field `ctoken_received` to be unambiguous when both
   adapters are used side-by-side, but the semantic is "Comet share /
   principal credit", not a separate ERC-20.
3. **Different rate API.** Aave V3 publishes a RAY-scaled per-second
   `liquidityRate` via `getReserveData(asset)`. Compound V3 exposes a
   per-second supply rate via `Comet.getSupplyRate(utilization)` that
   takes the *current* utilisation as input. The annualisation step
   (multiply by `SECONDS_PER_YEAR`) happens client-side. Phase 2 will
   wire this; Phase 1 returns a deterministic 4.5% mock.

Even with these differences, the **integration shape** is identical to
Aave V3 — a thin Python adapter, dry-run by default, three RPC endpoints
per chain, real contract addresses captured up-front. We therefore mirror
ADR-006 closely: the same three-phase rollout, the same feature flag
(`SPA_EXECUTION_MODE`), the same dual-driver pattern that BL-008 used to
land the PostgreSQL migration without freezing feature work.

The cost of not doing this is concrete: USDC supply yield on Compound V3
historically averages 30–50 bps higher than Aave V3 on the same chain
under similar utilisation regimes. Running Aave-only at go-live would
forfeit that diversification, leave SPA exposed to a single
counterparty-protocol risk, and undermine the existing `whitelist.json`
which already lists Compound V3 as an approved venue. We also want the
risk policy (`risk/policy.py`) to be exercised against a real two-venue
allocation in Phase 3, not a degenerate one-venue case.

## Decision

Adopt a **three-phase rollout** with a thin adapter
(`spa_core/execution/compound_v3_adapter.py`) sitting between the engine
and any future `web3.py` call. The adapter is dry-run by default; live
execution is opt-in via a constructor flag and gated by the same go-live
activation step that gates Aave V3.

The adapter intentionally **mirrors** `AaveV3Adapter` (FEAT-004 Phase 1):
same method names, same return shape, same RPC-fallback registry style,
same `health_check()` output keys. The only deltas are protocol-specific
naming (`comet_address` instead of `pool_address`, `ctoken_received`
instead of `atoken_received`) and the restricted asset set (USDC only).
This makes Phase 3 engine cutover almost mechanical: the engine sees two
adapters with the same interface and routes on `chain × asset × APY`.

### Phasing

* **Phase 1 — Scaffold (this sprint, ~4h).** Land `CompoundV3Adapter`
  with `supply`, `withdraw`, `get_supply_balance`, `get_supply_apy`,
  `health_check` and `_validate_inputs`. Every state-changing call
  returns a deterministic `DRY_RUN` payload; the same calls with
  `dry_run=False` return `NOT_IMPLEMENTED` instead of raising, so the
  engine can wire the adapter today without crashing on flag flips.
  Record real Compound V3 Comet (cUSDCv3) contract addresses for
  Ethereum (`0xc3d688B66703497DAA19211EEdff47f25384cdc3`), Arbitrum
  (`0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf`) and Base
  (`0xb125E6687d4313864e53df431d5425969c15Eb2F`), plus three RPC
  endpoints per chain — the same 3-RPC fallback shape we already use in
  `price_feeds.py` and `aave_v3_adapter.py`. RPC URLs use a
  `#compound-v3-comet:<address>` fragment hint so that, when both
  adapters are imported in the same process, the endpoint set for each
  protocol is unambiguous. Tests stay 100% offline (14 deterministic
  cases across 5 classes) and run in <0.1s.

  Deliverables for Phase 1 (this commit):
    1. `spa_core/execution/compound_v3_adapter.py` — `CompoundV3Adapter`
       class with the full public surface.
    2. `spa_core/tests/test_compound_v3_adapter.py` — 14 tests:
       `TestAdapterInit` (5), `TestSupply` (4), `TestWithdraw` (3),
       `TestBalanceAPY` (3), `TestHealthCheck` (2). All deterministic,
       all <0.1s, no network, no DB, no sleep.
    3. This ADR.

* **Phase 2 — Real on-chain execution (~12h).** Add `web3.py` and
  `eth_account` as deps (shared with FEAT-004 — they are added once
  for the project, not once per adapter). Implement
  `Comet.supply(asset, amount)` and `Comet.withdraw(asset, amount)`
  with EIP-1559 fee estimation, the 3-RPC fallback for read calls,
  `Comet.balanceOf(wallet)` for `get_supply_balance`, and
  `Comet.getSupplyRate(Comet.getUtilization())` × `SECONDS_PER_YEAR`
  for `get_supply_apy`. Note: unlike Aave V3 where `liquidityRate` is
  state-snapshot, Compound V3's rate is a function of *current*
  utilisation — Phase 2 must read utilisation in the same eth_call
  batch to avoid races. Sign with a key loaded from the secrets
  manager (NOT from the repo). Gate every live call behind
  `safety_checks.py`. Keep all Phase 1 tests green; add a separate
  `-m live` test marker for anvil-fork checks that runs out-of-band.

  Phase 2 will *not* introduce swap routing — Compound V3 USDC supply
  expects USDC input, and `engine.py` already routes capital so each
  adapter receives its native base asset. Slippage protection is
  therefore a Phase 2.5 concern (for cross-protocol rebalances that
  cross asset boundaries, e.g. USDC ↔ DAI), not in scope for the
  pure-Comet path.

* **Phase 3 — Engine cutover (~6h, paired with FEAT-004 Phase 3).**
  Replace the `engine.py` paper-trade dispatcher with a switch on
  `SPA_EXECUTION_MODE`: `paper` (default) → existing path,
  `dry_run` → `AaveV3Adapter(dry_run=True)` /
  `CompoundV3Adapter(dry_run=True)`, `live` → both adapters with
  `dry_run=False` plus the 11 go-live gates from
  `spa_core/golive/activate.py`. The engine selects the venue per
  decision tick by comparing `get_supply_apy()` across both adapters
  for each candidate chain and applying the risk policy (max position
  size, drawdown stop, depeg gate from SPA-V31-003). A full week of
  live operation with clean reconciliation reports is the gate before
  decommissioning the paper dispatcher.

## Alternatives considered

* **Stay Aave-only (ship FEAT-004 alone, defer FEAT-005 indefinitely).**
  Simpler, but forfeits roughly 30–50 bps of diversifiable USDC APY,
  concentrates SPA on a single lending counterparty, and contradicts
  the existing `whitelist.json` which already lists Compound V3 as an
  approved venue. The cost of adding the adapter is modest (~4h Phase 1,
  ~12h Phase 2) and the dual-venue setup is required for the strategy
  research backlog (cross-protocol rotation) anyway. Rejected.

* **Call Comet ABI directly from `engine.py`, no adapter.** This is the
  same antipattern ADR-006 rejected for Aave. It would conflate
  orchestration with chain semantics, make the engine impossible to
  unit-test offline, and force every flag flip to touch the engine.
  Worse, with two protocols there is now a real interface to keep
  honest: divergence between the Aave and Compound call sites would
  silently degrade venue-selection logic. Rejected.

* **Use a Compound Connector MCP / vendor SDK sidecar.** Some teams
  expose Compound V3 read/write through a hosted MCP server or a
  Node-only SDK (`@compound-finance/compound-js`). Both add external
  infrastructure dependencies that SPA explicitly avoids — the runtime
  is pure-Python and stdlib-first, and adding a Node sidecar would
  doubly violate that for both Aave and Compound. ADR-006 already
  reasoned this through for Aave; we extend the same conclusion here.
  Rejected.

* **Build a generic "lending protocol" adapter abstraction now.** Aave
  V3 and Compound V3 are similar but not identical (Compound is
  single-asset per Comet, has no aTokens, rate API differs). We will
  revisit a shared `LendingAdapter` interface only after FEAT-005
  Phase 2 ships and the two adapters have proven their delta in
  practice. Premature abstraction would lock us into the wrong shape
  and force rework when a third protocol (Spark, Morpho) lands.
  Rejected for now; revisit post-Phase 2.

## Consequences

* **Positive.** Strategy code can begin importing `CompoundV3Adapter`
  and exercising the dry-run path immediately, with no risk of
  accidental on-chain calls. The Comet addresses and RPC fallback
  registry live in one auditable file alongside Aave's. The two
  adapters share an interface modulo protocol-specific names, so the
  engine cutover in Phase 3 is a single switch statement, not two.
  Phase 1 lands behind a flag, so a single env var rolls back to paper
  trading in seconds. Restricting Phase 1 to USDC keeps the blast
  radius small and lets us validate the dual-adapter pattern before
  expanding to ETH-Comet or DAI-Comet.

* **Negative.** Until Phase 2 lands the live path is a stub; any code
  that flips `dry_run=False` will observe `NOT_IMPLEMENTED` payloads
  rather than real transactions. The engine integration layer must
  treat `NOT_IMPLEMENTED` as a hard error in pre-go-live tests (same
  contract as ADR-006). Multi-asset support (cWETHv3, cUSDTv3 where
  deployed) is deferred — strategies that want non-USDC Compound
  exposure will have to wait for Phase 2+.

* **Neutral.** Real wallet key custody, gas oracle integration, and
  multisig routing (Gnosis Safe for amounts >$500) remain owned by
  `wallet.py` / `safety_checks.py`. The adapter does not duplicate
  them. MEV protection (Flashbots bundle wiring) is also wallet-owned.

## Risk

* **Pool size / liquidity.** Compound V3 Comets on Arbitrum and Base
  are smaller than the Ethereum mainnet Comet. Phase 1 USDC-only on
  three chains, all backed by the largest single-asset Comet on each
  chain (cUSDCv3), keeps Phase 1 well within the safe size envelope.
  Multi-asset Comets (cWETHv3, cUSDTv3) with shallower TVL are deferred
  to Phase 2+ specifically so that we never accidentally route into a
  low-liquidity pool in dry-run-flips-to-live transition.

* **Rate volatility on Compound V3.** Because Compound V3 supply rate
  is a function of *current* utilisation, it can spike rapidly under
  large withdrawals. Phase 2 must read utilisation and rate atomically
  (single eth_call batch) and the risk policy must guard against rate
  decisions made on stale snapshots. Phase 3 will hook
  `risk/policy.py max_drawdown_stop` into the same kill-switch that
  Aave uses.

* **Comet base-token-only restriction.** Unlike Aave V3 (where each
  reserve is independently parameterisable), Compound V3 only allows
  supply of the **base token** of the Comet — supplying any other asset
  routes through collateral semantics, not earn semantics. The
  adapter's USDC-only Phase 1 surface enforces this at the type level:
  there is no codepath that can accidentally call `Comet.supply()` on
  a non-base asset.

* **Address verification.** Phase 1 captures Comet addresses as
  hardcoded constants. They are accurate as of 2026-05 per the
  Compound V3 deployments index, but Phase 2 will add a startup
  `eth_call` to `Comet.baseToken()` per chain that asserts the
  resolved base token matches the expected USDC address for that
  chain. This is the same defence ADR-006 spec'd for Aave Pool
  `getReserveData()`.

## Rollback

Phase 1 is **additive only** — deleting
`spa_core/execution/compound_v3_adapter.py` and its tests restores
pre-FEAT-005 behaviour byte-for-byte. Phase 2 and Phase 3 are
flag-guarded; `unset SPA_EXECUTION_MODE` (or set to `paper`) returns
the engine to paper trading without code changes. The kill-switch in
`risk/policy.py max_drawdown_stop` provides an additional
defence-in-depth: even with `SPA_EXECUTION_MODE=live`, a drawdown
trigger halts all adapter calls before they reach
`Comet.supply()` / `Comet.withdraw()`.

The dual-driver methodology is identical to BL-008 (PostgreSQL
migration) and to FEAT-004 / ADR-006: keep the legacy path live, run
the new path under a flag, switch when reconciliation is clean, and
preserve the ability to flip back via a single env var for one full
release cycle after cutover.

## Out of scope (for now)

* Multi-asset Comets (cWETHv3 on Ethereum/Base, cUSDTv3 on mainnet) —
  deferred to Phase 2+ after the USDC dual-adapter pattern is proven.
* Compound V3 borrow / leverage flows — out of scope for SPA's passive
  supply strategy.
* Cross-protocol rebalancing logic (USDC supply on Aave → withdraw →
  re-supply on Compound when APY delta exceeds threshold) — strategy
  layer concern, not adapter concern; will be specified in a separate
  ADR after FEAT-005 Phase 2 lands.
* Cross-chain capital rotation — bridge layer responsibility
  (`wallet.py` will own this in a future ADR).
* Gnosis Safe routing for amounts >$500 — already specified in
  `wallet.py`; the adapter just calls the wallet, it does not duplicate
  multisig logic.
* MEV / Flashbots protection — wallet-layer responsibility, shared
  with the Aave adapter via a single `wallet.py` send path.
