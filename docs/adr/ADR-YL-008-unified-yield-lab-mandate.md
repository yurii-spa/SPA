# ADR-YL-008 — Unified Yield Lab Mandate (spread-over-floor, every point risk-explained)

**Status:** Accepted (owner decision, resolves OQ-1). **Date basis:** yield-lab-scaffolding branch.
**Supersedes the open framing in:** `docs/31_open_questions.md` OQ-1.
**Related:** `docs/07_yield_lab_architecture.md`, `docs/11_strategy_card_system.md`,
`docs/14_risk_scoring_v2.md`, `docs/33_yield_thesis_map.md`, `docs/34_capital_tiers_strategy.md`,
`docs/37_apy_realism_and_evidence_standard.md`, `prompts/agents/red_team_agent.md`,
`prompts/agents/capital_allocation_agent.md`. **Preserves:** all SPA Core invariants (`docs/06`).

## Context

Two facts were in tension and had to be reconciled by an owner decision:

1. **The founder mission** (charter, `prompts/claude_code/yield_lab_master.md`): systematically
   discover and validate **fundable strategies in the 10–15% annualized range** (stablecoins, BTC,
   ETH), with capital preservation first.
2. **The audit finding** (`docs/02` §5, `docs/34`, `docs/31` OQ-1): the desk does **not** beat the
   RWA floor (≈3.4%, dynamic, live from `data/rwa_feed.py`) via *yield* at *fundable scale* — the
   optimizer edge goes negative past ~$1M and carry is venue-capped (~$1–2M). Chasing high absolute
   APY without accounting for this is self-deception.

OQ-1 posed these as an either/or: mandate = "find fundable 10–15%" **or** "prove why most 10–15% is
risk-compensation and find the rare exceptions." The owner rejects the dichotomy.

## Decision

**The Yield Lab mandate is unified, not a choice between the two:**

> Systematically search for **fundable strategies in the 10–15% range**, while **every point of spread
> over the current RWA floor** (≈3.4%, a **dynamic value taken from data, never hardcoded**) **must be
> explained by a specific accepted and measurable risk**. A strategy whose spread is **unexplained is
> rejected**. **Rejection is a full, positive result of the Lab's work and must be recorded in the
> refusal log.** The **RWA floor is the official baseline**: every Enhanced/Max strategy is evaluated
> as a **spread over the floor**, not as an absolute APY.

This synthesizes both poles: the Lab *actively searches* for high-yield mechanisms (mission), *and*
rigorously requires each basis point of spread to map to a named, accepted, measurable risk
(honesty). The rare strategies whose spread is fully risk-explained are the fundable exceptions; the
rest are refused — and the refusals are themselves the product.

## Consequences

### Approve / reject criteria (Yield Lab lifecycle, `docs/07`; Strategy Cards, `docs/11`)
- A candidate is no longer judged on **absolute APY**. It is judged on **spread = observed/sustainable
  APY − live RWA floor**, and on whether that spread is **fully accounted for** by named, accepted,
  measurable risks.
- **Spread-accounting requirement:** the sum of the priced, accepted risks must **explain the whole
  spread**. Residual (unexplained) spread is treated as **unpriced tail risk**, not as alpha.
- **Decision rule:** `unexplained_spread > 0` (beyond a documented tolerance) → **REJECT**. Fully
  explained + risks within policy + evidence sufficient → eligible to advance. This gate composes
  **under** the deterministic RiskPolicy (`docs/06` A.1) — only stricter, never looser.
- The **live floor baseline** used for the evaluation is recorded on the card (never a hardcoded
  literal): source = `data/rwa_feed.py` (fail-closed to the committed literal only if the feed is
  unavailable, and that fallback is flagged).

### Red-team review (`prompts/agents/red_team_agent.md`)
- Red Team gains a **mandatory spread-attribution check**: for the strategy's spread over the floor,
  is **every point explained by a specific, accepted, measurable risk?** Any **unexplained spread =
  a finding** (likely unpriced tail risk) → block until explained or reject.
- The existing loss-scenario battery still applies; the spread-attribution check is added on top and
  is mandatory for every Enhanced/Max/Experimental candidate.

### Refusal log (positive-result discipline)
- A rejection for **unexplained spread** is a **first-class positive output** and is written to the
  refusal log with: candidate id, floor baseline used, claimed spread, the risks that *were* priced,
  the residual unexplained spread, and the reason code (e.g. `unexplained_spread`). This reuses the
  existing hash-chained refusal machinery (`spa_core/strategy_lab/rates_desk/` decision log, the
  public `/refusals` surface) — refusals are the moat, per the Structural Desk arc.

### Strategy Card system (`docs/11`)
- New fields (advisory, non-runtime): `floor_baseline_pct` (the live floor used, with source +
  as-of), `spread_over_floor_bps`, `spread_risk_explanation` (the itemized mapping of spread → named
  accepted risks), `unexplained_spread_bps`, `spread_fully_explained` (bool). A card cannot advance to
  Enhanced/Max with `spread_fully_explained = false`.

### Risk Scoring v2 (`docs/14`, advisory only)
- Adds an advisory **`spread_attribution_score`**: how completely the observed spread is explained by
  the priced risk sub-scores (100 = fully explained, low = large unexplained residual). Low score is a
  **hard human-review + red-team trigger**. It remains **advisory** — never a hard gate, never wired to
  execution (ADR-YL-004 unchanged).

### Capital allocation (`prompts/agents/capital_allocation_agent.md`)
- The Capital Allocation agent recommends **only** over strategies that are `spread_fully_explained`
  and within RiskPolicy + capital-tier caps, and expresses targets in terms of **risk-explained spread
  over the live floor**, not absolute APY. It never overrides RiskPolicy and stays L0/L1.

## Alternatives considered (both rejected)

- **A — "Find fundable 10–15%" (pure yield-chasing).** Rejected: ignores the audit finding; would let
  the Lab market high absolute APY without accounting for the risk that produces it — the exact
  self-deception SPA's honesty culture exists to prevent.
- **B — "Prove most 10–15% is risk-comp and find the rare exceptions" (pure measurement/refusal).**
  Rejected: too passive; abandons the founder's active discovery mission and reduces the Lab to a
  critic. The unified mandate keeps the active search *and* the rigorous spread-attribution discipline.

The unified mandate (Decision) is the single source of truth for the Lab's approve/reject logic.
