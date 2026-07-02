# 39 — Investment Committee Workflow (§37)

**Purpose.** Define the investment-committee (IC) workflow — the gated path a candidate strategy travels
from discovery to allocation — as a 19-stage flow where each stage names its **owner**, **required
inputs/docs**, **pass/fail criteria**, and **artifacts produced**. This operationalizes the Yield Lab
lifecycle ([`07_yield_lab_lifecycle.md`](07_yield_lab_lifecycle.md)) into a governance process with an
auditable decision trail.

**Scope discipline.** Research / decision-support only. This workflow produces memos and approval
records; it does **not** move capital, sign, or override the deterministic RiskPolicy
([`06_spa_core_invariants.md`](06_spa_core_invariants.md) A/B). Human approval is mandatory; default
autonomy is L0/L1. Every stage outcome is written to the hash-chained decision log; a **refusal at any
stage is a first-class positive result** ([`adr/ADR-YL-008-unified-yield-lab-mandate.md`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).

**Cross-references:** [`07_yield_lab_lifecycle.md`](07_yield_lab_lifecycle.md) (lifecycle statuses this
gates), [`14_risk_scoring_v2.md`](14_risk_scoring_v2.md) (advisory scores consumed at review stages),
[`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md) (evidence levels
required to advance), [`43_dangerous_strategies.md`](43_dangerous_strategies.md) (patterns that trigger
mandatory red-team), [`33_yield_thesis_map.md`](33_yield_thesis_map.md) (yield-source + red-team battery).

---

## 1. The 19-stage flow

Roles: **RA** = Research Analyst · **RiskO** = Risk Officer · **RT** = Red Team · **IC** = Investment
Committee · **Owner** = human approver. Lifecycle mapping is to the statuses in doc 07.

| # | Stage | Owner | Required inputs / docs | Pass/fail criteria | Artifact |
|---|---|---|---|---|---|
| 1 | Candidate intake | RA | Hypothesis, source | Well-formed hypothesis + named source → `candidate` | Candidate record |
| 2 | Initial screen | RA | Doc 33 yield-source bucket, doc 43 pattern check | Not an outright REFUSE pattern (doc 43); has a plausible real yield source → advance, else refuse | Screen result |
| 3 | Yield-source verification | RA | Doc 33 §0 bucket, data feeds (doc 23) | "Who pays and why" verified; not pure tail-comp/points → advance | Yield-source memo |
| 4 | Protocol due diligence | RA | Protocol card, audits, governance, admin-key/timelock | Audits present; admin/timelock acceptable (doc 43 #1,#6) → advance | Protocol card |
| 5 | Stablecoin due diligence (if applicable) | RA | Stablecoin card, backing, peg history | Transparent backing; no algo/under-collateralized (doc 43 #2) → advance | Stablecoin card |
| 6 | Liquidity / capacity review | RA | Depth, exit-slippage, capacity method (doc 34) | Exitable at our size; capacity ≥ intended sleeve → advance | Capacity memo |
| 7 | Risk Scoring v2 (advisory) | RiskO | Sub-scores + spread-attribution score (doc 14) | Advisory; low score = mandatory human-review + red-team trigger (never a hard gate) | Risk score record |
| 8 | Red-team review | RT | Doc 33 battery + spread-attribution (ADR-YL-008) | Every loss scenario answered; **spread over floor fully explained**; unexplained spread = block/refuse | Red-team review |
| 9 | Capital-tier fit review | RiskO | Doc 34 tier rules + caps | Fits an allowed tier within RiskPolicy caps → advance | Tier-fit memo |
| 10 | Paper-test plan definition | RA | Harness plan, evidence target (doc 37) | Plan defines real cycle-log-backed test → `paper_testing` | Paper-test plan |
| 11 | Paper-test execution | RA | Live paper harness | Runs N continuous evidenced days (no backfill) | Paper track (L3) |
| 12 | Paper-test results review | RiskO | Track, forward-analytics vs RWA floor | Beats floor risk-adjusted after stress → `paper_passed`, else refuse | Results memo |
| 13 | IC memo drafting | RA | All artifacts above | Complete memo (thesis, evidence, risks, spread accounting, caps) | IC memo |
| 14 | IC review / discussion | IC | IC memo | Committee reaches a recommendation | IC minutes |
| 15 | Human approval decision | Owner | IC memo + minutes | Explicit human sign-off (mandatory) → advance, else freeze/refuse | Approval record |
| 16 | Small-capital-test plan | RiskO | Execution-support checklist (non-custodial) | Plan defines small real-capital test (frictions observed) | Test plan |
| 17 | Small-capital-test results review | RiskO | L4 evidence | Executable net APY confirmed at size → `small_capital_passed` | Results memo |
| 18 | Allocation approval (per line / tier) | Owner + IC | All above + caps | Approved for a product line/tier within caps → `approved_for_{line}` | Allocation approval |
| 19 | Post-allocation monitoring & review | RiskO | Live monitoring, alerts, drawdown | Continuous; breach → escalation/freeze/kill-switch | Monitoring record |

---

## 2. Per-stage template

Every stage record carries a uniform template:

- **Owner** — the accountable role (above).
- **Inputs** — the documents/data required to start the stage.
- **Required docs/artifacts** — cards, memos, evidence records that must exist.
- **Pass/fail gate** — the explicit criterion (above); fail routes to §4.
- **Artifact produced** — the record written on completion.
- **Decision-log entry** — id, stage, outcome, reason code, `prev_hash`, `hash`.

---

## 3. Decision-log linkage

Every stage outcome (pass, fail, freeze, refuse) is written to the hash-chained decision log
([`24`](24_database_schema.md) `decisions`; the existing rates-desk decision log + public `/refusals`
surface). This gives an end-to-end, tamper-evident trail from intake to allocation — and makes refusals
auditable as the desk's stated moat.

---

## 4. Escalation & refusal paths

- **Fail at a gate** → the candidate is routed to `rejected` (with reason code) or `frozen` (pending
  more data), and the outcome is logged. A rejection for **unexplained spread** (stage 8) is a
  first-class positive result ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
- **Red-team trigger** — any doc-43 dangerous pattern, low Risk-Scoring-v2 score, or
  Enhanced/Max/Experimental/leverage/credit/counterparty/bridge/basis classification forces stage 8
  before any advancement.
- **Post-allocation breach** (stage 19) — drawdown or risk-limit breach escalates to the two-tier
  kill-switch (SOFT −5% / HARD −10%, [`06`](06_spa_core_invariants.md)) and a freeze/review.
- **Owner override is only downward** — the human can refuse or freeze anything; no human or LLM can
  override `approved=False` from the deterministic RiskPolicy.
