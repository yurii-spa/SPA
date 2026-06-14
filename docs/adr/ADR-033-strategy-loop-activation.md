# ADR-033: Strategy Loop Activation Policy

**Date:** 2026-06-14
**Status:** Accepted
**Deciders:** Architect, Product Manager
**Implemented by:** Backend Developer (opus)

## Context

After 26 days of paper trading the tournament infrastructure (vPortfolio S0–S19,
`TournamentEvaluator`, `MultiStrategyRunner`, `PromotionEngine`) has been running
each cycle and writing `data/tournament_ranking.json`. However the
shadow→allocator feedback loop (SPA-V408) reported `strategy_loop_active: False`
in `paper_trading_status.json`, meaning the tournament's verdict has **never**
influenced the real (paper) allocation.

### Why was it off?

The allocator (`spa_core/allocator/allocator.py`) is constructed with
`strategy_loop_enabled=True` by default, but `strategy_loop_active` only flips to
`True` when `StrategySelector.select_best()` returns a strategy. That selector
(`spa_core/strategies/strategy_selector.py`) is intentionally cautious:

- a strategy needs a **non-null Sortino** AND **≥ 15 days** (`MEDIUM_CONFIDENCE_DAYS`)
  of its own history to be *selectable*;
- `< 7 days` → not even a candidate, `7–14 days` → `"low"` (eligible but not
  selectable), `15–29` → `"medium"`, `≥ 30` → `"high"`.

The current `data/strategy_shadow_comparison.json` shows `days_running: 3` and
every strategy's `sortino` is `null`. So the gate correctly refused to select
anything → `strategy_loop_active` stayed `False`.

The "26 days" refers to the **main** paper-trading equity track. The **shadow
strategy comparison** track is much younger (3 days) and has no Sortino yet, so
there is genuinely not enough per-strategy data to let the tournament steer real
capital. Activating full allocation control today would chase a few days of
noise.

## Options Considered

### Option A — Activate immediately (full tournament drives allocation)
Flip the loop on so the top shadow strategy's weights become the allocation base
right away.
- ❌ Only 3 days of shadow data, Sortino missing → would let noise pick the book.
- ❌ Bypasses the statistically-cautious 15-day confidence gate that was designed
  precisely for this moment.

### Option B — Shadow mode (tournament runs in parallel, does NOT affect allocation)
Tournament + leaderboard are evaluated and logged every cycle, the activation
state is recorded and auditable, but the real allocation is untouched until a
strategy organically earns medium confidence.
- ✅ Zero risk to the live paper book.
- ✅ Makes the activation state explicit, configurable and visible in the daily
  record instead of being an implicit side effect of the selector.
- ✅ When the shadow track crosses 15 days with a valid Sortino, the selector
  becomes ready and we flip to `active` with one config edit (no code change).

### Option C — Partial activation (only the Top-1 strategy, capped)
Let only the rank-1 strategy steer, with a small cap.
- ❌ Still acts on 3 days / null-Sortino data — same core flaw as A.
- ❌ Adds a second, ad-hoc gate that overlaps the existing confidence machinery.

## Decision

**Adopt Option B — Shadow mode.**

Introduce an explicit, persisted control file `data/strategy_config.json` with a
three-valued `strategy_loop_mode`:

| mode      | tournament evaluated & logged | drives real allocation |
|-----------|:-----------------------------:|:----------------------:|
| `off`     | no (loop fully disabled)       | no |
| `shadow`  | **yes** (advisory-only)        | **no** ← default today |
| `active`  | yes                            | yes (when a strategy is medium/high confidence) |

Set the file to `shadow` now. The cycle runner reads it each cycle, logs the mode
and the allocator's `strategy_loop_active`, and records a note in the cycle
result. The existing 15-day confidence gate in `StrategySelector` is retained
unchanged — `active` mode does not weaken it; it merely *permits* the selector's
output to reach the allocator.

**Promotion to `active`** happens by editing `strategy_loop_mode` to `"active"`
once `strategy_shadow_comparison.json` shows the leading strategy at
`days_running >= 15` with a finite Sortino. No code deploy is needed.

## Consequences / Constraints Applied

- **Read-only / advisory:** `strategy_config.py` is stdlib-only, never writes,
  and is fail-safe — a missing/corrupt file degrades to `shadow`, so a bad config
  can never crash a cycle.
- **Safety invariant enforced twice:**
  1. `_default_allocator` builds `StrategyAllocator(strategy_loop_enabled=...)`
     from the mode — `off`/`shadow` ⇒ the allocator never even consults shadow
     strategies.
  2. The cycle runner additionally forces `strategy_loop_active=False` (with a
     warning + note) if the mode is not `active` but the loop somehow reported
     active. Defence in depth.
- **Auditability:** every cycle now logs `strategy_loop_mode` and writes an
  `ADR-033 strategy_loop_mode=…` note into the cycle result, so the activation
  state is visible in the daily record and the MP-310 audit trail
  (`allocation_proposal` event already carries `strategy_loop_active`).
- **No change to risk gates:** tier caps (T1 40% / T2 20% / T2-total 35%), the
  TVL floor, risk-grade D exclusions, the kill-switch and the daily-limits HALT
  all remain authoritative and apply *on top* of any future shadow-derived
  weights.
- **Reversible:** flipping back to `shadow` or `off` is a one-line config edit.

## Files

- `data/strategy_config.json` — the control file (mode = `shadow`).
- `spa_core/strategies/strategy_config.py` — fail-safe reader.
- `spa_core/paper_trading/cycle_runner.py` — reads mode, logs + notes,
  enforces the safety invariant, builds the allocator accordingly.
- `spa_core/tests/test_strategy_loop_activation.py` — tests.
