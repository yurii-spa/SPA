# DeFi Yield Research — Best Stablecoin Opportunities (June 2026)
## Live Data from DeFiLlama (fetched: 2026-06-21)

**Source:** `https://yields.llama.fi/pools` (no API key required)
**Universe scanned:** 16,291 pools → 275 pure-stablecoin pools (DeFiLlama `stablecoin: true`, no IL risk) passing filter: TVL > $5M, APY 3–30%.
**Method note:** "Pure stablecoin" = DeFiLlama `stablecoin` flag true (single-asset or stable-stable, **no impermanent-loss exposure**). Volatile LP pairs (WETH-USDC, WBTC-USDT, etc.) appear in a naive symbol-substring filter but are **excluded** below — they carry directional/IL risk and are out of SPA's mandate.

---

## Top 10 Pools by APY (pure stablecoin, no IL, >$5M TVL)

| # | Project | Chain | Pool | APY | base / reward | TVL | DeFiLlama forecast |
|---|---|---|---|---|---|---|---|
| 1 | morpho-blue | Ethereum | ALPHAUSDCDELTAV2 | 21.78% | 21.78 / 0 | $53.6M | **Down** |
| 2 | pendle | Ethereum | APYUSD (PT) | 21.50% | 20.14 / 1.36 | $7.8M | **Down** |
| 3 | morpho-blue | Ethereum | ALPHAUSDCASIAV2 | 20.09% | 20.09 / 0 | $8.6M | **Down** |
| 4 | altura | Hyperliquid | USDT0 | 17.54% | 17.54 / 0 | $37.8M | **Down** |
| 5 | morpho-blue | Hyperliquid | ALPHAUSDTPRIME | 15.83% | 11.41 / 4.42 | $9.0M | **Down** |
| 6 | hyperion | Aptos | USDT-USDC | 15.13% | 14.81 / 0.32 | $6.3M | Down |
| 7 | apyx-protocol | Ethereum | APXUSD | 13.87% | 13.87 / 0 | $155.0M | Stable/Up |
| 8 | 3jane-lending | Ethereum | SUSD3 | 13.43% | 13.43 / 0 | $7.5M | Down |
| 9 | dolomite | Ethereum | USD1 | 13.13% | 3.11 / 10.02 | $48.5M | Down |
| 10 | mainstreet | Ethereum | MSUSD | 12.00% | 12.00 / 0 | $74.2M | Stable/Up |

⚠️ **8 of the top 10 carry DeFiLlama's "Down" prediction** — these are bootstrap/incentive-inflated yields, not sustainable base rates. The Morpho "ALPHA…" vaults are curated high-leverage markets; APXUSD/MSUSD are new synthetic-dollar protocols paying from token emissions or undisclosed strategies. **None belong in SPA's T1.**

---

## Categorization

### Ultra-Safe (T1-equivalent, >$100M TVL, sustainable base rate)

These are the realistically investable opportunities at SPA scale ($100k now → external AUM later). All are pure stablecoin, deep TVL, base-rate driven.

| Project | Chain | Pool | APY (base) | TVL | Category |
|---|---|---|---|---|---|
| maple | Ethereum | USDC | **4.94%** | **$3.10B** | Institutional credit |
| maple | Ethereum | USDT | 4.10% | $1.06B | Institutional credit |
| sky-lending | Ethereum | sUSDS | 3.60% | $5.91B | Sky Savings Rate |
| centrifuge | Ethereum | USDC | 5.73% | $370.7M | RWA (T-bill) |
| centrifuge | Ethereum | USDS | 4.79% | $868.4M | RWA |
| morpho-blue | Base | GTUSDCP | 4.65% | $425.0M | Curated lending |
| morpho-blue | Base | STEAKUSDC | 4.63% | $262.3M | Curated lending |
| jupiter-lend | Solana | USDC | 4.47% | $406.1M | Lending |
| fluid-lending | Ethereum | USDC | **6.22%** (base 5.16) | $116.8M | Lending |
| aave-v3 | Ethereum | USDC | 3.12% | $218.4M | Money market |
| aave-v3 | Ethereum | USDT | 2.12% | $753.6M | Money market |
| compound-v3 | Ethereum | USDC | 3.27% | $39.9M | Money market |

### High-Yield T2 Candidates ($5–100M TVL, plausible but watch)

| Project | Chain | Pool | APY (base) | TVL | Note |
|---|---|---|---|---|---|
| usd-ai | Arbitrum | sUSDAI | 7.65% | $294.5M | Yield-bearing synth dollar (>$100M but newer model) |
| re | Ethereum | reUSD | 7.03% | $180.4M | Reinsurance-backed stablecoin |
| accountable | Monad | AUSD | 6.83% | $118.5M | New chain (Monad) — chain risk |
| ember-protocol | Ethereum | USDC | 12.52% | $34.9M | New lender, verify backing |
| goldfinch | Ethereum | USDC | 10.12% | $36.7M | RWA private credit (established) |
| avantis | Base | USDC | 10.28% | $32.5M | Perp-DEX LP (counterparty/perp risk) |
| dolomite | Ethereum | USD1 | 13.13% (base 3.11) | $48.5M | 10% is reward emissions |

### Speculative / Excluded (high APY, "Down" forecast, thin or exotic)
Morpho ALPHA* vaults, Pendle PT APYUSD, altura, 3jane, mystic-finance, bitway-earn, unitas SUSDU — incentive-driven or unproven backing. **Advisory-only at most (ADR-021 class).**

---

## Notable Observations

**Is Morpho Blue still the best in our universe?**
For curated, deep, sustainable lending — **yes, Morpho remains best-in-class.** Base-chain Steakhouse/Gauntlet vaults (GTUSDCP $425M @ 4.65%, STEAKUSDC $262M @ 4.63%) beat Aave/Compound USDC (3.1–3.3%) by ~140bps at comparable or larger TVL and no IL. SPA's existing `morpho_steakhouse_adapter` (T1) is pointed at the right place. **However, the highest Morpho APYs (ALPHA* at 20%+) are leveraged/curator-specific markets carrying "Down" forecasts — do not conflate them with Steakhouse base vaults.**

**Any new protocols with >8% sustainable APY?**
A few worth tracking, none yet T1-clean:
- **Fluid (Instadapp) lending — USDC 6.22%, $116M, Ethereum.** Closest to "free" upgrade: blue-chip team, real lending demand, only ~1% is incentive. Strongest new T2 candidate.
- **usd-ai sUSDAI 7.65%, $294M** and **re reUSD 7.03%, $180M** — large TVL but novel collateral models (AI-compute lending; reinsurance). T2-SPEC at best until backing is audited.
- **Centrifuge USDC 5.73% / USDS 4.79%, $370M–$868M** — RWA T-bill exposure, institutional-grade. Plausible T2 add; introduces off-chain/RWA settlement risk.
- **Goldfinch USDC 10.12%, $36.7M** — established private-credit; real yield but illiquid/default risk → T3 private-credit category (ADR-020).

**Are there Aave/Compound alternatives we're missing?**
Yes — **Maple is the standout we should weight up.** Maple USDC is **$3.1B TVL at 4.94% base** — larger than Aave USDC and ~180bps higher, institutional overcollateralized credit. SPA already lists Maple as T2; on this data it arguably deserves a **larger cap than a typical T2**. Also **Fluid** and **Jupiter-lend** (Solana, $406M @ 4.47%) are credible Aave-class money markets not in SPA's registry.

**Recent hacks / issues to flag:**
- No confirmed exploit in the top-tier names this scan; but **breadth of brand-new synthetic dollars** (APXUSD, MSUSD, AUSD, reUSD, USD1, SUSD3) paying 7–14% is a depeg-cluster risk reminiscent of past stablecoin blowups. Treat any sub-1yr synthetic dollar as un-whitelistable until it survives a stress cycle.
- **Aave USDT base rate is only 2.12%** — utilization-driven; the $84M pool showing 6.25% is a reward-boosted market, not the base. Don't read boosted sub-pools as the headline rate.
- Several top pools sit on **young L1s (Monad, Hyperliquid, Aptos, Mezo, Flare)** — chain/bridge risk dominates protocol risk there.

---

## Recommendations for SPA

**1. Should we add new protocols?**
- **Add Fluid (Instadapp) lending as a T2 adapter** — USDC 6.22% @ $116M, blue-chip, mostly base rate. Best risk-adjusted upgrade available. (ERC-4626-style; fits existing adapter pattern.)
- **Evaluate Centrifuge (RWA T-bill) as T2/T3** — $370M–$868M, 4.8–5.7%, institutional. Adds real-yield diversification away from pure on-chain lending demand. Requires RWA/off-chain-settlement risk handling.
- **Promote Maple's effective cap** — at $3.1B/4.94% it out-yields and out-sizes Aave USDC; on current data Maple behaves more T1 than T2. Consider an ADR to raise its per-protocol cap.
- **Do NOT add** the 12–22% synthetic-dollar / ALPHA-vault cohort. Advisory-only (ADR-021 class) until proven.

**2. Are our current yield expectations accurate?**
Partly. CLAUDE.md's orientation table lists Aave ~3.5%, Compound ~4.8%, Morpho Steakhouse ~6.5%:
- **Aave V3 USDC 3.12% base** — close (3.5% is slightly optimistic; current is ~3.1%).
- **Compound V3 USDC 3.27% base** — **our 4.8% estimate is stale/high by ~150bps.** Update down.
- **Morpho Steakhouse 4.6% (Base) / 3.5% (Ethereum)** — **our 6.5% estimate is too high**; the deep Steakhouse vaults pay ~4.4–4.65% now. 6.5% only appears in thin/curated ALPHA markets that aren't the same risk. **Update Morpho expectation to ~4.5%.**
- Net: blended T1 base-rate environment is **~3.5–5%**, not ~5–6.5%. RiskPolicy APY-band of 1–30% remains correct, but planning models should assume a **lower ~4% blended T1 yield**.

**3. Any protocols to de-risk from?**
- Keep **Sky/sUSDS at 0%** per FORBIDDEN rule #7 (GSM Pause Delay gate) — note Sky pays only 3.60% now, so no opportunity cost in waiting.
- Avoid chasing the **boosted/reward-inflated sub-pools** (Dolomite USD1 10% reward, Aave boosted USDT 6.25%) — reward APY decays; base is the planning number.
- Treat all **<1-year synthetic dollars and young-L1 pools** as out-of-universe regardless of headline APY.

---

### Appendix — SPA whitelist current base rates (2026-06-21)

| Protocol | Pool | Base APY | TVL |
|---|---|---|---|
| Aave V3 (ETH) | USDC | 3.12% | $218.4M |
| Aave V3 (ETH) | USDT | 2.12% | $753.6M |
| Compound V3 (ETH) | USDC | 3.27% | $39.9M |
| Compound V3 (ETH) | USDT | 2.87% | $44.6M |
| Morpho Steakhouse (Base) | STEAKUSDC | 4.63% | $262.3M |
| Morpho Gauntlet (Base) | GTUSDCP | 4.65% | $425.0M |
| Yearn V3 (ETH) | USDC | 3.22% | $26.1M |
| Maple (ETH) | USDC | 4.94% | $3.10B |
| Maple (ETH) | USDT | 4.10% | $1.06B |
| Sky (ETH) | sUSDS | 3.60% | $5.91B |

*Raw top-50 snapshot saved to `research/_raw_top50.json`. Data is point-in-time; DeFiLlama APYs move daily.*
