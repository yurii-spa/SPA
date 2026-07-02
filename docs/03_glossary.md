# 03 — Glossary (DOCS-004)

Shared vocabulary for the Yield Lab / AI Investment OS research layer. Tight definitions; each entry
cross-references the doc where the concept lives in full. No invented numbers — any concrete APY/TVL is
`requires verification`. Cross-refs: [`02`](02_current_architecture_audit.md), [`06`](06_spa_core_invariants.md),
[`07`](07_yield_lab_architecture.md), [`33`](33_yield_thesis_map.md), [`34`](34_capital_tiers_strategy.md),
[`35`](35_strategy_discovery_engine.md), [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md).

---

## Yield & spread

- **Yield source** — the *actual* reason a strategy is paid, reduced to one of five honest buckets:
  borrow demand · risk premium (tail-comp) · basis/funding · incentives/subsidy · real economic yield.
  Knowing the bucket tells you why the yield can vanish. → [`33`](33_yield_thesis_map.md) §0.
- **RWA floor / baseline** — the live tokenized-T-bill yield (≈3.4% `requires verification`, TVL-weighted,
  **dynamic from `data/rwa_feed.py`, never hardcoded**). It is the **official baseline**: every
  Enhanced/Max strategy is judged as a *spread over the floor*, not as an absolute APY.
  → [`33`](33_yield_thesis_map.md) A10, [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md).
- **Spread-over-floor** — `spread = sustainable/observed APY − live RWA floor`, expressed in bps. The
  unit the Lab evaluates candidates in. → [`07`](07_yield_lab_architecture.md) §1a.
- **spread_fully_explained** — bool (advisory Strategy-Card field): the priced, accepted risks sum to
  explain the *whole* spread. If false, residual spread is treated as **unpriced tail risk** and the
  card cannot advance to Enhanced/Max. → [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md).

## Evidence & lifecycle

- **Evidence level L0–L6** — the mandatory ladder for any APY/performance claim. L0 idea/unverified ·
  L1 historical public APY observed · L2 data-source verified · L3 paper-tracked · L4 small-capital
  tested · L5 live-capital tested · L6 multi-cycle validated. "Evidenced" counts only real
  daily-cycle-log-backed days; backfill/warmup excluded. → [`06`](06_spa_core_invariants.md) §C-8,
  [`37`](37_apy_realism_and_evidence_standard.md).
- **Yield Lab lifecycle statuses** — `idea → research → rejected / paper_testing → paper_passed →
  small_capital_testing → small_capital_passed → approved_for_{preserve,core,enhanced,max_yield} /
  frozen / retired`. Each status has an entry/exit/evidence/approval contract. → [`07`](07_yield_lab_architecture.md) §3.
- **Refusal (positive result)** — a documented rejection (e.g. `unexplained_spread`). Refusals are a
  **first-class output** of the Lab, written to the hash-chained refusal log — not a failure, the
  product. → [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md), [`33`](33_yield_thesis_map.md) REFUSE markers.

## Product & capital

- **Product lines** — target ranges the Lab graduates into: **Preserve 4–7% · Core 7–10 · Enhanced
  10–13 · MaxYield 13–18 · Experimental 18–25%+** (ranges = categories, never promises). Higher lines
  require full lifecycle validation before public use. → [`33`](33_yield_thesis_map.md), [`34`](34_capital_tiers_strategy.md).
- **Capital tiers** — $100k → $100M+ scale bands that *change the strategy universe* (liquidity,
  capacity, slippage, lockups, counterparty limits, ops/legal/custody, concentration). The universe
  **contracts** with size. → [`34`](34_capital_tiers_strategy.md).
- **Sleeve** — an isolated, capacity-bounded book running one strategy/thesis (e.g. `rates_desk`
  FixedCarry, `eth_lst_neutral`). Advisory sleeves default `IS_ADVISORY=True` and move no live capital.
  → [`07`](07_yield_lab_architecture.md) §2, [`02`](02_current_architecture_audit.md) §2.

## Risk & governance

- **Risk Scoring v2 (advisory)** — 0–100 sub-scores → green/yellow/red + hard-reject / human-review /
  red-team triggers, plus an advisory `spread_attribution_score`. **Advisory only** — never a hard gate,
  never wired to execution. → [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md) (RSv2),
  ADR-YL-004, [`06`](06_spa_core_invariants.md) §A-2/E-17.
- **Risk taxonomy A/B/C/D** — the domain groupings used across the Lab: **A** stablecoin yield · **B**
  BTC yield & cycle (decision-support) · **C** ETH yield & cycle · **D** cross-cutting/off-code
  (custody, credit, legal). → [`33`](33_yield_thesis_map.md) Domains A/B/C + cross-domain summary.
- **Two-tier kill (SOFT/HARD)** — the deterministic drawdown ladder: **SOFT_DERISK** at drawdown
  ∈ [5%,10%) (halt new / no increase, does *not* liquidate); **HARD_KILL** at ≥10% inclusive (all-cash).
  Owner/ADR-gated (ADR-034/048); `spa_core/governance/kill_switch.py`. → [`06`](06_spa_core_invariants.md) §A-3.
- **Decision-support** — the Lab's default posture: research (L0) + recommendation (L1) only. No
  execution automation; BTC/ETH cycle modules are decision-support, never auto-trading (ADR-YL-007).
  → [`06`](06_spa_core_invariants.md) §E-18/19.
- **Non-custodial** — Execution Support never holds private keys, seeds, signs, or moves funds;
  human-in-the-loop only (ADR-YL-005). → [`06`](06_spa_core_invariants.md) §B.
