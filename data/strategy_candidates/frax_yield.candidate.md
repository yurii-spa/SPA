# Strategy Candidate — Frax (FXB bonds + sfrxUSD) → FXB ADVANCE (real non-Ethena fixed-rate, thin) · sfrxUSD WATCH (gov/AMO-gated)

> Auto-sprint batch (research agent, 2026-07-02). Non-Ethena. Rebrand note: FRAX→**frxUSD** (2025); legacy
> sFRAX deprecated. The live instruments are sfrxUSD (savings) + FXB (bonds). FXB = a SECOND real non-Ethena
> fixed-rate instrument (after PT-sUSDe=Ethena, Notional=dead) — alive but capacity-thin.

- **candidate_id:** `CAND-FRAX-001` · chains: Ethereum/Arbitrum/Fraxtal · Frax TVL ~$274.4M
- **FXB (Frax Bonds, zero-coupon) → ADVANCE (capacity-caveat):** trustless zero-coupon token, auctioned at discount, **redeems 1:1 for FRAX at a fixed maturity** (2025/2026/2029/2055), backing pre-funded into the FXB contract at mint → forms an on-chain FRAX yield curve = structural analog of a tokenized zero-coupon T-bill. `reason_code: real_non_ethena_fixed_rate`. Residual = FRAX-solvency-at-maturity (payout unit is the stablecoin) + duration (if sold early; held-to-maturity removes it). **THE constraint: THIN depth** (~$500K/series; one Fraxlend pool ~$42K) → small-ticket only; current YTM per maturity = requires verification (JS-rendered).
- **sfrxUSD (staked frxUSD, ~3.85%, +45bps over floor) → WATCH:** clean reserve (frxUSD CR ~102.38%, tokenized T-bills BUIDL/USTB/WTGXX + USDC, Chaos PoR, regulated custodians) BUT the +45bps = compensation for **AMO-opacity + veFXS-governance control + NO published GSM-style pause-delay** (weaker than Sky). `reason_code: gov_amo_gated`. Floor-plus-governance-premium, small sleeve — NOT a clean floor.
- **legacy sFRAX → REFUSE** `deprecated_below_floor` (0.21%, wind-down; capital migrating to sfrxUSD).
- **ladder implication:** FXB is a genuine non-Ethena FIXED-RATE rung (unlike dead Notional) — but thin depth caps it small. Confirms: non-Ethena fixed-rate EXISTS but is capacity-scarce.

*sources: DeFiLlama yields (sfrxUSD 3.85%/$34.7M, sFRAX 0.21%, FXB present, 2026-07-02 L-live), api.llama.fi/tvl/frax-finance $274.4M, docs.frax.finance/fxbs (maturities/redemption), Chaos/stablecoininsider (CR 102.38%), FRAX Mar-2023 $0.88 depeg history. FXB live YTM + real depth = requires verification.*
