# 17 — Portfolio Construction (recommendation framework)

> **Canonical (ADR-YL-009).** This is the **CANONICAL product-line definition** (spread-based). The absolute-APY bands in `docs/33`/`34`/`38`/`03` are illustrative pre-audit (OQ-12).

> **Task:** PORT-001. **Autonomy:** L0/L1 — **advisory, recommendation-only**. This framework
> **never auto-executes**, never moves capital, never overrides the deterministic RiskPolicy, and
> never touches the runtime execution path. It produces a *proposal* a human reviews and approves.
> **Related:** `docs/06` (invariants), `docs/07` (Yield Lab lifecycle), `docs/14` (Risk Scoring v2,
> advisory), `docs/34` (capital tiers), `docs/adr/ADR-YL-008` (spread-over-floor mandate),
> `docs/templates/allocation_proposal.md` (PORT-002).

## 1. What this is (and is not)

- **Is:** a vocabulary of portfolio *models* and the rules for recommending an allocation across
  validated strategies. Output is an **allocation proposal** (PORT-002) for human approval.
- **Is not:** an allocator, an execution engine, or a hard gate. The authoritative hard gate stays
  `spa_core/risk/policy.py` (`version: v1.0`). This framework composes **under** RiskPolicy — only
  stricter, never looser (`docs/06` A.1).

Every recommendation is expressed as a **spread over the live RWA floor**, not an absolute APY, per
ADR-YL-008. The floor is a **dynamic value read from `data/rwa_feed.py`** (fail-closed to the
committed literal only if the feed is unavailable, and that fallback is flagged) — **never
hardcoded**. Do not invent floor, APY, TVL, or capacity numbers; unknown = "requires verification".

## 2. Eligibility precondition (before any model applies)

A strategy may be recommended **only if** it has cleared the Yield Lab lifecycle (`docs/07`):
yield-source verified, protocol + stablecoin review done, Risk Scoring v2 run (advisory), Red Team
passed, paper-test plan met, human approval on file — **and** its Strategy Card has
`spread_fully_explained = true` (ADR-YL-008). A card with unexplained spread is **not eligible** in
any model.

## 3. The seven portfolio models

Four **base models** (increasing risk budget) plus three **thematic sleeves** that may be layered on
top of a base model. All caps below are **research-layer proposals** and are **subordinate to
RiskPolicy caps** — where they conflict, RiskPolicy wins.

### Base models

| Model | Intent | Target spread over floor | Eligible | Forbidden |
|---|---|---|---|---|
| **Preserve** | Capital preservation first; floor-tracking. | ~0 (floor itself) | T1 RWA cash-floor, T1 lending (Aave/Compound/Morpho blue-chip) | anything with unexplained spread; T2 beyond a small buffer; any Experimental |
| **Core** | Conservative optimizer; small, fully-explained spread. | small, positive, fully explained | Preserve set + validated T1/T2 lending & PT fixed-carry | leverage, directional sleeves, points/airdrop-comp yield, Experimental |
| **Enhanced** | Larger spread, each point risk-explained. | larger, every bp mapped to a named risk | Core set + validated T2 (hedged carry, curated Pendle PT, validated sleeves) | un-hedged directional as core holding; unexplained spread; leverage above tier cap |
| **MaxYield** | Highest risk budget the tiers permit; isolated. | highest, still fully explained | Enhanced set + validated higher-risk sleeves in **isolated** allocation | any sleeve not spread-explained; anything past its per-strategy cap; naked tail-comp yield |

### Thematic sleeves (layer on a base model, isolated, capped)

| Sleeve | Intent | Eligible | Forbidden |
|---|---|---|---|
| **BTC-cycle** | Decision-support BTC exposure per cycle state (`docs/15`/`docs/36`). **Not auto-trading** (ADR-YL-007). | validated BTC read-only / decision-support positions | auto-execution; leverage on BTC; treating cycle signals as a hard gate |
| **ETH-yield** | Staking / LST / hedged-LST yield (`docs/16`). | validated plain-LST + hedged (β≈0) sleeves | naked LRT as a core holding; points/airdrop yield presented as APY; un-hedged directional in Core/Enhanced |
| **Experimental** | Sandbox for candidates still in the lifecycle. | lifecycle candidates **in paper only** | any live/public capital; inclusion in Preserve/Core; presentation as validated |

## 4. Caps (respect RiskPolicy; add stricter research caps)

Recommendations must satisfy, in order of authority:

1. **RiskPolicy hard caps (authoritative, `docs/06` A.1):** TVL floor ≥ $5M/pool; per-protocol 40%
   T1 / 20% T2; T2 total ≤ 50%; APY gate 1%–30%; min cash ≥ 5%. A proposal violating any of these is
   **rejected at proposal time** — do not submit it for approval.
2. **Capital-tier caps (`docs/34`):** the tier for the capital being sized further constrains allowed
   strategies, per-strategy caps, and capacity. A model may allow a strategy the tier forbids — the
   **tier wins**.
3. **Model / sleeve caps (this doc):** thematic sleeves are **isolated and individually capped**;
   Experimental never receives live/public capital.

The binding cap for any line item is the **most restrictive** of the three.

## 5. Target = spread over floor (ADR-YL-008)

For each recommended line item, the proposal records: the **live floor baseline** used (value +
source + as-of), the strategy's **spread over floor (bps)**, the **itemized risk explanation** of
that spread, and confirmation that `unexplained_spread = 0` (within documented tolerance). The
portfolio's target is framed as **risk-explained spread over the floor**, never as a headline APY.

## 6. Rebalance & stop rules

- **Rebalance:** recommendation-only, on a documented cadence or when a line item drifts beyond a
  stated band. A rebalance proposal is a new allocation proposal (PORT-002) requiring human approval;
  it never executes itself.
- **Stops / de-risk:** the two-tier kill-switch is authoritative and owner/ADR-gated
  (SOFT_DERISK at drawdown ∈ [5%,10%); HARD_KILL at ≥10% inclusive → all-cash; `docs/06` A.3). This
  framework **defers entirely** to it and never proposes anything looser. A model may propose a
  *stricter* advisory de-risk trigger, clearly flagged as advisory.
- **Card-driven stop:** if a held strategy's card loses `spread_fully_explained` (a risk changes),
  it becomes ineligible → propose reducing to floor-eligible holdings, human-approved.

## 7. Suitable capital tiers (indicative, see `docs/34`)

| Model | Indicative tier fit |
|---|---|
| Preserve | any tier, including the largest (floor scales) |
| Core | small → large, subject to tier capacity |
| Enhanced | small → mid; capacity-limited at scale (thin carry/PT depth) |
| MaxYield | small only; isolated; capacity-limited |
| Sleeves | isolated overlays, capped per tier |

Exact per-tier caps, custody / legal / IC / reporting thresholds, and capacity notes live in
`docs/34`; do not restate numbers here (avoid drift). This doc governs *how* to recommend; `docs/34`
governs *how much* per tier.

## 8. Output

Every recommendation from this framework is emitted through the **allocation proposal template**
(`docs/templates/allocation_proposal.md`, PORT-002), which includes the cap-check section, the
spread-over-floor basis, and a **human-approval line**. No proposal is acted on without that
signature.
