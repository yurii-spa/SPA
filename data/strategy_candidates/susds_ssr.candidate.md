# Strategy Candidate — Sky Savings Rate (sUSDS) → REFUSED (governance-safety precondition)

> Edge-hunt cycle 5 (autonomous engine, ADR-YL-008). Evaluated the Sky Savings Rate via the
> spread-over-floor mandate → **REFUSED / HELD-AT-0%** on a **governance-safety precondition** (a
> NOVEL refusal reason vs the tail-comp refusals like leverage_loop). A positive result: the desk's
> own FORBIDDEN #8 rule + the mandate agree. Data sourced 2026-07-02 (WebSearch + DeFiLlama). Schema:
> `docs/schemas/candidate.schema.json`. Cross-ref: `data/stablecoin_cards/examples/usds.stablecoin.md`.

## Candidate
- **candidate_id:** `CAND-SUSDS-001`
- **source:** live-yield scan (Sky Savings Rate, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `rwa/savings` (deposit USDS → sUSDS, accrue the Sky Savings Rate)
- **assets:** `["USDS / sUSDS (Sky)"]`
- **protocols:** `["Sky (ex-MakerDAO)"]`
- **chains:** `["Ethereum (+ verify)"]`

## Yield & apparent edge (SOURCED)
- **apparent_yield:** `SSR ~3.60–3.75% APY` — **L2** (Sky governance-set Q2-2026 3.75%; DeFiLlama sUSDS pool ~3.60%). Peaked >8% in 2024; now tracks the rate environment.
- **suspected_yield_source:** administered rate from diversified Sky protocol revenue (T-bill/RWA + stability fees), governance-set.
- **Sky lending TVL:** `~$5.31B` (DeFiLlama `sky-lending`, 2026-07-02). [L2]
- **live RWA floor baseline:** `~3.4%` (rwa_feed, TVL-weighted).

## Spread over the floor (ADR-YL-008)
- **spread_over_floor_bps:** `~20–35 bps` (SSR ~3.6-3.75% − floor ~3.4%). **Near-floor** — the SSR is by design ≈ the front-end/T-bill rate.
- **spread_risk_explanation (the tiny spread):**
  - `governance rate-setting risk` — SSR is set by SKY token governance (can be cut/changed via a Spell). Bounded but real.
  - `USDC/PSM + RWA-backing correlation` — USDS inherits DAI-lineage backing (USDC/PSM + RWA); correlates with USDC's tail (see usds.stablecoin.md).
  - `governance-attack window` — the risk a malicious governance action reaches depositors; **mitigated by the GSM Pause Delay** (a timelock giving depositors a window to exit).

## Red-team + THE decisive gate
- **GSM Pause Delay (SOURCED 2026-07-02): currently 24 hours.**
- **Desk rule FORBIDDEN #8 (CLAUDE.md):** `sky_susds = 0% until a confirmed on-chain GSM Pause Delay ≥ 48h.` The pause delay is the depositor-protection window against a malicious governance Spell. At **24h < 48h**, that protection is BELOW the desk's threshold.
- **most-fragile assumption:** that 24h is enough for depositors to detect + exit a malicious governance action. The desk has already decided it is NOT (48h bar).

## Verdict
- **verdict:** **REFUSE / HOLD-AT-0%** — NOT a yield judgment (the ~3.6% is fine, near-floor). Refused on a **governance-safety precondition**: GSM Pause Delay 24h < the required 48h. This is a NOVEL refusal reason (`governance_safety_precondition`) distinct from tail-comp (leverage_loop) — and it is the desk's OWN existing rule (FORBIDDEN #8) agreeing with the mandate. **Positive result → refusal log.**
- **reason_code:** `governance_safety_precondition` (GSM Pause Delay < 48h)
- **also:** even if the gate cleared, the spread is only ~20-35 bps — a near-floor sleeve, not a fundable-edge; it would rank as Preserve-baseline, not an edge over the floor.
- **re-open condition:** if an on-chain GSM Pause Delay ≥ 48h is confirmed (verify via Sky governance / chain), re-evaluate as a low-risk Preserve floor-substitute (still tiny spread).
- **capital_protected_est:** conceptual — avoids holding a stablecoin whose depositor-protection window is below the desk's safety bar.

## Honesty note
A mainstream, low-risk, near-floor yield can still be correctly REFUSED — here on a governance-safety
precondition the desk set for itself (FORBIDDEN #8), independently reproduced by the mandate. The
refusal is the product: it documents WHY the desk won't hold sUSDS at non-zero yet, auditable and
re-openable on a specific on-chain condition.

*created_at: 2026-07-02 · sources: WebSearch (Sky Savings Rate 3.60-3.75%, GSM Pause Delay 24h, Sky forum/docs) + DeFiLlama sky-lending TVL $5.31B + CLAUDE.md FORBIDDEN #8 + docs/adr/ADR-YL-008.*
