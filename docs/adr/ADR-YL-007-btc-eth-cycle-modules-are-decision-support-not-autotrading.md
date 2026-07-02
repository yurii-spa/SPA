# ADR-YL-007: BTC / ETH cycle modules are decision-support, not auto-trading

| Field           | Value                                              |
|-----------------|----------------------------------------------------|
| **Date**        | 2026-07-02                                          |
| **Status**      | Accepted                                            |
| **Namespace**   | ADR-YL (Yield Lab)                                  |
| **References**  | `docs/06_spa_core_invariants.md` (18–19), `prompts/claude_code/yield_lab_master.md` (product lines, autonomy), ADR-YL-002, ADR-YL-005 |

---

## Context

The founder focus includes **BTC** and **ETH** alongside stablecoins, with dedicated "BTC Cycle" and
"ETH Yield" product lines. These modules analyze market regime, on-chain cycle signals, funding/basis,
and staking/LRT yields. The risk is that a "cycle model" quietly becomes an automated directional
trading bot — exactly the "AI trading bot" framing the master prompt forbids.

## Decision

**BTC and ETH cycle modules are decision-support only. They never auto-trade.**

- These modules produce **analysis and recommendations** (regime view, cycle stage, risk-on/risk-off
  read, yield/basis commentary) for a human. They do not place, size, or execute directional trades,
  and they do not move capital (invariant 18).
- Their outputs are advisory (Level 0 / Level 1 autonomy). They are **not** wired to execution and are
  subject to ADR-YL-002 (no LLM/analysis output on the execution path) and ADR-YL-005 (non-custodial,
  human-in-the-loop).
- Any live crypto-directional exposure that could arise from a BTC/ETH thesis must still pass the
  deterministic RiskPolicy and human approval, and — if it is a Yield Lab candidate — go through the
  full Yield Lab lifecycle and Strategy Card (`docs/07`, `docs/11`).
- Public BTC/ETH views carry the same APY/return evidence discipline (ADR-YL-006) and honest risk
  framing; no directional call is marketed as a guaranteed outcome.

## Consequences

- **Positive:** the desk can offer genuinely useful cycle/yield intelligence without becoming a
  black-box trading bot; the trust and safety boundary is unchanged.
- **Negative / cost:** timely signals still require a human to act — no automated capture of
  fast-moving directional moves.
- **Neutral:** BTC/ETH yield *strategies* (e.g. cash-and-carry, LST/LRT) are handled as normal Yield
  Lab candidates with Strategy Cards, distinct from the decision-support cycle *view*.

## Alternatives considered

- **Automate a small BTC/ETH directional sleeve behind risk caps** — rejected: introduces autonomous
  execution and directional auto-trading, both forbidden (18–19); caps do not change the category.
- **Fold BTC/ETH entirely into stablecoin lines** — rejected: loses genuinely distinct
  decision-support value; the honest fix is to scope them as advisory, not to hide them.
