# 42 — External Capital Readiness (§30)

**Purpose.** Define the readiness checklist that must be fully satisfied **before** any external
(non-owner) capital is accepted: legal review, entity/structure, disclosures, custody, reporting/track
methodology, KYC/AML, jurisdiction, and the final owner + legal sign-off gate. Each item states its
requirement and its owner.

**Scope discipline — hard gate.** **No external capital is accepted without legal review**
([`06_spa_core_invariants.md`](06_spa_core_invariants.md), invariant E-18). External capital is out of
scope until this checklist is fully satisfied and owner-approved. Nothing in the research layer
accepts, custodies, or moves external funds; the AI/LLM never holds keys, signs, or moves funds
(invariant B). This document is a governance checklist, not an offer of any product.

**Cross-references:** [`41_performance_reporting_methodology.md`](41_performance_reporting_methodology.md)
(track/reporting methodology investors would rely on), [`39_investment_committee_workflow.md`](39_investment_committee_workflow.md)
(allocation governance), [`34_capital_tiers_strategy.md`](34_capital_tiers_strategy.md) (the scale
thresholds at which external capital + legal review become mandatory), `spa_core/compliance/`
(existing audit-report + monthly-statement generators).

---

## 1. Readiness checklist

Every item must be **complete + signed off** before acceptance. Status values: not-started / in-progress
/ complete. Owner is the accountable party.

| # | Item | Requirement | Owner |
|---|---|---|---|
| 1 | **Legal review** | Mandatory prerequisite; **no external capital without it**. Covers securities/fund law, marketing constraints, no-guarantee framing. | Owner + external counsel |
| 2 | **Entity / structure** | Legal entity formed; fund structure defined (e.g. fund vs SMA); jurisdiction of formation chosen with counsel. | Owner + counsel |
| 3 | **Disclosures** | Risk disclosures + offering documents; explicit "no guaranteed / risk-free returns" framing; paper-vs-live honesty carried into all investor materials. | Counsel + RA |
| 4 | **Custody** | Custody model defined (non-custodial / qualified custodian); key-handling boundaries enforced — **no private keys / signing in-system** (invariant B). | Owner + custodian |
| 5 | **Reporting & track methodology** | Evidenced-track standard, paper-vs-live labelling, TWR/MWR, drawdown, disclosure rules ([`41`](41_performance_reporting_methodology.md)); investor reporting cadence + templates. | RiskO |
| 6 | **KYC / AML** | Investor onboarding, sanctions/PEP screening, record-keeping, ongoing monitoring. | Compliance + counsel |
| 7 | **Jurisdiction** | Permitted investor jurisdictions; per-region regulatory constraints; accreditation/eligibility rules. | Counsel |
| 8 | **IC & risk governance in place** | Formal IC, risk officer, and decision-log discipline operational ([`39`](39_investment_committee_workflow.md)) — these become mandatory at the tiers external capital implies ([`34`](34_capital_tiers_strategy.md) §4). | Owner |
| 9 | **Readiness gate** | The **full checklist passes + owner + legal sign-off** before any acceptance. Fail-closed: any incomplete item blocks acceptance. | Owner + counsel |

---

## 2. Custody & key-handling boundary (non-negotiable)

External capital does not relax the core invariant: the system remains **non-custodial and
human-in-the-loop**. The AI/LLM never holds private keys, sees seed phrases, signs transactions, or
moves/withdraws funds; Execution Support prepares checklists/approvals only and never controls funds
([`06`](06_spa_core_invariants.md) A/B). Any custody of external capital is via a qualified custodian
under the legal structure of item 2, entirely outside the research/AI layer.

---

## 3. Track & reporting standard investors rely on

Investor-facing performance uses the same honesty model as internal reporting
([`41`](41_performance_reporting_methodology.md)): evidenced track (real cycle-log days only), paper
never shown as live, every figure with evidence level + yield source + risk category + last-verified
date, and Enhanced/Max returns framed as **risk-explained spread over the RWA floor**
([`adr/ADR-YL-008-unified-yield-lab-mandate.md`](adr/ADR-YL-008-unified-yield-lab-mandate.md)). The
existing `spa_core/compliance/` generators (audit report, monthly statement) are the basis for investor
statements.

---

## 4. Sequencing with capital tiers

External-capital readiness is not a single event but tracks the tier ladder
([`34`](34_capital_tiers_strategy.md)): institutional custody, audit-grade reporting, dedicated risk
officer, formal IC, and external legal review become **mandatory** across the $5M → $50M range. External
capital cannot be accepted at any tier whose mandatory thresholds (§4 of doc 34) are unmet **and**
before the item-9 readiness gate passes with owner + legal sign-off. Until then, the desk operates on
owner capital only.
