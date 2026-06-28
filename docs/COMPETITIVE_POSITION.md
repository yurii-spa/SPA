# SPA — Competitive Position

_An honest, sourced positioning doc. The competitive analysis (`research/01_competitor_analysis.md`)
identified a structural white space; this document encodes it as **four differentiators, each backed
by a SHIPPED, independently verifiable surface** — not aspiration. Where a claim is forward-looking it
is **labeled FORWARD-LOOKING**. Honest framing: the track is THIN (accruing), capacity is bounded, the
capital is paper ($0 real). Nothing here claims $10M is reachable today._

> **Naming competitors publicly is borderline.** This doc keeps every comparison factual and sourced
> to the linked analysis. A public site version exists at `/competitive-position` but is **gated for
> owner sign-off** before any competitor is named on the public marketing surface — see the
> OWNER-DECISION flag at the end.

---

## 1. The white space (sourced)

The competitor analysis (`research/01_competitor_analysis.md`, §3.2) found four structural gaps that
**no** surveyed platform fills — surveyed set: Enzyme, dHEDGE/Chamber, Yearn v3, Idle/Pareto,
Sommelier, VaultCraft; with Morpho+Gauntlet / Steakhouse as the institutional-curated reference. The
gaps (verbatim intent from the report):

1. **No verifiable paper track record before go-live** (report Gap 1) — none documented pre-launch
   performance; all launched with real money or did not publish a pre-launch record.
2. **Autonomy without LLM-dependence in risk/execution** (report Gap 2) — a fully autonomous,
   deterministic RiskPolicy with no LLM in critical components is empty market space.
3. **An investor portal for the family office** (report Gap 3) — per-participant P&L attribution,
   onboarding, legal base.
4. **Positioning between retail aggregators and institutional curated vaults** (report Gap 4) — the
   $100K–$5M family-office band sits between retail auto-compounders (Yearn, Beefy, Idle) and the
   institutional $10M+ curated vaults (Morpho + Gauntlet).

The report's recommendation (§4): *position the "verifiable paper track record" as the primary trust
signal — it is unique and measurable.*

---

## 2. The four differentiators → each backed by a SHIPPED surface

The discipline of this doc: a differentiator only counts if a skeptical reviewer can **check it today**
on a shipped surface. The mapping:

| # | differentiator | the white-space gap it fills | SHIPPED verifiable surface | how a reviewer checks it |
|---|---|---|---|---|
| **D-1** | **Public refusal log** — "we publish what we refuse, not just what we trade" | extends Gap 1 (verifiable record) to a record of DECLINES, which **no** surveyed platform publishes | `/refusals` · `/api/rates-desk/refusals` · `data/rates_desk/decision_log.jsonl` (hash-linked) | run `python3 scripts/verify_spa.py data/rates_desk/` — every refusal's `entry_hash` re-derives; a worked refused-vs-approved example with real `proof_hash`es is in `docs/DD_PACK.md` §2 |
| **D-2** | **Liquidation-NAV by size** — what you actually realize on exit at a given ticket, not marketing NAV | not addressed by ANY surveyed platform (they quote headline APY / NAV) | `/exit-nav` · `/api/rates-desk/exit-nav` · `data/rates_desk/exit_nav.json` (per-row `proof_hash`) | `verify_spa.py` recomputes every exit-NAV row from its published inputs+outputs+prev_hash; a forged number diverges |
| **D-3** | **Anti-AI risk discipline** — deterministic RiskPolicy, **LLM-FORBIDDEN** in risk / execution / kill | directly fills Gap 2 (autonomy without LLM-dependence) | `spa_core/risk/policy.py` (deterministic, versioned `v1.0`) · `# LLM_FORBIDDEN` markers · `lint_llm_forbidden` test gate | the risk path imports no LLM; the lint test fails the build if an LLM call appears in a forbidden module; decisions are byte-reproducible |
| **D-4** | **Personal-capital, capacity-honest desk** — a transparent $100K–$5M risk desk that states its own ceiling | fills Gap 4 (the family-office band) + Gap 1 (verifiable track) | `/track-record` (hash-anchored, THIN-labeled) · the capacity model `data/rates_desk/portfolio_capacity.json` · `docs/DD_PACK.md` §4 | the capacity model publishes the per-book ceiling and the honest gap to $10M; the track publishes per-bar source labels (only cycle-logged days count) |

**The through-line:** the differentiator is not a higher number — it is **honest measurement made
checkable**. Three of the four (D-1, D-2, D-4) publish what competitors hide (declines, real exit
slippage, the honest ceiling); D-3 removes the human/LLM discretion that the report flags as the
family-office concern.

---

## 3. Per-differentiator detail

### D-1 — Public refusal log (SHIPPED)
Everyone publishes wins. The surveyed platforms publish APY and TVL; none publish the trades they
**declined** and why. SPA's refusal-first gate hashes every verdict — entry AND refusal — into an
append-only, tamper-evident chain. A toxic LRT carry book is refused on *structural* grounds (the fair
value after haircuts is negative) **before** economics: a great quoted rate cannot buy its way past the
veto. Surface: `/refusals`. Proof: `docs/DD_PACK.md` §2 walks a real `ezeth` REFUSAL and the adjacent
`susde` ENTRY, both with real `proof_hash`es, both reproducible by `verify_spa.py`.

### D-2 — Liquidation-NAV by size (SHIPPED)
A position's marketing NAV is not what you realize when you exit $X into finite depth. SPA publishes a
per-ticket exit schedule (`/exit-nav`): the haircut and net proceeds at each size, with a per-row
`proof_hash`. No surveyed platform exposes this; it is the honest answer to "what is this actually
worth on the way out." Reviewer check: `verify_spa.py` recomputes every row from its published
inputs+outputs.

### D-3 — Anti-AI risk discipline (SHIPPED)
The report (Gap 2) flags that family offices value predictability and the absence of a human/LLM factor
in risk management. SPA's `RiskPolicy` is deterministic and **versioned `v1.0`**; LLMs are **forbidden**
in risk, execution, monitoring and kill components (enforced by `# LLM_FORBIDDEN` markers + a lint test
gate). Same inputs -> same decision, byte-reproducible. This is a *removal* of discretion, and it is
checkable in source.

### D-4 — Personal-capital, capacity-honest desk (SHIPPED)
SPA targets the $100K–$5M band the report calls the SPA opportunity zone (report §3.3) — and, unusually,
**publishes its own capacity ceiling**. The capacity model (`data/rates_desk/portfolio_capacity.json`,
surfaced in `docs/DD_PACK.md` §4) states the fundable-book count, the depth-bounded deployable AUM, the
carry above the RWA floor, and the honest gap to the $10M target. The track (`/track-record`) counts
only days backed by a real daily-cycle log; the earlier backfill was reset out. The honest small number
IS the credibility.

---

## 4. Honest constraints (the same ones the funder sees)

- **THIN track.** The verifiable track is accruing to 30 evidenced days; risk-adjusted ratios land near
  day 30 and read `THIN` until then — never fabricated. (This is the differentiator D-1/D-4 *being
  honest about itself*.)
- **Bounded capacity.** The standalone rates-desk carry above the floor is real but capacity-bound;
  combined across sleeves, after a correlation haircut, the honest figure is lower still. **$10M = scale
  + decorrelation + AUM, NOT reachable today.**
- **Paper capital.** $0 real capital. Research / paper track on a virtual $100k book.

---

## 5. Forward-looking items (LABELED — not yet shipped)

These are from the report's recommendations and are **NOT** claimed as present differentiators:

- **FORWARD-LOOKING:** investor portal with per-participant P&L attribution + legal onboarding (report
  Gap 3). A cabinet exists but is owner-gated and not part of this public DD surface.
- **FORWARD-LOOKING:** 2+ independent code audits + Immunefi bug bounty before go-live (report §4 rec).
- **FORWARD-LOOKING:** the off-code scale legs (custody/MPC, legal, real capital + relationships) that
  gate $10M (see `docs/DD_PACK.md` §6).

---

## 6. OWNER-DECISION — public competitor naming

The competitive analysis names specific competitors (Enzyme, dHEDGE, Yearn, Idle, Sommelier, VaultCraft,
Morpho/Gauntlet). Naming them on the **public marketing site** (`/competitive-position`) is a
brand/legal judgment call.

- **This doc** (`docs/COMPETITIVE_POSITION.md`) keeps comparisons factual and sourced to the analysis —
  appropriate for a DD data-room shared with an LP under review.
- **The public site section** is written to stand WITHOUT naming competitors (it describes the white
  space and the shipped surfaces). **Owner must sign off** before any competitor name appears on the
  public marketing surface.

---

_Sources: `research/01_competitor_analysis.md` (the competitive analysis) · `docs/DD_PACK.md` (the
worked proofs + capacity) · the shipped surfaces `/refusals`, `/exit-nav`, `/track-record`,
`/proof-of-reserves` · `scripts/verify_spa.py` + `docs/PROOF_CHAIN_SPEC.md` (the verifier). Honest,
advisory, paper — not investment advice._
