# 43 — Dangerous Strategies (§42)

**Purpose.** This is the desk's catalogue of strategy *patterns it refuses or approaches with extreme
caution*. Capital preservation is the governing principle (charter): the desk refuses
risk-compensation yield it cannot justify. Each pattern below records **why it is dangerous**, the
**evidence required before it may ever be considered**, the **maximum allocation if it is ever
allowed**, the **human-approval + Red-Team requirements**, and a defined **emergency-exit**.

**Reading rules.**
- **No invented numbers.** All caps are expressed as *rules and methods* (subordinate to the RiskPolicy
  hard caps), never invented percentages. Any concrete figure is `requires verification`.
- A pattern appearing here is **presumed REFUSE**. Listing an "evidence required" bar does not imply the
  bar is reachable — several patterns are effectively un-clearable and are documented as such.
- Everything here composes **under** the deterministic RiskPolicy hard gate
  ([`06_spa_core_invariants.md`](06_spa_core_invariants.md) §A) and the unified spread-attribution
  mandate ([`adr/ADR-YL-008-unified-yield-lab-mandate.md`](adr/ADR-YL-008-unified-yield-lab-mandate.md)):
  **every basis point of spread over the RWA floor must map to a specific, accepted, measurable risk, or
  the candidate is REJECTED** and the rejection is written to the refusal log as a first-class result.

**Scope discipline.** Advisory research catalogue. Refusal culture is already load-bearing in
`spa_core/redteam/` (scenario battery + rotation) and the hash-chained refusal logs. This document
formalizes the pattern list; the deterministic RiskPolicy remains the hard gate, and Risk Scoring v2
([`14_risk_scoring_v2.md`](14_risk_scoring_v2.md)) is advisory only.

**RiskPolicy hard caps every entry sits under** (`docs/06` §A, never overridden): TVL floor ≥ $5M/pool,
per-protocol 40% T1 / 20% T2, T2 total ≤ 50%, APY band 1–30%, min cash buffer ≥ 5%, two-tier kill
(SOFT −5% de-risk / HARD −10% all-cash). A "max allocation if ever allowed" below is always the
*stricter* of the pattern-specific cap and these hard caps.

**Cross-references:** [`33_yield_thesis_map.md`](33_yield_thesis_map.md) (where the yield comes from and
which mechanisms are already REFUSED), [`14_risk_scoring_v2.md`](14_risk_scoring_v2.md) (advisory
scoring + hard-reject triggers), [`07_yield_lab_lifecycle.md`](07_yield_lab_lifecycle.md) (the red-team
gate), [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md) (evidence
levels), `spa_core/redteam/`, the refusal logs.

---

## How to read each entry

| Field | Meaning |
|---|---|
| **Why dangerous** | The specific loss mechanism — how this pattern takes your capital to zero or to a large impairment. |
| **Evidence required** | What must be true and verified *before the desk would even open research* (not approval — just consideration). Where the bar is effectively unreachable, it says so. |
| **Max allocation if ever allowed** | The ceiling *if* every gate below is cleared — always the stricter of this and the RiskPolicy hard caps. "0" means not deployable, research-only. |
| **Approval + Red Team** | The human sign-offs and mandatory red-team questions ([`33`](33_yield_thesis_map.md) battery + spread-attribution per [`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)). |
| **Emergency exit** | The pre-committed unwind path, sized *before* entry. If there is no reliable exit, that is itself a REFUSE. |

---

## Dangerous strategy patterns

### 1. Unaudited high-APY vaults
- **Why dangerous.** No audit means an unknown exploit surface behind an attractive yield; the headline APY is bait and the loss is the entire principal via a contract exploit or rug. High APY on unaudited code is negative expected value.
- **Evidence required.** At least two reputable independent audits with published findings + remediation; verifiable, immutable or timelocked contracts; a track record through at least one stress episode; open-source verified bytecode. Absent audits → not researchable.
- **Max allocation if ever allowed.** 0 while unaudited. Post-audit it ceases to be "unaudited" and is re-evaluated as an emerging protocol (see #20), capped there.
- **Approval + Red Team.** Full red-team (exploit surface, admin keys, oracle) + human approval mandatory. Spread over floor must be fully risk-explained; an unexplained spread on unaudited code is presumed unpriced tail risk → REJECT.
- **Emergency exit.** None reliable pre-audit — this is the point. If already exposed, withdraw immediately and treat as at-risk.

### 2. Unknown / algorithmic stablecoins
- **Why dangerous.** Reflexive peg mechanics (mint/burn, seigniorage, under-backed algo designs) can collapse to zero in a bank-run spiral; the yield is compensation for holding a fragile peg. The failure mode is fast and total (UST-class).
- **Evidence required.** Full backing transparency (what collateralizes the peg, where custodied, attestation cadence); peg-defense mechanism decomposed; historical peg-hold through stress; independent proof-of-reserves. Algorithmic/under-collateralized designs are presumed un-clearable.
- **Max allocation if ever allowed.** 0 for algorithmic/under-backed. Only fully-collateralized, transparently-backed stablecoins are eligible, and then via the stablecoin-card system, not this pattern.
- **Approval + Red Team.** Stablecoin due-diligence card + red-team (depeg scenario, backing quality, redemption under stress) + human approval. No LLM in the peg-risk judgment.
- **Emergency exit.** Swap to a blue-chip stable *before* any depeg; a depegging algo stable has no exit at par — you exit into the loss.

### 3. Weak-bridge assets
- **Why dangerous.** A bridged/wrapped asset is only as safe as its bridge; a bridge exploit or freeze zeros the wrapped asset regardless of the underlying's health. Bridges are among the largest historical loss vectors in crypto.
- **Evidence required.** Bridge security model documented (validator set, multisig, light-client vs external-verifier); audits; exploit history; the number and identity of parties that can move funds. Opaque or externally-verified low-quorum bridges → REFUSE.
- **Max allocation if ever allowed.** Only native or canonically-bridged assets on vetted bridges; wrapped-via-weak-bridge = 0.
- **Approval + Red Team.** Red-team (bridge exploit, freeze, governance-who-can-move) + human approval. Cross-ref [`33`](33_yield_thesis_map.md) B4 (wrapped-BTC risk multiplier).
- **Emergency exit.** Unbridge to native where possible; if the bridge is compromised there is no exit — hold time is loss time.

### 4. Leverage loop without a liquidation model
- **Why dangerous.** You cannot bound loss you cannot model. Recursive supply/borrow loops amplify a positive spread but a rate inversion, oracle lag, or collateral depeg triggers a liquidation cascade; without a liquidation model the tail is unquantified and the position can be wiped.
- **Evidence required.** A full, backtested liquidation model: health-factor path under a ≥ −20% collateral shock, borrow-rate-spike scenario, oracle-lag scenario; documented unwind speed vs pool depth. **This is the desk's canonical refusal example** — the aggressive lab studied recursive looping and **REFUSED** it (dated liquidation drawdowns recorded in `spa_core/strategy_lab/aggressive_lab/`; see [`33`](33_yield_thesis_map.md) A2), because the extra APY is tail-comp for liquidation risk.
- **Max allocation if ever allowed.** 0 without a validated liquidation model. With one: isolated Max/Experimental sleeve only, small, capacity-bounded by unwind speed; never on correlated collateral (see #19).
- **Approval + Red Team.** Mandatory red-team: health factor under −20% shock, borrow-rate spike, oracle manipulation, hidden leverage. Human approval + risk-officer sign-off.
- **Emergency exit.** **De-lever first, always** — unwind the loop before touching anything else; unwind speed is the binding constraint, size for it in advance.

### 5. Opaque CeFi yield
- **Why dangerous.** Undisclosed counterparty and rehypothecation; the yield is generated off-book by activity you cannot see, and the failure mode is a withdrawal freeze then insolvency (Celsius/BlockFi-class). "Trust us" is not underwriting.
- **Evidence required.** Full counterparty disclosure, proof-of-reserves + proof-of-liabilities, segregation-of-assets attestation, redemption terms, regulatory status. Opaque desks are un-clearable by definition.
- **Max allocation if ever allowed.** 0. Off-code, relationship- and legal-gated; not a research-layer strategy.
- **Approval + Red Team.** Legal review + red-team (counterparty default, withdrawal freeze, rehypothecation chain) + human approval. External-capital rules apply.
- **Emergency exit.** Withdraw ahead of any stress signal; once a CeFi desk freezes withdrawals there is no exit.

### 6. Admin-key protocols
- **Why dangerous.** Upgradeable or admin-controlled contracts can drain funds, change terms, or pause withdrawals at the will of a key-holder; the yield does not compensate for handing a stranger a drain function.
- **Evidence required.** Timelock length + who holds keys (multisig threshold, signer identities); upgradeability scope; pause powers; on-chain governance vs unilateral admin. No timelock / single-key admin → REFUSE.
- **Max allocation if ever allowed.** Only with a meaningful timelock and reputable multisig; still capped as elevated-risk (T2 caps or tighter). Single-admin, no-timelock = 0.
- **Approval + Red Team.** Red-team (admin drain, malicious upgrade, governance capture) + human approval. Cross-ref [`33`](33_yield_thesis_map.md) A1 red-team ("governance capture").
- **Emergency exit.** Monitor the timelock queue; exit on any hostile-upgrade proposal before it executes — the timelock *is* your exit window.

### 7. Illiquid pools
- **Why dangerous.** Exit is slower and worse than entry; thin liquidity means large slippage on withdrawal and, in stress, stuck capital. Headline APY on an illiquid pool overstates realizable return.
- **Evidence required.** Depth analysis: exit slippage at our position size, historical liquidity under stress, withdrawal mechanics (queues, gates). Executable/net APY must be modelled *after* exit slippage ([`37`](37_apy_realism_and_evidence_standard.md) §2).
- **Max allocation if ever allowed.** Bounded so our position is a small share of exit-able depth; concentration and per-protocol caps apply. Size = f(exitable depth), not f(target yield).
- **Approval + Red Team.** Red-team (liquidity vanishes, exit slower than expected) + human approval at higher tiers.
- **Emergency exit.** Pre-sized partial-exit ladder; if depth is gone, accept slippage — never assume the quoted APY exit price.

### 8. Points farming with unclear value
- **Why dangerous.** The reward has no verifiable cash value — points/airdrops may never convert, or convert far below the implied APY; this is speculation dressed as yield. Cross-ref the codified refusal of LBTC-restaking and Pendle YT points ([`33`](33_yield_thesis_map.md) A5).
- **Evidence required.** A verifiable conversion mechanism and rate; historical realized value of comparable programs; the base (ex-points) yield stated separately ([`37`](37_apy_realism_and_evidence_standard.md) base-vs-incentive split rule). Unclear conversion → treated as **speculation, not yield**.
- **Max allocation if ever allowed.** 0 as a yield strategy. Points may be an *incidental* byproduct of an already-approved base strategy, never the thesis, and never counted in claimable APY.
- **Approval + Red Team.** Red-team ("do points convert to cash, at what rate, is this an airdrop-leverage trap") + human approval to hold any points-bearing base position.
- **Emergency exit.** Exit the base position on its own merits; assign points zero value until realized.

### 9. Emissions-only yield
- **Why dangerous.** APY funded by token emissions, not real revenue; it is a subsidy that ends, and the emitted token often falls faster than the yield accrues. Not sustainable and not real economic return.
- **Evidence required.** Base-vs-incentive split (mandatory, [`37`](37_apy_realism_and_evidence_standard.md) rule 5); emission schedule + cliff date; the sustainable ex-incentive figure; token-price dependency of the headline APY.
- **Max allocation if ever allowed.** The *sustainable ex-emission* portion governs sizing; the emission portion is flagged as subsidy and never carded as durable. If ex-emission yield < floor → REFUSE.
- **Approval + Red Team.** Red-team ("incentives end", emission cliff, fee-vs-subsidy split) + human approval. Cross-ref [`33`](33_yield_thesis_map.md) A9/A12 (incentive farming = subsidy, not yield).
- **Emergency exit.** Exit before/at the emission cliff; do not hold for a subsidy that has ended.

### 10. Rehypothecated lending
- **Why dangerous.** Collateral is reused elsewhere, creating a hidden chain of counterparty risk; one link failing cascades. You cannot underwrite a chain you cannot see.
- **Evidence required.** Full disclosure of whether and where collateral is rehypothecated; the counterparty chain; segregation terms. Undisclosed rehypothecation → REFUSE.
- **Max allocation if ever allowed.** 0 where rehypothecation is undisclosed; where disclosed and bounded, treated as credit exposure and capped as such (see #14).
- **Approval + Red Team.** Legal + red-team (counterparty-chain failure, rehypothecation cascade) + human approval.
- **Emergency exit.** Recall collateral where contractually possible; a rehypothecation chain may block recall in stress — assume the worst link.

### 11. Long-lockup with unclear exit
- **Why dangerous.** Capital is trapped with no reliable redemption path; you cannot rebalance, de-risk, or respond to the kill-switch. Illiquidity is itself a risk the yield rarely compensates.
- **Evidence required.** Explicit lockup term, redemption mechanics, secondary-market depth (if any), historical redemption behavior in stress. No defined exit → REFUSE.
- **Max allocation if ever allowed.** Bounded so locked capital never breaches the min-cash buffer or the ability to honor kill-switch de-risking; long lockups sized as a small, ring-fenced portion.
- **Approval + Red Team.** Red-team ("exit slower than expected", redemption freeze) + human approval; at higher tiers, formal liquidity-plan document.
- **Emergency exit.** Only per the contractual redemption window; if none, there is no emergency exit — which is why sizing is severe.

### 12. Hidden short-vol structured products
- **Why dangerous.** Sells tail risk for steady premium; the payoff looks like smooth yield until a stress move, then it blows up. The "income" is the market paying you to be short the crash.
- **Evidence required.** Full payoff decomposition — every embedded option/leg identified, the tail loss quantified, path-dependency modelled. Any structure whose payoff cannot be fully decomposed → REFUSE ([`33`](33_yield_thesis_map.md) A12).
- **Max allocation if ever allowed.** 0 unless payoff fully decomposed *and* the tail is bounded and priced; then isolated Max/Experimental sleeve, small.
- **Approval + Red Team.** Mandatory red-team (short-vol tail, stress payoff, most-fragile assumption) + human approval + risk-officer sign-off.
- **Emergency exit.** Unwind the structure — costly precisely when you need it; pre-model the stress-unwind cost.

### 13. CEX-concentrated delta-neutral
- **Why dangerous.** Counterparty and custody concentration on a single exchange; the strategy may be market-neutral but it is not exchange-neutral — a venue default/freeze zeros the hedged book (FTX-class). The neutrality is an illusion if one venue holds everything.
- **Evidence required.** Venue diversification plan, per-venue custody limits, withdrawal-reliability history, funding-depth across venues. Cross-ref [`33`](33_yield_thesis_map.md) A6/A7 (basis/funding, CEX leg custody-gated, currently BLOCKED-NO-HEDGE in `rates_desk/`).
- **Max allocation if ever allowed.** Per-counterparty exposure cap mandatory; no single venue holds more than a bounded share; custody/legal-gated. Single-venue = 0.
- **Approval + Red Team.** Red-team (venue default, withdrawal freeze, funding reversal) + human approval + legal for CEX access.
- **Emergency exit.** Close both legs and withdraw; if one venue freezes, the hedge breaks — size the un-hedged residual in advance.

### 14. Undercollateralized lending
- **Why dangerous.** Default risk is not covered by collateral; this is pure credit exposure with no on-chain liquidation backstop. Recovery depends on legal process, not code.
- **Evidence required.** Named underwriter, borrower disclosure, default history, recovery process, legal enforceability. Anonymous/undisclosed borrowers → REFUSE. Cross-ref [`33`](33_yield_thesis_map.md) A11 (private credit, measurement-GO / book NO-GO).
- **Max allocation if ever allowed.** Small, legal-gated credit sleeve only, with named counterparties and per-name caps; the spread must be fully explained as credit-risk premium ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
- **Approval + Red Team.** Legal + credit review + red-team (borrower default, recovery, lockup under stress) + human approval.
- **Emergency exit.** Often **none before maturity** — this is the binding risk; size assuming zero early exit.

### 15. Single-custodian BTC yield
- **Why dangerous.** One custodian's failure zeroes the position; concentrating BTC yield behind a single custodian adds counterparty risk on top of an already-thin yield. Cross-ref [`33`](33_yield_thesis_map.md) B4 — WBTC excluded (governance overhang), LBTC-restaking REFUSED.
- **Evidence required.** Custodian attestations, insurance, segregation, multi-custodian option; the honest base yield (BTC lending is near-0%, [`33`](33_yield_thesis_map.md) B2). Single-custodian with no diversification → REFUSE.
- **Max allocation if ever allowed.** Multi-custodian, low-utilization-aware only; per-custodian cap. The yield is small by nature — do not add custody risk to chase it.
- **Approval + Red Team.** Red-team (custodian default, wrapped-asset depeg) + human approval.
- **Emergency exit.** Redeem to native BTC per custodian window; if the custodian fails, exposed to its solvency.

### 16. Opaque market-making
- **Why dangerous.** Undisclosed strategy and inventory risk; you cannot underwrite loss modes you cannot see (adverse selection, toxic flow, inventory blow-up). "MM returns" without transparency is a black box.
- **Evidence required.** Strategy disclosure, inventory/risk limits, historical drawdowns, execution-infra transparency. Opaque MM → research-only, not fundable. Cross-ref [`33`](33_yield_thesis_map.md) A12.
- **Max allocation if ever allowed.** 0 as an allocation; requires owned execution infra and full transparency to even research.
- **Approval + Red Team.** Red-team (inventory loss, adverse selection, toxic flow) + human approval.
- **Emergency exit.** Redeem per terms; opacity means you learn of losses late — assume delayed information.

### 17. Options-as-income without tail analysis
- **Why dangerous.** Premium income masks unbounded or large tail loss; selling options for steady income is short-vol and blows up in the move it is "insuring." Income smoothness is not safety.
- **Evidence required.** Full tail analysis — max loss in a large adverse move, assignment risk, roll risk, venue depth per strike. No tail analysis → REFUSE. Cross-ref [`33`](33_yield_thesis_map.md) B3/C4 (covered calls: REFUSE naked, decision-support overlay only).
- **Max allocation if ever allowed.** Only *covered* (fully-collateralized, no naked short) as a decision-support overlay on already-held spot; never leveraged, never naked. Naked short-vol = 0.
- **Approval + Red Team.** Mandatory red-team (behavior in a large rally/crash, vol crush, assignment/venue default) + human approval.
- **Emergency exit.** Buy back the options — costly in the adverse move; pre-model the stress buy-back cost.

### 18. APY paid in illiquid tokens
- **Why dangerous.** The headline yield cannot be realized at the quoted value; you are paid in a token you cannot sell without collapsing its price. Observed APY ≠ executable/net APY.
- **Evidence required.** Liquidity of the reward token (exit slippage at accrual size), historical realizable value, base yield stated in a liquid asset. Mark reward-token APY at *realizable*, not quoted, value ([`37`](37_apy_realism_and_evidence_standard.md)).
- **Max allocation if ever allowed.** Only the liquid-realizable portion counts toward sizing; illiquid reward value is discounted to what can actually be sold.
- **Approval + Red Team.** Red-team (reward-token depth, realizable value) + human approval.
- **Emergency exit.** Convert rewards to a liquid asset promptly; do not accrue an illiquid token expecting the quoted price.

### 19. Recursive leverage on correlated collateral
- **Why dangerous.** Correlation breaks the model exactly in stress; leveraging an asset against a correlated asset (e.g. LST vs ETH, or two pegged stables) assumes a peg/ratio that fails precisely when you are levered, triggering a cascading liquidation. The correlation assumption is the fragile point.
- **Evidence required.** Correlation-breakdown / depeg-residual model under stress; liquidation path when the "correlated" pair diverges; historical depeg episodes of the specific pair. Cross-ref #4 (liquidation model) — this is the strictly more dangerous variant.
- **Max allocation if ever allowed.** 0 by default. Even with a liquidation model, correlated-collateral looping is presumed to have hidden tail risk (the model breaks when correlation breaks) → research-only.
- **Approval + Red Team.** Mandatory red-team (depeg residual, correlation breakdown, cascade) + human approval + risk-officer sign-off.
- **Emergency exit.** De-lever *before* the correlation stress — but the stress arrives faster than the unwind; this is why the default is REFUSE.

### 20. Brand-new protocol with high APY
- **Why dangerous.** No track record; high APY on unproven code combines exploit risk, incentive-only yield, and unknown admin/governance — three of the loss modes above at once. New + high-APY is a compound risk, not an opportunity.
- **Evidence required.** Audits (see #1), time-in-production through at least one stress episode, base-vs-incentive split (see #9), admin-key/timelock disclosure (see #6). A brand-new protocol cannot hold evidence above L1/L2 by definition.
- **Max allocation if ever allowed.** 0 at launch. After it earns real track record it graduates out of "brand-new" and is re-evaluated under emerging-protocol rules — post-audit, strictly size-capped, isolated ([`33`](33_yield_thesis_map.md) mechanism #14 "emerging-protocol lending").
- **Approval + Red Team.** Full red-team (exploit surface, incentive durability, admin keys, governance) + human approval; the spread must be fully risk-explained or REJECT ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
- **Emergency exit.** Small size + fast exit plan; treat the whole position as at-risk until it has a real track record.

---

## Cross-cutting refusal discipline

Every pattern above is enforced by the same machinery, in this order:

1. **Deterministic RiskPolicy hard gate** ([`06`](06_spa_core_invariants.md) §A) — the caps above are
   never overridden; `approved=False` cannot be reversed by anyone, including an LLM.
2. **Spread-attribution gate** ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)) — every
   point of spread over the RWA floor must map to a named, accepted, measurable risk; unexplained spread
   → REJECT, recorded in the refusal log.
3. **Red-team battery** ([`33`](33_yield_thesis_map.md) red-team columns, `spa_core/redteam/`) — the
   loss-scenario questions, mandatory for every Enhanced/Max/Experimental/leverage/credit/counterparty/
   bridge/opaque/new-stablecoin/lockup/options/basis candidate.
4. **Human approval** — no dangerous-pattern candidate advances without explicit human sign-off; default
   autonomy is L0/L1 (research/recommendation), never execution.
5. **Refusal is a first-class positive result** — a rejection is written to the hash-chained refusal log
   (the desk's stated moat, [`33`](33_yield_thesis_map.md) cross-domain summary), not hidden. The
   canonical worked example is the **leverage-loop refusal** in `spa_core/strategy_lab/aggressive_lab/`
   (#4 above): studied, dated-drawdowns recorded, REFUSED because the excess APY was tail-comp for
   liquidation risk.

**The through-line:** the desk earns from real borrow demand and real economic yield, and refuses to be
paid for tail risk it cannot underwrite. Every entry above defaults to REFUSE; the "evidence required"
and "if ever allowed" columns describe the (often unreachable) bar for reconsideration, not a promise
that the bar can be met.
