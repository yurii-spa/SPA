# SPA Error Code Reference

**Source:** `spa_core/utils/errors.py` · **Catalog:** `spa_core/utils/error_catalog.py`  
**Updated:** 2026-06-20 (MP-1485 v11.01)

All SPA exceptions inherit from `SPAError`. Each instance carries:
- `.code` — machine-readable string (e.g. `"GATE_BACKTEST_FAIL"`)
- `.details` — dict with structured context
- `.to_dict()` — JSON-safe serialization for logging

---

## Error Hierarchy

```
SPAError (E001)
├── GateError (G001)               — validation gate failed
├── SourceError (S001)             — data source unavailable / stale
├── ValidationError (V001)         — field-level validation failure
├── KANBANError (K001)             — KANBAN.json operation failed
├── AdapterError (A001)            — DeFi adapter fetch / parse failure
├── ConfigError (C001)             — bad configuration / missing key
├── AtomicWriteError (W001)        — atomic file write failed (CRITICAL)
├── RegistryError (R001)           — adapter or strategy not registered
├── RiskPolicyError (P001)         — RiskPolicy constraint violated
├── AllocationError (L001)         — portfolio allocation constraint violated
└── LiveTradingForbiddenError (X001) — live trading blocked by safeguard
```

---

## E001 — SPAError (Base)

**Class:** `SPAError` | **Runtime code:** `SPA_UNKNOWN` | **Category:** base

**When raised:** Catch-all when no domain-specific subclass applies.

**Remediation:** Inspect `.code` and `.details` via `e.to_dict()`.
Prefer raising a specific subclass over bare `SPAError`.

```python
raise SPAError("unexpected condition", code="MY_CODE", details={"context": "startup"})
```

---

## G001 — GateError

**Class:** `GateError` | **Runtime code:** `GATE_{GATE}_{STATUS}` | **Category:** gate

**When raised:** A validation gate (backtest, pre-paper, paper, live) failed or
returned a non-PASS status. Gate JSON missing, status is FAIL/NOT_READY/BLOCKED,
or gate data is corrupt.

**Attributes:** `.gate` (gate name), `.status` (observed status)

**Remediation:**
1. Read `e.gate` and `e.status` to identify which gate failed
2. Re-run the gate: `python3 -m spa_core.backtesting.backtest_gate`
3. Check `data/backtest/<gate>.json` for root cause

```python
raise GateError("paper_ready", "NOT_READY")
# e.code → "GATE_PAPER_READY_NOT_READY"
```

---

## S001 — SourceError

**Class:** `SourceError` | **Runtime code:** `SOURCE_ERROR` | **Category:** data_source

**When raised:** DeFiLlama timeout, 5xx response, TVL below floor ($5M),
APY outside sanity band (0–200%), or adapter fetch returns `None`.

**Attributes:** `.source_id`, `.reason`

**Remediation:**
1. Check network and DeFiLlama status
2. Inspect `e.source_id` and `e.reason`
3. Cycle skips failed adapters and retries next run

```python
raise SourceError("aave_v3", "DeFiLlama returned HTTP 503")
```

---

## V001 — ValidationError

**Class:** `ValidationError` | **Runtime code:** `VALIDATION_ERROR` | **Category:** validation

**When raised:** Field value outside expected range — allocation weight > 1.0,
negative TVL, bad date format in state files.

**Attributes:** `.field`, `.value`, `.reason`

**Remediation:** Inspect `e.field`, `e.value`, `e.reason`. Correct the upstream data.

```python
raise ValidationError("clean_pct", 1.5, "must be in [0.0, 1.0]")
```

---

## K001 — KANBANError

**Class:** `KANBANError` | **Runtime code:** `KANBAN_ERROR` | **Category:** kanban

**When raised:** `KANBAN.json` is missing, not valid JSON, or `os.replace` fails.

**Remediation:**
1. Validate: `python3 -c "import json; json.load(open('KANBAN.json'))"`
2. Restore from last GitHub push if corrupt
3. Always write KANBAN.json with tmp + os.replace

```python
raise KANBANError("KANBAN.json: invalid JSON near line 42", code="KANBAN_PARSE_ERROR")
```

---

## A001 — AdapterError

**Class:** `AdapterError` | **Runtime code:** `ADAPTER_ERROR` | **Category:** adapter

**When raised:** Network failure, unexpected API response schema, missing required
key in payload, TVL/APY parse error in a DeFi protocol adapter.

**Attributes:** `.adapter_id`, `.reason`

**Remediation:**
1. Inspect `e.adapter_id` and `e.reason`
2. Check adapter logs
3. Cycle skips failed adapters and continues with available data

```python
raise AdapterError("compound_v3", "missing 'tvlUsd' key in response payload")
```

---

## C001 — ConfigError

**Class:** `ConfigError` | **Runtime code:** `CONFIG_ERROR` | **Category:** config

**When raised:** `GITHUB_PAT_SPA` not in Keychain, `DEFILLAMA_API_URL` empty,
or a required JSON config key is absent.

**Attributes:** `.key`, `.reason`

**Remediation:**
- PAT: `bash setup_pat.sh <token>` — see `docs/TOKEN_ROTATION_RUNBOOK.md`
- Env vars: verify defaults in `spa_core/adapters/config.py`

```python
raise ConfigError("GITHUB_PAT_SPA", "not found in macOS Keychain")
```

---

## W001 — AtomicWriteError ⚠️ CRITICAL

**Class:** `AtomicWriteError` | **Runtime code:** `ATOMIC_WRITE_ERROR` | **Category:** io

**When raised:** `os.replace` fails during tmp-file atomic write.
Causes: disk full, permission denied, cross-filesystem replace.

**Attributes:** `.path`, `.reason`

**Remediation:**
1. `df -h` — check disk space
2. `ls -la data/` — check permissions
3. Restore affected file from last GitHub push after fixing root cause

```python
raise AtomicWriteError("data/trades.json", "os.replace: [Errno 13] Permission denied")
```

---

## R001 — RegistryError

**Class:** `RegistryError` | **Runtime code:** `REGISTRY_ERROR` | **Category:** registry

**When raised:** Adapter or strategy key not found in `ADAPTER_REGISTRY`
or `strategy_registry.py`.

**Remediation:**
```bash
python3 -c "from spa_core.adapters.registry import ADAPTER_REGISTRY; print(list(ADAPTER_REGISTRY))"
```

```python
raise RegistryError("adapter 'unknown_v9' not in ADAPTER_REGISTRY")
```

---

## P001 — RiskPolicyError

**Class:** `RiskPolicyError` | **Runtime code:** `RISK_POLICY_ERROR` | **Category:** risk

**When raised:** RiskPolicy constraint violated — T1 > 40%, T2 > 20%, T2 total > 50%,
TVL < $5M, APY outside 1–30%, drawdown ≥ 5% (kill switch).

**Remediation:**
1. Check `data/risk_policy_blocks.json` for the blocking record
2. `RiskPolicy.approved=False` **cannot be overridden by any agent**
3. Wait for conditions to normalize or review allocation model

```python
raise RiskPolicyError("T2 total cap exceeded: 52% > 50% limit")
```

---

## L001 — AllocationError

**Class:** `AllocationError` | **Runtime code:** `ALLOCATION_ERROR` | **Category:** allocation

**When raised:** Allocation weights don't sum to 1.0, negative weight,
or `StrategyAllocator` received contradictory constraints.
(Distinct from P001 which covers RiskPolicy rule violations.)

**Remediation:**
1. Inspect allocation model output
2. Check `spa_core/allocator/allocator.py`
3. Ensure weights sum to 1.0 within float tolerance

```python
raise AllocationError("weights sum to 0.97, expected 1.0 ± 0.001")
```

---

## X001 — LiveTradingForbiddenError 🔒

**Class:** `LiveTradingForbiddenError` | **Runtime code:** `LIVE_TRADING_FORBIDDEN` | **Category:** safety

**NEVER suppress this exception.** It is the hard stop protecting real capital.

**When raised:** Any live-execution function is called while paper-ready or live gate
is not PASS. Also raised by `live_trading_forbidden()` safeguard.

**Attributes:** `.gate` (the gate that blocked activation)

**Remediation:**
1. **Do NOT suppress.**
2. Check `data/golive_status.json` — all 26 GoLiveChecker criteria must pass
3. Live trading can only be activated via `spa_core/golive/activate.py`
   with manual confirmation: `"I CONFIRM LIVE TRADING"`

```python
raise LiveTradingForbiddenError("paper_ready")
# LiveTradingForbiddenError: Live trading forbidden: gate 'paper_ready' has not passed
```

---

## Machine-Readable Catalog

```python
from spa_core.utils.error_catalog import lookup, list_codes, lookup_by_class

info = lookup("G001")
# {'code': 'G001', 'class': 'GateError', 'runtime_code': 'GATE_{GATE}_{STATUS}', ...}

list_codes()
# ['E001', 'G001', 'S001', 'V001', 'K001', 'A001', 'C001', 'W001', 'R001', 'P001', 'L001', 'X001']

lookup_by_class("LiveTradingForbiddenError")
# {'code': 'X001', ...}
```

---

## Quick Reference Table

| Code | Class | Category | Blocking? |
|------|-------|----------|-----------|
| E001 | SPAError | base | No |
| G001 | GateError | gate | Yes |
| S001 | SourceError | data_source | No (degrades) |
| V001 | ValidationError | validation | Depends |
| K001 | KANBANError | kanban | No |
| A001 | AdapterError | adapter | No (skips) |
| C001 | ConfigError | config | Yes |
| W001 | AtomicWriteError | io | Yes (CRITICAL) |
| R001 | RegistryError | registry | Yes |
| P001 | RiskPolicyError | risk | Yes |
| L001 | AllocationError | allocation | Yes |
| X001 | LiveTradingForbiddenError | safety | Yes (hard stop) |

---

*Generated by MP-1485 (v11.01) — 2026-06-20*
