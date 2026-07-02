# 35 — Screening Rubric (DISCOVERY-003)

The candidate screening rubric: a concise checklist run **before** a discovered candidate consumes any
due-diligence effort. It sits at the front of the funnel ([`35_strategy_discovery_engine.md`](35_strategy_discovery_engine.md)):
Candidate Record → **this rubric** → (reject / human-review / red-team) → lifecycle promotion
([`07`](07_yield_lab_architecture.md) §3). It **composes under** RiskPolicy (only stricter,
[`06`](06_spa_core_invariants.md) §A). No invented numbers — feed values are `requires verification`.

The rubric is a *filter*, not an approval. Passing every check makes a candidate eligible for the
8-step promotion gate ([`35_strategy_discovery_engine.md`](35_strategy_discovery_engine.md) §3); it
never approves anything (no LLM/score approves — human only).

---

## 0. ADR-YL-008 spread-attribution pre-screen (run FIRST)

Before any other check, attribute the spread. This kills most candidates cheaply.

- [ ] Compute `spread = observed/sustainable APY − live RWA floor` (floor from `data/rwa_feed.py`,
      dynamic, never hardcoded; record source + as-of).
- [ ] List the specific, **accepted, measurable** risks that should explain the spread and price each.
- [ ] `unexplained_spread = spread − Σ(priced accepted risks)`.
- **REJECT EARLY if `unexplained_spread > tolerance`** → residual is **unpriced tail risk, not alpha**.
  Write a refusal (`reason=unexplained_spread`) to the hash-chained refusal log — a first-class positive
  result ([`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
- [ ] `spread_fully_explained` recorded on the Candidate Record.

## 1. Hard-reject triggers (any → immediate REJECT, recorded)

- [ ] Unexplained spread persists after §0 (unpriced tail risk).
- [ ] Yield source cannot be named as one of the five buckets, or is **pure incentive/points/airdrop**
      dressed as sustainable yield ([`33`](33_yield_thesis_map.md) §0, A5) — subsidy, not yield.
- [ ] No **reproducible** data source our own code can pull (yield-source unverifiable < L2,
      [`37`](37_apy_realism_and_evidence_standard.md)).
- [ ] Underlying pool below the RiskPolicy TVL floor (≥ $5M/pool) or violates a hard cap
      ([`06`](06_spa_core_invariants.md) §A-1).
- [ ] Custody/keys/off-code dependency the desk cannot satisfy non-custodially (e.g. CEX-leg not built,
      `rates_desk` BASIS_HEDGE is BLOCKED-NO-HEDGE).
- [ ] Excluded-asset / codified refusal (e.g. WBTC governance overhang, LBTC-restaking,
      [`33`](33_yield_thesis_map.md) B4).
- [ ] Naked short-vol / structured payoff not fully decomposed ([`33`](33_yield_thesis_map.md) A12/B3).

## 2. Human-review triggers (any → hold at candidate; owner/IC must weigh in)

- [ ] Low advisory `spread_attribution_score` (large-but-under-tolerance residual)
      ([`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md) RSv2).
- [ ] Capacity/edge-cliff risk: candidate sits in a thin sleeve (~$1–2M carry/basis/Pendle depth) but is
      pitched at a larger tier ([`34`](34_capital_tiers_strategy.md) §1).
- [ ] Opaque or relationship/legal-gated (private credit, OTC, tokenized credit) — off-code
      underwriting ([`33`](33_yield_thesis_map.md) A11/A12).
- [ ] Lockup / redemption-queue exposure material at the intended tier.
- [ ] New launch (< track history) or single-counterparty concentration.

## 3. Red-team triggers (any → Red Team mandatory before promotion)

Red Team is mandatory for **Enhanced / Max / Experimental** and for any candidate involving: leverage ·
credit · counterparty · bridge · opaque mechanism · new stablecoin · lockup · options · basis.

- [ ] Any of the above categories present → run the `redteam/` battery ([`33`](33_yield_thesis_map.md)
      red-team Qs: how do we lose money, depeg, exploit, withdrawal freeze, funding reverse, basis
      collapse, BTC/ETH −50%, counterparty/oracle/governance fail, incentives end, APY compresses with
      capital, exit slower than expected, hidden leverage, most-fragile assumption).
- [ ] **Mandatory spread-attribution check** — is every point of spread explained by a specific,
      accepted, measurable risk? Any unexplained spread = a finding → block until explained or reject
      ([`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).

## 4. Verdict

| Outcome | Meaning | Next |
|---|---|---|
| **REJECT** | §0 or §1 tripped | Write refusal (positive result); terminal unless new evidence. |
| **HOLD** | §2 tripped | Stay at candidate; `next_action` updated for owner/IC. |
| **RED-TEAM** | §3 tripped | Run `redteam/`; only then eligible to advance. |
| **PASS** | none tripped, spread fully explained | Eligible for the 8-step promotion gate ([`35_strategy_discovery_engine.md`](35_strategy_discovery_engine.md) §3). Still requires human approval. |

Cross-refs: [`33`](33_yield_thesis_map.md), [`34`](34_capital_tiers_strategy.md),
[`35_strategy_discovery_engine.md`](35_strategy_discovery_engine.md), [`37`](37_apy_realism_and_evidence_standard.md),
[`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md), `spa_core/redteam/`, `spa_core/dfb/`.
