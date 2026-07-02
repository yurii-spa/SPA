# Strategy Candidate — Term Finance (fixed-rate auctions) → ADVANCE-WITH-CAP (real non-Ethena fixed-rate, but THIN/declining)

> Auto-sprint batch (research agent, 2026-07-03). Non-Ethena fixed-rate hunt. Term = auction-cleared fixed-rate
> lending (single market clearing rate per collateral×maturity). Confirms the pattern: EVERY non-Ethena
> fixed-rate venue (Frax FXB, Notional, Term) is real-but-thin — none is deep. Deep fixed-rate = Ethena PT only.

- **candidate_id:** `CAND-TERM-001` · chains: Ethereum + L2s · backers Coinbase Ventures/Electric/Maelstrom
- **yield:** organic auction clearing rate, historically USDC-4wk ~7.5-16% by collateral (BTC.b 7.5% → PT-sUSDe-collat 16%; ~Jan-2025 illustrative) = **+400 to +1000+bps over floor when it clears**. Current July-2026 rates = requires verification (JS-rendered, ~18mo-stale figures).
- **DEPTH (the binding fail):** Vaults TVL **$12.56M** (−74% from $48.2M peak); active lend book collapsed $68.3M peak → ~$58k snapshot. **Fundable ~$1M, NOT $10M** (that's ~80% of all vault TVL). Rails CAN scale (proven at $68M peak) but present liquidity doesn't. **Same real-but-thin bucket as Frax FXB / Notional.**
- **organic vs emissions:** clearing rate is organic (borrower-paid), BUT a TERM token (Mar-2025) + points/"Season 1" farming layer → strip TERM points from any headline; count only the organic clearing rate.
- **collateral (Ethena leak!):** overcollateralized isolated auctions; collateral incl. LSTs/LRTs (wstETH/weETH/tETH) + BTC variants + **PT-sUSDe** → some USDC auctions are Ethena/LRT-collateralized → "non-Ethena" leaks back via the COLLATERAL side. Screen those auctions out to keep the thesis honest.
- **verdict:** **ADVANCE-WITH-CAP** — `thin_declining_depth` (+ `incentive_layer_present`, `collateral_ethena_leak`). Real organic non-Ethena fixed-rate with a big spread, but capacity-limited + shrinking → cap to a small fraction of a single auction, exclude PT-sUSDe/LRT-collateralized auctions, count only organic clearing rate. No known incident (requires verification; audit firm unconfirmed).

*sources: DeFiLlama /protocol/termfinance-{lend,vaults} (TVL/peak, 2026-07-03), term.finance (auctions, ~Jan-2025 rates), Blockworks/Decrypt (launch), Bittime/CryptoRank (TERM token+points). Current rates + audit + incident-absence = requires verification.*
