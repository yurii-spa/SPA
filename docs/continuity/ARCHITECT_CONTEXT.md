# ARCHITECT_CONTEXT — stable architecture context for any fresh AI session

> **Kind:** CURATED, stable (changes rarely, only with an ADR). **Contract:** `arb-continuity/2`, ADR-610.
> **Read order:** this file → `CURRENT_STATE.md` (generated) → `docs/ROADMAP.md` → latest accepted epic
> report → pending Owner Gates → `ARCHITECT_DECISION_INDEX.md` → `OWNER_INTENT_LEDGER.md` → verify
> identities (`BOOTSTRAP.md`). Every claim below cites the canonical file that decides it. If this file
> and a cited canonical file disagree, the canonical file wins and this file is stale — say so.

## 1. Project identity

**Earn DeFi Studio OS** is a one-owner autonomous product studio running on a Mac Mini (launchd fleet,
stdlib Python), controlled from iPhone. Its first product is **SPA — Smart Passive Aggregator**, a DeFi
yield optimizer in **paper trading**: a virtual $100,000 USDC book, a daily cycle reading live APY/TVL
from whitelisted protocols, a deterministic RiskPolicy gate and a virtual rebalance (`CLAUDE.md`
«Что это»). Public site: earn-defi.com. Repository of record: `yurii-spa/SPA`, branch `main` (git files are
the source of truth — `CLAUDE.md` invariant #13).

## 2. Three worlds (ADR-592 §6, ADR-580)

| World | What lives there | Owns financial state? |
|---|---|---|
| **CAPITAL** | investment engines: DeFi books (Conservative / Balanced / Aggressive), Trading Research Engine (Trading Lab, BTC), Research Factory, Oracle, Sherlock, shadow execution | yes — each engine owns its own (ADR-525 §1) |
| **STUDIO OS** | control plane: tasks/cards, permissions, memory, releases, recovery, fleet, Mission Control, Telegram | **never** (ADR-525 §1) |
| **EARN DEFI PRODUCT** | the public product: site, publication, public truth of numbers | no; it publishes evidenced numbers only |

## 3. Roles and authority

| Role | Responsibility | Authority limit | Source |
|---|---|---|---|
| **Owner** (Yurii, @yurii) | intent, approvals, the three reserved subjects | sole authority over real money, public numbers/naming/legal, irreversible actions | ADR-285, `CLAUDE.md` |
| **ChatGPT — Architecture Review Board (ARB)** | architecture, conflict/supersession review, acceptance, precise assignments for Claude | decides architecture only after a FRESH bootstrap; never implements, never approves owner subjects | ARB-CONTINUITY-01 directive (2026-10-07), ADR-610 |
| **Claude Code** | implementation worker: code, tests, evidence, guarded delivery (`push_to_github.py --expected-base`) | a session's claim is not deployment proof; no owner subject without the owner | `CLAUDE.md`, ADR-285 |
| **Oracle** (`chief_investment_officer`; «Штирлиц» until 2026-10-04) | advisory / paper cross-sleeve recommendation + immutable decision ledger | **cannot move capital**, executes nothing | ADR-554, `architecture/roles.json` |
| **Sherlock** (`head_of_research`) | deterministic research evidence + paper admission | **no capital authority** | ADR-564, `architecture/roles.json` |

AI sessions (ChatGPT, Claude, any model) are **workers, not company memory**. Durable decisions live in
git: `docs/decisions/` (canonical ADR registry), `docs/ROADMAP.md` (single roadmap), `nimbalyst-local/tracker/`
(cards and the one owner queue), `.claude/rules/` and `CLAUDE.md` (rules). Chat is never canonical
(ADR-527 §2).

## 4. Permission model (ADR-285 boundary by subject)

- **GREEN — decide and do, record in the journal:** research, documents, sandbox prototypes, tests,
  read-only audits, reversible engineering inside the current mandate, guarded delivery of anything that
  touches none of the three subjects.
- **YELLOW — prepare a candidate, do not promote by implication:** anything a later reviewer must accept
  (architecture changes, publication candidates, deletions of unknown-purpose components).
- **RED — owner only:** (1) real money movement — execution, keys, payments, going live; (2) public yield
  numbers, tier naming, legal wording (`scripts/check_owner_gate.py` enforces this subject on the site);
  (3) irreversible actions — deleting data, external publication, external commitments.
- **REAL CAPITAL = $0** and **NO LIVE EXECUTION** unless the owner explicitly changes it (ADR-556:
  automated live execution PROHIBITED; RiskPolicy v1.0 is the only hard gate — `CLAUDE.md` inv. #1).
  The baseline is a policy, not a measured balance: the measured value is in `CURRENT_STATE.md`.
- LLMs are forbidden in risk / execution / monitoring / kill components (`CLAUDE.md` inv. #3).

## 5. Canonical source hierarchy (highest first, scoped)

1. Explicit current owner decisions and the safety rules (`CLAUDE.md`, `.claude/rules/`, ADR-285). Silence is not approval.
2. `docs/decisions/ADR-*.md` and their amendments decide architecture. `docs/adr/` is a historical
   second registry with number collisions — cite full paths. Bridge `docs/adr` (ADR-B*) governs Bridge only.
3. `docs/ROADMAP.md` is the single roadmap; every other `*ROADMAP*.md` is SUPERSEDED (ADR-527).
   `nimbalyst-local/tracker/` is the one task and owner-decision store (ADR-580 C5).
4. Engine-owned runtime evidence decides runtime state (`data/` on the production Mac, read through the
   Company Truth read model in Mission Control — ADR-592; no agent or gate reads that model).
5. `architecture/memory_truth.json` gives sourced semantic facts; they can lag the canon — compare.
6. **Read models, never authority:** `CURRENT_STATE.md`, `ARCHITECT_DECISION_INDEX.md`, `docs/STATE.md`,
   `docs/SYSTEM_BRIEFING.md`, the memory index, Mission Control / Director OS, Telegram surfaces. A read
   model that disagrees with its sources is stale or wrong, never right.

## 6. Principles that survive implementation changes

- **Preserve Intent ≠ Preserve Implementation.** An owner intent survives; its implementation may be
  replaced after an audit with explicit lineage (`OWNER_INTENT_LEDGER.md`).
- **UNKNOWN_PURPOSE ≠ obsolete.** Unknown purpose is a reason to investigate, never permission to delete
  (`.claude/rules/site-copy.md` «Память ДО правки», ADR-537).
- **Absence of observation is its own value** (`CLAUDE.md` inv. #17): measured · measured-and-zero · not
  measured must stay distinguishable. UNKNOWN is a valid answer; guessing is a failure.
- **Fail-CLOSED / refusal-first** (inv. #2): on missing data the system refuses or holds.
- **Deterministic control plane:** gates, readiness, kill-switch and this continuity generator are
  deterministic stdlib code; no model decides state.
- **Typed numbers** (ADR-580 C2): TARGET_RETURN · OBSERVED_RETURN · REALIZED_PAPER_RETURN ·
  MODELLED_RETURN · BACKTEST_RETURN are never collapsed into a generic «APY»; a rate is reportable only
  after 30 evidenced periods.
- **Forward-paper time is irreplaceable:** a bar that closed cannot be observed again; forward clocks are
  immutable and paper histories are never reset (ADR-580 C7, ADR-590, `docs/ROADMAP.md` «Standing constraints»).

## 7. Delivery semantics (scope every claim)

| Level | Meaning |
|---|---|
| **BUILT** | the artifact exists and its focused checks pass |
| **CONNECTED_E2E** | a real upstream event → canonical sources → producer → consumer path was observed |
| **OWNER_USABLE** | the owner can reach and use it in the intended surface, independently verified |
| **PROVEN_RESULT** | the defined outcome was observed in production; green unit tests alone are not this |

Delivery = code **running in production**, not a push (`.claude/rules/deployment.md`).

## 8. Owner Gates

An Owner Gate is an action only the owner can take (the three subjects above, or something an agent
physically cannot do). Gates are recorded in the owner queue (`nimbalyst-local/tracker/`, ADR-580 C5) or,
for epic-level gates, in the epic's `docs/ROADMAP.md` item («Owner gates: …»). A gate never blocks the
rest of an epic: skip only that action and continue (ARB-CONTINUITY-01 directive §0).
