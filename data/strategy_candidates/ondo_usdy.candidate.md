# Strategy Candidate — Ondo USDY (tokenized T-bill, floor-plus)

> Edge-hunt cycle (Yield Lab autonomous engine, ADR-YL-008). A Strategy **Candidate** record
> (pre-card) — evaluated through the spread-over-floor mandate. This is a rare **plausible-ADVANCE**
> case (spread appears risk-explainable), complementing the refusal examples (leverage_loop, etc.).
> Numbers sourced 2026-07-02 (WebSearch stablecoin-yield comparisons); exact live APY = **requires
> verification** at L2 before any paper test. Schema: `docs/schemas/candidate.schema.json`.

## Candidate
- **candidate_id:** `CAND-USDY-001`
- **source:** live-yield scan (DeFiLlama-ecosystem yield comparisons, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `rwa` (hold a tokenized short-term US-Treasury note; accrue the coupon)
- **assets:** `["USDY (Ondo)"]`
- **protocols:** `["Ondo Finance (issuer)"]`  <!-- needs an issuer/Protocol Card -->
- **chains:** `["Ethereum (+ others — verify)"]`

## Yield & apparent edge
- **apparent_yield:** `~5% APY` (T-bill-linked; observed via 2026 yield comparisons). [L1 — verify exact live rate]
- **suspected_yield_source:** short-dated US Treasury coupon (+ bank-deposit component), passed through by Ondo.
- **live RWA floor baseline:** `~3.4%` (TVL-weighted tokenized-T-bill basket, from `data/rwa_feed.py`).

## Spread over the floor (ADR-YL-008 — the decisive analysis)
- **spread_over_floor_bps:** `~160 bps` (5.0% − 3.4%).
- **spread_risk_explanation (attribute EVERY bps to a specific accepted, measurable risk):**
  - `single-issuer concentration` — USDY is ONE issuer (Ondo), vs the floor's TVL-weighted **diversified** basket (BUIDL/USYC/USDY/OUSG/USTB). Concentrating in one issuer captures more yield but accepts issuer/custody concentration. **Measurable** (issuer share = 100% vs basket weight). ~a chunk of the spread.
  - `custody / bank-deposit component` — USDY reserves include bank deposits (not pure on-chain T-bills); accepts banking-partner risk (an SVB-type tail). **Measurable** (reserve composition).
  - `duration / rate positioning` — if USDY runs slightly longer/less-laddered duration than the basket, it earns a small term premium and accepts more rate-MTM. **Measurable** (WAM).
  - `transfer restrictions / liquidity` — USDY has KYC + holding-period/transfer constraints → thinner secondary liquidity + slower exit than a free-floating stablecoin. Accepts exit-friction. **Measurable** (redemption terms + depth).
- **unexplained_spread_bps:** `~0 expected` — the ~160 bps plausibly maps entirely to the four accepted risks above (this is NOT a leveraged/incentive/tail-comp spread — it is a *diversification + concentration + liquidity* premium over the basket). **Pending exact bps decomposition + the Ondo issuer card.**
- **spread_fully_explained (provisional):** `LIKELY TRUE` — subject to (1) verifying the exact live APY, (2) an Ondo issuer/Protocol Card (reserve composition, custody, redemption terms, admin/freeze), (3) a bps decomposition. This is the mandate's *positive* path: a spread that is real risk-compensation for **accepted, bounded, non-tail** risks, not unpriced tail.

## Red-team (the mandatory questions — abbreviated)
- **how do we lose money?** issuer/custody failure, banking-partner failure, rate spike (MTM on longer WAM), redemption gating.
- **yield disappears?** rate cuts (the whole floor moves — not USDY-specific).
- **depeg/exploit?** USDY is redemption-backed by T-bills; primary risk is issuer/custody, not smart-contract depeg. **verify**.
- **liquidity freeze / exit at size?** the load-bearing one — USDY transfer restrictions + redemption windows; exit-at-size **requires verification**.
- **most-fragile assumption:** that Ondo's reserve custody + redemption hold under stress (single-issuer). Mitigated by capping issuer concentration.

## Verdict & next action
- **verdict:** **ADVANCE to research/candidate** (NOT refuse) — provisionally spread-explainable; a genuine floor-plus sleeve candidate. Contrast with `leverage_loop` (refused, unexplained tail spread): USDY's ~160 bps is a *bounded diversification/liquidity premium*, the kind the mandate is designed to APPROVE.
- **required_due_diligence:** `["verify exact live USDY APY (L2)", "Ondo issuer/Protocol Card (reserves/custody/redemption/freeze)", "exit-liquidity-at-size", "bps decomposition of the 160bps", "concentration cap vs the floor basket"]`
- **initial_product_line_fit:** `Preserve→Core` (a conservative floor-plus, not Enhanced/Max).
- **initial_capital_tier_fit:** `$100k–$10M+ (deep RWA market; issuer minimums/KYC gate small tiers)`.
- **next_action:** create the Ondo issuer Protocol Card + verify the live APY, then promote to a Strategy Card (status=research→paper_testing) if `spread_fully_explained` confirms.

## Honesty note
This is a *candidate*, not an approved strategy: `apparent_yield` is L1 (needs L2 verification), the issuer card doesn't exist yet, and `spread_fully_explained` is **provisional**. But it demonstrates the mandate's approve-path: a modest, fully-risk-explained spread over the floor is exactly what the Yield Lab hunts for — the fundable middle between "bank the floor" and "chase refused tail-comp."

*created_at: 2026-07-02 · source: WebSearch stablecoin-yield comparisons (eco.com/coinstancy/datawallet 2026) + docs/33 + ADR-YL-008. Exact APY + issuer facts require L2 verification.*
