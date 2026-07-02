# 29 — Yield Lab Backlog

> Prioritized research-layer backlog. **One task per iteration** (`docs/28` §9). All tasks are
> research-layer only (docs / schemas / templates / tests / non-runtime modules in NEW dirs); none
> touch runtime execution, RiskPolicy, the dashboard, or deploy — those are STOP-and-ask. Priority
> **P1/P2/P3**, complexity **S/M/L**. Tasks satisfied by the scaffolding run are marked **DONE**.
> Columns per task: id · title · description · inputs · outputs · acceptance · deps · pri · cx · CC prompt.

## AUDIT
- **AUDIT-001** — Current architecture audit. *Map charter assumptions vs existing repo.* in: repo, charter · out: `docs/02` · acc: every load-bearing module located, missing capabilities listed · deps: — · P1 · L · **DONE**. Prompt: "Audit spa_core vs the charter; write docs/02, invent nothing."
- **AUDIT-002** — Research-layer topology map. *How strategy_lab/redteam/riskwire/dfb/compliance map to charter vocabulary.* in: docs/02 · out: `docs/05` · acc: each module → charter role · deps: AUDIT-001 · P2 · M. Prompt: "Write docs/05 mapping existing research modules to charter layers."
- **AUDIT-003** — Test-suite health snapshot. in: tests/ · out: `docs/audit/test_health.md` · acc: pass/fail counts, no-network confirmed · deps: — · P2 · S. Prompt: "Snapshot suite health, no live-data mutation."

## DOCS
- **DOCS-001** — CC master instructions. out: `docs/28` · acc: constraints + safe-change + STOP-ask present · deps: AUDIT-001 · P1 · M · **DONE**.
- **DOCS-002** — Yield Lab architecture + lifecycle. out: `docs/07` · acc: full status table w/ approval/evidence · deps: AUDIT-001 · P1 · M · **DONE**.
- **DOCS-003** — Agent architecture. out: `docs/10` · acc: 16+9 agents w/ FORBIDDEN rows · deps: AUDIT-001 · P1 · M · **DONE**.
- **DOCS-004** — Glossary. out: `docs/03` · acc: yield-source/evidence/tier/sleeve defined · deps: — · P2 · S. Prompt: "Write docs/03 glossary."
- **DOCS-005** — Layered architecture doc. out: `docs/04` · acc: 5 layers + boundaries · deps: AUDIT-001 · P2 · M.

## YIELD_THESIS
- **YIELD-001** — Yield Thesis Map. *Where yield actually comes from (stablecoin/BTC/ETH), risks per source.* out: `docs/33` · acc: each source has mechanism + risk + evidence level · deps: AUDIT-001 · P1 · L · **DONE** (exists). Prompt: "Extend docs/33 with yield-source risk map."
- **YIELD-002** — APY realism + evidence standard. out: `docs/37` · acc: L0–L6 + taxonomy + hard rules · deps: — · P1 · M · **DONE** (exists).
- **YIELD-003** — Yield-source taxonomy tests. out: `tests/test_yield_thesis_map.py` · acc: every source has required fields · deps: YIELD-001 · P2 · S.

## STRATEGY_DISCOVERY
- **DISCOVERY-001** — Discovery Engine doc. *How candidates are found + screened (dfb, feeds, tournament).* out: `docs/35` · acc: pipeline + screen criteria · deps: AUDIT-001 · P2 · M. Prompt: "Write docs/35 referencing dfb + defillama_feed + tournament."
- **DISCOVERY-002** — Candidate schema. out: `docs/schemas/candidate.schema.json` · acc: id/source/thesis/evidence fields · deps: DISCOVERY-001 · P2 · S.
- **DISCOVERY-003** — Screening rubric. out: `docs/35a_screening_rubric.md` · acc: hard-reject + human-review triggers · deps: DISCOVERY-001 · P2 · S.

## STRATEGY_CARDS
- **STRAT-001** — Strategy Card schema. out: `docs/schemas/strategy_card.schema.json` · acc: lifecycle-bound fields · deps: DOCS-002 · P1 · M. Prompt: "Write strategy_card schema bound to docs/07 lifecycle."
- **STRAT-002** — Strategy Card template. out: `docs/templates/strategy_card.md` · acc: all schema fields · deps: STRAT-001 · P1 · S.
- **STRAT-003** — Strategy Card system doc. out: `docs/11` · acc: schema+template+lifecycle binding · deps: STRAT-001 · P1 · M.
- **STRAT-004** — Card validator (non-runtime). out: `research/cards/validate.py`, tests · acc: rejects missing evidence level · deps: STRAT-001 · P2 · M.
- **STRAT-005** — First-strategy roster to card. out: `docs/44` · acc: ≥5 existing strategy_lab sleeves carded · deps: STRAT-002 · P2 · M. Prompt: "Card the aggressive_lab + rates_desk sleeves per template."

## PROTOCOL_CARDS
- **PROTO-001** — Protocol Card schema. out: `docs/schemas/protocol_card.schema.json` · acc: audit/upgradeability/TVL/governance · deps: — · P2 · M.
- **PROTO-002** — Protocol Card template + doc. out: `docs/12`, `docs/templates/protocol_card.md` · acc: DD checklist · deps: PROTO-001 · P2 · M.
- **PROTO-003** — Seed 5 protocol cards (Aave/Compound/Morpho/Pendle/Euler). out: `research/cards/protocols/*.md` · acc: no invented facts, gaps marked · deps: PROTO-002 · P2 · M.

## STABLECOIN_CARDS
- **STABLE-001** — Stablecoin Card schema (peg/backing/redemption/depeg). out: `docs/schemas/stablecoin_card.schema.json` · acc: fields present · deps: — · P2 · M.
- **STABLE-002** — Stablecoin Card template + doc. out: `docs/13`, template · acc: depeg-scenario section · deps: STABLE-001 · P2 · M.
- **STABLE-003** — Seed cards (USDC/USDT/DAI/USDe/USDS). out: `research/cards/stablecoins/*.md` · acc: backing/redemption sourced or UNKNOWN · deps: STABLE-002 · P2 · M.

## YIELD_LAB
- **YL-001** — Lifecycle state-machine schema. out: `docs/schemas/lifecycle_state.schema.json` · acc: matches docs/07 transitions · deps: DOCS-002 · P2 · M.
- **YL-002** — Paper-test plan template. out: `docs/templates/paper_test_plan.md` · acc: duration/thresholds/auto-fail · deps: DOCS-002 · P2 · S.
- **YL-003** — Small-capital test report template. out: `docs/templates/small_capital_report.md` · acc: slippage/queue/drawdown fields · deps: YL-002 · P2 · S.
- **YL-004** — Retirement + lessons template. out: `docs/templates/retirement.md` · acc: lessons-learned section · deps: DOCS-002 · P3 · S.
- **YL-005** — Map existing sleeves onto lifecycle states. out: `docs/07a_sleeve_status.md` · acc: each strategy_lab sleeve has a status · deps: STRAT-005 · P2 · M.

## STABLECOIN_YIELD_ENGINE
- **SYE-001** — Stablecoin yield engine deep-dive doc. out: `docs/38` · acc: source taxonomy + capacity · deps: YIELD-001 · P2 · L.
- **SYE-002** — Stablecoin candidate scan template. out: `docs/templates/stablecoin_scan.md` · acc: ≥10% mechanisms sectioned by risk · deps: SYE-001 · P2 · S.

## RISK_SCORING_V2
- **RISK-001** — Risk Scoring v2 framework doc. *Advisory 0–100 sub-scores, never a hard gate.* out: `docs/14` · acc: sub-scores + green/yellow/red + hard-reject/human-review/red-team triggers, ADVISORY stated · deps: AUDIT-001 · P1 · M. Prompt: "Write docs/14; advisory only, reuse dfb overlay score, never wire to execution."
- **RISK-002** — Risk score schema. out: `docs/schemas/risk_score.schema.json` · acc: sub-scores + verdict · deps: RISK-001 · P2 · S.
- **RISK-003** — Advisory-only test. out: `tests/test_risk_scoring_advisory.py` · acc: asserts no import into risk/execution path · deps: RISK-001 · P2 · M.

## BTC_MODULE
- **BTC-001** — BTC cycle framework doc (decision-support). out: `docs/15` · acc: cycle states + ladder, no auto-trade · deps: AUDIT-001 · P2 · M. Prompt: "Write docs/15 BTC cycle decision-support."
- **BTC-002** — BTC capital-cycle machine doc. out: `docs/36` · acc: accumulate/rotate/profit-ladder, decision-support only · deps: BTC-001 · P2 · M.
- **BTC-003** — BTC signal schema. out: `docs/schemas/btc_signal.schema.json` · acc: state+confidence+source · deps: BTC-001 · P3 · S.

## ETH_MODULE
- **ETH-001** — ETH yield framework doc (staking/restaking/LST/LRT, decision-support). out: `docs/16` · acc: yield map + slashing/depeg risks · deps: AUDIT-001 · P2 · M. Prompt: "Write docs/16 ETH yield decision-support."
- **ETH-002** — LST/LRT DD template. out: `docs/templates/lst_dd.md` · acc: peg/slashing/points-vs-yield · deps: ETH-001 · P3 · S.

## CAPITAL_TIERS
- **CAPITAL-001** — Capital Tiers strategy doc ($100k→$100M+). out: `docs/34` · acc: allowed/forbidden strategies + caps + custody/legal/IC/reporting thresholds per tier · deps: AUDIT-001 · P1 · L. Prompt: "Write docs/34 capital tiers, reference capital_sweep.py."
- **CAPITAL-002** — Tier caps schema. out: `docs/schemas/capital_tier.schema.json` · acc: caps per tier · deps: CAPITAL-001 · P2 · S.
- **CAPITAL-003** — Capacity/liquidity per tier appendix. out: `docs/34_capacity.md` · acc: slippage/queue notes · deps: CAPITAL-001 · P3 · M.

## AGENTS
- **AGENT-001** — Agent architecture doc. out: `docs/10` · acc: roles+FORBIDDEN+approval · deps: AUDIT-001 · P1 · M · **DONE**.
- **AGENT-002** — Investment-agent prompt templates. out: `docs/agent_prompts/investment/*.md` · acc: ≥5 agents (discovery/protocol/stablecoin/red-team/reporting) w/ guardrails · deps: AGENT-001 · P2 · M. Prompt: "Write per-agent prompts, L0/L1, FORBIDDEN block each."
- **AGENT-003** — Builder-agent prompt templates. out: `docs/agent_prompts/builder/*.md` · acc: ≥4 (docs/backlog/QA/security) · deps: AGENT-001 · P2 · M.
- **AGENT-004** — Agent output schemas. out: `docs/schemas/agent_output.schema.json` · acc: UNKNOWN/abstain fields · deps: AGENT-001 · P3 · S.

## PORTFOLIO
- **PORT-001** — Portfolio recommendation framework doc. out: `docs/17_portfolio.md` · acc: recommendation-only, caps respected · deps: RISK-001 · P2 · M.
- **PORT-002** — Allocation-proposal template. out: `docs/templates/allocation_proposal.md` · acc: cap-check section · deps: PORT-001 · P3 · S.

## REPORTING
- **REPORT-001** — Performance/attribution reporting templates. out: `docs/41`, `docs/templates/perf_report.md` · acc: evidence levels on every number · deps: YIELD-002 · P2 · M. Prompt: "Write docs/41 reporting templates, evidence level per metric."
- **REPORT-002** — IC workflow doc. out: `docs/39` · acc: memo → review → approval flow · deps: DOCS-002 · P2 · M.
- **REPORT-003** — IC memo template. out: `docs/templates/ic_memo.md` · acc: red-team + risk-score + approval fields · deps: REPORT-002 · P2 · S.

## DASHBOARD
- **DASH-001** — Research-layer dashboard expansion PLAN (no code). out: `docs/26` · acc: plan only, existing dashboard untouched, STOP-ask noted · deps: AUDIT-001 · P2 · M. Prompt: "Write docs/26 dashboard expansion PLAN; do not edit landing/."
- **DASH-002** — Card/evidence surface mockup doc. out: `docs/26a_surfaces.md` · acc: read-only, evidence-level badges · deps: DASH-001 · P3 · S.

## DATA
- **DATA-001** — Research-layer data architecture doc (stub). out: `docs/23` · acc: NEW dirs only, runtime data/*.json untouched · deps: AUDIT-001 · P2 · M. Prompt: "Write docs/23 stub; research data in new dirs, never runtime data/."
- **DATA-002** — Card/evidence DB schema doc (future). out: `docs/24` · acc: card/evidence/decision-log tables · deps: DATA-001 · P3 · M.
- **DATA-003** — Data-quality gating doc. out: `docs/40` · acc: stale→UNKNOWN rule, reference data_trust/ · deps: DATA-001 · P3 · M.

## TESTS
- **TEST-001** — Schema-validity test harness. out: `tests/test_schemas_valid.py` · acc: every docs/schemas/*.json parses · deps: STRAT-001 · P2 · S.
- **TEST-002** — Card-completeness tests. out: `tests/test_cards_complete.py` · acc: seeded cards match schema · deps: PROTO-003, STABLE-003 · P2 · M.
- **TEST-003** — Lifecycle-transition tests. out: `tests/test_lifecycle_transitions.py` · acc: illegal transitions rejected · deps: YL-001 · P2 · M.
- **TEST-004** — Evidence-level guard test. out: `tests/test_evidence_levels.py` · acc: no APY without evidence field · deps: YIELD-002 · P2 · S.

## SECURITY
- **SECURITY-001** — Research-layer security review doc + checklist. out: `docs/security_review.md` · acc: no-keys/no-exec-import/no-secrets checklist · deps: AUDIT-001 · P1 · M. Prompt: "Write security review checklist; confirm no execution import from research code."
- **SECURITY-002** — Secret-scan test. out: `tests/test_no_secrets_in_research.py` · acc: fails on PAT/token patterns · deps: SECURITY-001 · P2 · S.
- **SECURITY-003** — Execution-import guard test. out: `tests/test_no_execution_import.py` · acc: research modules never import spa_core.execution · deps: SECURITY-001 · P2 · M.

## COMPLIANCE
- **COMPLIANCE-001** — Compliance-surface map (references existing compliance/). out: `docs/45` · acc: disclosure/external-capital gaps catalogued · deps: AUDIT-001 · P2 · M. Prompt: "Write docs/45 mapping existing compliance/ module + gaps."
- **COMPLIANCE-002** — External-capital readiness doc (legal-review gated). out: `docs/42` · acc: legal-review gate stated · deps: COMPLIANCE-001 · P3 · M.
- **COMPLIANCE-003** — Dangerous-strategies catalogue. out: `docs/43` · acc: refused strategies + why · deps: RISK-001 · P3 · M.
- **COMPLIANCE-004** — Risk-disclosure template. out: `docs/templates/risk_disclosure.md` · acc: on every public surface · deps: COMPLIANCE-001 · P3 · S.

## CLAUDE_CODE_WORKFLOW
- **BUILDER-001** — Backlog + first-30-days plan. out: `docs/29`, `docs/30` · acc: ≥60 tasks + week-by-week plan · deps: AUDIT-001 · P1 · L · **DONE**.
- **CCW-001** — Task-plan template + one-task-per-iteration guide. out: `docs/templates/task_plan.md` · acc: CC prompt + acceptance fields · deps: DOCS-001 · P2 · S.
- **CCW-002** — Report template (completed-work). out: `docs/templates/work_report.md` · acc: invariant re-confirm block · deps: DOCS-001 · P2 · S.
- **CCW-003** — ADR-YL template. out: `docs/adr/ADR-YL-template.md` · acc: namespaced, no collision · deps: — · P3 · S.
- **CCW-004** — Session-start checklist. out: `docs/session_checklist.md` · acc: read 28/06/02, pick one task · deps: DOCS-001 · P3 · S.

---

**Task count:** 73 tasks across 23 groups. **DONE this run:** AUDIT-001, DOCS-001/002/003,
YIELD-001/002, AGENT-001, BUILDER-001 (8). **Cross-reference:** `docs/28` (workflow), `docs/07`
(lifecycle), `docs/30` (plan).
