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
- **verdict:** **WATCH (held — per-pool DD attempted 2026-07-02, did NOT clear to ADVANCE)** — `senior_tranche_bounded_by_junior_firstloss`.
- **DD ATTEMPT RESULT (2026-07-02):**
  - ✅ **Structure confirmed real:** DROP (senior) is served first + protected by **TIN (junior) first-loss**; TIN absorbs losses before DROP (classic waterfall). Centrifuge TVL ~$1.64B (DeFiLlama). Underlying is real (e.g. New Silver = US real-estate bridge loans across 39 states); Tinlake has a defined write-off schedule (grace/collection).
  - ⛔ **The BINDING number is not publicly verifiable:** the **junior (TIN) buffer DEPTH (% cushion)** — the single metric that decides whether DROP is actually protected — is **pool-specific + off-chain + not transparently sourceable** from public data. Same for the specific pool's default/writedown history, current DROP APY, and redemption terms. Per rubric meta #6 ("underwrite the BUFFER, not the label"), **without the buffer % there is no ADVANCE.**
  - ⚠️ **Legacy nuance:** DROP/TIN is the **pre-May-2023 Tinlake** structure (New Silver etc. are legacy pools; some Tinlake pools wound down). Centrifuge's active ~$1.64B is mostly the **newer V3** (institutional tokenized funds) — so "~8% DROP" is a legacy-pool figure, not necessarily current/available.
  - ⚠️ **Asset cyclicality:** real-estate bridge loans (fix-and-flip) are real but **property-cycle-dependent + illiquid on default** — a bounded-but-real tail.
- **why it STAYS WATCH (honest):** the structure is sound but the desk **cannot underwrite the one binding number (buffer depth) from public sources** — this needs issuer-level data access (off-code). NOT a structural refusal; a **transparency/opacity hold.** Consistent with Goldfinch's lesson (senior label ≠ bound if buffer thin).
- **re-open/advance conditions:** obtain issuer-level per-pool data — junior-buffer % vs the loss distribution, pool default history, current DROP rate, redemption terms — then re-evaluate. Public data is insufficient to ADVANCE.

## Honest note (the lesson across A + B)
"Senior private-credit tranche 8-12%" is NOT one thing. **Goldfinch proves the senior label is worth
nothing if the first-loss buffer is thin vs systemic default** (it wound down, $50M stranded).
**Centrifuge DROP shows a real bound exists** when the junior tranche is genuinely loss-absorbing and
the assets are real — but at the *low* end (~8%) and gated on per-pool off-chain DD. Net: real 8-12%
bounded credit exists at the ~8% senior end with pool-level underwriting; the 10-14% "senior" pools are
usually senior-in-name over thin buffers — underwrite the buffer, not the label.

*created_at: 2026-07-02 · sources: Goldfinch — The Defiant (GIP-87 wind-down June-2026, ~$50M defaults, 3yr stranded), Goldfinch docs (Senior Pool / Backer first-loss), rwa.xyz (TVL low tens of M). Centrifuge — Eco/DEXTools/docs (DROP senior ~8%, 5-12% pool-specific, DROP/TIN senior-junior first-loss, TVL >$500M). ADR-YL-008 + underwriting_rubric.md.*
