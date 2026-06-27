# SPA — Fundability one-pager

_Auto-generated, real-data, HONEST. Every performance number is sourced live from `data/`; a missing source is reported as data unavailable, never fabricated. stdlib-only, deterministic, fail-CLOSED. NOT marketing — the refusal-chain and the published NO-GO are the differentiator._

---

## 1. The thesis — measurement, not yield

SPA's deep backtest (2024-06 -> 2026-06, real data including the Aug-2024 crash) already killed the obvious answer: **plain crypto-yield is a diversifier, not an edge**. Neutral books don't beat the ~3.4% tokenized-T-bill floor risk-adjusted, directional books eat the full drawdown, and LRT restaking dies in crashes (ezETH depeg). "More APY" is a dead end.

> **The edge is not yield. The edge is the structural role of honest measurement / underwriting** — being the party that can correctly price and refuse risk others don't see, and *prove* it.

The convergent, honest conclusion across the research arc: **the moat is real, but it is a scale / trust / relationships play, not a single-strategy alpha play.** $10M/year is reachable through scale across many capacity-bound books plus the trust earned by a transparent, fail-closed measurement-and-refusal engine — over multiple years — not by chasing a higher headline rate. The code builds the proof; the proof earns the trust; the trust + capital + relationships are what turn it into $10M.


---

## 2. The validated edge

### Rates Desk — **GO** (refusal-first carry)

A risk-adjusted fair-value model for tokenized yield that (a) harvests genuinely mispriced carry and (b) REFUSES yield that is just tail-risk compensation (the ezETH / over-levered-USDe pattern). RWA floor reference: **3.4%/yr**.


| sleeve | stage | net APY %/yr | beats floor | max DD % | refusals | kills |
|---|---|---:|:--:|---:|---:|---:|
| fixed_carry | PAPER_CANDIDATE | 6.0901% | yes | 0.000% | 1070 | 8 |
| levered_carry | PAPER_CANDIDATE | 4.9571% | yes | 6.856% | 2211 | 1 |
| basis_hedge | BLOCKED-NO-HEDGE | 3.4000% | no | 0.000% | 0 | 0 |
| rate_matrix | PAPER_CANDIDATE | 6.0863% | yes | 0.000% | 3098 | 328 |

**Proof chain** (live, hash-linked `data/rates_desk/decision_log.jsonl`): **246** logged decisions — **132 refusals** (of which **111** structural tail-vetoes) and **114 entries**. Every decision — entry AND refusal — is hashed into a tamper-evident record: the public "what we traded AND what we refused, and why."


**Honest caveats (stated, not hidden):**
- The refusal fired **early** — toxic LRT PT books (ezETH / rsETH) were refused ~100% of days on *structural* grounds, never held into the Aug-2024 / Oct-2025 / Apr-2026 depegs; a huge quoted rate never rescued a tail-vetoed book.
- Deflated Sharpe is **structurally degenerate** for locked held-to-maturity carry (near-zero downside variance by construction) — reported as a not-noise check only; the verdict rests on the realized book APY beating the floor in-sample, out-of-sample, and through every stress window.
- The carry edge is **capacity-bound** (~$250k fundable ceiling per book; the §9 exit-capacity rule sizes DOWN rather than eat slippage). A single rates book does **not** clear $10M — this needs **scale across many gated books**.


### RWA Repo Backstop — **measurement-GO / book NO-GO**

"Lend against Liquidation NAV, not marketing NAV." The Safety Board measures, from free data, that RWA collateral is genuinely **not cash-like** on an executable on-chain exit: **11/11** assets not cash-like (LIQUID 0 · THIN 1 · REDEMPTION_ONLY 9 · UNSAFE 1). Max on-chain ERC-4626 NAV divergence from $1.00 marketing NAV measured: **8.17%**. The *measurement* layer is GO (deterministic, fail-closed, runs continuously); the underwriting *book* is NO-GO read-only — it needs whitelisting + redemption agreements + capital + legal, none of it buildable in code.


### Liquidator — **NO-GO** (published — we publish what we kill)

The long-tail / nested-collateral liquidation opportunity was measured read-only at ~$3.8M/yr gross addressable (top-20 ~$2.2M/yr) — ~5-10x **below** the $20M/yr bar, too small to justify the custody + CEX + balance-sheet build. **VERDICT: NO-GO, published.** Publishing the kill is itself the credibility signal: the desk states plainly what it refuses to build, not only what it ships.


---

## 3. The forward track-to-date (accruing, not yet 30)

**6/30 evidenced days — accruing, not yet 30** (honest anchor 2026-06-22, target 2026-07-21). Go-live criteria: **26/29 pass** — NOT READY (the remaining blockers are time-gated: there is simply nothing to fix in code, only track days to accrue).


Forward-track integrity: **all_ok** — 8 forward tracks, 0 failing (no duplicates / gaps / out-of-order / future-dated points).


---

## 4. The safety architecture

- **Refusal-first gate** — a deterministic policy composed *under* the global RiskPolicy, only ever stricter; LLM-forbidden in risk/kill; fail-CLOSED (missing/invalid data -> max tail-risk, never a silent pass).
- **Kill switch** — drawdown >= 5% closes everything; cannot be overridden.
- **Proof-of-reserves / NAV reconciliation** — NAV conserved across the simulated rebalance.

- **Go-live dry-run harness** (`golive_dry_run.json`): all gates reached=yes, ordering_ok=yes, NAV reconciliation=PASS, live-trading gate active=no, would_proceed=no, moves_capital=no. The gates are **verified inert** — the harness proves the fail-closed chain fires (RiskPolicy blocks an over-concentrated trade, the live-trading gate stays inactive) WITHOUT moving any capital.

- **Honest-track reset as a TRUST signal** — the track shows **6/30 accruing**, anchored to the real evidenced start. It was reset to the honest count rather than padded; the published low number IS the credibility.


---

## 5. The off-code gates — honestly, what stands between here and $10M

The code did its job: it took each thesis to an honest verdict for free. But across all three, the same boundary appears — **the code can measure and refuse; the $10M is off-code.** Stated plainly, not hidden:

- **Custody / MPC** — institutional key management for real capital; not buildable in read-only paper code.
- **External audit** — independent code + controls audit of the execution path.
- **Legal** — fund structure, collateral perfection, redemption agreements, force-redemption rights; the RWA underwriting leg can only be *documented*, not *executed*, without it.
- **Real capital + relationships** — whitelisting / subscription access to redemption queues; the carry edge needs scale across many capacity-bound books, which needs AUM.

This is the honest scale truth: SPA contributes the cheapest, most defensible first layer — the transparent, fail-closed measurement-and-refusal engine that PROVES the mispricing — plus an honest record of exactly which off-code legs gate the business.


---

_Regenerated 2026-06-27 01:36 UTC. All numbers live from `data/` (golive_status.json · rates_desk/rates_desk_promotion.json · rates_desk/decision_log.jsonl · rwa_safety_board.json · forward_track_integrity.json · golive_dry_run.json). Regenerable via `python3 scripts/generate_fundability_onepager.py --md`. Follow-up: a public `/fundability` site page mirroring this doc._
