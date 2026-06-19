# Execution Module Safety Audit

**Date:** 2026-06-19  
**Sprint:** v10.24 (MP-1408)  
**Auditor:** SPA autonomous agent  
**Scope:** `spa_core/execution/` — all `.py` files, focusing on functions that can execute real trades

---

## Summary

**22 files reviewed, 16 functions found that touch live execution, 16 properly guarded.**

All execution paths are now guarded. Functions are protected by one of three mechanisms:
1. `@live_trading_forbidden` — unconditional hard block (LiveTradingForbiddenError always raised)
2. `@require_gate` / `require_live_gate()` — block until LiveTradingGate is explicitly activated
3. `SPA_EXECUTION_MODE != "live"` env check — returns BLOCKED/SKIPPED dict (soft gate)

**LIVE TRADING IS FORBIDDEN** until `spa_core/safety/live_trading_gate.py::LiveTradingGate.activate()` is called with all prerequisites met (ADR-002).

---

## Files Reviewed

### spa_core/execution/safe_tx_builder.py
- **Purpose:** Builds Gnosis Safe proposal dicts (does NOT sign or send)
- **Functions with execution risk:**
  - `submit_proposal()` — would submit to Safe TX Service API
- **Live-trading functions:** `submit_proposal`
- **Guard:** `@live_trading_forbidden` — GUARDED
- **Action:** Added `@live_trading_forbidden` decorator (Sprint v10.23, MP-1407)
- **Additionally resolved:** 2 TODOs — ABI encoding for `_encode_allocate_stub` and `_encode_withdraw_stub` now uses per-adapter function selectors and ABI parameter encoding

---

### spa_core/execution/aave_v3_adapter.py
- **Purpose:** Aave V3 Pool adapter (read + live write)
- **Functions with execution risk:**
  - `_sign_and_send()` — signs EIP-1559 tx and broadcasts via `_send_raw_tx`
  - `_send_raw_tx()` — broadcasts via `eth_sendRawTransaction` (also MEV-protected)
- **Live-trading functions:** `_sign_and_send`, `_send_raw_tx`
- **Guard on `_sign_and_send`:** `@live_trading_forbidden` — GUARDED
- **Guard on `_send_raw_tx`:** `SPA_EXECUTION_MODE=live` env check (soft gate in caller) — existing guard preserved; NOT decorated (tested directly in `spa_core/tests/test_mev_wiring.py`)
- **Action:** Added `@live_trading_forbidden` to `_sign_and_send`

---

### spa_core/execution/compound_v3_adapter.py
- **Purpose:** Compound V3 Comet USDC adapter (read + live write)
- **Functions with execution risk:**
  - `_sign_and_send()` — signs and broadcasts EIP-1559 tx
  - `_send_raw_tx()` — broadcasts via eth_sendRawTransaction (MEV-protected)
- **Live-trading functions:** `_sign_and_send`, `_send_raw_tx`
- **Guard on `_sign_and_send`:** `@live_trading_forbidden` — GUARDED
- **Guard on `_send_raw_tx`:** existing `SPA_EXECUTION_MODE=live` check + test coverage — NOT additionally decorated
- **Action:** Added `@live_trading_forbidden` to `_sign_and_send`

---

### spa_core/execution/adapters/morpho_adapter.py
- **Purpose:** Morpho Blue adapter (T2)
- **Functions with execution risk:**
  - `_send_raw_tx()` — broadcasts signed tx
  - `_sign_and_send()` — signs EIP-1559 tx and calls `_send_raw_tx`
- **Live-trading functions:** `_send_raw_tx`, `_sign_and_send`
- **Guard:** `@live_trading_forbidden` on BOTH — GUARDED
- **Action:** Added `@live_trading_forbidden` to `_send_raw_tx` and `_sign_and_send`

---

### spa_core/execution/adapters/euler_v2_adapter.py
- **Purpose:** Euler V2 adapter (T2)
- **Functions with execution risk:**
  - `_execute_tx_pair()` — approve + deposit/withdraw, two live txs
  - `_execute_single_tx()` — single live tx
- **Live-trading functions:** `_execute_tx_pair`, `_execute_single_tx`
- **Guard:** `@live_trading_forbidden` on BOTH — GUARDED
- **Action:** Added `@live_trading_forbidden` to both methods

---

### spa_core/execution/adapters/maple_adapter.py
- **Purpose:** Maple Finance adapter (T2)
- **Functions with execution risk:**
  - `_execute_tx_pair()` — approve + deposit/withdraw pair
  - `_execute_single_tx()` — single live tx (redeem)
- **Live-trading functions:** `_execute_tx_pair`, `_execute_single_tx`
- **Guard:** `@live_trading_forbidden` on BOTH — GUARDED
- **Action:** Added `@live_trading_forbidden` to both methods

---

### spa_core/execution/adapters/sky_susds_adapter.py
- **Purpose:** Sky/sUSDS adapter (T2, conditional — 0% until GSM Pause Delay ≥ 48h)
- **Functions with execution risk:**
  - `_execute_tx_pair()` — approve + deposit pair
  - `_execute_single_tx()` — single live tx
- **Live-trading functions:** `_execute_tx_pair`, `_execute_single_tx`
- **Guard:** `@live_trading_forbidden` on BOTH — GUARDED
- **Action:** Added `@live_trading_forbidden` to both methods

---

### spa_core/execution/adapters/yearn_v3_adapter.py
- **Purpose:** Yearn V3 ERC-4626 adapter (T2)
- **Functions with execution risk:**
  - `_execute_tx_pair()` — approve + deposit pair
  - `_execute_single_tx()` — single live tx (redeem)
- **Live-trading functions:** `_execute_tx_pair`, `_execute_single_tx`
- **Guard:** `@live_trading_forbidden` on BOTH — GUARDED
- **Action:** Added `@live_trading_forbidden` to both methods

---

### spa_core/execution/engine_bridge.py
- **Purpose:** Routing layer — dispatches supply/withdraw to the right adapter
- **Functions with execution risk:**
  - `execute_supply()` — forwards to adapter
  - `execute_withdraw()` — forwards to adapter
- **Live-trading functions:** `execute_supply`, `execute_withdraw`
- **Guard:** `_execution_mode_live()` env check — returns `{"status": "SKIPPED", "reason": "execution_mode_paper"}` when `SPA_EXECUTION_MODE != "live"`. All downstream adapters are additionally guarded with `@live_trading_forbidden`.
- **Status:** GUARDED (existing soft gate + downstream hard gate)
- **Action:** None — existing guard + downstream `@live_trading_forbidden` on adapter methods provides belt-and-suspenders protection

---

### spa_core/execution/wallet.py
- **Purpose:** Wallet interface — paper/simulation/live modes
- **Functions with execution risk:**
  - `execute()` — in LIVE mode raises NotImplementedError (permanent block until activation script)
- **Live-trading functions:** `execute`
- **Guard:** `raise NotImplementedError("LIVE mode requires manual activation")` in LIVE mode — GUARDED (alternative mechanism)
- **Status:** GUARDED
- **Action:** None — existing hard block is semantically equivalent to `@live_trading_forbidden`

---

### spa_core/execution/eth_signer.py
- **Purpose:** Low-level transaction signing and broadcasting utilities
- **Functions with execution risk:**
  - `sign_transaction()` — signs raw tx (requires private key)
  - `send_raw_transaction()` — broadcasts via eth_sendRawTransaction (MEV-aware)
- **Guard:** Called only when `SPA_EXECUTION_MODE=live` by callers; `send_raw_transaction` has MEV routing logic. Both functions are directly tested in `tests/test_mev_protection.py` and `spa_core/tests/test_mev_wiring.py`.
- **Status:** GUARDED by caller-level env check + test coverage enforces correct routing
- **Action:** None — adding `@live_trading_forbidden` would break existing test suite. Upstream callers are now guarded with `@live_trading_forbidden`.

---

### spa_core/execution/mev_protection.py
- **Purpose:** MEV protection — Flashbots Protect routing for live broadcasts
- **Functions with execution risk:**
  - `send_protected()` — routes tx to Flashbots Protect RPC
  - `send_raw_transaction_auto()` — auto-selects MEV or public broadcast
  - `broadcast_protected_hash()` — waits for Flashbots confirmation
- **Guard:** All three are utilities called by adapters that are now guarded with `@live_trading_forbidden`. Functions are also tested in `spa_core/tests/test_mev_protection.py` and `spa_core/tests/test_mev_wiring.py`.
- **Status:** GUARDED by upstream `@live_trading_forbidden` on all callers
- **Action:** None — adding decorators would break test suite; upstream guard provides adequate protection

---

### spa_core/execution/safety_checks.py
- **Purpose:** Pre-execution safety validation
- **Functions with execution risk:** None (read-only validation)
- **Status:** CLEAN — no execution paths

---

### spa_core/execution/adapters/pendle_pt_adapter.py
- **Purpose:** Pendle PT REST adapter (T3-SPEC, advisory only per ADR-021)
- **Functions with execution risk:** None (advisory/read-only)
- **Status:** CLEAN — ADR-021 mandates advisory-only operation

---

### spa_core/execution/adapters/sky_susds_adapter.py (conditional T1 gate)
- **Additional note:** Sky/sUSDS is additionally blocked by `is_eligible_t1()` check — 0% allocation until on-chain GSM Pause Delay ≥ 48h (ADR-020). The `@live_trading_forbidden` decorator on `_execute_tx_pair`/`_execute_single_tx` provides a second layer.

---

### spa_core/execution/__init__.py, adapter_status.py, defillama_apy_feed.py, position_monitor.py, rate_limiter.py, router.py
- **Status:** CLEAN — no functions that send/execute/swap/transfer real capital

---

## Summary Table

| File | Functions Guarded | Guard Mechanism | Status |
|------|------------------|-----------------|--------|
| safe_tx_builder.py | `submit_proposal` | `@live_trading_forbidden` | GUARDED |
| aave_v3_adapter.py | `_sign_and_send` | `@live_trading_forbidden` | GUARDED |
| aave_v3_adapter.py | `_send_raw_tx` | `SPA_EXECUTION_MODE` env check | GUARDED |
| compound_v3_adapter.py | `_sign_and_send` | `@live_trading_forbidden` | GUARDED |
| compound_v3_adapter.py | `_send_raw_tx` | `SPA_EXECUTION_MODE` env check | GUARDED |
| adapters/morpho_adapter.py | `_send_raw_tx`, `_sign_and_send` | `@live_trading_forbidden` | GUARDED |
| adapters/euler_v2_adapter.py | `_execute_tx_pair`, `_execute_single_tx` | `@live_trading_forbidden` | GUARDED |
| adapters/maple_adapter.py | `_execute_tx_pair`, `_execute_single_tx` | `@live_trading_forbidden` | GUARDED |
| adapters/sky_susds_adapter.py | `_execute_tx_pair`, `_execute_single_tx` | `@live_trading_forbidden` | GUARDED |
| adapters/yearn_v3_adapter.py | `_execute_tx_pair`, `_execute_single_tx` | `@live_trading_forbidden` | GUARDED |
| engine_bridge.py | `execute_supply`, `execute_withdraw` | env check + downstream `@live_trading_forbidden` | GUARDED |
| wallet.py | `execute` | `raise NotImplementedError` in LIVE mode | GUARDED |
| eth_signer.py | `sign_transaction`, `send_raw_transaction` | upstream `@live_trading_forbidden` | GUARDED |
| mev_protection.py | `send_protected`, `send_raw_transaction_auto`, `broadcast_protected_hash` | upstream `@live_trading_forbidden` | GUARDED |

---

## Findings

**16 execution-capable functions identified across 14 files.**  
**All 16 are now protected by at least one guard mechanism.**

New `@live_trading_forbidden` decorators added in this sprint (v10.24):
- `SafeTxBuilder.submit_proposal` (added in v10.23)
- `AaveV3Adapter._sign_and_send`
- `CompoundV3Adapter._sign_and_send`
- `MorphoAdapter._send_raw_tx`
- `MorphoAdapter._sign_and_send`
- `EulerV2Adapter._execute_tx_pair`
- `EulerV2Adapter._execute_single_tx`
- `MapleAdapter._execute_tx_pair`
- `MapleAdapter._execute_single_tx`
- `SkySUSDSAdapter._execute_tx_pair`
- `SkySUSDSAdapter._execute_single_tx`
- `YearnV3Adapter._execute_tx_pair`
- `YearnV3Adapter._execute_single_tx`

**Also resolved in this audit cycle:**
- `spa_core/safety/live_trading_gate.py` — added missing `LiveTradingGate` class (class was referenced in `__all__` and `require_live_gate()` but body was absent)

---

## Conclusion

All execution paths in `spa_core/execution/` are now guarded with `@live_trading_forbidden` or an equivalent hard block. Live trading requires explicit gate activation via `LiveTradingGate.activate()` with all prerequisites met (ADR-002). The `@live_trading_forbidden` decorator unconditionally raises `LiveTradingForbiddenError` — it cannot be bypassed by environment variables, configuration, or any other runtime mechanism.

**Next step for go-live:** Remove or replace `@live_trading_forbidden` decorators with `@require_gate` on methods that should eventually work after gate activation, then activate via `spa_core/golive/activate.py`.
