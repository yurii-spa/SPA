# 31 — Open Questions

Questions surfaced by the audit that need an owner decision or future verification. Not blockers for
scaffolding; each notes who resolves it and why it matters. Nothing here was invented — where a fact
is unknown it is marked *requires verification*.

## Strategic
- **OQ-1 — 10–15% target vs honest edge-at-scale. ✅ RESOLVED — see `docs/adr/ADR-YL-008`.** The
  owner rejected the either/or and set a **unified mandate**: systematically search for fundable
  10–15% strategies, **but every point of spread over the live RWA floor (≈3.4%, dynamic from
  `data/rwa_feed.py`, never hardcoded) must be explained by a specific accepted, measurable risk** —
  unexplained spread ⇒ **REJECT**, and rejection is a **positive result recorded in the refusal log**.
  The floor is the **official baseline**: Enhanced/Max strategies are judged as **spread over the
  floor**, not absolute APY. This is now the single source of truth for the Lab's approve/reject logic
  (propagated to docs/07, 11, 14 and the red_team + capital_allocation prompts).
- **OQ-2 — Yield Lab vs existing `strategy_lab/`.** The master prompt's "Yield Lab" substantially
  overlaps `spa_core/strategy_lab/` (aggressive_lab, rates_desk, rwa_backstop, …). Decision: treat
  the docs as the *formal spec* over the existing code (recommended), or build a parallel structure
  (not recommended — would duplicate). Docs assume the former.

## Structural
- **OQ-3 — ADR numbering.** Existing `docs/adr/` holds ADR-002…025. New ADRs use the **ADR-YL-###**
  namespace to avoid clobbering. Confirm this is acceptable, or map to the next free integer range.
- **OQ-4 — Risk Scoring v2 reuse.** Should Risk Scoring v2 reuse the existing dfb risk overlay /
  `risk_scoring_engine` (ADR_014) / analytics scores, or be a new advisory layer? Docs recommend
  reuse + a thin advisory scorecard, never wired to execution.
- **OQ-5 — Card storage.** Cards start as markdown + JSON in `data/*_cards/` (Phase A). When do they
  migrate to the future research DB (Phase B/C, `docs/24`)? Owner/roadmap decision.

## Data / verification
- **OQ-6 — Live APY/TVL.** All strategy/protocol/stablecoin APY and TVL values in the cards are
  **placeholders requiring live verification** via the existing DeFiLlama feed / adapters. No card
  ships a live number as fact until verified at evidence level ≥ L2.
- **OQ-7 — Data sources.** Which paid sources (Glassnode, Dune, Token Terminal, CryptoQuant,
  Coinglass) are actually available vs aspirational? *Requires verification* before the BTC/ETH cycle
  and discovery docs assume any of them; the frameworks are written source-agnostic until confirmed.

## Governance / compliance
- **OQ-8 — External capital.** No external capital is accepted without legal review (`docs/42`).
  Owner + counsel decision; out of scope for code.
- **OQ-9 — Autonomy ceiling.** Default is L0/L1. When (if ever) does L2 (assisted, unsigned-tx
  checklists) become appropriate? Requires the execution-support + multisig prerequisites first.

## Housekeeping
- **OQ-10 — Working-tree divergence.** Local `main` diverges from `origin/main` (the repo pushes via
  API directly to origin; local git drifts). This branch was cut from local `b71dde9e2`; a future
  session syncing to origin should `git fetch && reset --hard origin/main` on `main` first, never on
  this branch's committed docs. *Recovery note, not a blocker.*

## Documentation unification (ADR-YL-009, 2026-07-02)
- **OQ-11 — Verdict taxonomy vs lifecycle status (two vocabularies).** System A (operational) uses a
  5-verdict enum (**ADVANCE / WATCH / REFUSE / NO-EDGE / BASELINE**, `docs/underwriting_rubric.md`);
  System B (`docs/07`) uses lifecycle **statuses** (idea→research→rejected→paper_testing→…→approved).
  `ADR-YL-008` does NOT reconcile them. **Recommended (Option 1 — the canonical bridge):** keep both,
  add ONE mapping — ADVANCE→advance-toward-paper_testing · REFUSE→rejected · WATCH→research(held) ·
  NO-EDGE→research(hold-the-floor, not advanced) · BASELINE→the floor (not a candidate). Verdicts = the
  human decision surface (site); lifecycle status = the pipeline stage. Option 2: collapse to one
  vocabulary (larger rewrite, breaks the site's verdict labels). **→ owner: confirm Option 1.**
- **OQ-12 — Product-line bands: absolute-APY (System B) vs spread-based (System A / `docs/17`).**
  `docs/33` (+`03`/`38`/`07`/charter) define Preserve 4–7 / Core 7–10 / Enhanced 10–13 / Max 13–18 /
  Exp 18–25%. But the desk's REAL decisions call Maple ~4.7% "**Core**" (`decision_index.md`) — A relabels
  by risk-structure/spread, invalidating the absolute-APY bands. `ADR-YL-008` doesn't touch this.
  **Recommended (Option 1):** make `docs/17`'s SPREAD-BASED definition canonical; demote the numeric APY
  bands everywhere to "illustrative, pre-audit." Option 2: keep absolute-APY bands canonical + re-tier A's
  decisions (contradicts the honest 2026 finding: fundable non-Ethena ~4.3–4.75%). **→ owner: confirm
  Option 1.** *(Applied this session: `docs/07`'s broken "product-line ranges live in `docs/34`" pointer —
  they were never defined in 34; corrected to `docs/17`/`docs/33`.)*
