# Strategy Candidate — Tokenized private-credit SENIOR tranches → SPLIT (Goldfinch REFUSE/dead · Centrifuge WATCH)

> Edge-hunt cycle 22 (autonomous engine, 8-12% bounded hunt). Evaluated the "senior private-credit
> tranche" archetype — the cleanest-sounding source of 8-12%. Result is a sharp, honest SPLIT: one
> (Goldfinch) is a **realized-loss cautionary tale** (protocol winding down); the other (Centrifuge
> DROP) is a **bounded WATCH** at the low end of the band. Proves that "senior tranche" is a structure,
> not a guarantee — the underwriting is the collateral quality, not the label. Data sourced 2026-07-02
> (WebSearch/rwa.xyz/The Defiant). Rubric: `docs/underwriting_rubric.md`. Cross-ref: Maple (CAND-SYRUP-001, WATCH).

## Candidate
- **candidate_id:** `CAND-PRIVCRED-001`
- **source:** live private-credit scan (Goldfinch + Centrifuge, 2026-07-02)
- **strategy_type:** `private-credit / tranched` (supply to a SENIOR tranche of a tokenized credit pool)
- **live RWA floor baseline:** `~3.4%` (rwa_feed).

---

## Sub-case A — Goldfinch Senior Pool → REFUSE (realized default, protocol winding down)
- **apparent_yield:** `Senior Pool ~10-14% APY` (historically) — **L2**. EM uncollateralized private credit; Backers provide first-loss, Senior Pool diversifies.
- **spread_over_floor_bps:** `~660-1060 bps` — large, because the risk was large.
- **THE decisive fact (sourced 2026-07-02):** **Goldfinch is FORMALLY WINDING DOWN** — GIP-87 (Warbler Labs, June 12 2026) moves it to "maintenance mode" after it **could not recover from widespread borrower defaults that stranded depositors for ~3 years.** ~**$50M defaults** on ~$100M originated (The Defiant); Tugende-Kenya default (2023) hit Backers then the Senior Pool. TVL collapsed to low tens of millions (rwa.xyz Q1-2026).
- **verdict:** **REFUSE** — `uncollateralized_credit_realized_default`. The 10-14% was compensation for **uncollateralized EM corporate-credit default risk, and the tail FIRED at scale.** The "senior" position did NOT bound it — first-loss Backer capital was insufficient against *widespread* defaults. A realized-loss twin to Resolv (different mechanism, same lesson: the headline yield was the tail).
- **re-open:** none — the protocol is winding down.

## Sub-case B — Centrifuge DROP (senior tranche) → WATCH (bounded, low end of band)
- **apparent_yield:** `DROP (senior) ~8% APY` (pool-specific 5-12%) — **L2**. From real RWA cash flows (invoices, credit repayments, T-bills).
- **spread_over_floor_bps:** `~460 bps` at ~8% (senior). Low end of the 8-12% band — *because* it is senior.
- **structure (the bound):** **DROP (senior) absorbs losses LAST; TIN (junior) is the first-loss buffer below it.** Senior yield is bounded by the junior tranche's first-loss depth + the underlying RWA cash flows. TVL >$500M (2026). This is a *real* tranched-credit bound (unlike Goldfinch, where first-loss proved thin vs systemic default).
- **residual risks (measurable but real):** off-chain **opacity** (RWA cash flows are off-chain — verify pool-by-pool), **pool-specific default** (some Centrifuge pools riskier than others — not a single number), **lockup / illiquidity** (redemption depends on pool cash flows), **junior-buffer adequacy** (how thick is TIN vs the loss distribution?).
- **verdict:** **WATCH** — `senior_tranche_bounded_by_junior_firstloss`. A genuinely bounded senior-credit yield at ~8% (low end), fundable IF: per-pool DD (which assets, junior-buffer %, servicer), off-chain-cashflow verification, lockup/redemption terms, strict per-pool cap. Not clean-ADVANCE (off-chain opacity + Goldfinch precedent demand pool-level DD).
- **re-open/advance conditions:** pick a specific DROP pool → verify junior-buffer depth + underlying asset quality + servicer track record + redemption terms → then paper.

## Honest note (the lesson across A + B)
"Senior private-credit tranche 8-12%" is NOT one thing. **Goldfinch proves the senior label is worth
nothing if the first-loss buffer is thin vs systemic default** (it wound down, $50M stranded).
**Centrifuge DROP shows a real bound exists** when the junior tranche is genuinely loss-absorbing and
the assets are real — but at the *low* end (~8%) and gated on per-pool off-chain DD. Net: real 8-12%
bounded credit exists at the ~8% senior end with pool-level underwriting; the 10-14% "senior" pools are
usually senior-in-name over thin buffers — underwrite the buffer, not the label.

*created_at: 2026-07-02 · sources: Goldfinch — The Defiant (GIP-87 wind-down June-2026, ~$50M defaults, 3yr stranded), Goldfinch docs (Senior Pool / Backer first-loss), rwa.xyz (TVL low tens of M). Centrifuge — Eco/DEXTools/docs (DROP senior ~8%, 5-12% pool-specific, DROP/TIN senior-junior first-loss, TVL >$500M). ADR-YL-008 + underwriting_rubric.md.*
