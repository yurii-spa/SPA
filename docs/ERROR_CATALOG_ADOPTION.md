# Error Catalog Adoption Report

Date: 2026-06-19
Sprint: v10.31–v10.32 (MP-1415, MP-1416)

## Status

**10 core modules** migrated (MP-1415). **6 adapter files** migrated + safe_call() refactored (MP-1416).
Total: **55 tests pass** (30 error catalog + 25 adapter errors).

---

## MP-1415: Core Modules (v10.31)

| File | Before | After | Tests Pass |
|------|--------|-------|------------|
| `spa_core/data_pipeline/price_feeds.py` | `raise RuntimeError(...)` × 6 (eth_call HTTP, JSON, RPC, sanity) | `raise SourceError("chainlink_rpc", ...)` × 6 | ✅ |
| `spa_core/family_fund/api/keychain.py` | `raise RuntimeError(...)` — JWT secret not found | `raise ConfigError(KEYCHAIN_SERVICE, ...)` | ✅ |
| `spa_core/family_fund/telegram_blast.py` | `raise RuntimeError(...)` — Keychain lookup failed | `raise ConfigError(key, ...)` | ✅ |
| `spa_core/family_fund/lead_tracker.py` | `raise RuntimeError(...)` — Keychain lookup failed | `raise ConfigError(key, ...)` | ✅ |
| `spa_core/paper_trading/engine.py` | `raise ValueError(f"No open position for {key}")` | `raise SPAError(..., code="NO_OPEN_POSITION")` | ✅ |
| `spa_core/paper_trading/engine.py` | `raise ValueError(f"Protocol not found in whitelist")` | `raise RegistryError(...)` | ✅ |
| `spa_core/export_data.py` | `raise ValueError("DeFiLlama returned empty histories")` | `raise SourceError("defillama", ...)` | ✅ |
| `spa_core/message_bus/bus.py` | `raise ValueError(f"Unknown topic: ...")` | `raise RegistryError(..., code="UNKNOWN_TOPIC")` | ✅ |
| `spa_core/database/connection.py` | `raise ValueError(...)` × 2 (bad URL, bad scheme) | `raise ConfigError("DATABASE_URL", ...)` × 2 | ✅ |
| `spa_core/strategies/strategy_registry.py` | `raise ValueError(...)` — duplicate strategy ID | `raise RegistryError(..., code="STRATEGY_DUPLICATE_ID")` | ✅ |
| `spa_core/allocator/allocator.py` | `raise ValueError(...)` — unknown allocation model | `raise AllocationError(..., code="UNKNOWN_ALLOCATION_MODEL")` | ✅ |

**Note:** `ValueError` in `__post_init__` validators (strategy type, risk tier, capital > 0, amount > 0) were intentionally kept — these are input validation, not business logic errors.

---

## MP-1416: Adapter Layer (v10.32)

| File | Change | Tests Pass |
|------|--------|------------|
| `spa_core/adapters/adapter_registry.py` | `raise ValueError("no APY available")` → `raise AdapterError(protocol, ...)` | ✅ |
| `spa_core/adapters/aave_v3.py` | `try/except` → `safe_call()` around DeFiLlama get_apy/get_tvl | ✅ |
| `spa_core/adapters/euler_v2.py` | `try/except` → `safe_call()` around DeFiLlama get_apy/get_tvl | ✅ |
| `spa_core/adapters/maple.py` | `try/except` → `safe_call()` around DeFiLlama get_apy/get_tvl | ✅ |
| `spa_core/adapters/morpho_blue.py` | `try/except` → `safe_call()` around DeFiLlama get_apy/get_tvl | ✅ |
| `spa_core/adapters/yearn_v3.py` | `try/except` → `safe_call()` around DeFiLlama get_apy/get_tvl | ✅ |

**Adapters with no changes needed:** compound_v3.py, aave_v3_optimism_adapter.py, aave_v3_polygon_adapter.py, aave_arbitrum_adapter.py — already had DeFiLlama error handling via try/except; ValueError in these files are ALL input validation (capital > 0, amount > 0) and correctly remain as ValueError.

---

## Error Code Registry

| Code | Class | Description | Raised In |
|------|-------|-------------|-----------|
| `SPA_UNKNOWN` | `SPAError` | Default fallback when no code given | any |
| `GATE_<GATE>_<STATUS>` | `GateError` | Gate check failed — auto-generated | `require_gate()` |
| `SOURCE_ERROR` | `SourceError` | Data source unavailable or invalid | `price_feeds.py`, `export_data.py` |
| `VALIDATION_ERROR` | `ValidationError` | Field-level validation failed | validators |
| `KANBAN_ERROR` | `KANBANError` | KANBAN.json operation failed | kanban writers |
| `ADAPTER_ERROR` | `AdapterError` | DeFi adapter failed to fetch data | `adapter_registry.py` |
| `CONFIG_ERROR` | `ConfigError` | Missing or invalid configuration | `keychain.py`, `telegram_blast.py`, `lead_tracker.py`, `database/connection.py` |
| `ATOMIC_WRITE_ERROR` | `AtomicWriteError` | Atomic file write (mkstemp+replace) failed | state writers |
| `REGISTRY_ERROR` | `RegistryError` | Adapter/module not found in registry | `strategy_registry.py`, `message_bus/bus.py`, `engine.py` |
| `RISK_POLICY_ERROR` | `RiskPolicyError` | RiskPolicy violation detected | risk domain |
| `ALLOCATION_ERROR` | `AllocationError` | Invalid allocation or constraint violation | `allocator.py` |
| `LIVE_TRADING_FORBIDDEN` | `LiveTradingForbiddenError` | Live trading attempted before gates PASS | `require_gate()` |
| `UNKNOWN_TOPIC` | `RegistryError` | Message bus publish to unknown topic | `message_bus/bus.py` |
| `STRATEGY_DUPLICATE_ID` | `RegistryError` | Strategy ID already registered with different metadata | `strategy_registry.py` |
| `UNKNOWN_ALLOCATION_MODEL` | `AllocationError` | Unknown allocation model requested | `allocator.py` |
| `NO_OPEN_POSITION` | `SPAError` | Close/rebalance requested for protocol with no open position | `engine.py` |

---

## Migration Rules (for future reference)

| Situation | Exception |
|-----------|-----------|
| Gate BLOCKED / not PASS | `GateError(gate, status)` |
| Data source unavailable / stale | `SourceError(source_id, reason)` |
| Live trading without gate PASS | `LiveTradingForbiddenError(gate)` |
| DeFi adapter cannot fetch data | `AdapterError(adapter_id, reason)` |
| Missing/invalid config (env var, Keychain) | `ConfigError(key, reason)` |
| Module/adapter not in registry | `RegistryError(message, code=...)` |
| RiskPolicy violation | `RiskPolicyError(message, code=...)` |
| Allocation constraint violated | `AllocationError(message, code=...)` |
| Atomic write failed | `AtomicWriteError(path, reason)` |
| General business logic (no subclass fits) | `SPAError(message, code="ERR_CODE")` |
| **Input validation** | **Keep as `ValueError`** — this is correct Python |

---

## What Was NOT Migrated (intentional)

- `ValueError` in strategy constructors (`__post_init__`) — input validation, correct as-is
- `ValueError` in adapter simulation methods (`allocate`, `withdraw`, `simulate_deposit`) — input validation for capital_usd/amount_usd > 0
- `ValueError` in math utilities (`probabilistic_sharpe.py`, `return_distribution.py`) — domain checks
- `RuntimeError` in `execution/` domain — LLM_FORBIDDEN in execution domain; migration deferred to a separate ADR
- `RuntimeError` in `execution/eth_signer.py`, `execution/aave_v3_adapter.py`, `execution/adapters/morpho_adapter.py` — execution domain, out of scope for paper-trading sprint
