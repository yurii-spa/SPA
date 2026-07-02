# Strategy Candidate — Arbitrum-native USDC lending → ADVANCE (capped, currently sub-floor) — real non-Ethena diversifier chain

> Auto-sprint batch (research agent, 2026-07-02). Chain-diversification check (cf. Base=still-Ethena, Solana=real). Result: Arbitrum PASSES the Ethena-independence test (better than Base) but the organic rung is currently below floor.

- **candidate_id:** `CAND-ARB-001` · chains: Arbitrum
- **organic rung:** **Aave V3 Arbitrum USDC ~2.56% spot** (hist 3-7% by utilization), Dolomite base ~2.9% — genuine borrow-driven interest, **NOT Ethena, NOT points**. **Native USDC via CCTP** (no bridge IOU; avoid legacy USDC.e).
- **Ethena check:** USDe/sUSDe ARE on Arbitrum (LayerZero OFT) BUT **NOT embedded in the base USDC lending markets** — supplying USDC to Aave-Arb does not route into Ethena (key contrast with Base). Caveat: some elevated rates come from borrowers looping sUSDe (indirect demand; principal stays in the pool).
- **emissions rungs REFUSE/CAP:** Dolomite oARB / Radiant RDNT / Silo ARB (token incentives). GMX GM/GLP = real-yield but LP/perp-MM risk, NOT stable lending.
- **verdict:** **ADVANCE (capped) — real non-Ethena diversifier chain, but currently SUB-FLOOR** (~2.56% < 3.4%). `reason_code: organic_lending_non_ethena_but_sub_floor`. Advance only when Aave/Dolomite base APY > 3.4%; cap ARB-emissions out. Chain risk: single centralized sequencer (Offchain Labs; BoLD fraud-proofs rolling out), transient stalls (Dec-2023) but no fund-loss halt — moderate, ~Base-level.

*sources: Aavescan/app.aave (~2.56%, L2), Dolomite/stakingrewards (oARB, L2), Circle CCTP (native USDC), Arbitrum status/Dedaub (sequencer). Radiant/Silo 2026 APY + $280M-TVL figure = requires verification.*
