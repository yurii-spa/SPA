# Yield Lab — Decision Index ("check our decisions")

> Measurement-moat surface (autonomous engine cycle 7). The Yield Lab's **decisions are the product**:
> every candidate evaluated through the ADR-YL-008 mandate — **spread over the live RWA floor, every
> point risk-explained** — with its verdict, reason, and evidence level, in one auditable place.
> A skeptic can open each card and check the reasoning. Refusals are first-class positive results.
> **Live floor baseline:** ~3.4% (dynamic, `data/rwa_feed.py`). Proof: the rates-desk decision
> proof-chain reproduces (`scripts/verify_spa.py` → VERDICT OK, chain valid, 464 rows, 2026-07-02).
> Updated by the value-engine; last: 2026-07-02.

## Real-data decisions (sourced, ADR-YL-008 applied)

| id | mechanism | verdict | reason (spread over floor) | spread | evidence | card |
|---|---|---|---|---|---|---|
| **CAND-USDY-001** / SC-USDY-001 | Ondo USDY floor-plus (tokenized T-bill) | **ADVANCE → research** | spread risk-explained (single-issuer / custodian-freeze / 8%-banking / KYC-liquidity), all **bounded, sourced** via PC-ONDO-001 | ~**160 bps** | L1 (APY)→needs L2; issuer L2 | `data/strategy_candidates/ondo_usdy.candidate.md`, `data/strategy_cards/examples/ondo_usdy_floor_plus.strategy.md` |
| **CAND-SUSDS-001** | Sky Savings Rate (sUSDS) | **REFUSE / HOLD-AT-0%** | `governance_safety_precondition` — GSM Pause Delay **24h < the desk's 48h bar** (FORBIDDEN #8); also near-floor | ~**20–35 bps** | L2 | `data/strategy_candidates/susds_ssr.candidate.md` |
| **SC-LEVLOOP-001** | Leverage loop (recursive) | **REJECTED** | tail-comp — nominal spread is **unpriced liquidation tail** (realized **−8.95%**, DD ~28%); unexplained | NOMINAL ~1160 bps / realized negative | L3 (failed) | `data/strategy_cards/examples/leverage_loop.strategy.md` |
| **SC-RDFC-001** | Rates Desk Fixed Carry (Pendle PT) | **PAPER_TESTING (held)** | backtest carry real, but **realized-at-size spread = 0 / INSUFFICIENT_DATA**; spread not yet risk-attributed at size | backtest ~269 bps / realized 0 | L3 (thin) | `data/strategy_cards/examples/rates_desk_fixed_carry.strategy.md` |
| **SC-SUSDEDN-001** | sUSDe delta-neutral (Ethena) | **research (risk-comp)** | funding carry = risk-comp; funding-flip/CEX-counterparty/peg tail not decomposed → not fully explained | nominal (headline ~11%) | L3 | `data/strategy_cards/examples/susde_dn.strategy.md` |
| **SC-ETHLSTN-001** | eth_lst_neutral (hedged ETH β≈0) | **paper_testing** | realized spread INSUFFICIENT_DATA; LST-depeg-residual/funding/hedge risks itemized, unpriced pending data | not yet measured | L3 (thin) | `data/strategy_cards/examples/eth_lst_neutral.strategy.md` |
| **SC-RWA-001** | RWA sleeve (tokenized T-bill floor) | **BASELINE** | it **IS** the floor — spread ≈ 0 by construction; the yardstick every other card is judged against | ≈ 0 | L3 | `data/strategy_cards/examples/rwa_sleeve.strategy.md` |
| **CAND-SYRUP-001** | Maple syrupUSDC (institutional credit) | **WATCH / CONDITIONAL-ADVANCE** | credit-risk-comp now **bounded** (overcollateralized 120–170% + Anchorage/BitGo/Copper custody + ~3yr zero-loss Syrup) — acceptable in principle, but gated on DD given the v1 **$50M/2022 default** precedent | ~**180 bps** | L2 | `data/strategy_candidates/maple_syrupusdc.candidate.md` |
| **CAND-RESOLV-001** | Resolv RLP / USR (first-loss tranche) | **REFUSE (HARD)** | the 20–30% is **first-loss + self-balancing-leverage tail-comp**, and the tail **FIRED** — 2026 mint exploit (~$25M extracted, 80M unbacked USR, **−39% depeg**, TVL $400M→$9M). Yield = payment to absorb a realized loss | ~**1700–2700 bps** | L2 | `data/strategy_candidates/resolv_rlp.candidate.md` |

## Illustrative example cards (scaffolding — numbers illustrative, not sourced decisions)
`SC-EX-001` core_stablecoin_lending (held) · `SC-EX-002` pendle_pt_stablecoin (paper) · `SC-EX-003`
susde_yield (research) · `SC-EX-004` btc_basis (research) · `SC-EX-005` eth_staking_lrt (paper) — all
ADR-YL-008-conformant (5 spread fields present) but with `illustrative — requires verification` numbers.

## What this shows (the moat)
- **The mandate is applied, not asserted:** 1 ADVANCE (USDY — bounded, sourced spread), 1 **WATCH/
  conditional** (Maple credit — bounded but DD-gated), REFUSE/HOLD by **distinct reasons** (leverage_loop
  = recursive-leverage tail-comp; sUSDS = governance-safety precondition; **Resolv RLP = first-loss-leverage
  tail-comp with a REALIZED $25M mint exploit + −39% depeg**; FixedCarry = unrealized-at-size), 1 baseline,
  plus research/paper sleeves. **Four verdict types** (ADVANCE / WATCH / REFUSE / BASELINE); the biggest
  headline number (Resolv 20-30%) drew the hardest NO — refusals + gates dominate by design.
- **Yield ≠ edge, demonstrated:** the spread ranking is INVERSE to fundability — the ~1700-2700bps Resolv
  spread is the *least* fundable (pure tail-comp, tail fired), the ~160bps USDY spread the *most* (bounded,
  sourced). High APY draws scrutiny, not capital.
- **Every number carries an evidence level** (L0–L6, docs/37) and a source; unknowns are `requires
  verification`, never fabricated.
- **Auditable:** open any card; the spread-attribution cites the sourced issuer/protocol/stablecoin
  card; the rates-desk proof-chain reproduces standalone (`verify_spa.py`).
- **Honest edge:** no sleeve yet has a *realized, fully-explained, fundable* spread over the floor at
  size — the desk's value is the disciplined, documented decision (ADR-YL-008), not a headline APY.

*This index is a research-layer artifact; it moves no capital and is never read by RiskPolicy/execution.*
