# ADR-009 — Aave V3 Live Write Methods (FEAT-004 Phase 3)

* Sprint: v3.9 (SPA-V39-001)
* Status: Accepted (2026-05-27)
* Supersedes/extends: ADR-006 (Aave V3 Phase 2 read RPC), ADR-007/008
  (Compound + Chainlink Phase 2)
* Author: claude-agent
* Reviewers: yurii-spa

## Context

Phase 1 (v3.2) shipped a scaffold `AaveV3Adapter` with deterministic mock
balances/APYs and a `NOT_IMPLEMENTED` short-circuit for `supply()` /
`withdraw()` whenever `dry_run=False`. Phase 2 (v3.6, SPA-V36-001) replaced
the read-side mocks with real on-chain `eth_call` decoding for
`get_supply_apy` and `get_supply_balance`, keeping the write-side scaffolded.

The paper-trading engine and risk overlay now consume real Aave + Compound
APY + Chainlink price data, but every state change still flows through a
mock. To unblock the v4.0 paper→live cutover we need a signed
`Pool.supply(...)` / `Pool.withdraw(...)` path **whose default behaviour
remains a no-op** — anything looser will, sooner or later, send a real tx
during a stray pytest run.

## Decision

Phase 3 wires `supply()` / `withdraw()` into a real signed transaction path
gated behind a multi-layer safety stack. Every dependency is lazy-loaded
and every failure mode returns a structured dict.

### Multi-layer safety gates

1. **`dry_run=True` (default)** — unchanged: deterministic DRY_RUN dict, no
   imports, no RPC. This is what tests, the engine, the dashboard, and any
   ad-hoc REPL use unless explicitly overridden.
2. **`dry_run=False` + `SPA_EXECUTION_MODE != "live"`** — short-circuits to
   `{"status": "BLOCKED", "reason": "SPA_EXECUTION_MODE!=live"}`. No keys
   are loaded, no `eth_account` import, no RPC call. The env flag is the
   "I really mean it" lever; production systemd units set it explicitly,
   developer shells almost always have it unset.
3. **`SPA_PRIVATE_KEY` missing or malformed** — returns
   `{"status": "ERROR", "reason": "SPA_PRIVATE_KEY ..."}`. We validate
   format (64 hex chars, 0x-prefix optional) before any `eth_account` call,
   so a fat-fingered env entry fails fast.
4. **Derived address ≠ `SPA_WALLET_ADDRESS`** — returns `ERROR`. Catches
   the case where the key in the secret store points at a different wallet
   than the one the operator believes is configured. (Phase 2 already used
   `SPA_WALLET_ADDRESS` for `balanceOf` so we re-use it here for free.)
5. **Sanity gate** — `amount <= 0` raises `ValueError` (unchanged from
   Phase 1 input validation), `amount > 10_000_000` returns `ERROR`. The
   ceiling is a translation-bug shield: if a strategy ever fed unscaled
   wei into the human-units adapter we'd catch it before broadcast.
6. **Any RPC / signature / receipt revert** — caught and returned as
   `{"status": "FAILED", "phase": "approve" | "supply" | "withdraw",
     "reason": "..."}`. The orchestration engine never sees an exception
   propagate out of the live write path; the worst case is a logged
   `[FALLBACK] WARNING` and a FAILED record in the trade journal.

### Dependency policy: lazy `eth_account`

`eth_account>=0.10.0` is the only new third-party dep. It is imported
inside `_require_eth_account()` — *not* at module top — which mirrors the
psycopg2 pattern in `spa_core/database/connection.py`. Consequences:

* The Phase 1/2 mock path (which all 28 existing tests use) does not
  require `eth_account` to be installed.
* CI containers that only run dry-run paths don't pay the install cost.
* If `eth_account` is missing and the operator hits the live path, the
  adapter returns `{"status": "FAILED", "reason": "eth_account not
  installed ..."}` instead of raising `ImportError`. Tested explicitly.

### Transaction shape

EIP-1559 by default, gas params derived from `eth_gasPrice`:
`maxPriorityFeePerGas = gasPrice // 10` (floor 1 wei), `maxFeePerGas =
gasPrice * 2`. Conservative but mempool-accepted on Ethereum L1, Arbitrum,
and Base — all three chains we support. Legacy `gasPrice` mode is reachable
via direct `_sign_and_send` override, but the public `supply()` /
`withdraw()` only emit EIP-1559.

Selectors are hardcoded (`0x095ea7b3` approve, `0x617ba037` Pool.supply,
`0x69328dec` Pool.withdraw) so we do not pull in `eth_utils.keccak`.

### Receipt polling

`eth_getTransactionReceipt` polled every 2s, max 30s wall-clock. Two-tx
flows (approve + supply) run sequentially with `nonce + 1` on the second
tx; we deliberately do not parallelise to avoid mempool reordering risk.
A revert (`status: 0x0`) on either tx halts the flow and tags the failure
with the correct `phase`.

## Rollback Plan

If a v4.0 deployment misbehaves:

1. **Immediate**: unset `SPA_EXECUTION_MODE` in the production env. Within
   one process restart all write paths revert to `BLOCKED`. No git revert
   needed.
2. **Per-strategy disable**: each strategy passes `dry_run=True` into its
   adapter constructor; flip the strategy config flag, restart. Other
   strategies keep running.
3. **Code-level revert**: this commit is self-contained — `git revert`
   the v3.9 commit restores the Phase 2 `NOT_IMPLEMENTED` scaffold. The
   28 Phase 1/2 tests guarantee the read path keeps working.
4. **Secret rotation**: `SPA_PRIVATE_KEY` is read at call time, not at
   import. Rotating the secret store value takes effect on the next
   `supply()` / `withdraw()` call without restart.

## Phase 4 hooks

Phase 4 will cut `spa_core/orchestration/engine.py` over from paper to
live execution. The engine already knows about `AaveV3Adapter` via the
`spa_core/execution/execution_router.py` shim. The cutover will:

* Read a strategy-level `live_execution: bool` flag from the strategy YAML.
* If true AND `SPA_EXECUTION_MODE == "live"` AND the strategy's risk-policy
  guardrails pass — pass `dry_run=False` into the adapter constructor.
* Otherwise default to `dry_run=True` (the current behaviour).
* Log every BLOCKED / ERROR / FAILED dict into the existing trade journal
  alongside DRY_RUN and SUCCESS records, so the dashboard can surface a
  unified history.

## Alternatives Considered

* **web3.py** — rejected. Drags a large dependency tree (`eth-abi`,
  `pycryptodome`, `lru-dict`, ...) and most of its surface area (contract
  ABIs, filters, providers) we do not need. Phase 2 already proved that
  hand-rolled ABI encoding works for our limited surface (two read methods,
  three write methods, three chains, three assets).
* **Hardware-wallet signing (Ledger / Frame)** — deferred. Phase 3 keeps
  the private key in env so we can iterate fast on the engine wiring.
  A future ADR will introduce a `Signer` protocol with `EnvKeySigner`,
  `LedgerSigner`, and `KMSSigner` implementations.
* **Async / batched send** — deferred. Synchronous polling is simpler and
  the per-call latency (≤ 30s receipt wait) is acceptable for the current
  rebalance cadence (hourly, not sub-second).

## Test Coverage

`spa_core/tests/test_aave_v3_adapter_phase3.py` — 15 deterministic
network-free tests covering: execution-mode gate (3), private-key
validation (3), supply happy + 3 sad paths, withdraw happy + revert,
eth_account missing → FAILED, sanity gate (negative + >10M). Combined with
Phase 1 (13) + Phase 2 (15) = 43 tests, all passing in < 0.1s. Full
execution-stack regression (Compound + router + price feeds) = 104 tests
still pass.
