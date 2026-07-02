# Strategy Candidate — Resolv RLP / USR → REFUSED (first-loss leverage tranche + REALIZED exploit)

> Edge-hunt cycle 11 (autonomous engine, ADR-YL-008). The highest-headline yield evaluated so far
> (RLP **20–30% APY**) → the **strongest REFUSE**: the yield is a **first-loss leveraged insurance
> tranche** (structural tail-comp) AND the tail **already fired** — a 2026 mint-contract exploit
> extracted ~$25M and depegged USR −39%. A ~1700–2700 bps "spread" that is pure tail-compensation,
> with a **realized** loss on record. Data sourced 2026-07-02 (DeFiLlama + The Block/KuCoin/MEXC +
> Steakhouse/Resolv). Schema: `docs/schemas/candidate.schema.json`.

## Candidate
- **candidate_id:** `CAND-RESOLV-001`
- **source:** live-yield scan (Resolv RLP/USR, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `structured / first-loss-tranche` (RLP = risk-absorbing equity tranche; USR = protected stable)
- **assets:** `["RLP (Resolv Liquidity Pool)", "USR (Resolv stable)"]`
- **protocols:** `["Resolv"]`
- **chains:** `["Ethereum"]`

## Yield & apparent edge (SOURCED)
- **apparent_yield:** `RLP ~20–30% APY (some sources 30%+); USR stakers ~7%.` — **L2** [verified 2026-07-02]
- **suspected_yield_source:** delta-neutral funding (ETH/BTC perp funding) + DeFi lending + RWA, with **RLP taking first-loss + self-balancing leverage** (thinner RLP layer → higher leverage → higher RLP yield).
- **Resolv TVL:** `~$8.95M` (DeFiLlama `resolv`, 2026-07-02) — **collapsed from ~$400M USR mcap (Feb 2026) → ~$100M pre-attack → ~$9M now.** [L2]
- **live RWA floor baseline:** `~3.4%` (rwa_feed).

## Spread over the floor (ADR-YL-008)
- **spread_over_floor_bps:** RLP `~1700–2700 bps` (20–30% − 3.4%). Enormous — a red flag by itself.
- **spread_risk_explanation — the spread IS the tail, NOT a bounded risk:**
  - `first-loss subordination` — **RLP absorbs ALL protocol losses to protect USR** (insurance/equity tranche). Its 20-30% is compensation for being the buffer that eats the first loss. Not a measurable bounded edge — a concentrated tail.
  - `self-balancing LEVERAGE` — thinner RLP layer → higher leverage. When the pool shrinks (exactly under stress), leverage RISES — pro-cyclical tail amplification.
  - `funding-flip / delta-neutral basis` — the underlying delta-neutral yield can flip negative (like sUSDe), and RLP eats it first.
  - `smart-contract / mint integrity` — **the decisive one: PROVEN failure.**

## Red-team — THE decisive facts (REALIZED, not modeled)
- **REALIZED EXPLOIT (2026):** an attacker exploited the **USR minting contract**, minted **~80M unbacked USR with ~$100K**, and **extracted ~$25M**. **USR depegged −39%.** [L2 — The Block / KuCoin / MEXC]
- **The insurance layer was thin:** RLP had only **~$38.6M** pre-exploit against a ~$400M→$100M USR book — the first-loss buffer is small relative to what it insures.
- **TVL collapse:** ~$400M → ~$9M. Liquidity/continuity risk is now acute.

## Verdict
- **verdict:** **REFUSE (HARD)** — the ~20-30% RLP yield is **first-loss-tranche + self-balancing-leverage tail-compensation**, and the tail is **not hypothetical: it materialized** (mint exploit, $25M loss, −39% depeg, TVL collapse). This is the cleanest refusal in the index: a headline yield that is entirely unpriced tail, with a **realized** failure on record.
- **reason_code:** `first_loss_leverage_tranche + realized_mint_exploit_depeg`
- **relation to other refusals:** distinct from leverage_loop (recursive-leverage tail-comp), sUSDS (governance-safety precondition), Maple (bounded credit — WATCH). Resolv is **structural-subordination tail-comp WITH a proven exploit** — the "high APY = compensation for a tail that already fired" archetype (docs/43 dangerous strategies: hidden-short-vol / structured first-loss / recent-exploit).
- **USR side:** even the ~7% "stable" leg is disqualified here by the **recent mint exploit + depeg + collapsing TVL** — a stablecoin that depegged 39% on an unbacked-mint bug fails the stablecoin DD (docs/13) outright.
- **re-open condition:** not re-openable on current evidence. Would require a fully re-audited mint path, a rebuilt track (post-exploit), a materially larger RLP buffer, and time — i.e., a different protocol posture.
- **capital_protected_est:** avoided a first-loss leveraged tranche in a protocol that just lost $25M to an unbacked-mint exploit — a direct, concrete refusal.

## Honesty note
A 20-30% headline is not an edge; here it is **payment for standing first in line to absorb losses**,
in a protocol whose mint contract was just exploited for $25M with a 39% depeg. The mandate's whole
point: refuse yield that is tail-compensation, especially when the tail is **on the record**. This is
the archetypal REFUSE — and a strong "check our decisions" datapoint (we say NO to the biggest number).

*created_at: 2026-07-02 · sources: DeFiLlama resolv TVL $8.95M; Resolv.xyz/RLP + Steakhouse Financial (RLP 20-30% first-loss self-balancing leverage, USR ~7%, delta-neutral funding); The Block / KuCoin / MEXC (2026 mint-contract exploit: 80M unbacked USR minted with ~$100K, ~$25M extracted, USR −39% depeg, RLP ~$38.6M, mcap $400M→$100M) + ADR-YL-008 + docs/43.*
