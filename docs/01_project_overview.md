# 01 — Project Overview

> Research-layer document. It describes what SPA is and where the Yield Lab / AI Investment OS is
> going. It does not modify runtime code, the deterministic RiskPolicy, the kill-switch, the public
> dashboard, or deployment. Charter: [`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md).
> Read this alongside [`00_index.md`](00_index.md) (documentation map) and
> [`06_spa_core_invariants.md`](06_spa_core_invariants.md) (the invariants every session preserves).

---

## 1. What SPA is today

**SPA — Smart Passive Aggregator** is a **paper-stage DeFi stablecoin yield + risk desk**. It runs a
deterministic daily cycle on a **virtual** book: it pulls live APY/TVL from whitelisted protocols,
runs candidate allocations through a deterministic **RiskPolicy** gate, and rebalances a virtual
portfolio. No external capital is managed and no funds are moved — the desk is building an evidenced,
transparent track record before any live cutover is contemplated.

Its distinguishing culture is **measurement honesty**: APY/performance claims carry an explicit
evidence level, paper is never presented as live, and the desk publicly records the risk it *refuses*
to take. This is the trust foundation on which everything else is built.

## 2. The layered target architecture

The project is evolving from a single conservative optimizer into a layered, AI-native yield research
and decision-support system. Each layer is built **around** the SPA Core trust foundation, never
**through** it (see [`04_layered_architecture.md`](04_layered_architecture.md) for detail):

1. **SPA Core** — the existing deterministic, paper-tracked stablecoin yield optimizer. The trust
   foundation: deterministic RiskPolicy v1.0, two-tier kill-switch, paper track + GoLiveChecker.
2. **Yield Lab** — a closed research layer that discovers, tests, and either validates or **rejects**
   higher-yield strategies before any public exposure (lifecycle in [`07_yield_lab_architecture.md`](07_yield_lab_architecture.md)).
3. **AI Investment OS** — research / decision-support agents (discovery, protocol and stablecoin due
   diligence, risk memos, red-team, BTC/ETH cycle, portfolio recommendations, reporting).
4. **Builder OS** — dev-support agents (docs, backlog, prompts, architecture review).
5. **Execution Support** — **non-custodial, human-in-the-loop**: prepares checklists and unsigned
   approval packets; never holds keys, never signs, never moves funds
   ([`19_execution_support.md`](19_execution_support.md), ADR-YL-005).

## 3. Founder vision

Systematically discover and validate real, fundable yield mechanisms — targeting the **10–15%
annualized** range across **stablecoins, BTC, and ETH**, with opportunistic 15–20% reserved only for
limited high-risk sleeves. The overriding constraint is **capital preservation first**: the mission is
not diluted into a simple safe 5–8% optimizer, but higher yield is only pursued through evidence and
review, never through hype. BTC/ETH work is **decision-support, not auto-trading** (ADR-YL-007).

## 4. The honest edge finding

SPA's audit (see [`02_current_architecture_audit.md`](02_current_architecture_audit.md) §5,
[`34_capital_tiers_strategy.md`](34_capital_tiers_strategy.md), [`31_open_questions.md`](31_open_questions.md)
OQ-1) established a finding the desk does not hide:

> The desk **measures and refuses risk at a high standard, but does not beat the RWA floor
> (≈3.4%, dynamic and taken live from `data/rwa_feed.py`, never hardcoded) via *yield* at *fundable
> scale*.** The optimizer edge goes negative past ~$1M and carry is venue-capped (~$1–2M).

The edge is therefore **measurement and refusal**, not raw yield. **ADR-YL-008** resolves this into
the **unified Yield Lab mandate**: actively search for fundable 10–15% strategies **and** require that
**every point of spread over the live RWA floor be explained by a specific, accepted, measurable
risk**. Unexplained spread is treated as unpriced tail risk and **rejected — and each rejection is a
first-class positive result recorded in the refusal log.** Strategies are evaluated as **spread over
the floor**, never as absolute APY.

## 5. Pointers

- **Documentation map:** [`00_index.md`](00_index.md)
- **Invariants (read before any related work):** [`06_spa_core_invariants.md`](06_spa_core_invariants.md)
- **Honest architecture audit:** [`02_current_architecture_audit.md`](02_current_architecture_audit.md)
- **Unified mandate:** [`adr/ADR-YL-008-unified-yield-lab-mandate.md`](adr/ADR-YL-008-unified-yield-lab-mandate.md)
- **Evidence standard:** [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md)
- **Autonomy / governance:** [`20_human_in_the_loop_governance.md`](20_human_in_the_loop_governance.md)

> Where any doc and the charter diverge, the charter's *intent* governs. Never invent APY/TVL/repo
> facts; anything unknown is marked as **requiring verification**.
</content>
</invoke>
