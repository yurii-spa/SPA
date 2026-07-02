# ADR-YL-009 — Canonical documentation structure (single source per concept)

**Status:** ACCEPTED (2026-07-02, owner-directed docs-unification sprint)
**Owners:** owner + autonomous engine
**Supersedes/relates:** ADR-YL-008 (unified mandate — the canonical *mandate*), ADR-YL-003 (Yield Lab as a research layer)

## Context

The Yield Lab documentation had drifted into **two overlapping systems**:

- **System A — OPERATIONAL docs, referenced by the public site** (`landing/src`): the live "decisions
  are the product" surface. Site-referenced files (grep `landing/src` for `docs/`, all resolve):
  `docs/decision_index.md`, `docs/underwriting_rubric.md`, `docs/non_ethena_ladder.md`,
  `docs/STRUCTURAL_DESK.md`, `docs/RATES_DESK_VALIDATION.md`, `docs/DD_PACK.md`, `docs/FUNDABILITY.md`,
  `docs/LIQUIDATOR_DERISK.md`, `docs/PROOF_CHAIN_SPEC.md`, `docs/COMPETITIVE_POSITION.md`,
  `docs/VERIFIER_RELEASE.md`, `docs/DFB_METHODOLOGY.md`, `docs/SITE_DESIGN_SYSTEM(_V2).md`.
- **System B — FRAMEWORK scaffolding** (the `NN_*.md` numbered set, 00–45, + `ADR-YL-*`): the "why and
  how" — architecture, card systems, evidence standard, capital tiers, agent design.

The same concept (mandate, floor, evidence levels, product lines, verdicts) was defined — sometimes
divergently — in both. A concept with two definitions drifts. This ADR ends the sprawl.

## Decision (owner, not up for debate)

1. **One concept = one canonical definition = one file.** Every load-bearing concept has exactly one
   canonical home; every other mention **links** to it and must not restate its content.
2. **Operational docs keep their names and paths.** The public site references them; those references
   must not break. Content is not gutted; only *duplicated* definitions elsewhere are replaced by a link.
3. **Framework docs are the "why & how" layer.** They reference the operational canon and the ADRs;
   they do not duplicate operational content. Where a framework doc restated an operational definition,
   it now carries a `> **Canonical:** <file>` pointer instead.
4. **The site references only files that exist in `main`.** No public page may link a `docs/*.md` that
   is absent on the merged branch. (Verified: all 14 current site refs resolve.)
5. **Conflicts are never resolved silently.** A genuine divergence of definitions goes to
   `docs/31_open_questions.md` as an `OQ-N` with both options; if `ADR-YL-008` obviously resolves it,
   it is applied and marked resolved.

## Canonical source per concept (the map)

| Concept | Canonical file | Notes |
|---|---|---|
| **Yield Lab mandate** (spread over the live floor; every bp risk-explained; unexplained → reject) | **`docs/adr/ADR-YL-008`** | The "10–15%" is a *search range*, judged as spread over the floor → mostly refused. Others LINK, never restate. (was C1 — resolved by ADR-YL-008) |
| **RWA floor** (~3.4%, live/dynamic, never hardcoded) | **`data/rwa_feed.py`** (runtime) surfaced in `docs/decision_index.md` + `docs/non_ethena_ladder.md` | No divergent hardcode exists. |
| **Evidence levels L0–L6** | **`docs/37_apy_realism_and_evidence_standard.md`** | Others use the tags; only 37 defines them. |
| **Underwriting method** (Q1→Q4 decision tree + reason-code taxonomy) | **`docs/underwriting_rubric.md`** (operational) | Distilled from real decisions; `docs/11 §3.4a` holds the card *fields*, `ADR-YL-008` the approve/reject *criteria*. |
| **Verdict taxonomy** (ADVANCE/WATCH/REFUSE/NO-EDGE/BASELINE) ↔ **lifecycle status** (idea→…→approved) | verdicts: `docs/underwriting_rubric.md`; lifecycle: `docs/07_yield_lab_architecture.md` | Mapping bridge added to `docs/07`. (was C2 — see OQ-11) |
| **Product lines** (Preserve/Core/Enhanced/Max/Experimental) | **`docs/17_portfolio_construction.md`** (spread-based, canonical) | The absolute-APY bands in 33/03/38/07 are **illustrative, pre-audit** — A's real decisions (e.g. Maple ~4.7% = Core) supersede them. (was C3 — see OQ-12) |
| **Capital tiers** ($100k→$100M+) | **`docs/34_capital_tiers_strategy.md`** | Operational per-pool capacity in `non_ethena_ladder.md` applies it. |
| **Live decisions** (per-candidate verdicts) | **`docs/decision_index.md`** (operational) | The audit surface; the site's "check our decisions." |
| **Fundable ladder / portfolio** | **`docs/non_ethena_ladder.md`** (operational) | The assembled honest book. |
| **Honest edge finding** (yield ⟂ fundability; $10M = trust/relationships off-code) | **`docs/STRUCTURAL_DESK.md`** (convergent thesis) + `non_ethena_ladder.md` (numbers, scope-stated) | Different books/scopes cross-referenced, not contradictory. |

## Consequences
- New docs declare their canonical concept or link to the owner of it; no concept gets a second definition.
- `docs/00_index.md` is the master index over BOTH systems (operational / framework / ADR) + this map.
- Reviewers verify (grep) that no concept has two diverging definitions and that every site `docs/`
  reference resolves, before any merge.

*Research-layer ADR; changes no runtime/RiskPolicy/dashboard/deploy. Docs-only.*
