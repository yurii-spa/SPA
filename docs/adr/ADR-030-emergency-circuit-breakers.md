# ADR-030: Emergency Circuit Breakers

**Status:** Accepted  
**Date:** 2026-06-12  
**Authors:** SPA Architect  
**Related:** ADR-021 (Pendle YT risk), ADR-002 (go-live transfer rule), MP-108 (kill switch engine.py), MP-375 (daily_limits.py DL-01..DL-05)

---

## Context

`DailyLimitsChecker` (DL-01..DL-05, `spa_core/risk/daily_limits.py`) handles
**normal operational risk**: daily loss caps, drawdown thresholds, adapter
concentration, and APY sanity bounds. These checks run inside every allocation
cycle and are well-tested.

However, there is a category of **catastrophic scenarios** that DailyLimitsChecker
is not designed to catch:

| Scenario | Why DL-01..DL-05 misses it |
|---|---|
| Smart contract exploit (sudden APY spike to 500%+) | DL-05 ceiling is 50 % — a T1 protocol reporting 500 % gets only a WARN, not a HALT |
| Oracle price manipulation cascade (multiple adapters diverge simultaneously) | No multi-adapter divergence check exists |
| Chain-level gas crisis (Ethereum gas > 50 Gwei sustained) | DL checks are purely data-layer; gas is not checked |
| Flash crash within a single cycle run (equity −15 % in one cycle) | DL-01 compares consecutive daily bars; a within-cycle crash goes undetected until the next bar |
| Data corruption (NaN equity, negative equity, non-monotonic timestamps) | DL reads equity values but does not validate structural integrity |

The existing `RiskPolicy.check_portfolio_health` kill switch (drawdown ≥ 5 %)
operates at the portfolio-state level and is also not designed for the above
scenarios.

We need a **coarser, faster, fail-hard layer** that halts the system before any
of these catastrophic states can propagate.

---

## Decision

Introduce `EmergencyBreakers` (`spa_core/risk/emergency_breakers.py`) — five
named circuit breakers (EB-01..EB-05) that sit **above** DailyLimitsChecker
in the check hierarchy.

### EB-01: Protocol Exploit Alert (HALT)

| Field | Value |
|---|---|
| **Trigger** | Any single adapter in `apy_map` reports APY > **100 %** |
| **Rationale** | Legitimate DeFi stablecoin yields never reach 100 %. A sudden spike of this magnitude is a strong signal of an exploit probe, oracle manipulation, or a protocol reporting corrupted data. The DL-05 ceiling (50 %) is a sanity warning; 100 % is a hard halt threshold. |
| **Action** | HALT all allocations. Log `EB-01` with offending adapter(s) and APY values. Telegram CRITICAL alert (implementation delegated to caller). |
| **Recovery** | Manual review required. No automatic recovery. |

### EB-02: Oracle Divergence Cascade (HALT)

| Field | Value |
|---|---|
| **Trigger** | **≥ 3 adapters** simultaneously diverge more than **500 bps** from their `static_apy` fallback values |
| **Rationale** | A single adapter diverging is normal drift. Three or more adapters diverging simultaneously indicates a systemic oracle issue, a DeFiLlama API anomaly, or a broader market dislocation. The 500 bps threshold avoids false positives from routine APY volatility. |
| **Action** | HALT. Switch to static APY mode (advisory — implementation in caller). Telegram CRITICAL. |
| **Recovery** | Auto-recovers when divergence normalises below 500 bps on subsequent cycle. |

### EB-03: Gas Crisis (PAUSE)

| Field | Value |
|---|---|
| **Trigger** | Base gas price > **50 Gwei** |
| **Rationale** | At 50+ Gwei, gas costs for rebalancing would dwarf any yield benefit in a paper-trading simulation and would be uneconomical in live trading. ADR-025 includes a gas-cost gate; this breaker is coarser and fires before individual protocol checks. |
| **Action** | PAUSE. No new allocations. Existing positions held untouched. |
| **Recovery** | Auto-recovers when gas drops below threshold. |

### EB-04: Equity Flash Crash (HALT)

| Field | Value |
|---|---|
| **Trigger** | Equity drops > **15 %** between the last two entries in `equity_history` within a single cycle run |
| **Rationale** | DL-01 catches a daily loss > 2 %; a within-cycle flash crash of 15 % either indicates a catastrophic real loss or a data/accounting error. Either scenario requires an immediate halt and manual review. A 15 % threshold is intentionally permissive to avoid false positives from initial setup edge cases. |
| **Action** | HALT. Log the flash-crash event with old/new equity and percentage drop. Telegram CRITICAL. |
| **Recovery** | Manual review required. No automatic recovery. |

### EB-05: Data Corruption (HALT)

| Field | Value |
|---|---|
| **Trigger** | `equity_history` contains: (a) non-monotonic timestamps, OR (b) NaN/Infinity equity values, OR (c) negative equity values |
| **Rationale** | Corrupted state files propagate silently through downstream analytics (drawdown, attribution, GoLiveChecker) if not caught early. All three corruption types invalidate the entire equity curve and must halt further processing. |
| **Action** | HALT. Log corruption event with first offending record. |
| **Recovery** | Manual repair required. No automatic recovery. |

---

## Verdict Precedence

```
EB-01 | EB-02 | EB-04 | EB-05  →  HALT  (no new cycles, immediate stop)
EB-03                           →  PAUSE (cycle skipped, positions held)

If both HALT and PAUSE triggered  →  HALT wins
If no breakers triggered          →  CLEAR
```

All EB triggers → immediate Telegram CRITICAL alert (caller responsibility).

---

## Integration Point

`EmergencyBreakers.check_all()` is called by `cycle_runner.py` **before**
`DailyLimitsChecker.check()` and **before** `RiskPolicy.check_portfolio_health()`.

Call order in cycle:

```
1. EmergencyBreakers.check_all()   ← this ADR
   → status HALT/PAUSE → abort/skip cycle
2. DailyLimitsChecker.check()      ← DL-01..DL-05
   → gate HALT → abort cycle
3. RiskPolicy.check_portfolio_health()  ← existing
4. StrategyAllocator + rebalance
```

Result is written atomically to `data/emergency_status.json`.

---

## Non-Goals

- Does **NOT** replace `DailyLimitsChecker` (DL-01..DL-05).
- Does **NOT** replace `RiskPolicy` (concentration, APY window, cash buffer).
- Does **NOT** auto-execute any on-chain transactions.
- Does **NOT** require smart contract interaction of any kind.
- Does **NOT** require external dependencies — pure Python stdlib.
- Does **NOT** send Telegram messages itself — caller handles alerts based on returned status.

---

## Consequences

**Positive:**
- Provides a coarse but decisive fail-safe against catastrophic events that
  DL-01..DL-05 were not designed to catch.
- All five checks are O(n) in the size of the input data — negligible overhead.
- Pure stdlib, deterministic, no LLM involvement (`LLM_FORBIDDEN_AGENTS` rule satisfied).
- Atomic write to `data/emergency_status.json` is safe under concurrent processes.

**Negative / Tradeoffs:**
- EB-01 (APY > 100 %) is a blunt instrument. High-APY speculative positions
  (e.g. Pendle YT in bull mode) could theoretically approach this threshold.
  However, YT strategies are paper-only and advisory; their APY does not feed
  the T1 adapter check in EB-01.
- EB-03 (gas) is advisory in paper trading since no actual gas is spent.
  Included for realism and preparedness for go-live.

---

## Related Decisions

- **ADR-002** — Go-live transfer rule (30-day gap_monitor required)
- **ADR-021** — Pendle YT T3-SPEC classification (advisory only, no auto-positions)
- **ADR-028** — Oracle price diversification (feeds EB-02 static fallback logic)
- **MP-108** — kill switch in `engine.py` (portfolio-level drawdown)
- **MP-375** — `daily_limits.py` DL-01..DL-05 (normal operational risk)
