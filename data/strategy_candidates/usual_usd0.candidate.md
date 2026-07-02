# Strategy Candidate — Usual USD0 / USD0++ (bUSD0) → REFUSE (realized redemption-rule-change depeg + emissions)

> Auto-sprint batch (research agent, 2026-07-02). Non-Ethena RWA-backed stablecoin + its 4yr bond token.
> Archetypal refusal: the RWA collateral is REAL, but the bond-redemption mechanism was unilaterally
> rewritten by governance → realized depeg, still unhealed, yield paid in a collapsed emissions token.

- **candidate_id:** `CAND-USUAL-001` · chains: Ethereum
- **backing (real, L4):** USD0 fully collateralized by tokenized short-dated US T-bills — primary **Hashnote USYC** (BNY Mellon custody; USYC now Circle-owned), + M0/Superstate USTBL. The collateral is genuine + bankruptcy-remote — NOT the problem.
- **USD0 (base):** pays holder ~0 (T-bill revenue → treasury 70% / locked-USUAL 30%) → spread over floor ≈ 0/negative.
- **USD0++/bUSD0 (4yr bond, maturity 2028-06-11):** yield = "Alpha Yield" in **USUAL emissions** (variable, no fixed APY; USUAL mcap collapsed to ~$29M → realized $ value depressed).
- **THE tail (realized):** **Jan-2025 USD0++ depeg** — Usual unilaterally replaced implicit 1:1 redemption with a **governance-set floor price ($0.87)**, trapping holders + cascading liquidations (Morpho hardcoded-$1 oracle → bad debt, Curve/Pendle). Post-incident dual-exit: conditional 1:1 (forfeit rewards + rising USUAL fee) OR unconditional at floor (~$0.92, accretes to $1 at 2028). **bUSD0 STILL ~$0.96 on 2026-07-02 — ~4% below par 18 months later** (persistent realized discount, governance-discretionary floor).
- **verdict:** **REFUSE** — `realized_depeg_redemption_rule_change + emissions_yield + still_sub_par`. The refusal-first gate's exact archetype: real T-bill collateral does NOT rescue a bond token with a governance-discretionary redemption floor + emissions yield + an unhealed realized depeg.
- **TVL:** DeFiLlama frozen/stale post-depeg (~$96.8M, last point 2025-01-30; peaked ~$1.8B pre-depeg) → current = requires verification. Irrelevant given REFUSE.

*sources: Usual docs (llms-full.txt), The Block/Blockworks/ChainCatcher (Jan-2025 depeg mechanics, floor $0.87, UIP-12 bUSD0 rename), CoinGecko (bUSD0 $0.961 2026-07-02), DeFiLlama (TVL stale) — L3-L5. Current live APY/TVL/supply = requires verification.*
