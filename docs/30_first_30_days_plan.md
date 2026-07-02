# 30 — First 30-Days Plan

> Week-by-week execution plan for standing up the Yield Lab **documentation + schema + prompt**
> foundation. Research-layer only — no runtime / RiskPolicy / dashboard / deploy changes (STOP-and-ask
> if any task drifts there, `docs/28` §13). Tasks reference `docs/29` ids. Maps to the Priority 1/2/3
> doc set from the charter. **Items already delivered by the scaffolding run are marked ✅.**

## Week 1 — Foundation & guardrails (Priority 1)

**Goal:** any future session can orient safely and pick one task. Lock the invariants and the
lifecycle vocabulary before any card/agent work.

- Deliverables / files:
  - ✅ `docs/02` audit (AUDIT-001), ✅ `docs/06` invariants, ✅ `docs/28` CC master instructions (DOCS-001).
  - ✅ `docs/07` Yield Lab architecture + lifecycle (DOCS-002).
  - ✅ `docs/33` yield thesis map + ✅ `docs/37` APY evidence standard (YIELD-001/002).
  - `docs/03` glossary (DOCS-004); `docs/session_checklist.md` (CCW-004).
- Acceptance: invariants stated with enforcement points; lifecycle table complete with
  approval/evidence per status; a session can pick exactly one backlog task from `docs/29`.
- Risk: over-scoping into code. Mitigation: docs-only; STOP-ask gate enforced.

## Week 2 — Cards, risk scoring, agents (Priority 1 → 2)

**Goal:** the comparison substrate — Strategy/Protocol/Stablecoin Cards, advisory Risk Scoring v2,
and the agent architecture (prompts + guardrails, no autonomy).

- Deliverables / files:
  - ✅ `docs/10` agent architecture (AGENT-001).
  - `docs/11` + `docs/schemas/strategy_card.schema.json` + template (STRAT-001/002/003).
  - `docs/12`/`docs/13` protocol + stablecoin card systems (PROTO-001/002, STABLE-001/002).
  - `docs/14` Risk Scoring v2 — **advisory only, never a hard gate** (RISK-001).
  - `docs/agent_prompts/` investment + builder templates (AGENT-002/003).
- Acceptance: card schemas validate; each card binds to a lifecycle status; Risk Scoring v2 doc
  states advisory-only + trigger set; every agent prompt has a FORBIDDEN block and L0/L1 autonomy.
- Risk: duplicating the existing research layer (`strategy_lab`, `redteam`, `dfb`). Mitigation:
  cards/scoring cross-reference existing modules, do not re-implement them.

## Week 3 — Capital tiers, BTC/ETH, discovery, security (Priority 2)

**Goal:** the strategy universe by scale, the two decision-support asset modules, the discovery
pipeline, and the security review that gates everything.

- Deliverables / files:
  - `docs/34` capital tiers ($100k→$100M+) + caps schema (CAPITAL-001/002).
  - `docs/15`/`docs/36` BTC cycle + capital-cycle machine; `docs/16` ETH yield (BTC-001/002, ETH-001) — **decision-support only**.
  - `docs/35` discovery engine + candidate schema (DISCOVERY-001/002).
  - `docs/38` stablecoin yield engine (SYE-001).
  - `docs/security_review.md` + guard tests (SECURITY-001/002/003).
- Acceptance: tier doc lists allowed/forbidden strategies + custody/legal/IC/reporting thresholds;
  BTC/ETH docs contain no auto-trade path; security tests fail on secrets or execution import.
- Risk: BTC/ETH framing drifting toward signals/execution. Mitigation: decision-support wording +
  no-autotrade acceptance check.

## Week 4 — Reporting, IC, tests, compliance, seeding (Priority 2 → 3)

**Goal:** close the loop — reporting/IC memos, a test harness for the new schemas, compliance map,
and first seeded cards + strategy roster so the lifecycle has real content.

- Deliverables / files:
  - `docs/41` reporting templates + `docs/39` IC workflow + IC memo template (REPORT-001/002/003).
  - `docs/23` data architecture stub + `docs/26` dashboard expansion PLAN (DATA-001, DASH-001).
  - `docs/45` compliance map + `docs/43` dangerous strategies (COMPLIANCE-001/003).
  - `docs/44` first strategy roster carded + seeded protocol/stablecoin cards (STRAT-005, PROTO-003, STABLE-003).
  - Schema/lifecycle/evidence tests (TEST-001..004); ADR-YL template (CCW-003).
- Acceptance: seeded cards validate against schemas with no invented facts (gaps = UNKNOWN); tests
  green and network-free; dashboard doc is plan-only (no `landing/` edits).
- Risk: touching runtime `data/*.json` or the dashboard while seeding. Mitigation: research data in
  NEW dirs only; dashboard remains plan-only; STOP-ask before any runtime/deploy edit.

---

**End-state:** Priority-1 doc set complete (weeks 1–2), Priority-2 substantially delivered (weeks
3–4), Priority-3 stubbed for MVP 2–3. RiskPolicy `v1.0`, the kill-switch, the public dashboard, and
deployment remain untouched throughout. **Cross-reference:** `docs/29` (backlog), `docs/28` (workflow),
`docs/00_index.md` (full doc map).
