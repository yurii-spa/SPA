# ADR-010 — Compound V3 Live Write Methods (FEAT-005 Phase 3)

* Sprint: v3.10 (SPA-V40-001)
* Status: Accepted (2026-05-27)
* Supersedes/extends: ADR-007 (Compound V3 Phase 2 read RPC), ADR-009
  (Aave V3 Phase 3 live writes — the canonical template)
* Author: claude-agent
* Reviewers: yurii-spa

## Context

Phase 1 (v3.3) shipped a scaffold `CompoundV3Adapter` with deterministic
mock balances/APYs and a `NOT_IMPLEMENTED` short-circuit for `supply()` /
`withdraw()` whenever `dry_run=False`. Phase 2 (v3.7, SPA-V37-001) replaced
the read-side mocks with real on-chain `eth_call` decoding for
`get_supply_apy` (two chained calls — `getUtilization` then
`getSupplyRate`) and `get_supply_balance` (`Comet.balanceOf`).

ADR-009 (v3.9) shipped the exact-same flow for Aave V3 via eth_account-
signed EIP-1559 transactions. This ADR mirrors that decision for the
Compound V3 Comet markets so the v4.0 paper→live cutover can flip either
protocol on or off independently.

## Decision

Phase 3 wires `CompoundV3Adapter.supply()` / `withdraw()` into a real
signed transaction path gated behind a multi-layer safety stack. Every
dependency is lazy-loaded and every failure mode returns a structured dict.

### Multi-layer safety gates (identical to ADR-009)

1. **`dry_run=True` (default)** — unchanged: deterministic DRY_RUN dict, no
   imports, no RPC. This is what tests, the engine, the dashboard, and any
   ad-hoc REPL use unless explicitly overridden.
2. **`dry_run=False` + `SPA_EXECUTION_MODE != "live"`** — short-circuits to
   `{"status": "BLOCKED", "reason": "SPA_EXECUTION_MODE!=live"}`. No keys
   are loaded, no `eth_account` import, no RPC call.
3. **`SPA_PRIVATE_KEY` missing or malformed** → `{"status": "ERROR", ...}`.
   We validate format (64 hex chars, 0x-prefix optional) before any
   `eth_account` call.
4. **Derived address ≠ `SPA_WALLET_ADDRESS`** → `ERROR`. Catches the case
   where the key in the secret store points at a different wallet than the
   one Phase 2 read methods are configured against.
5. **Sanity gate** — `amount <= 0` raises `ValueError` (unchanged from
   Phase 1 input validation), `amount > 10_000_000` returns `ERROR`.
6. **Any RPC / signature / receipt revert** — caught and returned as
   `{"status": "FAILED", "phase": "approve" | "supply" | "withdraw", ...}`.
   The orchestration engine never sees an exception propagate out of the
   live write path.

### Differences vs Aave V3 (ADR-009)

The Compound V3 Comet contract has a deliberately tighter ABI surface
than Aave V3 Pool, so the adapter is simpler in three places:

* **Function selectors differ** —
  * Comet.supply(asset, amount) = `0xf2b9fdb8` (vs Aave's
    Pool.supply(asset, amount, onBehalfOf, referralCode) = `0x617ba037`).
  * Comet.withdraw(asset, amount) = `0xf3fef3a3` (vs Aave's
    Pool.withdraw(asset, amount, to) = `0x69328dec`).
  * approve(spender, amount) is the same ERC-20 selector `0x095ea7b3`.
* **No `onBehalfOf` / `to` arguments** — Comet credits/debits `msg.sender`
  directly. The caller's address is the only beneficiary. This shaves one
  32-byte slot off each calldata and avoids a class of self-vs-other-wallet
  bugs.
* **Single-asset markets** — `SUPPORTED_ASSETS = ["USDC"]`. The widely
  deployed Comet on all three chains is cUSDCv3. cWETHv3 and other
  base-asset variants are deferred to a future ADR. (Aave V3 supports
  USDC / USDT / DAI on the same Pool because Pool is multi-asset by
  design.)
* **balanceOf semantics** — `Comet.balanceOf(wallet)` returns
  *presentValue* (raw base-asset units already including accrued
  interest), so there is no aToken-style indirection. Phase 2's read
  path stays the canonical one — Phase 3 doesn't touch it.

Everything else — lazy `eth_account` import, EIP-1559 type=2 with
`maxFeePerGas = gasPrice * 2` and `maxPriorityFeePerGas = gasPrice // 10`,
2-second receipt polling with a 30-second wall-clock cap, `_eth_rpc` /
`_rpc_first` / `_send_raw_tx` / `_wait_for_receipt` / `_receipt_success` —
is a near-byte-identical port of the Aave V3 adapter.

### Dependency policy: lazy `eth_account`

`eth_account>=0.10.0` is already pinned in `requirements.txt` (ADR-009).
This ADR re-uses the same pin. The Compound adapter imports it inside
`_require_eth_account()` — *not* at module top — which mirrors the
psycopg2 pattern in `spa_core/database/connection.py`.

Consequences:

* The Phase 1/2 mock path (which all 33 existing Compound tests use) does
  not require `eth_account` to be installed.
* CI containers that only run dry-run paths don't pay the install cost.
* If `eth_account` is missing and the operator hits the live path, the
  adapter returns `{"status": "FAILED", "reason": "eth_account not
  installed ..."}` instead of raising `ImportError`. Tested explicitly.

### Transaction shape

Identical to ADR-009 — EIP-1559 by default, gas params derived from
`eth_gasPrice`: `maxPriorityFeePerGas = gasPrice // 10` (floor 1 wei),
`maxFeePerGas = gasPrice * 2`. Conservative but mempool-accepted on
Ethereum L1, Arbitrum, and Base.

### Receipt polling

`eth_getTransactionReceipt` polled every 2s, max 30s wall-clock. Two-tx
supply flow (approve + Comet.supply) runs sequentially with `nonce + 1`
on the second tx; we deliberately do not parallelise to avoid mempool
reordering risk. A revert (`status: 0x0`) on either tx halts the flow and
tags the failure with the correct `phase`.

## Rollback Plan

If a v4.0 deployment misbehaves:

1. **Immediate**: unset `SPA_EXECUTION_MODE` in the production env. Within
   one process restart all Compound write paths revert to `BLOCKED`. No git
   revert needed.
2. **Per-protocol disable**: paper-trading engine flips
   `compound_live_execution: false` in its config; the Aave path keeps
   running unchanged.
3. **Per-strategy disable**: each strategy passes `dry_run=True` into the
   `CompoundV3Adapter` constructor; flip the strategy config flag,
   restart. Other strategies keep running.
4. **Code-level revert**: this commit is self-contained — `git revert`
   the v3.10 commit restores the Phase 2 `NOT_IMPLEMENTED` scaffold. The
   Phase 1/2 tests guarantee the read path keeps working.
5. **Secret rotation**: `SPA_PRIVATE_KEY` is read at call time, not at
   import. Rotating the secret store value takes effect on the next
   `supply()` / `withdraw()` call without restart.

## Phase 4 hooks

Phase 4 (v4.0) will cut `spa_core/orchestration/engine.py` over from paper
to live execution. The engine already routes Compound trades through
`spa_core/execution/execution_router.py`. The cutover will:

* Read a strategy-level `live_execution: bool` flag from the strategy YAML.
* If true AND `SPA_EXECUTION_MODE == "live"` AND the strategy's risk-policy
  guardrails pass — pass `dry_run=False` into the adapter constructor.
* Otherwise default to `dry_run=True` (the current behaviour).
* Log every BLOCKED / ERROR / FAILED dict into the existing trade journal
  alongside DRY_RUN and SUCCESS records, so the dashboard can surface a
  unified history.

The Aave + Compound adapter contracts are now byte-identical at the public
API level (`supply` / `withdraw` / `get_supply_apy` / `get_supply_balance`
/ `health_check`), so the engine can treat them as interchangeable
implementations of an implicit `LendingAdapter` protocol.

## Alternatives Considered

* **web3.py** — rejected for the same reasons as ADR-009. Hand-rolled ABI
  encoding works fine for the two-selector surface (supply, withdraw).
* **Hardware-wallet signing (Ledger / Frame)** — deferred to the
  forthcoming `Signer` protocol ADR (will cover both Aave and Compound).
* **Async / batched send** — deferred. Synchronous polling is simpler and
  the per-call latency (≤ 30s receipt wait) is acceptable for the
  hourly rebalance cadence.
* **Wrap Aave V3 adapter into Compound** (i.e. duplicate the entire
  Phase-3 helper bundle into one shared `EvmWriteHelpers` module) —
  considered, deferred. The two adapters are 90% identical but the
  duplication is *deliberate*: it lets us evolve each protocol's
  selectors / sanity gates independently without a shared-utility
  refactor. We'll reconsider when the third protocol (Spark / Sky / Sushi
  Earn) lands.

## Test Coverage

`spa_core/tests/test_compound_v3_adapter_phase3.py` — 15 deterministic
network-free tests covering: execution-mode gate (3), private-key
validation (3), supply happy + 3 sad paths, withdraw happy + revert,
eth_account missing → FAILED, sanity gate (negative + >10M).

Combined with Phase 1 (17) + Phase 2 (16) = 48 Compound tests, all
passing in < 0.1s. Full execution-stack regression (Aave Phase 1+2+3,
Compound Phase 1+2+3, router, price_feeds Phase 1) = 140/140 tests still
pass.
