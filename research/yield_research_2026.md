# SPA Yield Research Report — June 2026
## New Strategy Candidates: S22 / S23 / S24

**Research date:** June 21, 2026
**Methodology:** 5 parallel deep-search agents; primary sources fetched directly from DeFiLlama API (`yields.llama.fi/pools`), Pendle API (`api-v2.pendle.finance`), Kamino live app, Aave Governance Forum, rekt.news leaderboard (301 entries), Chainalysis 2026 Crime Report; adversarial 3-vote cross-verification on all key claims.

---

## ⚡ EXECUTIVE SUMMARY: TOP 3 RECOMMENDATIONS

| Rank | Strategy | Protocol | APY | Risk Tier | SPA Fit |
|------|----------|----------|-----|-----------|---------|
| **S22** | Fluid Protocol USDC Lending | Fluid (Instadapp) | **6.22%** | T2 | Strong — direct USDC deposit, ERC-4626, DeFiLlama fetchable |
| **S23** | Pendle PT Fixed-Yield (Rolling) | Pendle Finance | **4.4–8.5%** | T2-FIXED | New ADR needed; PT ≠ YT (ADR-021 doesn't apply) |
| **S24** | f(x) Protocol Stability Pool | f(x) / AladdinDAO | **6.17%** | T2 | Novel mechanism; organic yield; direct USDC; new ADR needed |

**Also watch:** Centrifuge USDC (5.73%, $370M TVL, RWA-backed), sGHO via Aave (4.25% base sustainable), USD-AI/SUSDAI on Arbitrum (7.67%, $294.5M TVL — audit status TBD).

---

## ⚠️ CRITICAL SECURITY BRIEFING (2025–2026)

Before protocol analysis, context on the threat landscape:

| Date | Protocol | Loss | Vector |
|------|----------|------|--------|
| Feb 2025 | Bybit (CeFi) | $1.436B | DPRK private key |
| Nov 2025 | Balancer V2 (65+ forks) | $128M | Rounding error in `_upscale()` |
| Nov 2025 | Moonwell (Base) | $1M | Oracle price feed manipulation |
| Feb 2026 | Moonwell (Base) | $1.78M | cbETH oracle misconfiguration |
| Mar 2026 | Aave V3 (Ethereum) | $27.78M | Chaos Labs CAPO oracle stale anchor — *healthy positions liquidated; DAO committed reimbursement* |
| Mar 2026 | Resolv Labs (USR) | $25M | Supply chain attack on CI/CD |
| Apr 2026 | **Drift Protocol** | **$285M** | DPRK social engineering + durable nonce pre-signed transactions (Solana) |
| Apr 2026 | **KelpDAO / LayerZero** | **$290M** | DPRK breached LayerZero infrastructure; forged bridge message |
| May 2026 | Fluid Protocol | $215K | Private key compromise (infrastructure, not smart contract) |
| May 2026 | Seamless Protocol (Base) | Shutdown | Wind-down announced Apr 7; UI offline **Jun 30, 2026** |

**Chainalysis 2026:** DPRK stole $2.02B in 2025 (+51% YoY); $6.75B all-time. Private key compromises = 88% of Q1 2025 stolen value. 18 DPRK-attributed operations in 2026 (through April). **Solana is an active DPRK targeting zone.**

**SPA implication:** Solana cross-chain integration is not recommended at this time (see Kamino section). Ethereum-native protocols remain the safest execution environment.

---

## PROTOCOL ANALYSIS

---

### 1. ETHENA sUSDe

**Current APY (June 21, 2026):** 3.55%
**Historical range:** 3–27%+ (cyclical, peaks in bull funding-rate environments)

| Metric | Value | Source |
|--------|-------|--------|
| Native sUSDe staking APY | **3.546%** | DeFiLlama / ethena-usde pool (live) |
| Pool TVL (sUSDe contract) | **$1.710B** | DeFiLlama live |
| Protocol TVL (all chains) | **$4.852B** | DeFiLlama |
| PT-sUSDe Aug 2026 (Pendle, fixed) | 4.375% | Pendle API |
| sUSDe on Aave V3 (Ethereum, reward) | 2.976% | DeFiLlama |

**Mechanism:** USDe is collateralized by staked ETH/LST + BTC with equal short perpetual futures positions on CEXs (delta-neutral). Revenue = LST staking yield + perpetual funding rate income. Rewards transferred to StakedUSDe (sUSDe, ERC-4626) every 8 hours; vest linearly. Reserve Fund covers periods of negative funding rates.

**Entry path from USDC:**
1. Swap USDC→USDe via DEX aggregator (1inch, CoW Swap) — deep Curve liquidity
2. Stake USDe→sUSDe at `app.ethena.fi/earn`
3. **7-day unstaking cooldown** applies

**Key risks:**
- Funding risk: Current 3.55% vs. 27%+ peak — highly cyclical
- Custodial risk: Collateral at OES custodians (Copper, Cobo, Ceffu), not self-custodied
- Exchange risk: CEX shorts at Binance/Bybit — exchange failure risk
- Geo-restriction: EU/EEA residents blocked from Ethena Labs directly
- 7-day cooldown: liquidity risk for rapid rebalancing

**Audits:** Zellic, Quantstamp, Spearbit, Pashov (×3), Code4rena, Cyfrin, Chaos Labs (economic) — all no critical/high findings.

**SPA Tier Assessment:** T3-SPEC (consistent with current S8 strategy)

**SPA Recommendation:** Already covered by S8 (Delta-Neutral sUSDe). Current 3.55% APY is below Fluid (6.22%) and f(x) (6.17%). No new strategy needed at this APY level. **Re-evaluate if sUSDe APY rises above 10% in next bull cycle.**

---

### 2. FLUID PROTOCOL (Instadapp) ← **S22 CANDIDATE**

**Current APY — Ethereum Mainnet (June 21, 2026):**

| Asset | APY Total | Base APY | Reward APY | Pool TVL |
|-------|-----------|----------|------------|----------|
| **USDC (primary pool)** | **6.22%** | 5.16% | 1.06% (FLUID) | **$116.8M** |
| USDT | 4.35% | 3.29% | 1.06% (FLUID) | $116.3M |
| USDC (Fluid Lite) | **8.42%** | ~8.42% | — | $35.6M |
| GHO | 6.11% | 3.46% | 2.65% (FLUID) | $13.2M |

**Multi-chain USDC APY:**

| Chain | APY | TVL |
|-------|-----|-----|
| Base | 5.42% | $8.7M |
| Arbitrum | 4.96% | $36.6M |

**DeFiLlama Pool IDs (for adapter):**
- USDC Ethereum: `4438dabc-7f0c-430b-8136-2722711ae663`
- USDT Ethereum: `4e8cc592-c8d5-4824-8155-128ba521e903`
- USDC Fluid Lite: `488f06db-5a36-450e-9ba9-b4321be39c7c`

**Protocol metrics:**
- Total TVL: **$713.39M** (all chains)
- Active loans: $656.14M
- Annualized fees: $75.69M | Revenue: $12.66M | Token buybacks to FLUID holders: $6.66M/year
- Chains: Ethereum, Arbitrum, Base, Plasma

**Architecture:** Fluid is the evolution of Instadapp's lending infrastructure. fToken model (ERC-4626 compatible). Revenue-sharing: borrowers pay interest; percentage flows to treasury and FLUID token buybacks. Fluid Lite = higher-yield smart vaults using optimized strategies.

**Security:**
- Historical audits: Certik, MixBytes, Dedaub, Peckshield (prior Instadapp rounds, confirmed)
- **May 31, 2026 incident:** $215,000 lost via **private key compromise** (NOT a smart contract exploit). Infrastructure breach, not protocol logic failure.
- Audit reports: `https://docs.fluid.instadapp.io/`

**SPA RiskPolicy gates:**
- TVL floor (≥$5M): ✅ PASSES ($116.8M USDC pool)
- APY bounds (1–30%): ✅ PASSES (6.22%)
- T2 cap applies: 20% per-protocol, 50% T2 total

**SPA Tier:** T2 (newer protocol; one private key incident)

**SPA Recommendation:** ✅ **Implement as S22.** Fluid USDC at 6.22% is +3.1% above current Aave V3 Ethereum (~3.1% live rate) and +1.6% above Compound V3 (~4.6%). USDC deposit is direct (fToken = ERC-4626). DeFiLlama fetchable via existing yield API. The May 2026 incident was private key (infrastructure), not smart contract — risk is different in nature from a code exploit. Requires new ADR documenting this distinction and the FLUID reward token component.

**Adapter design notes:**
```
GET https://yields.llama.fi/pools
→ filter project="fluid-lending", chain="Ethereum", symbol="USDC"
Pool ID: 4438dabc-7f0c-430b-8136-2722711ae663
On-chain: fToken ERC-4626 deposit/withdraw — same interface as other SPA adapters
APY: use apy_base=5.16% for conservative RiskPolicy; note apy_reward=1.06% (FLUID token)
```

---

### 3. PENDLE PT (PRINCIPAL TOKEN) POOLS ← **S23 CANDIDATE**

**Context — PT vs YT (critical distinction):**
Pendle PTs are zero-coupon bonds — buy at a discount, redeem 1:1 for underlying at maturity. The Fixed APY is locked in at purchase. **Unlike YT (Pendle Yield Tokens, which decay to zero at maturity and are governed by ADR-021 as T3-SPEC advisory-only), PTs guarantee full principal return if held to maturity.** A PT-specific strategy is distinct from ADR-021's scope.

**Top Stablecoin PT Pools — Ethereum (June 21, 2026, Pendle API live):**

| PT Symbol | Expiry | Fixed APY | Underlying APY | Pool TVL | Underlying | Risk |
|-----------|--------|-----------|----------------|----------|------------|------|
| **PT-sUSDE-13AUG2026** | Aug 13 | **4.38%** | 3.58% (sUSDe) | **$9.5M** | Ethena | Conservative |
| **PT-sUSDS-26NOV2026** | Nov 26 | **5.10%** | 3.60% (Sky) | **$6.1M** | Sky/MakerDAO | Conservative |
| **PT-sNUSD-24SEP2026** | Sep 24 | **5.95%** | 4.46% | **$6.1M** | Neutrl | Moderate |
| **PT-srUSDe-22OCT2026** | Oct 22 | **5.23%** | 2.88% | $1.1M | Strata/Ethena | Moderate |
| **PT-USDat-27AUG2026** | Aug 27 | **7.71%** | ~0% | **$10.0M** | Saturn | Moderate |
| **PT-apxUSD-27AUG2026** | Aug 27 | **7.96%** | ~0% | **$6.3M** | APYX | Moderate |
| **PT-apyUSD-27AUG2026** | Aug 27 | **14.79%** | 14.91% | **$7.8M** | APYX | Speculative |
| **PT-superUSDC-26NOV2026** | Nov 26 | **7.60%** | 13.18% | $2.4M | Superform USDC | Moderate |

**Arbitrum PT Pools:**

| PT Symbol | Expiry | Fixed APY | Pool TVL | Protocol |
|-----------|--------|-----------|----------|----------|
| **PT-USDai-15OCT2026** | Oct 15 | **6.46%** | **$50.5M** ← *largest stablecoin PT pool found* | USD.AI |
| **PT-sUSDai-15OCT2026** | Oct 15 | **8.54%** | **$14.9M** | USD.AI |

**Cross-verified APY claims:**
- PT-sUSDe 4.38%: confirmed via Pendle API + Google AI Overview (~4.3–4.5%)
- PT-sUSDS 5.10% (Nov 2026): confirmed; near-expiry stUSDS at 6.35% = maturity premium effect
- PT-apyUSD 14.79%: confirmed; Google AI Overview range 13.7–18.0%

**Risk considerations:**
1. Duration/liquidity risk: Funds locked until maturity; early exit via Pendle AMM incurs slippage
2. Underlying protocol risk: PT only fixes the rate — doesn't eliminate underlying asset risk
   - PT-sUSDE: Ethena risk (custodian, funding rate) — well-established, ~$4.8B TVL
   - PT-sUSDS: Sky/MakerDAO risk — most conservative; 9-year track record
   - PT-apyUSD: APYX is newer (~$62M underlying pool TVL, dividend-backed)
   - PT-USDai: USD.AI "AI-directed" strategy; unknown audit status despite $50.5M TVL
3. Pendle smart contract risk: Pendle V2 audited by multiple firms; $2B+ TVL history
4. Very-high APY = risk signal: PT-reUSDe at 39.69% = illiquidity premium; avoid

**SPA Tier:** T2-FIXED (new sub-tier; distinct from T3-SPEC YT under ADR-021)

**SPA Recommendation:** ✅ **Implement as S23 (Pendle PT Rolling Adapter).** Conservative default: PT-sUSDE (4.38% fixed) and PT-sUSDS (5.10% fixed) as eligible underlyings. Auto-roll logic: if <14 days to maturity, rotate to next available eligible PT. Key advantage: eliminates APY variance for the locked allocation tranche. Requires new ADR explicitly distinguishing PT from YT and confirming this strategy operates outside ADR-021 scope.

**Adapter design notes:**
```
GET https://api-v2.pendle.finance/core/v1/1/markets (Ethereum)
Filter: underlyingAsset in [sUSDe, sUSDS]; TVL > $5M; daysToMaturity > 14; daysToMaturity < 180
Strategy: select highest fixed_apy from eligible set; hold to maturity; roll at <14d
Conservative: PT-sUSDE, PT-sUSDS only (whitelisted underlyings)
Expanded (ADR required): PT-apxUSD, PT-USDai (separate approval per underlying)
RiskPolicy note: fixed_apy is locked at entry; report entry_apy not live_apy in equity curve
```

---

### 4. EtherFi weETH / Liquid Restaking

**Finding:** No significant direct stablecoin yield from weETH liquidity pools at SPA-appropriate TVL in June 2026. weETH pools are ETH-denominated; stablecoin-adjacent positions require ETH price exposure incompatible with SPA's capital allocation model.

**SPA Recommendation:** ❌ Skip. Not applicable to USDC/USDT capital without ETH exposure.

---

### 5. AAVE GHO STABILITY MODULE / sGHO

**sGHO (Aave Savings Rate for GHO):**

| Parameter | Value | Source |
|-----------|-------|--------|
| Current base APR | **4.25% fixed** | Aave Governance ARFC, TokenLogic, Mar 25 2026 |
| Transitional Stakoor boost | +~5% (temporary) | Merkl incentive campaign |
| Total APR with boost | **~9.25%** | Transitional only; base 4.25% is sustainable |
| sGHO contract | `0x1a88Df1cFe15Af22B3c4c783D4e6F7F9e0C1885d` | ERC-4626 |
| GHO circulating supply | 404.7M GHO (all-time high, Mar 2026) | Aave Governance |
| sGHO deposits | 304.6M GHO (~75% locked in savings) | Aave Governance |
| APR max cap (contract) | 50% APR | |
| Rate mechanism | `fixedRate=425 bps, floatRate=0` — fully fixed | Decoupled from market rates |
| Slashing risk | None | |
| Cooldown | None | |
| Audits | Certora + Sherlock | |

**GSM USDC deposit (direct):** Returns **0% yield**. GSM is a conversion mechanism (USDC↔GHO 1:1), not a yield product. Fees go to Aave DAO treasury only.

**Entry path:** USDC → GHO via GhoRouter (one atomic tx, small GSM fee ~0.1%) → deposit GHO into sGHO vault → earn 4.25% APR fixed.

**Aave governance risk (March 2026):** Chaos Labs oracle parameter update ($27.78M in healthy positions liquidated due to stale anchor). DAO committed reimbursement. BGD Labs + ACI (core dev and governance teams) both announced departures within days — governance fragility is elevated in mid-2026.

**Risks:** GHO peg risk (has historically traded below $1.00 on secondary markets); governance rate change risk; USDC→GHO conversion (small fee and slippage).

**SPA Tier:** T2 (Aave ecosystem, well-audited, but GHO peg and governance disruption risks)

**SPA Recommendation:** 🟡 Watch list for S25/S26. Base 4.25% is below Fluid (6.22%) and f(x) (6.17%). Stakoor ~9.25% is transitional. Governance disruption in March 2026 warrants additional monitoring before new ADR. Not urgent given stronger candidates available.

---

### 6. BASE CHAIN — USDC YIELD LANDSCAPE

**Base TVL context (June 21, 2026):** $4.21B total; $2.76B in Morpho alone (65% concentration). Native Circle USDC on Base — zero bridge risk for USDC itself.

#### Morpho on Base (already in SPA — expanding vaults):

| Vault | Curator | APY (spot) | APY (30d) | TVL |
|-------|---------|------------|-----------|-----|
| GTUSDCP | Gauntlet | **4.65%** | 4.46% | **$426M** |
| STEAKUSDC (primary) | Steakhouse Financial | **4.63%** | 4.46% | **$262M** |
| STEAKUSDC (v2) | Steakhouse Financial | **4.41%** | 4.37% | **$238M** |
| SIRLOINUSDC | Clearstar | **4.80%** | 4.49% | **$81M** |
| BBQUSDC | Steakhouse | **5.98%** | 5.80% | **$27M** |
| MWUSDC | Moonwell/Block Analitica | **5.84%** | 5.55% | **$9.3M** |

**⚠️ APY discrepancy note:** CLAUDE.md states Morpho Steakhouse ~6.5% APY. Live DeFiLlama data shows 4.37–5.98% across all Base Morpho vaults. The CLAUDE.md figure may reflect an earlier bull-rate period or MORPHO token incentives not currently active. Update CLAUDE.md after verifying Ethereum mainnet Morpho Steakhouse rate (separate from Base). The BBQUSDC vault at 5.98% is the closest to the 6.5% historical estimate.

**Coinbase integration (verified):** Coinbase launched in-app USDC lending Sept 2025 via Morpho Base (Steakhouse curation). Launch APY 10.8%; normalized to 4.4–5.9%. Source: morpho.org blog (Sept 18, 2025).

#### Aerodrome Finance:

| Pool | Type | APY (spot) | APY (30d) | TVL | Notes |
|------|------|------------|-----------|-----|-------|
| MSUSD-USDC | Slipstream CL50 | **6.64%** | 5.55% | **$21.1M** | 4.42% fees + 2.22% AERO |
| MSUSD-USDC | V1 stable | **11.18%** | 8.77% | **$7.7M** | 100% AERO rewards |
| USDC-USDT | Slipstream CL1 | **8.19%** | 24.89%* | $2.0M | ❌ Below $5M TVL floor |

*30d avg of 24.89% for USDC-USDT due to short-lived incentive spike; not representative.

**Risks:** AERO token price risk (2.22–11.18% of APY is AERO-denominated); mUSD (Moonwell stablecoin) counterparty risk in MSUSD pools; LP position required (not single-asset lending).

**SPA Tier for Aerodrome:** T2 (AMM LP model; AERO reward token risk)

#### Avantis (Base):

| Pool | APY (spot) | APY (30d) | TVL |
|------|------------|-----------|-----|
| USDC LP vault | **10.28%** | 9.92% | **$33M** |

**Mechanism:** USDC LPs are counterparty to all Avantis perpetual traders. Earn 100% of trading fees + net trader losses. Real 10%+ APY exists but directionally exposed to trader performance. 2 audits.

**SPA Tier:** T3-SPEC (perp DEX counterparty — requires new ADR like ADR-021)

#### Moonwell (Base): ❌ DO NOT ALLOCATE

Four security incidents in under 3 years ($320K Dec 2024, $1.7M Oct 2025, $1M Nov 2025, $1.78M Feb 2026). USDC pool TVL = $1.79M — **fails $5M TVL floor** regardless of security concerns.

#### Seamless Protocol (Base): ❌ SHUTTING DOWN

Wind-down announced April 7, 2026. **UI goes offline June 30, 2026 (9 days from today)**. Exit any position immediately.

#### Other Notable Base Protocols:

| Protocol | APY | TVL | Notes |
|----------|-----|-----|-------|
| Centrifuge USDC | 5.73% | $50M (Base) | RWA; Coinbase strategic investment May 2026 |
| Fluid Lending USDC | 5.42% | $9M | Same protocol as S22 (Base deployment) |
| Avantis USDC | 10.28% | $33M | Perp DEX; T3-SPEC |

---

### 7. KAMINO FINANCE (Solana)

**Current APY (June 21, 2026, live kamino.com):**

| Market / Vault | APY | TVL |
|----------------|-----|-----|
| Main Market USDC (base supply) | **3.62%** | **$115.76M** |
| Main Market USDT | **3.78%** | $7.24M |
| Elemental USDC Optimizer | **6.92%** | $2.68M |
| RockawayX RWA USDC | **6.67%** | $26.85M |
| Steakhouse USDC High Yield | **6.47%** | $2.79M |
| Neutral Trade USDC Max Yield | **7.10%** | $1.44M |

**Protocol TVL:** $1.227B (down from $3.714B peak Oct 2025 — broad Solana DeFi contraction, not protocol-specific)

**Security (exceptional for the space):**
- 20 external audits; 4 formal verifications (Certora)
- March 2026: OtterSec + Certora formal verification of Lend v1.16.0/v1.17.0 (most recent)
- 0 critical vulnerabilities across all audits
- $1.5M Immunefi bug bounty
- 4 oracle sources: Chainlink, Pyth, Switchboard, Redstone + proprietary Scope oracle
- $19.33B through Scope oracle, 0 oracle exploits
- 100,000+ liquidations, $0 bad debt
- 5/10 multisig + 12-hour timelock (correct standard per Drift post-mortem)

**Why SPA should NOT integrate now:**

1. **Drift Protocol exploit (April 1, 2026, $285M):** DPRK social engineering over 6 months; durable nonce pre-signed transactions enabled $285M drain in 128 seconds. $230M+ moved via Circle CCTP off Solana within 6 hours during US business hours — Circle did not freeze proactively.
2. **DPRK active targeting:** Chainalysis + Elliptic confirmed Solana as primary DPRK target zone in 2025–2026
3. **Bridge required:** SPA's USDC is on Ethereum. Kamino requires bridge integration. LayerZero suffered $290M exploit April 2026 (DPRK breached LayerZero infrastructure itself).
4. **Curated vault TVL:** 6.47–7.10% vaults have only $1.44M–$2.79M TVL — below or barely above the $5M floor
5. **Main market rate (3.62%)** is below existing SPA T1 adapters

**SPA Recommendation:** ❌ **Do not integrate at this time.** Kamino is one of the best-audited protocols in DeFi — protocol risk is low. But chain-level and bridge risk are unacceptably high for this period. Revisit when: (a) Solana DPRK risk profile improves, (b) SPA formally adopts a cross-chain ADR, (c) curated vault TVL exceeds $10M, (d) Circle demonstrates proactive CCTP freeze capability.

---

### 8. USUAL PROTOCOL (USD0 / bUSD0)

**Current APY (June 21, 2026, DeFiLlama):**

| Product | APY | TVL | Yield Type |
|---------|-----|-----|------------|
| bUSD0 (Bond USD0) | **2.27%** | **$506M** pool | USUAL token emissions |
| sUSD0 (Savings USD0) | **4.10%** | **$0.36M** ❌ | Organic (T-Bill yield) |
| USUALx | 13.96% base / 42.07% with emissions | $6.28M | Governance token — not stablecoin |

**Protocol TVL:** $99.5M | Collateral: USYC (Hashnote, BNY Mellon custody) + eUSD0 (Euler) | Total raised: $18.5M

**Risk flags:**
- January 2025 depeg incident: Usual changed USD0++ redemption from 1:1 to floor price — USD0++ traded at ~$0.87 temporarily. Product restructured; rebranded as bUSD0.
- USUAL token price risk: bUSD0's 2.27% yield is paid in USUAL tokens (~$0.01, FDV $18.9M — down massively from peak). Real APY depends on USUAL price.
- May 2025 exploit: $43,000 via arbitration logic bug

**Audits:** 20+ audits (Cantina, Sherlock, Spearbit, Halborn, Hexens, Paladin, Blackthorne)

**SPA RiskPolicy check:**
- bUSD0 pool TVL: $506M ✅ PASSES floor
- sUSD0 pool TVL: $0.36M ❌ **FAILS** floor
- bUSD0 APY: 2.27% in USUAL tokens — token-denominated, not USD yield

**SPA Recommendation:** ❌ **Do not integrate.** sUSD0 (the only organic-yield product) fails the $5M TVL floor at $0.36M. bUSD0 yield is USUAL-token-denominated with severe token price risk. USD0++ depeg event demonstrates governance risk. Revisit only if sUSD0 TVL grows to >$10M.

---

### 9. f(x) PROTOCOL (fxUSD Stability Pool) ← **S24 CANDIDATE**

**Current APY (June 21, 2026, DeFiLlama):**

| Pool | APY | TVL | Notes |
|------|-----|-----|-------|
| **FXUSD Stability Pool V2.0** | **6.17%** | **$57.87M** | Primary stablecoin yield product |
| USDC+fxUSD LP (Curve) | 3.30% | $7.91M | LP with minor IL |
| FXSAVE-scrvUSD | 6.10% | $0.55M | Auto-compounding vault |
| MSUSD+FXUSD | 8.69% | $0.99M | Higher yield, small pool |

**Protocol TVL:** $89.87M | Fees (annualized): $6.79M | Revenue: $948,952

**Mechanism:** fxUSD is backed by wstETH (Lido). The protocol creates two tranches:
- **fxUSD (stablecoin):** Floating leverage position on ETH volatility; pegged via Stability Pool
- **xPOSITION (leverage):** Absorbs ETH price volatility; earns leverage-enhanced ETH upside

**Stability Pool mechanics:**
- Accepts USDC directly (no conversion needed) and fxUSD
- Earns: wstETH staking yield (~3-4%) + xPOSITION opening fees + minor FXN emissions
- Acts as peg keeper: absorbs fxUSD discounts during ETH crashes
- "Liquidation Brake" rebalancing prevents cascading liquidations
- Stability Pool depositors absorb bad debt only in the extreme scenario where Pool is fully exhausted
- Protocol documentation explicitly acknowledges: "If mechanism becomes exhausted, xTokens could drop to zero" and "stablecoin may temporarily de-peg"

**Yield source is organic** (ETH staking + trading fees) — not token emissions. More durable than USUAL's bUSD0.

**Security:**
- 16 audits claimed ("100% of deployed code is audited" — official website)
- AladdinDAO (parent) historically audited by SECBIT Labs
- Specific auditor names for f(x) v2 not publicly indexed (docs paths return 404) — this is a gap
- **No exploits found** in rekt.news 301-entry leaderboard

**SPA RiskPolicy check:**
- TVL floor: $57.87M ✅ PASSES
- APY bounds (1–30%): 6.17% ✅ PASSES
- T2 cap applies

**SPA Tier:** T2 (novel mechanism; ETH-backed stablecoin)

**SPA Recommendation:** ✅ **Implement as S24.** 6.17% organic APY with $57.87M TVL passes all RiskPolicy gates. Organic yield (not token inflation) is more sustainable than most alternatives at this APY level. Direct USDC deposit simplifies adapter design. Requires new ADR documenting: ETH-backed stablecoin risk, Stability Pool exhaustion scenario, maximum allocation (recommend 10% portfolio cap). **ADR must require full audit report verification before go-live** — current public accessibility of v2 audit reports is insufficient.

**Adapter design notes:**
```
DeFiLlama: filter project="fx-protocol", pool="FXUSD Stability Pool V2.0"
On-chain: fx.aladdin.club Stability Pool contract — direct USDC deposit
APY: track apy_base only (exclude FXN token component if any)
Monitoring: track fxUSD/USDC price on secondary markets; trigger if < $0.99
Max allocation: 10% of portfolio (conservative given novel mechanism)
```

---

### 10. ADDITIONAL VENUES: LEGITIMATE 10%+ APY?

**Adversarial finding:** No legitimate, audited, blue-chip protocol offers sustainable 10%+ APY on pure USDC/USDT in June 2026. The honest base-rate ceiling for T1-quality protocols is approximately **5–7%**.

To reach 10%+ requires one of:
- Ethena's funding-rate cyclicality (3.55% today; ~27% at cycle peak)
- Pendle YT speculation (value decays to zero at maturity — ADR-021 T3-SPEC)
- Temporary token incentives (Morpho/Coinbase launch: 10.8% → normalized to 4.6%)
- Smaller/less-audited protocols (Avantis 10.28% = perp DEX counterparty risk)
- Near-expiry PT APY distortion (annualized 39.69% on PT expiring in 4 days = $0 gain)

| Venue | APY | Sustainable? | Verdict |
|-------|-----|--------------|---------|
| Avantis USDC (Base) | 10.28% | Conditional | T3-SPEC; perp DEX counterparty; real yield, but not lending |
| Aerodrome MSUSD-USDC V1 | 11.18% | Conditional | Real AERO rewards; AERO price risk; mUSD counterparty |
| Pendle PT-apyUSD | 14.79% fixed | Yes (at purchase) | APYX newer protocol; locked until Aug 2026 |
| sGHO Stakoor boost | ~9.25% | Partial | Base 4.25% sustainable; +5% Stakoor is transitional |
| Ethena sUSDe (bull market) | 10–27%+ | Cyclical | Current 3.55%; waits for bull funding rates |

---

## COMPLETE RANKING TABLE

| Protocol | Current APY | TVL (USDC pool) | Risk Tier | SPA ADR Needed | Priority |
|----------|-------------|-----------------|-----------|----------------|----------|
| **Fluid USDC (ETH)** | **6.22%** | $116.8M | T2 | New ADR | **S22 — Implement now** |
| **Pendle PT-sUSDE** | **4.38% fixed** | $9.5M | T2-FIXED | New ADR (distinct from ADR-021) | **S23 — Implement** |
| **f(x) Stability Pool** | **6.17%** | $57.87M | T2 | New ADR (ETH-backed stablecoin) | **S24 — Implement (pending audit verification)** |
| Centrifuge USDC | 5.73% | $370.7M | T2-RWA | New ADR (T2-RWA category per ADR-020) | S25 — Watch |
| sGHO (Aave) | 4.25% base | 304.6M GHO | T2 | New ADR (GHO peg risk) | S26 — Watch |
| Morpho BBQUSDC (Base) | 5.98% | $27M | T1 extension | Extend existing Morpho adapter | Easy win |
| Morpho GTUSDCP (Base) | 4.65% | $426M | T1 extension | Extend existing Morpho adapter | Easy win |
| Aerodrome MSUSD-USDC | 6.64% spot / 11.18% V1 | $21.1M / $7.7M | T2 | New ADR (AMM LP, AERO token) | Consider |
| Avantis USDC | 10.28% | $33M | T3-SPEC | New ADR (perp DEX counterparty) | Advisory only |
| Ethena sUSDe | 3.55% current | $1.71B | T3-SPEC | Existing (S8) | Already covered |
| Sky sUSDS | 3.60% | $5.9B | Watchlist | Existing policy | Waiting GSM check |
| USD-AI (SUSDAI) | 7.67% | $294.5M | Unknown | Deeper diligence first | Watch |
| Maple USDC | 4.94% | $3.09B | T2 (existing) | Existing | Already in SPA |
| Usual sUSD0 | 4.10% | $0.36M ❌ | — | — | TVL floor fail |
| Kamino USDC (Solana) | 3.62% base | $115.76M | Cross-chain | New cross-chain ADR | Solana risk too high now |
| Moonwell USDC | 4.42% | $1.79M ❌ | — | — | TVL floor fail + 4 exploits |
| Seamless Protocol | N/A | ~$2M | — | — | **SHUTTING DOWN Jun 30 — EXIT NOW** |

---

## S22/S23/S24 IMPLEMENTATION NOTES

### S22: Fluid Protocol Adapter (`spa_core/adapters/fluid_v1.py`)

```
DeFiLlama: GET https://yields.llama.fi/pools
Filter: project="fluid-lending", chain="Ethereum", symbol="USDC"
Pool ID: 4438dabc-7f0c-430b-8136-2722711ae663
On-chain: fToken = ERC-4626 (same interface pattern as existing adapters)
APY reporting: apy_base=5.16% for RiskPolicy; note apy_reward=1.06% (FLUID token) separately
Tier: T2 (20% per-protocol cap, 50% T2 total cap per RiskPolicy v1.0)
ADR required: Document private-key incident (infrastructure vs. contract logic distinction)
```

### S23: Pendle PT Rolling Adapter (`spa_core/adapters/pendle_pt_rolling.py`)

```
API: GET https://api-v2.pendle.finance/core/v1/1/markets (Ethereum)
Filter: underlyingAsset in WHITELIST; TVL > $5M; daysToMaturity in [14, 180]
Initial WHITELIST: ["sUSDe", "sUSDS"] (Ethena + Sky only)
Strategy: select max(fixed_apy) from eligible; hold to maturity; roll when <14d remaining
Entry price locking: store fixed_apy at purchase time in trade record (not live rate)
RiskPolicy note: PT is principal-protected at maturity — zero APY variance for locked tranche
ADR required: explicitly confirm PT ≠ YT; PT strategy outside ADR-021 scope
Tier: T2-FIXED (new sub-tier; recommend defining in ADR)
Expanded whitelist (future ADR): PT-apxUSD, PT-USDai (require separate approval per underlying)
```

### S24: f(x) Stability Pool Adapter (`spa_core/adapters/fx_protocol.py`)

```
DeFiLlama: filter project="fx-protocol", pool contains "Stability Pool V2.0"
On-chain: fx.aladdin.club Stability Pool contract — direct USDC deposit supported
APY composition: wstETH staking yield + xPOSITION opening fees + minor FXN emissions
Peg monitoring: check fxUSD/USDC on Curve pool; trigger withdrawal if price < $0.99
Max allocation: 10% of portfolio (conservative given novel ETH-backed mechanism)
Tier: T2 (20% per-protocol cap applies)
ADR requirements before go-live:
  1. Obtain and verify all f(x) v2 audit reports (16 claimed, not publicly indexed — contact AladdinDAO)
  2. Document Stability Pool exhaustion scenario and probability threshold
  3. Define automated drawdown trigger for fxUSD depeg
  4. Confirm peg monitoring integration in cycle_runner
```

---

## SECURITY FRAMEWORK FOR NEW ADAPTERS

Based on 2025–2026 exploit landscape, the following must be verified in any new adapter ADR:

1. **Oracle architecture review required** (Aave Mar 2026: $27.78M from CAPO config error; Moonwell Feb 2026: $1.78M cbETH oracle)
2. **Supply chain / CI-CD audit required** for any protocol handling >$50M (Resolv Labs Mar 2026: $25M via CI/CD)
3. **Private key infrastructure verification** (Fluid May 2026: $215K; Bybit 2025: $1.436B)
4. **No cross-chain bridges to Solana** without dedicated bridge-risk ADR (LayerZero Apr 2026: $290M)
5. **DPRK social engineering protocols:** any protocol core team with known external contractor exposure should be flagged
6. **TVL floor $5M** remains critical risk filter — exploits disproportionately target low-TVL pools

---

## SOURCES

### Live Data (June 21, 2026)

- DeFiLlama Yields API: `https://yields.llama.fi/pools`
- DeFiLlama Protocol APIs: `https://api.llama.fi/protocol/<name>`
- Pendle Finance API: `https://api-v2.pendle.finance/core/v1/1/markets` (Ethereum mainnet)
- Kamino Finance live app: `https://kamino.finance/borrow`, `https://kamino.finance/earn/lend`, `https://kamino.finance/security`
- f(x) Protocol: `https://fx.aladdin.club`
- Aave Governance ARFC (sGHO): `https://governance.aave.com/t/arfc-sgho-launch-configuration/24346`
- Rekt.news leaderboard (301 entries): `https://rekt.news/leaderboard/`
- Chainalysis 2026 Crypto Crime Report: `https://www.chainalysis.com/blog/crypto-hacking-stolen-funds-2026/`

### Protocol Documentation

- Ethena: `https://docs.ethena.fi/resources/audits`, `https://docs.ethena.fi/solution-design/staking-usde`
- Fluid: `https://defillama.com/protocol/fluid`, `https://fluid.instadapp.io/`
- Pendle: `https://app.pendle.finance`, `https://api-v2.pendle.finance`
- Usual Money: `https://docs.usual.money/`
- f(x) Protocol: `https://defillama.com/protocol/fx-protocol`
- Morpho: `https://docs.morpho.org/get-started/resources/audits/`, `https://morpho.org/blog/morpho-is-now-powering-usdc-lending-on-coinbase`
- Extra Finance: `https://docs.extrafi.io`
- DeFiLlama Hacks DB: `https://defillama.com/hacks`

### Incident Reports

- Drift Protocol ($285M): `https://rekt.news/drift-protocol-rekt`
- KelpDAO ($290M): `https://rekt.news/kelpdao-rekt`
- Aave V3 oracle ($27.78M): `https://rekt.news/aave-rekt`
- Resolv Labs ($25M): `https://rekt.news/resolv-labs-rekt`
- Balancer V2 ($128M): `https://rekt.news/balancer-rekt2`
- Moonwell (Nov 2025): `https://www.cryptotimes.io/2025/11/04/moonwell-hit-by-1m-oracle-exploit-on-base-and-optimism/`
- Moonwell (Feb 2026): `https://www.theblock.co/post/390302/defi-lending-protocol-moonwell-hit-with-1-8-million-bad-debt-after-oracle-misconfiguration`
- Seamless shutdown: `https://phemex.com/news/article/seamless-protocol-to-shut-down-users-must-withdraw-by-june-30-71532`

### Cross-Reference

- eco.com — Best USDC/USDT Yield 2026 (June 16, 2026)
- CoinGecko — APYX/Pendle integration (May 11, 2026)
- Bitget — Pendle sUSDS $50M TVL (June 2026)
- Stablecoininsider.org — Pendle+Aave USDe integration guide
- Aave Governance Forum — PT-sUSDe-22OCT2026 onboarding, June 2026

---

*Report generated by SPA deep-research workflow. All APY data from live API calls June 21, 2026.*
*Verify all rates before implementation — DeFi yields change daily.*
*Next update recommended: July 21, 2026 (30-day cadence) or upon any risk event affecting listed protocols.*
