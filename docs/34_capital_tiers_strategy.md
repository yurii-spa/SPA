# 34 — Capital Tiers Strategy

> **Canonical (ADR-YL-009).** This is the **CANONICAL capital-tiers** definition. Product-line APY bands are **NOT** defined here (a common mis-reference from `docs/07`) — see `docs/17` (spread-based, canonical) + OQ-12.

**Purpose.** Document how **capital scale changes the strategy universe**. A strategy that works at
$100k can fail at $10M — liquidity thins, capacity caps bite, slippage grows, lockups and redemption
queues matter, counterparty limits appear, ops/legal/custody obligations multiply, and concentration
becomes unavoidable. This doc gives, per tier, the allowed/forbidden strategy types, allocation caps,
and the operational/custody/legal/reporting thresholds that become **mandatory** as size grows.

**No invented numbers.** Every concrete APY/TVL/depth/threshold below is `requires verification`; caps
are expressed as *rules and methods*, not invented percentages beyond the RiskPolicy hard caps that
already exist ([`06_spa_core_invariants.md`](06_spa_core_invariants.md) §A: TVL floor ≥ $5M/pool,
per-protocol 40% T1 / 20% T2, T2 total ≤ 50%, APY 1–30%, min cash ≥ 5%).

**Do not duplicate.** The capital-scaling analysis is already partly coded — this doc *formalizes* it:
- `capital_sweep.py` — sweeps deployable size vs rate-compression / cap headroom (referenced in
  [`02_current_architecture_audit.md`](02_current_architecture_audit.md) §3 and the backlog `CAPITAL-001`).
- `forward_analytics.py` — risk-adjusted scorecard vs the RWA floor.

---

## 1. The honest scale finding (read first)

The desk's audited conclusion, and the frame for every tier below:

> **Pure yield does not beat the ~3.4% RWA floor (`requires verification`) at fundable scale by a
> durable margin.** The core plain-lending book scales roughly *flat* to a deployment ceiling on the
> order of ~$50–100M (`requires verification`) — caps and rate-compression barely bite there and it
> stays above the floor. But the *edge* (carry / basis / Pendle sleeves) is **venue- and depth-capped**
> on the order of ~$1–2M (`requires verification`); past that the marginal APY compresses toward, and
> then below, the floor.

Two distinct ceilings, do not conflate them:
- **Deployment-cap** (~$50–100M): how much the *conservative core* can hold before per-protocol/TVL
  caps and pool-share limits force dilution. Large.
- **Rate-compression / edge-cliff** (~$1–2M): how much the *thin exotic sleeves* (Pendle PT depth,
  funding depth) can hold before the excess-over-floor disappears. Small.

**Implication for tiers:** as capital grows, the mix must shift *toward* the deep conservative core and
*away* from the thin edge — the strategy universe **contracts** with size, it does not expand. See
[`33_yield_thesis_map.md`](33_yield_thesis_map.md) capacity rows and
[`37`](37_apy_realism_and_evidence_standard.md) §2 (capital-compression is a mandatory disclosure).

---

## 2. Tier ladder

Caps are **rules**, always subordinate to the deterministic RiskPolicy hard caps (never overridden,
[`06`](06_spa_core_invariants.md) §A). "Forbidden" means *not deployed at this tier*, not *never studied*.

### $100k
- **Allowed:** conservative lending, curated vaults, Pendle fixed, stable LP (base fees), RWA floor.
- **Forbidden (deployed):** private credit, OTC, structured products, looping, standalone basis/funding (custody-gated).
- **Caps:** per-strategy / per-protocol / per-stablecoin bounded by RiskPolicy; concentration barely binds — liquidity is ample at this size.
- **Requirements:** self-custody + paper-track honesty; daily monitoring; personal-grade reporting. No external obligations.
- **Mandatory thresholds triggered:** none beyond the invariants.

### $200k
- **Allowed:** as $100k. · **Forbidden:** as $100k.
- **Caps:** same rules; still liquidity-comfortable. · **Requirements:** as $100k; begin per-strategy attribution.

### $500k
- **Allowed:** as above; a **small** red-team-cleared basis/carry sleeve becomes *considerable* (isolated), subject to custody being solved.
- **Forbidden:** looping, structured products, unvetted credit.
- **Caps:** exotic-sleeve sizing starts to matter — cap the edge sleeve to its verified depth (the ~$1–2M cliff is now visible in method).
- **Requirements:** documented allocation policy; per-strategy monitoring; monthly reporting.

### $1M
- **Allowed:** full conservative core + edge sleeves *at their capacity limit*.
- **Forbidden:** anything whose capacity is exceeded at this size; unvetted counterparty exposure.
- **Caps:** **edge-cliff binds here** — the thin carry/basis/Pendle sleeves approach their ~$1–2M ceiling; incremental capital must go to the deep core, not the edge.
- **Requirements:** formal allocation limits; slippage/entry-price accounting; **capital-compression disclosure mandatory** (doc 37 §4 rule 6).

### $5M
- **Allowed:** conservative core dominates; edge sleeves *capped* (already at/over their cliff — no further edge scaling).
- **Forbidden:** relying on the edge for marginal yield (it no longer beats the floor at this incremental size).
- **Caps:** per-protocol pool-share limits begin to bite; concentration management is now a first-class task; queue/lockup exposure must be sized.
- **Requirements:** **institutional custody** becomes appropriate; **audit-grade reporting**; documented liquidity/exit plan per position; risk review cadence formalized.

### $10M
- **Allowed:** conservative core across diversified deep protocols; RWA floor as a large stable base.
- **Forbidden:** treating exotic sleeves as material yield contributors (a $100k strategy *fails* here — see §1).
- **Caps:** concentration + pool-share limits actively force diversification; single-protocol exposure bounded well under pool-liquidity share.
- **Requirements:** **institutional custody mandatory**; **external legal review** for any credit/OTC/off-code exposure; **audit-grade reporting mandatory**; formal risk-review cadence.

### $25M
- **Allowed:** deep conservative core + large RWA; only capacity-proven mechanisms.
- **Forbidden:** any strategy without demonstrated capacity + institutional-grade exit liquidity.
- **Caps:** counterparty limits and venue concentration are binding; per-counterparty exposure caps mandatory.
- **Requirements:** **OTC access** becomes relevant for sizing entries/exits without moving markets; **dedicated risk officer**; **formal Investment Committee (IC)** for allocation decisions.

### $50M
- **Allowed:** as $25M; deployment approaches the conservative-core ceiling (~$50–100M).
- **Forbidden:** as $25M; edge sleeves are noise at this scale.
- **Caps:** deployment-cap starts to constrain — dilution across more protocols/chains, or accept lower blended yield.
- **Requirements:** **OTC / institutional custody / external legal / risk officer / formal IC** all mandatory; **audit-grade reporting**; external-capital handling requires legal review ([`06`](06_spa_core_invariants.md) §E-18).

### $100M+
- **Allowed:** conservative core + RWA at institutional scale; capacity-proven only.
- **Forbidden:** any material reliance on thin/exotic yield; anything without institutional exit liquidity.
- **Caps:** deployment-cap binds — blended yield converges toward the floor; concentration and cross-chain/cross-protocol diversification are unavoidable.
- **Requirements:** full institutional stack — custody, audit-grade reporting, IC, risk officer, legal, external-capital legal review, formal ops. The strategy universe is **narrowest** here.

---

## 3. What scale changes (the axes)

Every tier transition moves these, and each can turn a working strategy into a failing one:

| Axis | How scale bites |
|---|---|
| **Liquidity** | Exit depth thins relative to position; a clean exit at $100k becomes a market-moving exit at $10M. |
| **Capacity** | Thin sleeves (Pendle PT depth, funding depth) cap out ~$1–2M; the core caps ~$50–100M. |
| **Slippage** | Entry/exit price impact grows with size — erodes executable/net APY (doc 37 §2). |
| **Lockups & queues** | Redemption windows, unstake queues, and credit lockups become material exposure to size. |
| **Counterparty limits** | CEX/custodian/issuer per-name limits appear; concentration on any single counterparty must be capped. |
| **Ops** | Monitoring, reconciliation, and reporting obligations scale from personal → institutional. |
| **Legal** | External capital, credit, and OTC require legal review; jurisdiction/reg exposure grows. |
| **Concentration** | Pool-share and per-protocol caps force diversification, diluting the best rates. |

**The rule:** before deploying an existing strategy at a larger tier, re-run its capacity/liquidity/
slippage analysis at the new size (`capital_sweep.py` method) and re-verify it still beats the RWA floor
*risk-adjusted, after stress, net of compression*. If it does not, it is forbidden at that tier — a
$100k strategy is not automatically a $10M strategy.

---

## 4. Threshold summary — what becomes mandatory when

| Requirement | Becomes mandatory around |
|---|---|
| Documented allocation policy + per-strategy attribution | $500k |
| Capital-compression disclosure on every claim | $1M |
| Institutional custody (appropriate → mandatory) | $5M → $10M |
| Audit-grade reporting | $5M (appropriate) → $10M (mandatory) |
| External legal review (credit / OTC / external capital) | $10M |
| Dedicated risk officer | $25M |
| Formal Investment Committee | $25M |
| OTC access for sizing entries/exits | $25M |
| Full institutional stack (all of the above) | $50M–$100M+ |

Cross-references: [`33_yield_thesis_map.md`](33_yield_thesis_map.md) (per-mechanism capacity + tier
rows), [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md)
(capital-compression as a mandatory disclosure), [`38_stablecoin_yield_engine.md`](38_stablecoin_yield_engine.md)
(per-stablecoin max-allocation logic), [`06_spa_core_invariants.md`](06_spa_core_invariants.md) §A
(the hard RiskPolicy caps these tier rules sit under), and `capital_sweep.py` / `forward_analytics.py`
(the code that measures the ceilings).
