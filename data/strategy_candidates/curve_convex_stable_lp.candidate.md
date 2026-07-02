# Strategy Candidate — Curve/Convex stablecoin LP → REFUSE (emissions-dependent, unpriced spread)

> Edge-hunt cycle 19 (autonomous engine, ADR-YL-008). A NEW risk shape: **stablecoin LP + emissions**
> (IL + token-incentive dependence, distinct from lending/RWA/credit/carry/first-loss). Introduces a
> NEW refusal reason: **`emissions_dependent_unpriced`** — the spread that makes it look attractive is
> paid in **CRV/CVX token emissions** (speculative $ value), not organic risk-comp; strip emissions and
> the base fee yield is ~floor-parity + volume-dependent. Data sourced 2026-07-02 (WebSearch). Schema:
> `docs/schemas/candidate.schema.json`. (docs/43 dangerous-strategies: emissions-only / APY-in-illiquid-tokens.)

## Candidate
- **candidate_id:** `CAND-CURVE-001`
- **source:** live-yield scan (Curve stablecoin pool + Convex boost, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `lp / emissions-farm` (provide USDC/USDT liquidity to a Curve stable pool, stake LP on Convex for boosted CRV+CVX)
- **assets:** `["USDC", "USDT (Curve stable LP)"]`
- **protocols:** `["Curve", "Convex"]`
- **chains:** `["Ethereum"]`

## Yield & apparent edge (SOURCED)
- **apparent_yield:** `~4–10% total` — **L2** (2026): **base trading fees ~3–6% + CRV/CVX emissions ~1–4%.** Sample position cited: 6.02% APY = **$212 fees + $89 CRV (~30% of the yield is emissions).** [verified 2026-07-02]
- **suspected_yield_source:** (a) organic Curve **trading fees** (volume-dependent, low per-trade on stables) + (b) **CRV + CVX token emissions** via Convex boost (up to 2.5× with veCRV).
- **live RWA floor baseline:** `~3.4%` (rwa_feed).

## Spread over the floor (ADR-YL-008) — split organic vs emissions
- **headline spread_over_floor_bps:** `~60–660 bps` (4–10% − 3.4%) — but **this is the wrong number to underwrite.**
- **ORGANIC (fee) spread:** base fees ~3–6% → **~0–260 bps over floor, volume-dependent** (thin at the low end; not durable — it tracks trading volume).
- **EMISSIONS portion (~1–4% / ~30% of the sample yield):** paid in **CRV + CVX tokens** — **unpriced**: the $ value is speculative + can be dumped + emissions can be cut by governance. **This is NOT risk-comp; it is a token-distribution subsidy.**
- **spread_risk_explanation (why even the organic part isn't a clean edge):**
  - `emissions-dependence` — the attractive part of the APY is token emissions (unpriced, non-durable). **The decisive refusal reason.**
  - `impermanent loss` — <0.5% for USDC/USDT normally, but **real on a genuine depeg** (exactly when it hurts).
  - `smart-contract / hack history` — **Curve suffered a 2023 Vyper-reentrancy exploit** (post-hack recovery); Convex adds a **second protocol layer** (composability risk).
  - `volume risk` — the organic fee yield is volume-dependent; it can fall below the floor in quiet markets.

## Red-team (abbreviated)
- **strip the emissions — is there an edge?** Barely: base fees ~3–6% ≈ floor-to-slightly-above, volume-dependent, with IL + hack-history + Convex-composability tails. Not a durable, bounded spread.
- **most-fragile assumption:** that CRV/CVX emissions retain $ value AND trading volume stays high AND neither Curve nor Convex has another incident. Three fragile legs for a spread that's mostly subsidy.

## Verdict
- **verdict:** **REFUSE (emissions-dependent)** — the spread that makes this attractive is **CRV/CVX token emissions (unpriced, non-durable subsidy)**, not organic risk-compensation. Stripped of emissions, the organic fee yield is ~floor-parity + volume-dependent, carrying IL + Curve-2023-hack + Convex-composability tails. The mandate does not fund yield that is a token-distribution subsidy dressed as APY.
- **reason_code:** `emissions_dependent_unpriced_spread`
- **relation to other decisions:** distinct from Aave (floor-parity, no emissions) and sUSDe (funding-carry tail). This is the **"farm APY = emissions, not edge"** archetype. If one insists, it could be *research-only with emissions EXCLUDED* from the return — at which point it's ~floor-parity and there's no reason to take the LP/IL/composability risk.
- **re-open condition:** only if the **organic fee yield alone** (emissions excluded) durably clears the floor by a margin that pays for IL + composability — historically it does not for stable pairs.

## Honesty note
A 6–10% "stablecoin farm" headline is mostly **CRV/CVX emissions** — a subsidy, not an edge. The
mandate's discipline: value the yield you'd keep if the token rewards went to zero. Here that's
~floor-parity, so the honest answer is REFUSE. Emissions can be a reason to *look*, never a reason to
*fund*.

*created_at: 2026-07-02 · sources: WebSearch (Curve/Convex stable-LP 2026: base fees 3-6% + CRV/CVX emissions 1-4%, sample 6.02% = $212 fees + $89 CRV; IL <0.5% stable-pair but real on depeg; Convex veCRV boost up to 2.5x; Curve 2023 Vyper hack post-recovery) + ADR-YL-008 + docs/43.*
