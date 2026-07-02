# Strategy Candidate — Aave V3 USDC lending → NO-EDGE / FLOOR-PARITY (hold the floor instead)

> Edge-hunt cycle 16 (autonomous engine, ADR-YL-008). Evaluated the **mainstream T1 lending anchor**
> (Aave V3 USDC) → a NEW verdict flavor: **NO-EDGE / FLOOR-PARITY.** The safest, deepest DeFi lending
> venue yields **≈ the RWA floor** (spread ~5 bps) and is trending **below** it — so it adds
> smart-contract risk for *no* spread. This is the anchor result of the whole thesis: plain blue-chip
> lending has been arbitraged down to the floor, so any real edge MUST come from accepted incremental
> risk (which the mandate then makes you price). Data sourced 2026-07-02 (DeFiLlama/Aavescan + WebSearch).
> Cross-ref: `data/protocol_cards/examples/aave_v3.protocol.md` (PC-AAVE, ~$12B, 5-of-9 guardian).

## Candidate
- **candidate_id:** `CAND-AAVE-001`
- **source:** live-yield scan (Aave V3 USDC, Ethereum, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `lending` (supply USDC to Aave V3 — vanilla overcollateralized retail lending)
- **assets:** `["USDC"]`
- **protocols:** `["Aave V3"]`
- **chains:** `["Ethereum"]`

## Yield & apparent edge (SOURCED)
- **apparent_yield:** `Aave V3 USDC supply ~3.45% APY` — **L2** (Ethereum, 2026-07-02; Aavescan/DeFiLlama). **Algo predicts it falls below ~2.76% within ~4 weeks** (utilization-driven). [verified 2026-07-02]
- **suspected_yield_source:** overcollateralized borrower interest (utilization-driven variable rate).
- **Aave V3 TVL:** `~$12.0B protocol-wide` (DeFiLlama, per PC-AAVE). Deepest stablecoin lending venue, longest track record. [L2]
- **live RWA floor baseline:** `~3.4%` (rwa_feed).

## Spread over the floor (ADR-YL-008)
- **spread_over_floor_bps:** `~5 bps` (3.45% − 3.4%) — **essentially ZERO, and trending NEGATIVE** (toward ~2.76% < floor).
- **spread_risk_explanation:** there is **no spread to explain** — the yield is at the floor. The ~5 bps does NOT compensate for Aave's real (if low) risks:
  - `smart-contract risk` — Aave V3 is heavily audited, but non-zero (a codebase, not a T-bill).
  - `utilization / rate risk` — the rate is variable and falling; no fixed carry.
  - `centralization` — USDC freeze + Aave Emergency Guardian (5-of-9) — accepted but real.
- **risk-adjusted read:** at floor-parity yield, plain Aave USDC is **risk-adjusted WORSE than the floor** — same ~3.4%, but you add smart-contract + variable-rate risk the tokenized-T-bill floor doesn't have.

## Red-team (abbreviated)
- **why isn't this an edge?** because the market already competed it away — the safest, deepest venue pays the floor. If Aave paid materially above the floor, capital would flow in until utilization/rate fell back (exactly what the ~2.76% forecast shows).
- **most-fragile assumption:** none needed — the honest finding is that there's nothing to underwrite; the yield is the floor.

## Verdict
- **verdict:** **NO-EDGE / FLOOR-PARITY (HOLD THE FLOOR INSTEAD)** — Aave V3 USDC supply ≈ the RWA floor (~5 bps, trending negative). Not a REFUSE (Aave is safe, blue-chip); not an ADVANCE (no spread over the floor, and risk-adjusted it's *behind* the floor). The correct action is to hold the tokenized-T-bill floor (rwa_sleeve) directly rather than take Aave smart-contract risk for the same yield.
- **reason_code:** `no_edge_floor_parity`
- **the anchor lesson (why this matters most):** this is the datapoint that JUSTIFIES the whole ADR-YL-008 framing. The safest mainstream DeFi lending = the floor. Therefore **every basis point of real edge must be bought with accepted, measured incremental risk** — a curated vault (Steakhouse, ~150bps for bounded curator/oracle risk → ADVANCE), an issuer (USDY, ~160bps for issuer/custody risk → ADVANCE), or credit (Maple, ~180bps → WATCH). Plain Aave offers none, so it earns none. Yield is priced.
- **re-open condition:** if Aave USDC supply moves materially above the floor (a real utilization spike), re-evaluate — but expect it to compress back.

## Honesty note
The most important result is often the boring one: the safest lending in DeFi pays the floor. That is
not a failure — it is the proof that the floor is the right baseline and that spread is *earned by
risk*, not conjured. A desk that reports "Aave = floor, no edge, hold the T-bill" is more trustworthy
than one that dresses 3.45% up as alpha.

*created_at: 2026-07-02 · sources: DeFiLlama/Aavescan Aave-V3-Ethereum-USDC (~3.45% supply, forecast <2.76% in 4wk); DeFiLlama aave-v3 TVL ~$12B; PC-AAVE protocol card; ADR-YL-008. Floor ~3.4% = rwa_feed.*
