# ADR-593 · Backfill: Conservative is the evidenced go-live book (UX-26, 2026-07-11)

- **Status:** Accepted (backfilled 2026-10-06, from commit message only — no ADR existed)
- **Date of decision:** 2026-07-11 22:30 CEST
- **Author/approved by:** owner
- **Executed by:** commit `6ca6cf282` ("UX-26 resolved (owner: Conservative is the evidenced book)")
- **Related:** ADR-OWN-2026-07-owner-decisions-batch.md (same-day taxonomy decision, 22:03, 27 min
  earlier — names the three tiers but does not say which carries the evidenced track);
  `docs/SITE_TAXONOMY_NUMBERS_DECISION.md` (the investigation that produced the owner question, "UX-26")

## Context

Same evening as the Conservative/Balanced/Aggressive taxonomy decision, the site carried a live
self-contradiction: `strategy_config.json` said the evidenced, paper-tracked flagship was
**Balanced** (by composition: the live go-live book holds T1+T2 — aave_v3 + pendle + susde + morpho,
~$100,379 equity), while `tier_bands.json` and `/packages` said the evidenced, LIVE book was
**Conservative** (by realized return: ~3.3-4.2% at the time, which reads as conservative-range).
Three signals said Conservative, two said Balanced. `docs/SITE_TAXONOMY_NUMBERS_DECISION.md` laid out
both readings and asked the owner to pick one, explicitly flagging it as a product-definition /
public-claim decision (owner subject — public numbers), not something the agent should infer.

## Decision

**The evidenced $100k go-live paper track (anchor 2026-06-22, `cycle_runner.py`) is publicly labelled
Conservative.** Composition (T1+T2 mix) does not override realized-return framing for the public tier
label. `strategy_config.json` was aligned same day: `conservative` → "Paper Tracked · evidenced",
`balanced` → "Research / Paper", `max-yield` → "Research · refused". The homepage Conservative card
became green "Paper-tracked · evidenced"; the Balanced card became amber "Research / paper · not in
go-live track".

## Consequences

- Every surface agreed, as of 2026-07-11 22:30, on exactly one meaning of "the evidenced book":
  Conservative. This ADR backfills the record so that meaning has a decision document, not only a
  commit message.
- This decision does **not** cover what number represents "Conservative's APY" day to day — that is a
  separate, still-open set of defects (three/four live numbers for the same book: `paper_apy_pct`
  compound, `apy_today_pct` single-day, `books_summary.annualized_apy_pct` linear,
  `tier1_packages.blended_net_apy_pct` backtest — see RM-TRUTH-01 A2 finding #5, A3 §2/§5 D1/D2/D5,
  and this report's §1 row 7 / §2 R3). Those are number-provenance defects, governed by
  `.claude/rules/site-numbers.md`, and are explicitly out of scope for this backfill.
- `scripts/tier_paper_rollup.py` and `tier_bands.json.alt_en/alt_ru` still encode the *pre-decision*
  "Core = the live go-live track" framing as dead text (no reader on the rollup file; no renderer for
  the alias fields). This ADR does not require their deletion — flagged to the owner-subject queue as
  RECONNECT-or-ARCHIVE (already named in `REVIEW_1.md` §3.2 item 8 and A2 §12); not actioned by a
  read-only audit.

## Acceptance

`strategy_config.json.conservative.status == "evidenced"` AND
`landing/src/pages/packages.astro` + home Conservative card both render "LIVE · evidenced" for the
Conservative tier, as they do today (verified live, `page_packages.html`/`page_home.html`,
2026-10-05).


