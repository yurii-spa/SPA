# ADR-011 — Engine Live-Execution Bridge (FEAT-004/005 Phase 4)

* Sprint: v3.11 (SPA-V41-001)
* Status: Accepted (2026-05-27)
* Supersedes/extends: ADR-009 (Aave V3 live writes), ADR-010 (Compound V3
  live writes). Both Phase 3 cards explicitly deferred the engine cutover
  to "Phase 4 behind a per-strategy `live_execution` flag" — this ADR
  closes that loop.
* Author: claude-agent
* Reviewers: yurii-spa

## Context

After Sprints v3.9 (FEAT-004 Phase 3) and v3.10 (FEAT-005 Phase 3) we have
fully-signed `supply()` / `withdraw()` paths on `AaveV3Adapter` and
`CompoundV3Adapter`. Both are gated behind `SPA_EXECUTION_MODE=live` and
never raise — every failure mode returns a structured `{"status":
"FAILED|BLOCKED|ERROR", "reason": ...}` dict.

However, the paper-trading engine (`spa_core/paper_trading/engine.py`) has
never called those adapters. `PaperTrader.open_position` /
`close_position` write rows to the SQLite `paper_trades` table and stop
there. The 100+ existing call-sites that instantiate `PaperTrader()` (CLI,
scheduled orchestrator, agent layer, tests, dashboard, replay tool, …)
must continue to work BYTE-IDENTICALLY in paper mode.

We need a path that lets one specific strategy (or one specific CLI
invocation) opt in to the live execution leg WITHOUT changing the default
behaviour of any other caller.

## Decision

Introduce a thin façade — `spa_core.execution.engine_bridge.LiveExecutionBridge`
— and a single new constructor flag on `PaperTrader`:

```python
PaperTrader(db_path=..., live_execution=False)   # ← default, unchanged
PaperTrader(db_path=..., live_execution=True)    # ← opts in to bridge
```

The bridge is invoked **only when both** `live_execution=True` **and**
`SPA_EXECUTION_MODE=live` at call time. Anything else returns a
structured `{"status": "SKIPPED", "reason": "..."}` and the bridge becomes
a no-op.

### Multi-layer safety stack

1. **`live_execution=False` (default)** — `_get_live_bridge()` returns
   `None` immediately. No import, no instantiation, no side effects. This
   is the regression gate that protects the 100+ existing call-sites.
2. **`live_execution=True` + `SPA_EXECUTION_MODE != "live"`** — the bridge
   returns `{"status": "SKIPPED", "reason": "execution_mode_paper"}`
   without touching any adapter.
3. **Unparseable `protocol_key`** (e.g. `"not-a-protocol"`,
   `"pendle-pt-steth-arbitrum"`) — returns `{"status": "SKIPPED", "reason":
   "unparseable_protocol_key"}` and logs the bad key to the audit file so
   operators see it.
4. **Unsupported chain on a known family** (e.g. `aave-v3-usdc-solana`) —
   `AaveV3Adapter("solana")` raises `ValueError` at construction; the
   bridge catches it and returns `{"status": "SKIPPED", "reason":
   "unsupported_protocol"}`.
5. **Adapter exception** (defensive — adapters guarantee they don't raise)
   — the bridge wraps every `supply()` / `withdraw()` call in `try/except`
   and synthesises `{"status": "ERROR", "reason": "adapter raised: ..."}`.
6. **Adapter returns FAILED / BLOCKED / ERROR** — the bridge returns the
   adapter's dict verbatim (augmented with `bridge_action`, `protocol_key`,
   `family`, `amount_usd`, `timestamp`), logs a WARNING, and writes the
   row to the audit log. `PaperTrader.open_position` logs the failure and
   continues with the paper INSERT regardless.

### Paper book is source-of-truth

Both `open_position` and `close_position` always perform the SQLite
`paper_trades` write, regardless of what the bridge returns. This keeps
the dashboard / Sharpe / drawdown math consistent even when the live leg
flakes for hours. The on-chain leg is purely ADDITIVE.

### Routing

`_parse_protocol_key(protocol_key)` splits a SPA-canonical key into a
3-tuple:

| Input                          | family        | asset | chain    |
|--------------------------------|---------------|-------|----------|
| `aave-v3-usdc-ethereum`        | `aave_v3`     | USDC  | ethereum |
| `aave-v3-dai-base`             | `aave_v3`     | DAI   | base     |
| `aave-v3-usdt-arbitrum`        | `aave_v3`     | USDT  | arbitrum |
| `compound-v3-usdc-ethereum`    | `compound_v3` | USDC  | ethereum |
| `compound-v3-usdc-arbitrum`    | `compound_v3` | USDC  | arbitrum |
| `compound-v3-usdc-base`        | `compound_v3` | USDC  | base     |
| anything else                  | `None`        | —     | —        |

The parser is permissive on input case (`"AAVE-V3-USDC-ETHEREUM"` works)
but strict on shape — anything that doesn't match a known prefix or that
lacks both `<asset>` and `<chain>` segments returns `None`.

For withdraws, `close_position` reads the protocol key from each open
`paper_trades` row directly (already in the DB) so the live withdraw
always targets the exact protocol the position was opened on. No
cross-protocol surprises.

### Lazy adapter import

Adapter classes are imported **inside** `LiveExecutionBridge._get_adapter`
(not at module top). This:

  * Keeps `engine.py` startup time unchanged for the 99% paper case.
  * Avoids pulling `eth_account` into test runs that don't touch the
    bridge (the import in the adapter is itself already lazy, but the
    bridge can short-circuit even earlier).
  * Caches per-`(family, chain)` so a hot rebalance loop doesn't re-pay
    construction cost.

### Audit log

Every non-skipped bridge invocation (SUCCESS, FAILED, BLOCKED, ERROR, or
SKIPPED-due-to-bad-key) appends a row to
`data/live_execution_log.json`. The file is a flat JSON array (not
JSON-lines) for trivial dashboard inspection. We cap at `LOG_MAX_ENTRIES
= 1000`; on each append the file is loaded, the new entry is pushed, and
if length > 1000 we trim the oldest entries before writing. All I/O is
wrapped in `try/except` and any audit failure is logged at WARNING but
never propagated — the audit log is **never allowed to block a paper
trade**.

The "SKIPPED due to `execution_mode_paper`" branch deliberately does NOT
log. That outcome is the steady-state for ~all callers, and writing 6
audit rows per rebalance for "nothing happened" would drown the signal.

## Consequences

### Positive

* Zero behavioural change for every existing call-site (regression
  proven via `test_default_live_execution_flag_is_false` and
  `test_default_trader_does_not_init_bridge_on_open`).
* A single per-strategy flag turns live execution on for one strategy
  without affecting any other. This unlocks the v4.0 "shadow mode" —
  run two `PaperTrader` instances side-by-side, one paper-only and one
  with `live_execution=True`, on the same DB and compare divergence.
* Structured failure semantics — no surprises in the paper book even
  when RPCs flake, adapters break, or chains de-peg.
* Full audit trail in `data/live_execution_log.json` with a hard
  rotation cap so the file size is bounded.

### Negative / risks

* The bridge currently dispatches **per individual `open_position` /
  `close_position` call**. A strategy that opens 8 positions in one
  rebalance cycle will fire 8 separate adapter calls. Batching is
  deferred to Phase 5 (FEAT-007 — multi-call routing).
* When live execution succeeds but the paper INSERT later fails (e.g.
  SQLite write error), the two views will diverge. Mitigation: the paper
  INSERT is single-row and runs immediately after the bridge call inside
  the same Python function; in practice this is a non-issue. A formal
  two-phase commit is out of scope for v3.11.
* No partial-fill handling. If the adapter returns SUCCESS but the
  on-chain amount differs from `amount_usd` (e.g. slippage on a wrapped
  flow), the paper book still records `amount_usd`. Phase 5 will read
  back the receipt amount and reconcile.

## Alternatives considered

1. **Direct adapter calls from `engine.py`.** Rejected — couples engine
   to two adapter modules + their imports, makes the multi-layer gate
   harder to unit-test, and prevents future adapters (Morpho, Yearn)
   from plugging in without engine edits.
2. **Make the bridge a class method on `ExecutionRouter`.** Rejected —
   the router (ADR-008) is currently a pure dispatch helper for
   adapter-side decisions (APY arbitration, risk gates). Adding
   audit-log + env-var gate concerns to it would muddle its
   responsibility. The bridge is a separate concern.
3. **Synchronous "wait for receipt" in `open_position`.** Already done
   by the adapter (30s poll). The bridge just forwards the result; the
   engine doesn't add another wait layer.
4. **Append to the audit log via JSON-lines instead of an array.**
   Slightly faster on append but requires a separate rotation tool and
   makes ad-hoc dashboard reads harder. We chose the array format and
   accept O(N) rewrite per entry because N ≤ 1000.

## Operational notes

To enable live execution for a specific run:

```bash
export SPA_EXECUTION_MODE=live
export SPA_PRIVATE_KEY=0x...          # 64 hex chars
export SPA_WALLET_ADDRESS=0x...        # optional; must match derived address

python -c "from spa_core.paper_trading.engine import PaperTrader; \
           PaperTrader(live_execution=True).open_position( \
               'aave-v3-usdc-ethereum', 100.0, 4.65, 138e6)"
```

To audit what the bridge did:

```bash
cat data/live_execution_log.json | jq '.[-5:]'
```

To disable live execution mid-run: just unset `SPA_EXECUTION_MODE`. The
next bridge call returns `{"status": "SKIPPED", "reason":
"execution_mode_paper"}` and the engine continues paper-only.

## Tests

`spa_core/tests/test_engine_bridge.py` — 37 deterministic tests covering:

  * `_parse_protocol_key` happy paths + 9 malformed-input parametrisations
  * `SPA_EXECUTION_MODE` env gate (5 variants)
  * SKIPPED branches (paper mode, unparseable key, unsupported protocol)
  * Live SUCCESS path for both Aave and Compound families
  * Adapter-returns-FAILED / BLOCKED / raises-exception (all logged, none raise)
  * `live_execution=False` regression gate (most important — proves
    default behaviour is byte-identical)
  * `live_execution=True` engine→bridge wiring
  * Audit log rotation at `LOG_MAX_ENTRIES=1000`
  * Audit log handles missing / corrupted files gracefully
  * Paper INSERT still happens when live leg returns FAILED
