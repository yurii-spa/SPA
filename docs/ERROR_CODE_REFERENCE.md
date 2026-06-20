# SPA Error Code Reference

Version: 10.50  
Generated: 2026-06-20  
Source: `spa_core/utils/errors.py` (MP-1382 v9.98)

---

## Error Hierarchy

```
SPAError (base)                     — spa_core/utils/errors.py
├── GateError                       — CPA gate failures (4-state gate system)
├── SourceError                     — Data source unavailable or invalid
├── ValidationError                 — Field-level validation failure
├── KANBANError                     — KANBAN.json operation failures
├── AdapterError                    — DeFi adapter fetch/parse failures
├── ConfigError                     — Missing or invalid configuration
├── AtomicWriteError                — Atomic file write (tmp+os.replace) failed
├── RegistryError                   — Adapter/module not found in a registry
├── RiskPolicyError                 — RiskPolicy violation detected
├── AllocationError                 — Invalid allocation or constraint violation
└── LiveTradingForbiddenError       — Live trading attempted before gate PASS
```

All exceptions carry:
- `code` — machine-readable string (e.g. `"GATE_LIVE_BLOCKED"`)
- `details` — free-form dict with contextual information
- `to_dict()` — JSON-safe serialisation for logging and API responses

---

## Error Codes by Class

### SPAError (base)

| Code | Description | Raised By |
|------|-------------|-----------|
| `SPA_UNKNOWN` | Default code when none specified | `SPAError` base |
| `NOT_INITIALIZED` | Method called before required compute step | `analytics/*.py` |
| `NO_OPEN_POSITION` | Protocol has no open position to close | `paper_trading/engine.py` |

### GateError

Auto-generates code as `GATE_<GATE>_<STATUS>` (uppercased, dashes → underscores).

| Code Pattern | Example | Description | Raised By |
|---|---|---|---|
| `GATE_<name>_FAIL` | `GATE_BACKTEST_FAIL` | Gate returned FAIL status | `backtesting/gate.py`, `safety/live_trading_gate.py` |
| `GATE_<name>_NOT_READY` | `GATE_PAPER_NOT_READY` | Gate not in PASS state | `backtesting/gate.py` |
| `GATE_<name>_UNKNOWN` | `GATE_LIVE_UNKNOWN` | Gate file missing or corrupt | `backtesting/gate.py` |
| `GATE_<name>_BLOCKED` | `GATE_LIVE_BLOCKED` | Gate explicitly blocked | `backtesting/cpa_daily_cycle.py` |

### SourceError

Fixed code `SOURCE_ERROR`. All instances carry `source_id` and `reason` in details.

| Source ID | Reason | Raised By |
|-----------|--------|-----------|
| `chainlink_rpc` | `eth_call HTTP failure: …` | `data_pipeline/price_feeds.py` |
| `chainlink_rpc` | `eth_call malformed JSON: …` | `data_pipeline/price_feeds.py` |
| `chainlink_rpc` | `eth_call RPC error: …` | `data_pipeline/price_feeds.py` |
| `chainlink_rpc` | `eth_call missing/invalid result: …` | `data_pipeline/price_feeds.py` |
| `chainlink_rpc` | Feed timeout or stale data | `data_pipeline/price_feeds.py` |
| `defillama` | `DeFiLlama returned empty histories` | `export_data.py` |

### ValidationError

Fixed code `VALIDATION_ERROR`. Carries `field`, `value`, `reason` in details.

| Field | Description | Raised By |
|-------|-------------|-----------|
| manifest fields | Invalid adapter manifest schema | `adapter_sdk/manifest.py` |
| `clean_pct` | Value outside `[0.0, 1.0]` | `utils/errors.py` (example) |

### KANBANError

Default code `KANBAN_ERROR`. Custom codes set per raise site.

| Code | Description | Raised By |
|------|-------------|-----------|
| `KANBAN_PARSE_ERROR` | Failed to parse KANBAN.json | KANBAN write utilities |
| `KANBAN_ERROR` | Generic KANBAN operation failure | KANBAN write utilities |

### AdapterError

Fixed code `ADAPTER_ERROR`. All instances carry `adapter_id` and `reason` in details.

| Adapter ID | Reason | Raised By |
|------------|--------|-----------|
| `<protocol>` | `no APY available from any interface` | `adapters/adapter_registry.py` |
| `compound_v3` | `TVL response missing 'tvlUsd' key` | (example in errors.py docstring) |

### ConfigError

Fixed code `CONFIG_ERROR`. Carries `key` and `reason` in details.

| Key | Reason | Raised By |
|-----|--------|-----------|
| `DATABASE_URL` | Could not extract sqlite path from URL | `database/connection.py` |
| `DATABASE_URL` | No SQLite path found | `database/connection.py` |
| `GITHUB_PAT_SPA` | not found in Keychain | `family_fund/api/keychain.py` |
| `TELEGRAM_BOT_TOKEN` | not set (env or Keychain) | `family_fund/lead_tracker.py` |
| `TELEGRAM_BOT_TOKEN` | not set in env or Keychain | `family_fund/telegram_blast.py` |
| `<keychain_key>` | Keychain lookup failed: `<stderr>` | `telegram_protocols_reporter.py` |

### AtomicWriteError

Fixed code `ATOMIC_WRITE_ERROR`. Carries `path` and `reason` in details.

| Description | Raised By |
|-------------|-----------|
| `mkstemp + os.replace` failure on state files | Any atomic write helper |

### RegistryError

Default code `REGISTRY_ERROR`. Custom codes set per raise site.

| Code | Description | Raised By |
|------|-------------|-----------|
| `REGISTRY_ERROR` | Protocol not found in whitelist | `paper_trading/engine.py` |
| `STRATEGY_DUPLICATE_ID` | Strategy ID already registered with different metadata | `strategies/strategy_registry.py` |
| `UNKNOWN_TOPIC` | Topic not in `Topic.ALL` | `message_bus/bus.py` |

### RiskPolicyError

Default code `RISK_POLICY_ERROR`.

| Description | Raised By |
|-------------|-----------|
| RiskPolicy constraint violation | `risk/policy.py` |

> Note: `RiskPolicyViolation` in `paper_trading/engine.py` (line 69) is a legacy local exception class — not yet migrated to `RiskPolicyError`. Tracked separately.

### AllocationError

Default code `ALLOCATION_ERROR`. Custom codes set per raise site.

| Code | Description | Raised By |
|------|-------------|-----------|
| `UNKNOWN_ALLOCATION_MODEL` | Allocation model string not in dispatch table | `allocator/allocator.py` |
| `ALLOCATION_ERROR` | Generic allocation constraint violation | `allocator/allocator.py` |

### LiveTradingForbiddenError

Fixed code `LIVE_TRADING_FORBIDDEN`. Carries `gate` in details.

| Gate | Description | Raised By |
|------|-------------|-----------|
| `live_trading_gate` | Live gate check failed | `safety/live_trading_gate.py` |
| `<func_name>` | Function decorated with `@safeguard` called without gate PASS | `safety/safeguard.py` |
| `<gate_name>` | `require_gate()` assertion failed | `utils/errors.py:require_gate()` |
| `paper_ready` | Paper gate not PASS on activation | `golive/activate.py` |

---

## Utility Functions

### `safe_call(func, *args, default=None, log_error=True, logger_name="spa.safe_call", **kwargs)`

Exception-safe wrapper. Returns `default` on any exception. Logs at WARNING level.

**Use in:** background tasks, launchd jobs, daily cycle non-critical sections.  
**Do NOT use in:** live trading paths, test assertions.

```python
result = safe_call(adapter.fetch, default={"apy": 0.0})
```

### `require_gate(gate_status: str, gate_name: str) -> None`

Asserts gate is `"PASS"` — raises `LiveTradingForbiddenError` otherwise.

**Use at:** entry point of any live-trading function.

```python
require_gate(status["live"], "live")   # raises LiveTradingForbiddenError if not "PASS"
```

---

## Usage Patterns

### Importing

```python
from spa_core.utils.errors import (
    SPAError,
    GateError,
    SourceError,
    ConfigError,
    RegistryError,
    AdapterError,
    AllocationError,
    LiveTradingForbiddenError,
    safe_call,
    require_gate,
)
```

### Catching all SPA errors

```python
try:
    run_cycle()
except LiveTradingForbiddenError:
    raise          # never swallow live trading blocks
except SPAError as e:
    logging.error("SPA error: %s", e.to_dict())
```

### Safe adapter call

```python
apy = safe_call(adapter.fetch_apy, default=None)
if apy is None:
    # adapter failed — handled gracefully
    ...
```

---

## Error Code Migration Status

| Batch | Files | Status |
|-------|-------|--------|
| Batch 0 | `utils/errors.py` (catalog) | ✅ v9.98 |
| Batch 1 | price_feeds, keychain, telegram_blast, lead_tracker, engine, export_data, message_bus/bus, database/connection, strategy_registry, allocator, adapter_registry, aave_v3, euler_v2, maple, morpho_blue, yearn_v3 | ✅ v10.48 |
| Batch 2 | analytics/protocol_liquidity_depth_analyzer, analytics/rebalance_cost_estimator, analytics/yield_compressor_score, analytics/yield_timing_optimizer, analytics/protocol_tvl_filter, analytics/protocol_adoption_scorer, telegram_protocols_reporter | ✅ v10.49 |
| Pending | `execution/` domain (eth_signer, aave_v3_adapter, compound_v3_adapter, morpho_adapter) | 🔲 Separate domain — execution-only RuntimeError |

> **LLM_FORBIDDEN:** `execution/` and `risk/` components must NOT use LLM-generated code paths (prompt injection vector). RuntimeErrors in `execution/` are intentional low-level guards and do not require SPAError migration.

---

*Updated: 2026-06-20 (MP-1434 v10.50)*
