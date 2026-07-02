# Strategy Candidate — Solana-native stablecoin lending → ADVANCE (capped) — a REAL non-Ethena diversifier

> Auto-sprint batch (research agent, 2026-07-02). Chain-diversification check (like Base — is Solana yield
> real non-Ethena bounded, or emissions/Ethena again?). Result: **Solana PASSES** as a genuine non-Ethena,
> non-emissions bounded rung at the base-lending layer — BETTER than Base (native-CCTP USDC, Ethena isolated
> to Drift). But the fundable spread over the floor is thin + Solana adds a chain-liveness tail.

- **candidate_id:** `CAND-SOL-001` · **strategy_type:** `lending (Solana L1)` · **chains:** Solana
- **venues (2026):** Kamino (base ~3.5% organic, reward-null at baseline; ~$1-1.9B TVL, dominant), marginfi, Save (ex-Solend) — cluster 4-9% typical, spike 24-39% at high utilization. Canonical anchor: **Kamino USDC base 3.52% APY, reward APY NULL** (organic).
- **the split (the key analysis):**
  - **(a) organic lending — YES, the real story:** base ~3.5% is genuine borrower-paid interest (measurable utilization risk), non-Ethena. The 24-39% headlines = transient utilization spikes, NOT durable → underwrite to ~3.5-5%.
  - **(b) emissions/points overlay — flag/refuse:** KMNO points, PYUSD/USDG premium (+224% since Sep-2025 "driven almost entirely by incentives") → `emissions_bootstrap`, strip it.
  - **(c) Ethena — present but ISOLATED to Drift** (USDe/sUSDe as perp collateral via LayerZero OFT), **NOT in the Kamino/marginfi/Save USDC base markets.** Unlike Base (where Ethena crept into the "safe" rung), Solana's core money-market USDC yield is NOT Ethena-collateralized. Refuse the Drift lane as `ethena_again`.
- **chain risk (the distinct tail):** last official full halt Feb-2024 (~5h); ~16-22mo no acknowledged halt since (best streak) BUT ≥9 UNacknowledged disruptions Oct-2024→Feb-2025 (some ~13h) → real bounded liveness tail (can't exit during a window). **USDC is NATIVE (Circle CCTP, not bridged)** → NO bridge-hop / wrapped-collateral risk (the thing that would sink a chain-diversification thesis). Depth concentrated in Kamino (single-protocol).
- **verdict:** **ADVANCE (capped)** — `organic_lending_bounded_but_thin`. A REAL non-Ethena diversifier (SOL money-market carry ≠ Ethena funding carry; native-CCTP). Cap conditions: underwrite to base ~3.5-5% (reject 24-39% spikes); refuse PYUSD/USDG emissions premium + the Drift Ethena lane; size conservatively (thin ~0-150 bps over floor + chain-liveness tail + single-protocol concentration).
- **ladder implication:** Solana base-lending is the **first genuinely-diversifying non-Ethena, non-EVM rung found** — adds real cross-chain diversification the EVM stack lacks, at ~3.5-5% Core with a bounded chain tail.

*sources: DeFiLlama yields (Kamino USDC base 3.52% reward-null, 2025-08-09), Kamino/marginfi/Save TVL (DeFiLlama + secondary, requires verification), DL News (24-39% spikes points-driven), Drift/Solana Compass (Ethena via Drift), Circle CCTP (native USDC, Solana Oct-2025), Helius/StatusGator (outage history) — accessed 2026-07-02. + underwriting_rubric.md.*
