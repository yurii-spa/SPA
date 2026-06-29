# PRE-CUTOVER READINESS GATE

**Status:** active · **Domain:** read-only / inert · **Owner:** SPA Engineering
**Module:** `spa_core/paper_trading/pre_cutover_gate.py` ·
**CLI:** `scripts/pre_cutover_gate.py`

---

## What this is

SPA's **single authoritative pre-cutover readiness gate** — the artifact that
proves **every money-path defense provably fires** before anyone considers
flipping `is_live`. It does **not** flip `is_live`; the `LiveTradingGate` stays
the master block and the whole gate is **inert** (never moves capital, never
signs, never touches a wallet / bridge / chain, never imports `execution/`).

It is **not a 4th harness.** Three overlapping harnesses already exist and are
*composed* (as advisory sub-reports), not duplicated:

| Existing harness | What it checks | Role here |
|---|---|---|
| `scripts/cycle_dry_run.py` (MP-428) | adapter import / strategy run / file presence smoke | advisory (wired/importable) |
| `scripts/golive_preflight.py` (MP-351) | ADR-011 go-live security checklist (secrets, track-days, drills) | advisory sub-report |
| `scripts/day1_readiness_check.py` (MP-1428) | Day-1 CRITICAL checks (gate locked, kill-switch present, registry) | advisory sub-report |

The gate adds the one thing none of those do: it **drives a cycle through each
failure mode against a sandbox and asserts the correct defensive response
actually fires** — and exits 0 *only* when all of them do.

---

## What each gate proves

Each defense is a drill: it DRIVES the failure mode against a sandbox and ASSERTS
the response. The report is a list of `{gate, expected, actual, pass, detail}`.

| Gate | Drives | Asserts |
|---|---|---|
| `HARD_KILL_DRAWDOWN` | 15% evidenced drawdown (≥ 10% hard threshold) | `KillSwitchChecker` fires → kill-switch override forces **all-cash** |
| `HARD_KILL_MANUAL` | manual `kill_switch_active.json` present | kill fires → all-cash override |
| `HARD_KILL_RED_FLAGS` | > 5 CRITICAL red-flags on a **held** protocol | kill fires → all-cash override |
| `SOFT_DERISK` | 8% evidenced drawdown (∈ [5%,10%)) | **no new** position, **no increase** of held (clamped to held), reduction intact, **not liquidated** |
| `DL01_DAILY_LOSS` | single-day loss > 2% | `DailyLimitsChecker` **HALT** (DL-01) — distinct daily-loss axis, never deferred |
| `DL02_DEFERS_TO_KILL` | peak-to-trough ≥ 10% (DL-02 rung) | **ADR-048:** the hard kill OWNS this rung → DL-02's HALT is **deferred** in `run_cycle` so the **all-cash** kill fires (stronger action wins; the DL-02 primitive still HALTs in isolation) |
| `RISKPOLICY_BLOCK` | a 90%-concentration target | `RiskPolicy` `approved=False` (T1 cap breach) |
| `ANALYTICS_BLOCK` | a Tier-A `BLOCK` signal | the blocked protocol's target is **zeroed** |
| `BASE_GAS_BLOCK` | Base-gas kill-switch active | all **Base** allocations zeroed (non-Base intact) |
| `NAV_RECONCILE` | flat → target dry-run rebalance + a corrupted outcome | clean reconcile has **NAV residual == 0**; corrupted book is **caught** |
| `POSITION_MONITOR` | post-HARD-kill all-cash + post-SOFT held-only + a corrupt book | monitor reports correctly in **both new states**; corrupt book caught |
| `FAILSAFE_HOLD` | a safety eval that **raises** | LAW-1 **fail-safe HOLD** (no new trades, positions kept) — never fail-open |
| `LIVE_GATE_INERT` | (none — reads the master block) | `LiveTradingGate` is **LOCKED** → `would_cutover` is **always False** |

The NAV-reconcile and position-monitor checks are **pure-stdlib re-derivations
local to the gate module** — `execution/reconciliation.py` and
`execution/position_monitor.py` are deliberately **not** imported (the gate must
never import `execution/`).

### The two NEW states this sprint validates

Before this sprint, NAV-reconcile and position-monitor were never asserted in:

1. the **post-HARD-kill all-cash** state (every protocol forced to 0), and
2. the **post-SOFT held-only** state (held positions kept, no new/increase).

`POSITION_MONITOR` now asserts the monitor reports correctly (no false anomaly)
in *both*, and that a deliberately-corrupted position set (negative / non-finite /
over-capital) is caught. `NAV_RECONCILE` asserts a flat→target rebalance
reconciles to a **zero NAV residual** and that a corrupted outcome is caught.

---

## How to run it

```bash
# Ephemeral sandbox (auto-created and torn down); prints the report.
python3 -m spa_core.paper_trading.pre_cutover_gate

# Or via the thin script wrapper (identical behaviour):
python3 scripts/pre_cutover_gate.py

# Against an explicit sandbox dir (NEVER the live data/ dir — that is refused):
python3 scripts/pre_cutover_gate.py --data-dir /tmp/spa_sandbox

# JSON output:
python3 scripts/pre_cutover_gate.py --json-only
```

The gate **refuses** to run against the live `data/` directory — it raises rather
than risk reading/writing live track state.

### What exit 1 means

```
exit 0  ⇔ EVERY defense demonstrably fired (all assertions pass).
exit 1  ⇔ one or more defenses did NOT fire.
```

On exit 1 the report's `failing_gates` array **names** every defense that did not
fire (and `_print_report` prints `FAILING GATES: …`). An exit 1 means a money-path
defense could not be proven to fire — it is a **hard stop** on any cutover thinking
until the named defense is fixed. A drill that itself raises is treated as
**fail-CLOSED** (the defense is *not* proven → that gate fails).

---

## The full drawdown ladder

Four deterministic, evidenced-bars-only, non-finite-safe thresholds gate the
money path down a drawdown. Order of **effects** as the book falls:

The ladder (ADR-048, owner-approved 2026-06-27 — hard kill lowered 15→10, boundary
inclusive, DL-02 reconciled):

| Rung | Threshold | Source | Effect |
|---|---|---|---|
| **DL-01 daily** | single-day loss **> 2%** | `daily_limits.py` `MAX_DAILY_LOSS_PCT` | **HALT** the cycle (independent of cumulative drawdown). **NEVER deferred.** |
| **SOFT de-risk** | drawdown **∈ [5%, 10%)** | `kill_switch.py` `SOFT_DERISK_THRESHOLD_PCT` | halt new / no increase, **hold + reduce only**; edge-triggered WARNING; **no liquidation** |
| **HARD kill** | drawdown **≥ 10%** (inclusive `>=`) | `kill_switch.py` `DRAWDOWN_THRESHOLD_PCT` | **all-cash** kill `{cash:1.0, …:0.0}` — **OWNS the 10% peak-drawdown rung** |
| **DL-02 peak** | peak drawdown **> 10%** | `daily_limits.py` `MAX_DRAWDOWN_PCT` | HALT primitive (unchanged), but in `run_cycle` it **DEFERS** to the armed hard kill at ≥10% → cycle goes **all-cash**, not HOLD |

So down a single sustained drawdown the sequence is:
**SOFT de-risk (5%) → HARD all-cash (≥10%)**, with DL-01 (2% single-day) able to
HALT at any point on a sharp daily move. The DL-02 10%-peak rung is now SUBSUMED by
the hard kill (the stronger action) — a ≥10% peak drawdown goes all-cash, it no
longer HOLDs.

### Day-1 findings — RESOLVED by ADR-048

The two findings below were flagged at Day-1 as OWNER-DECISIONs; the owner resolved
both on 2026-06-27 (ADR-048 in `docs/DECISIONS.md`). Kept here for the audit trail.

1. **DL-02 @ 10% peak shadowed the HARD kill.** ~~The DL-02 HALT fired below the 15%
   hard kill and (because DL-02 runs at Step 2a, before the Step 2c kill override)
   early-returned a HOLD, preempting the all-cash kill.~~ **RESOLVED:** the hard kill
   was lowered to **10%** and now OWNS that rung; in `run_cycle` a DL-02-only HALT
   **DEFERS** to the armed hard kill so the all-cash override fires. DL-01 (daily
   loss) is never deferred. End state: ≥10% peak drawdown → ALL-CASH.
2. **The boundary gap.** ~~`check_drawdown_trigger` used strict `>` while
   `drawdown_tier` used `>=`, so they disagreed at exactly the threshold.~~
   **RESOLVED:** `check_drawdown_trigger` now uses `>=` — both fire at exactly 10.0%.

---

## OWNER-ONLY cutover blockers (code cannot satisfy these)

Even when **all defenses fire (exit 0)**, a real cutover is still blocked by items
that no code can satisfy — they are listed in every report under
`owner_only_blockers`:

- **custody** — Gnosis Safe 2-of-3 deployed + keys provisioned (ADR-010).
- **audit** — external security audit of the execution path signed off.
- **track_days** — ≥ 30 evidenced honest paper-track days (the go-live gate).
- **hot_key_hardware** — the signing hot key must be moved off a raw env-var
  into an **HSM / MPC / hardware signer** before cutover (see WS-5.4 below).

The pre-cutover gate proves the *software* defenses are sound; the cutover itself
remains an owner decision gated on custody, audit, track record, **and hardware
key custody**.

---

## WS-5 — structural execution arming + hot-key custody (owner-gated)

The capital primitives are guarded **structurally** (WS-5.1/5.2): every
sign/broadcast/send primitive (`eth_signer.sign_transaction`,
`eth_signer.send_raw_transaction`, `mev_protection.send_protected`) and every
adapter broadcast chokepoint **self-checks** the global arming flag and
HARD-RAISES unless it is explicitly armed. The defense no longer depends on a
decorator sitting on one wrapper method — a direct call to a primitive (the
classic bypass) is still blocked.

### `SPA_EXEC_ARMED` — THE owner-gated go-live arming flag

| | |
|---|---|
| Env var | `SPA_EXEC_ARMED` |
| Default | **OFF** (any non-affirmative value — unset / `""` / `0` / `false` — is OFF; fail-CLOSED) |
| Affirmative tokens | `1` / `true` / `yes` / `on` (case-insensitive, trimmed) |
| Module | `spa_core/execution/arming.py` (`is_exec_armed`, `assert_live_armed`) |
| Status during paper period | **STAYS OFF the entire paper period** |

Flipping `SPA_EXEC_ARMED` ON **is** the owner-gated go-live cutover for the
capital primitives. It is deliberately **separate** from `LiveTradingGate`
(`data/live_trading_gate.json`) and from each adapter's `is_live` flag — none of
those are touched by the arming layer; the `@live_trading_forbidden` decorator
stays as defense-in-depth on top. No automated process, test, agent, or sprint
flips it. The owner flips it as an explicit, deliberate cutover act, in
conjunction with the custody / audit / track-day blockers above.

### WS-5.4 — hot-key storage is OWNER-GATED (HSM / MPC)

`spa_core/execution/wallet.py` documents that the live signing key is sourced
from a raw environment variable (`SPA_PRIVATE_KEY`) and explicitly **recommends a
hardware wallet (Ledger/Trezor) or a KMS** instead. A raw hot key in an env var
is acceptable for an *inert, never-armed* paper system, but is **NOT acceptable
for a real cutover**:

- **Requirement (owner-provisioned, off-code):** before `SPA_EXEC_ARMED` is ever
  flipped ON, the signing key MUST be migrated to an **HSM, MPC signer, or
  hardware wallet** — the raw-env-var hot key path must not be the live signer.
- **This is surfaced, not papered over.** The code does **not** silently change
  key storage — that is the owner's provisioning decision (hardware procurement,
  KMS/MPC setup, key ceremony). WS-5.4 only makes the requirement explicit and
  records it as a pre-cutover OWNER-GATED blocker (`hot_key_hardware`).
- **Consistent MEV posture (WS-5.3):** the raw broadcast path
  (`eth_signer.send_raw_transaction`) is now fail-CLOSED by default — a
  Protect-RPC failure ABORTS rather than silently falling through to the public
  mempool. Public fallback re-enables **only** when the owner explicitly sets
  `MEV_PROTECT_FALLBACK=true` (default flipped `true → false`), matching the
  adapter path's fail-CLOSED posture.

---

## Guarantees

- **INERT** — `would_cutover` is **always False**; never moves capital / signs /
  touches a chain. `is_inert=True`, `moves_capital=False`.
- **No `execution/` import** — verified by test (`test_no_execution_import`).
- **Sandbox-only** — runs against a temp / supplied `data_dir`; **refuses** the
  live `data/` dir; the report records `live_data_untouched=True`.
- **stdlib-only · deterministic · fail-CLOSED · atomic writes · LLM FORBIDDEN.**

---

## Advisory wiring (non-blocking)

The gate is wired as an **advisory** CI step (`.github/workflows/ci.yml`,
`pre-cutover-gate` job) and a standalone test
(`spa_core/tests/test_pre_cutover_gate.py`). It is **advisory only** — it never
gates a push and never flips `is_live`. No new launchd agent is added (fleet
churn avoided); the gate is run on demand and in CI.

```bash
python3 -m pytest spa_core/tests/test_pre_cutover_gate.py -p no:randomly -q
```
