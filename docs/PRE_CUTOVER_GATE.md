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
| `HARD_KILL_DRAWDOWN` | 20% evidenced drawdown | `KillSwitchChecker` fires → kill-switch override forces **all-cash** |
| `HARD_KILL_MANUAL` | manual `kill_switch_active.json` present | kill fires → all-cash override |
| `HARD_KILL_RED_FLAGS` | > 5 CRITICAL red-flags on a **held** protocol | kill fires → all-cash override |
| `SOFT_DERISK` | 8% evidenced drawdown (∈ [5%,15%)) | **no new** position, **no increase** of held (clamped to held), reduction intact, **not liquidated** |
| `DL01_DAILY_LOSS` | single-day loss > 2% | `DailyLimitsChecker` **HALT** (DL-01) |
| `DL02_PEAK_DRAWDOWN` | peak-to-trough > 10% | `DailyLimitsChecker` **HALT** (DL-02) |
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

| Rung | Threshold | Source | Effect |
|---|---|---|---|
| **SOFT de-risk** | drawdown **≥ 5%** (and < 15%) | `kill_switch.py` `SOFT_DERISK_THRESHOLD_PCT` | halt new / no increase, **hold + reduce only**; edge-triggered WARNING; **no liquidation** |
| **DL-02 peak** | peak drawdown **> 10%** | `daily_limits.py` `MAX_DRAWDOWN_PCT` | **HALT** the cycle (no new trades this cycle) |
| **HARD kill** | drawdown **≥/> 15%** | `kill_switch.py` `DRAWDOWN_THRESHOLD_PCT` | **all-cash** kill `{cash:1.0, …:0.0}` |
| **DL-01 daily** | single-day loss **> 2%** | `daily_limits.py` `MAX_DAILY_LOSS_PCT` | **HALT** the cycle (independent of cumulative drawdown) |

So down a single sustained drawdown the sequence is:
**SOFT de-risk (5%) → DL-02 HALT (10%) → HARD all-cash (15%)**, with DL-01 (2%
single-day) able to HALT at any point on a sharp daily move.

### Day-1 findings — flagged as OWNER-DECISIONS to reconcile

These are **not code defects** (the gate proves the defenses fire on both sides of
each boundary). They are threshold-coordination questions deferred to the owner;
they are also recorded in `docs/DECISIONS.md` (ADR-034 addendum).

1. **DL-02 @ 10% preempts HARD @ 15%.** The DL-02 peak-drawdown HALT (10%) fires
   *below* the HARD all-cash kill (15%). A falling book therefore HALTs (stops
   adding) at 10% before the 15% all-cash kill is reached. Arguably correct
   (HALT-then-kill is safe ordering), but the two numbers were chosen
   independently. **OWNER-DECISION:** confirm the 10%-HALT / 15%-kill ordering is
   intentional, or reconcile into one explicit ladder.
2. **The 15.0% boundary gap.** `check_drawdown_trigger` HARD-kills on
   `drawdown > 15.0%` (strictly greater), while `drawdown_tier` classifies
   `drawdown >= 15.0%` as `HARD_KILL`. At **exactly 15.0%** the classifier says
   HARD but the trigger does not yet fire. The strictly-greater boundary is kept
   to preserve existing eval-path tests. **OWNER-DECISION:** make both `>=` (or
   both `>`), or accept the documented zero-width gap as immaterial.

---

## OWNER-ONLY cutover blockers (code cannot satisfy these)

Even when **all defenses fire (exit 0)**, a real cutover is still blocked by items
that no code can satisfy — they are listed in every report under
`owner_only_blockers`:

- **custody** — Gnosis Safe 2-of-3 deployed + keys provisioned (ADR-010).
- **audit** — external security audit of the execution path signed off.
- **track_days** — ≥ 30 evidenced honest paper-track days (the go-live gate).

The pre-cutover gate proves the *software* defenses are sound; the cutover itself
remains an owner decision gated on custody, audit, and track record.

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
