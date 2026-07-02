# Strategy Candidate — Maple High Yield Secured (on-chain-verifiable buffer) → CONDITIONAL-PASS — the non-Ethena 8-12% that answers the Centrifuge opacity problem

> Auto-sprint batch (research agent, 2026-07-02). BREAKTHROUGH: the transparency scan found the ONE tokenized-credit
> product whose loss-absorbing buffer is PUBLICLY ON-CHAIN — clearing exactly where Centrifuge DROP was held
> (`off_chain_opacity_hold`). A genuinely publicly-underwritable, non-Ethena, 8-12% credit rung.

- **candidate_id:** `CAND-MAPLE-HY-001` · chains: Ethereum
- **yield:** Maple **High Yield Secured tier >11% (≈9% net USDC)** — distinct from the flagship syrupUSDC ~4.7% Core; this is the higher-yield tier.
- **THE distinction (vs Centrifuge):** the **over-collateralization ratio + margin-call events are ON-CHAIN and independently queryable** (120-170% in BTC/ETH/SOL/XRP/POL, active on-chain margin calls). Centrifuge DROP's junior buffer was off-chain/unquantifiable → held. Maple's buffer you can VERIFY. Risk factor = **credit/collateral, NOT funding-basis** → genuinely non-Ethena/diversifying. ~3yr post-2022-rebuild ZERO principal loss.
- **verdict:** **CONDITIONAL-PASS** — `on_chain_buffer_verifiable`. The buffer clears from public data; residual = **collateral-concentration + liquidation-cascade** in volatile crypto collateral (higher-yield tier = more concentrated than flagship). 
- **remaining gap (honest):** on-chain shows collateral value + margin calls, but **borrower identity, concentration limits, legal recourse are OFF-CHAIN** → promote to CONDITIONAL-PASS pending a borrower-concentration/recourse data room (issuer access), NOT full GO. The 2022 Orthogonal default is the pre-rebuild tail reminder.
- **ladder implication:** this is the FIRST publicly-underwritable non-Ethena ~9-11% rung — the 8-12% non-Ethena isn't purely opaque after all; Maple HY's on-chain buffer is the exception. Gated on counterparty DD (off-code), not opacity.

*sources: Maple HY Secured PDF (>11%/9% net, 120-170% overcollat), TID/OAK/Modular Capital/Vaasblock, Stablewatch (syrupUSDC ~$1.22B, 3yr zero-loss) — L2. Live yield requires re-verification at use.*

## DD UPDATE (2026-07-03, borrower-concentration gate)
The one binding number — **HY-pool top-N borrower concentration — is NOT publicly disclosed**, but (unlike Centrifuge) it is **ON-CHAIN retrievable** via Maple Proof-of-Reserves / syrup.fi (every loan/borrower/collateral balance on-chain). So this is a SOFT conditional (data exists, retrievable), not a hard opacity hold. Stays **CONDITIONAL-PASS** — `concentration_unverified_but_onchain_retrievable`; one PoR query from ADVANCE-WITH-CAP.
- **buffer (clears):** HY Secured target collat **150-500%** (thicker than Core's 100-150%, because collateral is volatile BTC/ETH/SOL/BNB/XRP at Anchorage/BitGo/Coinbase tri-party); 24h margin-call → liquidate. Oct-10-2025 stress (>$19B industry liquidations): 9 margin calls all cured ≤3h, ZERO liquidations/losses.
- **recourse (RESOLVED, favorable):** Maple institutional loans are **dual-protected — overcollateralization PLUS legal recourse to the borrower entity** (signed legal agreements), not collateral-only.
- **losses:** post-rebuild (secured v2, 2023→2026) ZERO losses/defaults on ~$4.45B; the 2022 Orthogonal ~$36M was the pre-rebuild UNSECURED v1 (a Feb-2026 headline just recycled it).
- **path to ADVANCE:** pull HY top-1/top-3 from PoR → ADVANCE-WITH-CONCENTRATION-CAP if top-1 ≤~25% / top-3 ≤~55% (size so a top-1 jump-to-default is covered by the 150-500% buffer under stress haircut); re-verify each cycle. If top-1 >~30% → stay CONDITIONAL, cap to buffer coverage.
- **residual:** single-name jump-to-default with recovery lag (not slow buffer erosion) — the concentration % is the sole unmeasured variable.
*sources: Maple HY datasheet (downloads.eth.maple.finance, L4), Maple Oct-2025 event + 2025 Data Review (L3, 60 borrowers/$11.27B), Modular Capital/OAK (recourse+legal, L2), The Block (2022 Orthogonal L2). HY top-N concentration = L0/requires on-chain PoR pull, NOT fabricated. 2026-07-03.*
