# ADR-556 · RM-LIVE-01 — Shadow execution + limited capital pilot readiness

- **Status:** ACCEPTED — architecture freeze (owner macro-epic 2026-10-04 «RM-LIVE-01»)
- **Date:** 2026-10-04
- **Related:** ADR-554 (Investment CIO «Штирлиц»), ADR-533/537 (three paper books), ADR-010/022/024 (Safe), ADR-032
  (live trading gate), ADR-228 (arming reachability), ADR-YL-005 (non-custodial), ADR-183 (pilot target chain),
  invariants #1 (RiskPolicy), #2 (fail-closed), #3 (no LLM in risk/execution), #4 (stdlib), #6 (no `spa_core/execution`
  import from paper code), #7 (no secrets in files), #17 (absence is its own value).
- **Boundary (absolute):** real capital $0. Automated live execution PROHIBITED. Nothing in this layer signs, holds a
  key, broadcasts, submits an order, approves, deposits, withdraws or moves funds. RiskPolicy, limits, stops,
  leverage, tiers, live admission and strategy mechanics are read, never changed.

## Phase 0 — evidence (three independent read-only audits, 2026-10-04)

**Execution surfaces.** A dormant on-chain execution layer exists (`spa_core/execution/`): `eth_signer` (sign +
`eth_sendRawTransaction`), `mev_protection` (Flashbots), Aave v3 / Compound v3 adapters and `execution/adapters/`
(euler, maple, sky, yearn, morpho), `engine_bridge` (paper trade → live leg), `safe_tx_builder` (unsigned Safe
proposals), `draft_prep` (unsigned «level A» drafts for a human signer), `wallet` scaffold. Every signing path ends in
`@live_trading_forbidden` (always raises) and/or `SPA_EXEC_ARMED`; `SPA_PRIVATE_KEY` is absent everywhere; no running
process reaches a send path. earn-defi has a dormant WhiteBIT `LiveExecutor` (`live_enabled=false`, no keys, never
instantiated). Telegram money-adjacent actions: `/pause`/`/resume` (owner-gated paper kill switch) only.
**Verdict: nothing can sign, broadcast or place a production order today.** Classes: LIVE_CAPABLE-but-DORMANT (signer,
MEV relay, protocol adapters, earn-defi LiveExecutor), SHADOW_CAPABLE (draft_prep, engine_bridge seam,
safe_tx_builder proposals), DEPRECATED (wallet scaffold), UNKNOWN_PURPOSE/DORMANT (familyfund `withdrawal_engine`,
`intraday_actor`) — none deleted.

**Gaps found (hardened in this epic, no credential change):** `eth_signer.sign_message` lacks the arm guard; the
`LiveTradingGate` is not consulted on signing paths; the `PaperTrader(live_execution=True)` seam has no machine check;
signer keys come from an environment variable (no plist/env may ever carry `SPA_PRIVATE_KEY`/`SPA_EXEC_ARMED` —
enforced by test); cloudflared carries its tunnel token on argv; three plaintext secret-shaped files in `~` /
`~/Documents`.

**Credentials (names/metadata only).** No wallet key, seed, keystore or exchange key exists on this Mac. Runtime holds
non-money authority (GitHub PAT, tunnel token, Cloudflare refresh token, family-fund JWT secret, two bot tokens);
every same-user process can read every keychain item — a breach of «runtime lacks authority even if compromised» for
NON-money assets, recorded as debt. **The automated runtime cannot move money.**

**Lineage — where the chain breaks.** CIO recommendation (ADR-554, display only) ✗→ books (each allocates its own
$100k) → paper trades (`trades.json`, PT legs, loop events) ✗→ execution layer (no intent handoff) → no on-chain
observation ✗→ reconciliation (`execution/reconciliation.py` tautological: target compared with target; last
2026-06-24) → paper accounting → kill switch / stops → CIO outcomes. The simulation gate is hollow
(`wallet.simulate_transaction` always succeeds).

**Infrastructure.** Keyless `eth_call` 2-of-N quorum against public RPCs already runs (`paper_trading/onchain_read`);
**`eth_call` with a state override is accepted by publicnode, drpc and 1rpc (measured)**; no fork tooling (anvil/forge
absent); no exchange sandbox or keys; `eth_abi`/`eth_account` installed but runtime stays stdlib (invariant #4).

## Inherited blockers (classification)

| Blocker | Class | Why |
|---|---|---|
| No counterparty-risk source (Maple credit, Ethena) | **BLOCKS_ALL_PILOTS** | real capital would carry an unmeasured counterparty; SHADOW_ONLY_OK |
| No custody (no Safe / signer configured) | **BLOCKS_ALL_PILOTS** | nothing to execute a manual pilot from with controls; SHADOW_ONLY_OK |
| No independent (off-host) integrity anchor for decision/shadow ledgers | **BLOCKS_ALL_PILOTS** | `is_real_remote=false`; iCloud copy excludes the CIO ledgers |
| GoLive owner decision pending (`gate_passed_owner_decision_pending`) | **BLOCKS_ALL_PILOTS** | owner subject №1 |
| Live admission: Conservative NOT_APPROVED, Balanced/Aggressive REFUSED | BLOCKS_SPECIFIC_SLEEVE | admission is an owner decision |
| Default grade «B» for unscored protocols (maple, fluid) | BLOCKS_SPECIFIC_SLEEVE (Conservative) | money-path weight on an unscored protocol |
| 0 % mark-to-market on sleeves | BLOCKS_SPECIFIC_SLEEVE (Balanced, Aggressive) | sUSDe/PT price risk not in NAV |
| Immature history (3/30) | BLOCKS_SPECIFIC_SLEEVE (Balanced, Aggressive) | ADR-554 maturity |
| Depeg input hard-coded 0 in `hy_cycle` regime | BLOCKS_SPECIFIC_SLEEVE (Balanced, Aggressive) | fail-open on depeg |
| B/C outside RiskPolicy (caps mirrored, not imported) | BLOCKS_SPECIFIC_SLEEVE (Balanced, Aggressive) | invariant #1 |
| Missing execution adapters (PT market, sUSDe, Morpho borrow) | BLOCKS_SPECIFIC_SLEEVE (Balanced, Aggressive) | no simulatable action path |
| Stale Basis feed (08-29) | BLOCKS_SPECIFIC_SLEEVE (Basis — observe-only) | |
| Trading research: no venue sandbox, no keys | BLOCKS_SPECIFIC_SLEEVE (Trading — observe-only) | a CEX pilot is a separate custody decision |
| Incomplete correlation history | NOT_RELEVANT for a single-sleeve pilot | blocks cross-sleeve sizing only |
| `market_structure` stale «live» label | SHADOW_ONLY_OK | advisory, not read |
| Kill switch `CLEAR_PARTIAL` (fallback used) | must be CLEAR at pilot time | checked at every transition |

## Execution modes (WP-A00)

`RESEARCH` · `PAPER` · `SHADOW` · `MANUAL_PILOT_READY` · `BLOCKED` · `LIVE_AUTOMATION_PROHIBITED`.
There is **no AUTO_LIVE**. `MANUAL_PILOT_READY` = «the deterministic system believes a small OWNER-executed pilot could be
attempted subject to an explicit owner decision» — never permission for automation. The layer's own operating mode is
fixed `SHADOW` with `LIVE_AUTOMATION_PROHIBITED` as a constant, not a setting.

## WP-A03 — authority / two-key boundary

- **AI may:** research, recommend, construct an UNSIGNED intent, simulate (read-only JSON-RPC: `eth_chainId`,
  `eth_call`, `eth_estimateGas`, `eth_getCode`, `eth_blockNumber`, `eth_getBlockByNumber` — an allow-list), shadow,
  reconcile, alert, prepare an owner runbook.
- **AI may not:** sign, broadcast, place an order, transfer. The package `spa_core/capital_shadow` imports nothing from
  `spa_core.execution`, `eth_account`, `web3`, any exchange SDK; its RPC client refuses every method outside the
  allow-list (a `send*`/`sign*`/`personal_*` method raises before any network I/O); it holds no key and accepts no key
  argument. The runtime therefore lacks authority to execute even if compromised (it has no key to sign with).
- **Owner** is the only actor who can cross the money boundary (sign with a device the runtime cannot reach).

## WP-A01 — `CapitalActionIntent` (`capital-intent/1`, immutable, executes nothing)

`intent_id` (sha256 of the canonical semantic fields — same snapshot ⇒ same id) · `created_at` · `expires_at` ·
`source_recommendation_id` · `source_role_id` · `sleeve_id` · `strategy_id` · `action_type`
(`SUPPLY`/`WITHDRAW`/`DEPOSIT_4626`/`REDEEM_4626`/`APPROVE`/`SPOT_ORDER`/`NO_ACTION`) · `network_or_venue` (chain id or
venue) · `instrument` (contract) · `from_asset` · `to_asset` · `notional` + `notional_unit` (token base units and
human) · `expected_price` · `max_slippage` · `expected_fees` · `expected_gas` · `expected_position_after` ·
`risk_snapshot` (kill switch, derisk, RiskPolicy verdict, CIO stance, book state — each with `as_of` and digest) ·
`constraints` · `evidence_refs` · `simulation_required=true` · `owner_action_required=true` · `execution_mode` ·
`reason` · `unknowns` · `scenario` (`CURRENT_STATE` | `TEST_SCENARIO:<name>`) · `policy_version` · `schema_version`.
Missing values are `NOT_MEASURED`/`UNKNOWN` cells (ADR-554 contract helpers). No secret material, ever. When the CIO
abstains, the current-state intent is `NO_ACTION` with the CIO's reason — no action is manufactured.

## WP-A04 — state machine (deterministic, append-only)

`DRAFT → VALIDATED → SIMULATED → SHADOW_READY → SHADOW_EXECUTED → RECONCILED → MANUAL_PILOT_READY → OWNER_GATE`
Failure states: `INVALID · STALE · SIMULATION_FAILED · RISK_BLOCKED · RECONCILIATION_FAILED · EXPIRED · CANCELLED ·
INCIDENT`. **No transition leads to execution.** `OWNER_GATE` is terminal for the machine: crossing it is an owner act
outside the system. Each transition appends one evidence record; transitions are keyed `(intent_id, to_state)` —
a repeated transition is idempotent (no duplicate record), an illegal one is refused. Before `SHADOW_EXECUTED` and
before `MANUAL_PILOT_READY` the risk snapshot is RE-READ (TOCTOU guard): any change in kill switch, derisk, RiskPolicy
verdict/version, CIO recommendation id or book state digest ⇒ `RISK_BLOCKED` / `STALE` (a new intent is required).

## WP-A05 — reconciliation

Compares intended → simulated → shadow-accounted, per field: cash before, position before, intended delta, fees,
gas, slippage, fills/partial fills, cash after, position after, NAV impact, unrealised/realised PnL, residual
exposure, drift vs target. Outcomes `MATCHED · PARTIAL · MISMATCH · NOT_MEASURED · FAILED`; tolerances are declared per
field (no invented precision); a field the simulation cannot observe is `NOT_MEASURED`, never assumed equal. **MISMATCH
or NOT_MEASURED on a mandatory field blocks MANUAL_PILOT_READY.** The shadow ledger is hypothetical state, labelled
as such; the books remain the only paper accounting truth (no second source of truth).

## Simulation (WP-S02/S03)

On-chain: stdlib keccak-256 + ABI encoding (selectors computed, verified against known vectors), allow-listed JSON-RPC,
2-of-N quorum. Per action: `eth_chainId` must equal the intent's chain; `eth_getCode(instrument)` non-empty;
`decimals()` read and checked against the registry; balance/allowance established by **state override** of the token's
storage (balance slot per token, declared and verified by reading back `balanceOf`); `eth_call` of the action from a
fresh synthetic address (not a funded wallet) ⇒ revert reason or return data; `eth_estimateGas` with the same override;
post-state expectation: ERC-4626 `previewDeposit` vs the call's returned shares; Aave/Comet: success + expected
position token delta where readable. Venues in v1: Ethereum mainnet Aave v3 Pool, Compound v3 Comet USDC, ERC-4626
vaults (fluid fUSDC; Morpho vaults where the chain RPC supports overrides); unsupported venue ⇒ `NOT_MEASURED`
(blocks), never «assume ok». Centralised trading: no sandbox exists ⇒ deterministic local exchange simulator (public
filters only: tick, lot, min notional, fee) for order-shape validation; it never falls back to production.

## Idempotency and concurrency

`intent_id` = content hash ⇒ the same snapshot cannot create two intents; ledger append is under `flock`, verifies the
hash chain, refuses a duplicate `(intent_id, state)` key; a shadow fill is keyed `(intent_id, fill_seq)`; a crash
mid-run leaves only whole lines (single `os.write` + `fsync`), the next run resumes from the last recorded state.
External anchor in a sibling directory (as ADR-554).

## WP-A06 — failure model (frozen safe responses)

| # | Failure | Safe response |
|---|---|---|
| 1 | stale recommendation | intent `STALE`, no simulation |
| 2 | stale quote | `STALE`, re-quote required |
| 3 | stale oracle / price | `STALE` |
| 4 | quote changes before action | re-simulate; drift > max_slippage ⇒ `SIMULATION_FAILED` |
| 5 | RPC unavailable / no quorum | `NOT_MEASURED` ⇒ blocks; never single-witness |
| 6 | API unavailable | `NOT_MEASURED` |
| 7 | exchange 429 | back-off, `NOT_MEASURED` this run |
| 8 | exchange 500 | `NOT_MEASURED` |
| 9 | transaction revert (simulated) | `SIMULATION_FAILED` with reason |
| 10 | failed simulation (malformed) | `SIMULATION_FAILED` |
| 11 | excessive gas | `RISK_BLOCKED` (gas > declared ceiling) |
| 12 | excessive slippage | `SIMULATION_FAILED` |
| 13 | partial fill | reconciliation `PARTIAL` ⇒ blocks readiness |
| 14 | duplicate submission (same intent) | idempotent: second append refused/no-op |
| 15 | lost response after submission | N/A in shadow (no submission); runbook requires owner to check by tx hash before retry |
| 16 | nonce conflict | N/A (no signing); runbook names it |
| 17 | chain reorg | simulation pinned to a block; re-run on next block, compare |
| 18 | wrong chain | `eth_chainId` mismatch ⇒ `INVALID` |
| 19 | wrong token address | registry mismatch / no code ⇒ `INVALID` |
| 20 | token-decimal mismatch | `INVALID` |
| 21 | insufficient allowance | simulated revert ⇒ `SIMULATION_FAILED` (intent must include approve) |
| 22 | excessive allowance | `RISK_BLOCKED` (approve must equal the amount, never unlimited) |
| 23 | insufficient wallet balance | N/A (no wallet); runbook prerequisite |
| 24 | depeg | price input outside band ⇒ `RISK_BLOCKED` |
| 25 | strategy enters HOLD after intent | TOCTOU re-read ⇒ `RISK_BLOCKED` |
| 26 | kill switch changes after simulation | TOCTOU re-read ⇒ `RISK_BLOCKED` |
| 27 | RiskPolicy changes after simulation | version/verdict digest mismatch ⇒ `RISK_BLOCKED` |
| 28 | CIO recommendation superseded | id mismatch ⇒ `STALE` |
| 29 | process crash mid-run | whole-line ledger; resume from last state; no duplicate |
| 30 | corrupted journal | chain/anchor verify fails ⇒ `INCIDENT`, read model BROKEN, repair only torn tail |
| 31 | concurrent runners | `flock`; loser exits 75; no interleaved lines |
| 32 | intent expired | `EXPIRED` |

## Readiness (`PilotReadinessReport`, `pilot-readiness/1`)

Per sleeve, every field from the epic list. State ∈ `NOT_READY · SHADOW_READY · MANUAL_PILOT_READY · BLOCKED`.
`SHADOW_READY`: fresh data, an intent constructible for the sleeve's venues (scenario mode allowed), simulation
passed, reconciliation MATCHED, no shadow-level blocker. `MANUAL_PILOT_READY`: SHADOW_READY AND every mandatory gate
PASS — strategy evidence MATURE, risk (RiskPolicy coverage), protocol (no default grade), counterparty, liquidity,
mark-to-market, reconciliation, simulation, custody, rollback, incident response, observability, off-host anchor,
live admission APPROVED, kill switch CLEAR. **UNKNOWN fails closed.** `BLOCKED`: an active hard block (kill switch,
incident, broken ledger). The runbook generator runs only for a MANUAL_PILOT_READY sleeve; amount is always
`OWNER_DECISION_REQUIRED`.

## Guards (WP-S08) and hardening

AST/import tests: `capital_shadow` imports no forbidden module and names no send/sign method; the RPC allow-list test
calls every forbidden method and expects a refusal before I/O; no plist, wrapper or `launchctl` env may contain
`SPA_PRIVATE_KEY`/`SPA_EXEC_ARMED`; no non-test caller builds `PaperTrader(live_execution=True)`; `eth_signer.sign_message`
gets the same arm guard as `sign_transaction`; signing paths also consult `LiveTradingGate.active` (stricter only).
cloudflared reads its token from the environment (not argv).

## Mission Control

Capital tab, section «Live readiness / shadow»: execution mode, «automated live execution: PROHIBITED», real capital
$0, sleeve readiness, top blockers, last simulation, last shadow execution, reconciliation, incidents, recovery, and
whether an owner action is currently possible. No execute/deploy/sign button.

## Package

`spa_core/capital_shadow/` (`contract`, `keccak`, `abi`, `rpc`, `simulate`, `exchange_sim`, `intent`, `machine`,
`ledger`, `reconcile`, `readiness`, `runbook`, `run`, `read`), data `data/capital_shadow/` (+ anchors sibling),
agent `com.spa.capital_shadow` (daily, after the CIO). Distinct from the pre-existing `spa_core/shadow` (advisory
shadow allocator), which is not touched.

## Revision after the independent architecture review (2026-10-04) — BINDING, supersedes conflicting text above

Sixteen findings (1 CRITICAL, 7 HIGH). Every one is accepted. The binding design is:

1. **Runbook ≠ signing payload (CRITICAL).** The runbook never contains raw calldata or hex to paste. It contains:
   - contract address (from a pinned registry), method signature, selector and every argument in human-readable form,
     amount as `OWNER_DECISION_REQUIRED`;
   - the expected receiver / `onBehalfOf` = the owner's own Safe;
   - simulation evidence (block, block hash, witnesses);
   - abort criteria.

   A separate command, `python -m spa_core.capital_shadow.verify --intent <id> --payload <what the wallet shows>`,
   decodes the payload, diffs it field by field against the intent and the pinned registry, re-simulates at the
   current block, and re-reads kill switch / RiskPolicy digest / CIO id / depeg. Any difference ⇒ ABORT. The owner
   signs only with clear-signing on a hardware device.
2. **What simulation proves.** Every simulation record is labelled `SIMULATED_UNDER_ASSUMED_STATE` and carries a
   fixed `not_proven` list: the real wallet's balance / allowance / nonce; Safe threshold and modules; gas price at
   inclusion; MEV and sandwich; oracle or rate movement between simulation and inclusion; allow-list, KYC and
   blacklist. Rules:
   - balance AND allowance are overridden through slots declared per token and per implementation version, and
     verified by reading back `balanceOf` / `allowance`;
   - permissioned venues (Maple, KYC vaults) are `NOT_SIMULATABLE`, which blocks;
   - a pilot needs a pre-sign re-simulation from the real Safe at the current block (owner side, `verify`).
3. **Pinned block, independent operators.** Block number and block hash are taken by quorum first; every call and
   estimate runs at that explicit block; witnesses must agree on the hash. Operators are declared (publicnode —
   Allnodes; drpc — dRPC; 1rpc — Automata). Fewer than 2 independent operators answering ⇒ `NOT_MEASURED`. The trust
   model is stated in every report: «consistency of public RPCs, not verified state — no light client».
4. **Reconciliation is a forward test, not a self-comparison.**
   - Simulated shares are compared with `previewDeposit` / `convertToAssets` re-read later at a pinned block.
   - The simulated position value at N+k is compared with the paper book's own mark for the same position.
   - A post-execution reconciler reads the owner's Safe position by address (keyless quorum); with no Safe
     configured it is `NOT_MEASURED`.
   - Until a real pilot is reconciled MATCHED, the sleeve is `AWAITING_RECONCILIATION`. `PARTIAL` for on-chain venues
     is reserved for that real-execution reconciler.
5. **Double submission and approval replay.**
   - `intent_id` includes the pinned block, so a legitimate repeat is a new intent.
   - At most ONE outstanding owner action per sleeve: no new runbook while an earlier one is not
     EXPIRED / CANCELLED / RECONCILED against an observed tx hash.
   - An owner approval recorded by the system binds `intent_id + block + expires_at` and is single-use.
6. **Readiness is not authorization.** The report splits into:
   - `system_checks`: machine gates only, independent of owner decisions;
   - `owner_preconditions`: GoLive, live admission, custody, amount — each `GRANTED` | `PENDING` with a decision
     reference.

   The top state `MANUAL_PILOT_READY` means all system checks PASS. It is displayed as «Eligible for owner review —
   NOT authorized» and is never green. A test asserts it is unreachable today: four BLOCKS_ALL_PILOTS system blockers.
7. **No vacuous gates.**
   - Each gate has a probe with positive and negative controls; «all mandatory gates PASS» is set equality against a
     frozen gate list, so an empty or short list is FAIL.
   - `rollback` is replaced by `unwind_path`: a simulated WITHDRAW/REDEEM for the same position passes, measured
     available liquidity ≥ 3 × the position, and withdrawal latency is measured (Maple queue / PT before maturity ⇒
     FAIL).
8. **Off-host anchor — a named mechanism.**
   - Mechanism: the ledger head hash is published to `origin` (GitHub) through the existing delivery path, and the
     gate verifies the REMOTE copy against the local ledger.
   - Until that publication exists the gate is FAIL (`is_real_remote=false` stays FAIL). A sibling directory never
     satisfies it.
9. **TOCTOU at the signing gap.** Readers compute expiry from `now`, never from stored state; a pilot runbook expires
   in ≤ 1 h; `verify` immediately before signing is mandatory.
10. **Writer ≠ certifier.** `run` writes intents / simulations / ledger. `read` is a separate read-only verifier: it
    recomputes the readiness verdict from the ledger and anchors and verifies the chain. Mission Control, Telegram
    and the runbook renderer show only the verifier's result.
11. **Intent source.**
    - The intent comes from the book's own paper trade (already gated by `cio_arming.gate_sleeve_book`; current
      verdict HOLD ⇒ `NO_ACTION`).
    - The ADR-554 CIO recommendation id is kept in `risk_snapshot` as a consistency check; disagreement ⇒ `NO_ACTION`
      with the reason. Nothing is manufactured.
12. **UNKNOWN never becomes safe.**
    - A missing price or depeg reading ⇒ `NOT_MEASURED` ⇒ blocks.
    - Snapshot cells carry provenance; known hard-coded inputs (e.g. `hy_cycle` depeg 0.0) are rejected as
      measurements.
    - `TEST_SCENARIO` intents can reach at most `SHADOW_EXECUTED`; they can never reach `MANUAL_PILOT_READY` or a
      runbook (type-level, tested).
    - The exchange simulator never feeds a sleeve verdict.
13. **Guards that cannot be bypassed by construction.**
    - Only `capital_shadow/rpc.py` may import `urllib` / `http` / `socket` / `ssl`.
    - No `importlib`, `__import__`, `exec`, `eval`, `subprocess`, `os.system` anywhere in the package.
    - The client builds every payload itself, refuses batch arrays, and matches method names exactly against a frozen
      set.
    - A forbidden-method attempt is a SECURITY incident (alert), not only an exception.
14. **Incidents are sticky.** INCIDENT never auto-clears.
    - Owner alert via the existing Telegram alert path on: ledger/anchor break, forbidden-method attempt, quorum value
      disagreement (not mere unavailability), an unexpected position on the owner's Safe.
    - Clearing needs a recorded repair with evidence; with a pilot position open, clearing is the owner's.
15. **Signer hygiene.** The environment-key path in the dormant signer refuses (an owner-held hardware signer is the
    only intended path). `LiveTradingGate` consultation is defence in depth only — its state file is writable by the
    same user, and this is stated.
16. **Mission Control wording.** «Owner decisions pending: N»; fixed banner «Readiness is not authorization · real
    capital $0»; nothing past SHADOW_READY is green; no execute/deploy/sign button.

## Implementation notes (2026-10-04)

- **Simulation is real.** A pinned block is agreed on its hash by independent operators (Allnodes, dRPC, Automata).
  Balance and allowance slots are overridden and verified by reading them back. Amounts are scaled by token
  decimals at exactly one point (`tokens.to_base_units`). Live evidence:
  - fluid fUSDC `deposit` of 1000 USDC returns exactly `previewDeposit` shares (≈ 820.2 M fUSDC base units), gas
    142,048;
  - Aave v3 `supply` passes every check, gas ≈ 212 k.

  Maple is `NOT_SIMULATABLE` (permissioned). Base-chain Morpho is `NOT_MEASURED`: no override-capable quorum is
  declared for chain 8453. Withdrawals on Aave/Compound are `NOT_MEASURED`: no position-token slot is declared.
- **The forward reconciliation is real.** A later run re-reads `previewDeposit` / code / `asset()` at a strictly
  later block. Mandatory fields are declared per action.
  - `book_mark` — the shadow position against the paper book's own mark — is mandatory for CURRENT-STATE intents.
  - A TEST_SCENARIO canary has no book position: for it `book_mark` is named «not applicable» and never assumed
    equal.
  - Canary evidence lives under the non-candidate sleeve `scenario_canary` and a `venue_canary` section, and never
    reaches a sleeve gate.
- **Production profile:** `com.spa.capital_shadow` runs daily at 09:45 with `--live-rpc --scenario daily_canary`.
  Current-state intents are `NO_ACTION` when the CIO abstains or the book says HOLD — both reasons are named.
- **Hardening delivered.**
  - The env-key signing path is removed from the dormant signer and all 7 execution adapters
    (`arming.refuse_env_private_key`).
  - `eth_signer.sign_message` is `@live_trading_forbidden` and additionally armed- and `LiveTradingGate`-checked.
  - Dead env-key reads are gone; an AST guard sweeps all of `spa_core/execution/`.
  - No plist, wrapper or installed agent may carry `SPA_PRIVATE_KEY` / `SPA_EXEC_ARMED` (test).
  - No non-test caller may build `PaperTrader(live_execution=True)` (test).
  - cloudflared receives its token through `TUNNEL_TOKEN` instead of argv.
  - The three plaintext secret-shaped files in `~` / `~/Documents` are now mode 600. Rotating or deleting them is
    the owner's call.
- **Stated limits.**
  - `LiveTradingGate` is consulted by `sign_message` but not by `sign_transaction`. `sign_transaction` stays blocked
    by `SPA_EXEC_ARMED`, and its callers by `@live_trading_forbidden`. The gate file is writable by the same user —
    defence in depth only.
  - The earn-defi `LiveExecutor` (separate repo) does not enforce `check_limits` itself — recorded as debt.
  - Every keychain item is readable by any same-user process. These are non-money credentials: GitHub PAT, tunnel
    token, family-fund JWT secret, bot tokens, the Cloudflare refresh token in `~/.wrangler`. Recorded as debt;
    splitting the keychain or logging out of wrangler is the owner's choice.

## Post-implementation review (2026-10-04) and remediation

Fifteen findings: 1 CRITICAL, 7 HIGH, 5 MEDIUM, 2 LOW. No path to money or signing was found. All fixed, each with
a test that fails without the fix.
- **#1** — `verify` decodes only against the action's registry signature and compares field by field: target =
  pinned address, asset, exact base-unit amount, receiver/onBehalfOf = Safe, approve spender and exact amount. It
  checks expiry from now, requires the current risk state (kill switch CLEAR, derisk off, RiskPolicy PASS, depeg
  MEASURED), and re-simulates from the Safe (`sender=`). The reproduced `transfer(attacker)` attack now ABORTs.
- **#2** — the runbook builds arguments from the registry and the intent only; asserts are replaced by explicit
  refusals, proven under `python -O`.
- **#3** — canary isolation (as above).
- **#4** — decimals scaling.
- **#5** — security events, including a minority dissent in a satisfied quorum, are escalated into sticky incidents
  by the pipeline. A ledger break raises an incident before exit.
- **#6** — one outstanding owner action per sleeve; approvals are bound to intent + block + expiry and single-use.
- **#7** — intents come only from recorded book trade deltas, keyed by trade id (never replayed). A missing field
  gives NO_ACTION, never a default.
- **#8** — dangerous or unknown CURRENT risk (kill switch not exactly CLEAR, derisk, RiskPolicy not PASS, depeg not
  measured) blocks both intent building and `recheck`. Depeg is folded into `risk_evidence`.
- **#9** — `book_mark`; NOT_MEASURED reconciliations are retried until expiry; the dead self-compare is removed.
- **#10** — no missing-as-zero in fills, policy checks or gates.
- **#11** — the incident store is hash-chained and anchored; clearing ledger/anchor/position incidents needs an
  owner confirmation token; repair records a `ledger_repaired` incident and never silently certifies a tail.
- **#12** — no action intent without a MEASURED pin; expiry is checked before idempotency.
- **#13** — the failure matrix induces conditions through the real RPC client and simulator, a run-level lock, and
  real concurrent processes.
- **#14** — the execution leftovers above.
- **#15** — exchange_sim cash/position checks and PARTIAL status; Mission Control labels scenario evidence.

## Second independent re-review (2026-10-04) and remediation — N1–N8

The second reviewer re-read the code after the first remediation. All eight findings are fixed; each fix has a
regression test that was shown red without the fix.

- **N1** — `verify` requires READY state AND fresh risk files (`freshness_check`, 26 h, fail-closed); the
  readiness `kill_switch_clear` gate delegates to the same check, so a stale CLEAR fails.
- **N2** — the APPROVE amount check compares base units (`intent.to_base_units_for_intent`, the same scaling
  authority as the simulator), exact integer equality.
- **N3** — owner confirmation is an out-of-band file `data/capital_shadow/owner_confirmations/<incident>.json`
  carrying the incident's nonce; the runtime never writes it; empty evidence, missing file and wrong nonce are
  refused.
- **N4** — the read summary reports a broken incident store as `BROKEN` (`incidents.store_state`), never as zero
  open incidents; Mission Control shows CRITICAL.
- **N5** — `venue_canary` is its own top-level key, never inside the six-sleeve readiness map.
- **N6** — a blocked trade stays retry-eligible until the shadow TTL, then is finalised exactly once. Found while
  writing the test: the final NO_ACTION collided with the retry row on the frozen id fields and was silently
  dropped by idempotency; fixed by date scoping.
- **N7** — alerts from runs whose data dir is not the production `data/` go to a local outbox, never to
  production alert channels.
- **N8** — repair never re-anchors on its own: a missing tail anchor raises an incident and waits for owner
  confirmation.
- Plus the remainders: security events from every client (pin, forward reconciliation) escalate once per event;
  exchange rows 5/6/7 use a labelled injectable fetcher with the real `exchange_sim` as control, row 34 induces a
  real PARTIAL fill and expects NOT_MEASURED; the observability gate is an allowlist (`OK`/`HEALTHY`).

## Final re-review (2026-10-04) — round 3 remediation

The second reviewer re-probed the N1–N8 fixes adversarially. N1–N5, N8, the RPC allow-list, no-sign/no-broadcast,
TEST_SCENARIO readiness, the observability allowlist and `kill_switch_clear` were CLOSED. The items below were open
or new; each is now fixed with a test shown red without the fix.

- **N6** — the retry window was the 6 h intent TTL, but the agent runs once a day, so a trade blocked on day 1 was
  finalised before day 2 could retry it. New `intent.TRADE_RETRY_WINDOW_S` = 72 h (≥ 3 daily cycles); the intent
  TTL is unchanged.
- **N7 / M2** — production was recognised through the env-overridable `live_data_dir()`, so a sandbox named by
  `SPA_DATA_DIR` got the real alert dispatcher and vice versa. Detection is now structural (the code tree's own
  `data/`, environment ignored). Separately, `run.main` defaulted to the CWD-relative `data` and ignored
  `SPA_DATA_DIR`, so the pre-deploy gate's trial run on 2026-10-04 08:13 wrote into production
  `data/capital_shadow` (harmless: it is the agent's own store, the run was the agent's normal run). The default is now
  `live_data_dir()`.
- **Row 34 / PARTIAL fill** — the row asserted a hard-coded literal, and the real pipeline booked a partial
  exchange fill as SIM_PASS. A PARTIAL fill is now `result=PARTIAL` → `SIMULATION_FAILED`; the row drives the real
  run path.
- **M1** — repair treated a mid-chain payload tamper whose line still parsed as a "torn tail" and moved legitimate
  rows aside. Repair now fixes only an unparseable or hash-broken LAST line that was never anchored; any earlier or
  anchored break is `ledger_tampered`: incident raised, file byte-identical.
- **L1** — unresolvable base units or a non-integer amount in an APPROVE is a policy violation (fail-closed).
- **L3** — security events are escalated once per event identity across pin, simulation and reconciliation, even
  through one shared client.
- **L4** — any kill-switch state other than exactly `CLEAR` counts as armed (the real writer publishes `TRIGGERED`,
  `UNMEASURED`, `CLEAR_PARTIAL`).
- **L5** — evidence rows are excluded from a real sleeve by their owning intent's scenario, not only by sleeve id;
  one case-insensitive `intent.is_test_scenario` replaces five copies. Measured on production: all 48 TEST_SCENARIO
  rows carry `scenario_canary`.
- **L6** — clearing an incident twice is refused. Stated plainly: the owner nonce is in plaintext in
  `incidents.jsonl`; the out-of-band file stops the runtime from clearing its own incidents (no code path writes a
  confirmation), not a hostile process running as the same OS user.

- **Re-verification of round 3** by the same reviewer: N6, N7/M2, row 34 with the PARTIAL path, L1, L3, L4, L6
  CLOSED. Two residuals and one side effect were then fixed, each with a test shown red without the fix:
  **M1-r** — an anchored last row cut short to unparseable was still "repaired"; an unparseable line whose position
  is anchored is now tampering. **L5-r** — `readiness._scenario_intent_ids` kept its own case-sensitive prefix
  check; it now calls `intent.is_test_scenario`. **L-new** — with `SPA_DATA_DIR` unset the default data dir fell
  back to the LIVE tree, so a worktree run appended to the production ledger; the default is now `SPA_DATA_DIR`,
  else this code tree's own `data/`.
- Accepted, recorded rather than fixed: two identical `forbidden_method` attempts collapse into one incident (the
  attempt count is lost, the escalation is not); emptying both `incidents.jsonl` and its LOCAL anchors reads as
  zero incidents — the local anchor is not an off-host witness, which is exactly why `offhost_anchor` is a hard FAIL;
  `verify.expected_amount_base_units` is a second scaling helper (it fails closed where it diverges).

## Final evidence (2026-10-04)

- Tests: capital_shadow + Mission Control + guards + ratchets + execution hardening — **3351 passed, 1 skipped** (pre-existing).
- Failure matrix: **34 induced failures, 0 failing**.
- Recovery drill (copy of production data, `--no-rpc`): restart duplicates nothing (24 → 24 rows); corrupt or
  missing `latest.json` is rebuilt from the ledger; truncated tail, tampered row and missing anchors all give
  integrity BROKEN, readiness withheld, Mission Control CRITICAL, exit 2; repair refuses tampering and waits for
  owner confirmation on a torn anchor; a broken incident store gives CRITICAL; readiness never became green.
- Verdict on production data (after round 3, 2026-10-04 07:05Z): the three DeFi sleeves **BLOCKED** (kill switch
  `CLEAR_PARTIAL` counts as armed — L4), cash / trading_research / market_neutral_basis **NOT_READY**; none is
  SHADOW_READY or MANUAL_PILOT_READY; no runbook generated; real capital $0; automated live
  execution PROHIBITED; no real transaction or order was submitted.
