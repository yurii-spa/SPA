# 06 — SPA Core Invariants

These are **permanent invariants**. Every future session (human or agent) preserves them. They are
the trust foundation the Yield Lab / AI Investment OS is built *around*, never *through*. Each is
stated with its enforcement point in the repo so it can be verified, not just asserted.

## A. Risk & execution (hard, non-negotiable)

1. **Deterministic RiskPolicy is authoritative and is the sole hard execution gate.**
   `spa_core/risk/policy.py`, `version: v1.0`. No component may override an `approved=False`.
   Caps (canonical): TVL floor ≥ $5M/pool; per-protocol 40% T1 / 20% T2; T2 total ≤ 50%; APY gates
   1%–30%; min cash ≥ 5%. RiskPolicy `version` stays **"v1.0"** for the whole paper period; any
   change requires a new ADR.
2. **No LLM in the risk, execution, monitoring, or kill path.** Enforced by `spa-lint.yml`
   (LLM-forbidden lint). Deterministic only. Risk Scoring v2 (this project) is **advisory** and must
   never become a hard gate or import into the execution path.
3. **Two-tier kill-switch is fixed and owner/ADR-gated.** `spa_core/governance/kill_switch.py`:
   SOFT_DERISK at drawdown ∈ [5%,10%) (halt new / no increase, does NOT liquidate); HARD_KILL at
   drawdown ≥ 10% inclusive (all-cash). Values are owner-gated (ADR-034/048); do not change without
   an ADR. SOFT gate lives in `paper_trading/cycle_gates.py::apply_soft_derisk_gate`.
4. **Hard risk gates remain non-overridable** by any agent, recommendation, or advisory score.

## B. Custody & keys (hard)

5. **No private-key handling, no seed phrases, no auto-signing, no fund movement, no withdrawals**
   anywhere in the codebase or any agent. Execution Support (future) is **non-custodial** and
   human-in-the-loop only.
6. **`spa_core/execution/` must NOT be imported from read-only / paper / research code.** The
   read-only adapter domain never writes execution-owned state (`data/adapter_status.json` is
   execution-owned).

## C. Track & evidence honesty (hard)

7. **Paper trading and GoLiveChecker remain intact.** `paper_trading/cycle_runner.py` runs the daily
   cycle; `golive_checker.py` evaluates the 29 criteria. Do not weaken or bypass.
8. **APY / performance claims require an evidence level (L0–L6, `docs/37`).** Never present
   paper/backtest as live; never present advertised APY as executable/observed; always show yield
   source, risk category, and last-verified date. The "evidenced" track counts only real
   daily-cycle-log-backed days — backfill/reconstructed/warmup are excluded and labelled.
9. **Public logs and proof chains remain transparent.** Refusal logs + hash-chained decision logs +
   standalone verifiers ("don't trust us, check us") are load-bearing, not decoration.

## D. Data & platform (hard)

10. **Runtime `data/*.json` formats are not broken without a migration plan.** Research-layer card
    data goes in NEW directories only; runtime state and existing `data/*/` subdirs are untouched.
11. **Atomic writes only** for state files: canonical `spa_core.utils.atomic.atomic_save`
    (same-dir tmp + `os.replace`). Never a bare `open(..., "w")` on a state file.
12. **stdlib-only Python in runtime code** (FastAPI/uvicorn/bcrypt/Astro are the documented
    exceptions for the API/cabinet/site, not the deterministic core).
13. **The current public dashboard / Desk Cockpit / DFB board must not break.** Deployment behavior
    (`deploy-landing.yml` → Pages) is out of scope for research-layer changes.

## E. Governance & product (hard)

14. **Protocol whitelist and caps remain conservative** unless changed by an ADR + owner decision.
15. **Risk disclosure and honest framing remain visible** on every public surface. The desk is not a
    high-yield product; it holds a conservative book and refuses risk-compensation yield it cannot
    justify.
16. **Higher-yield strategies go through the Yield Lab lifecycle before any public/live use**
    (`docs/07`). No strategy reaches Enhanced/Max without yield-source verification, protocol +
    stablecoin review, liquidity review, Risk Scoring v2, Red Team review, a paper-test plan, and
    human approval.
17. **Risk Scoring v2 is advisory, not an execution gate** (ADR-YL-004).
18. **Execution Support is non-custodial** (ADR-YL-005). **External capital requires legal review**
    before acceptance. **BTC/ETH cycle modules are decision-support, not auto-trading** (ADR-YL-007).
19. **Default autonomy is Level 0 / Level 1 only** (research / recommendation). No execution
    automation is introduced by the Yield Lab work.

## F. Change discipline (workflow)

20. **No big-bang rewrites; one task per iteration; no hidden behavior; no architecture drift.**
    Code changes require tests; behavior changes require doc updates. Stop and ask before touching
    the runtime execution path, RiskPolicy, public dashboard, security-sensitive behavior, or
    deployment. Research-layer docs/templates/schemas may proceed without asking.

> Verification: a future session can check each invariant against its named enforcement point. If any
> code change would violate one, it is out of scope for the research layer and must be escalated.
