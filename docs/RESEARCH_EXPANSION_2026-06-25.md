# SPA — Research Expansion: BTC / ETH deposits + product roadmap (2026-06-25)

> **Scope.** Internet research to answer four questions for SPA (deterministic, stdlib-only
> stablecoin-yield optimizer, paper trading, $100k virtual book, moving toward managing external
> AUM after a 30-day honest track record). Each section: concrete current numbers + sources +
> a recommendation grounded in the existing architecture (`CLAUDE.md`, `docs/ARCHITECTURE_TIER1.md`,
> `docs/STRATEGY_LAB.md`).
>
> **How findings map to SPA.** SPA already separates *think* (read-only adapters / Strategy Lab,
> LLM-forbidden RiskPolicy) from *act* (execution dry-run, custody-gated). New asset classes enter
> as **read-only adapters + advisory strategies (`IS_ADVISORY=True`)** and as **Strategy-Lab
> candidates** measured against the RWA floor — never as live positions before canary + custody.
>
> **Numbers are point-in-time (Apr–May 2026 snapshots from cited sources). Treat APYs as live feeds,
> never hardcode — same rule the Strategy Lab already enforces.**

---

## TL;DR — top recommendations

| # | Recommendation | Risk tier | Effort | Verdict |
|---|---|---|---|---|
| 1 | **BTC deposit = tBTC/cbBTC *lending* on Aave/Morpho only** (read-only adapter + advisory strategy + Strategy-Lab BTC sleeve). No wrapped-BTC price exposure beyond what the depositor chose. | T2 | Quick win | **DO** |
| 2 | **ETH deposit = stETH/rETH staking, hedged (Variant N style) for the stable mandate; pure LST as an ISOLATED directional sleeve.** | T2 (LST) / isolated (directional) | Medium | **DO, gated** |
| 3 | **Avoid LRT restaking (eETH/ezETH) as a core building block.** Our own Lab already kills it; real ezETH depeg (-79% in <1h, ~$60M liquidations) corroborates. Keep advisory-only. | — | — | **AVOID for core** |
| 4 | **Add tokenized T-bills (RWA) as the real risk-free floor / cash sleeve** (BUIDL/USYC/BENJI/USDY/OUSG). Already partly modelled as `rwa_floor`; wire a real feed. | T1 | Quick win | **DO** |
| 5 | **Keep / formalize the delta-neutral funding sleeve (sUSDe)** already present (`s71_delta_neutral`, `delta_neutral_susde.py`) but cap it and add a negative-funding kill. | T2 | Quick win | **DO (capped)** |
| 6 | **Product/trust features:** proof-of-reserves / verifiable NAV (have `nav_proof`), risk-tiered packages (have), auto-compound accrual (have), curated-vault framing. Borrow the *neobank* UX framing. | — | Medium | **DO (positioning)** |
| 7 | **Regulatory posture:** stay "research, not raising capital"; pre-build MPC 2-of-3 custody + external audit + proof-of-reserves as the canary→live gate. | — | Bigger bet | **PLAN** |

---

## 1. BTC yield ("вклад BTC") — how to add Bitcoin safely

### Landscape & current numbers

**Wrapped-BTC lending (the conservative path).** Aave V3 and Morpho dominate wrapped-BTC lending;
Aave accepts WBTC/cbBTC as collateral, Morpho runs curated WBTC vaults. **Supply APYs on the
*safe* (lending) side are very low** — BTC is borrowed little, so suppliers earn little:
- Morpho Gauntlet WBTC Core ≈ **1.20% APY**, ~$4.4M TVL
- Aave Arbitrum WBTC ≈ **0.05% APY**, ~$156M TVL
- Aave Base cbBTC ≈ **0.02% APY**, ~$129M TVL
(source: eco.com BTCfi 2026; DeFiLlama). Utilization is low (WBTC 6.3%, cbBTC 3.5%, tBTC 2.3% on Aave V3).

**Wrapped-BTC custody/trust models (the key risk axis):**
- **WBTC** — federated trust; after the 2024 BitGo → BiT Global (Justin-Sun-linked) restructure,
  2-of-3 keys moved to Hong Kong/Singapore custody. Coinbase delisted WBTC; "some protocols have
  been quietly reducing exposure." Inherits custodian/sanction/key-management risk.
- **cbBTC** — single US-regulated public company (Coinbase). No DAO, no key-sharding, audit surface
  is *regulatory* (Coinbase filings), not cryptographic.
- **tBTC** (Threshold) — **decentralized**, threshold-ECDSA signer group, no single party can move
  reserves, permissionless mint/redeem. ~$481M DeFi TVL Q1 2026, the only decentralized wrapper with
  borrow enabled on Aave V3; leads 6 of 8 liquidity-depth metrics.

**BTC LSTs / restaking (the higher-yield, higher-risk path).** Lombard **LBTC** (Bitcoin liquid
staking on **Babylon**): >$1.5B TVL, 70+ DeFi integrations (incl. Aave/Morpho). But **native yield
is tiny** — Babylon rewards ≈ **0.4% APY**, LBTC 14-day trailing ≈ **0.5–1%**. "Extra" yield comes
from *restaking* LBTC into Symbiotic/Karak (points/airdrop-driven, not contractual) — i.e. the BTC
analogue of the ETH-LRT risk we already reject. Withdrawals to native BTC take 7 days.

### Risks
- **Bridge/custody risk of the wrapper** (the dominant BTC-DeFi risk): WBTC custodian/governance,
  cbBTC single-entity, LBTC adds Babylon staking + bridge layers.
- **Depeg risk** of the wrapper vs spot BTC in stress.
- **Smart-contract risk** on the lending venue.
- **Yield-vs-risk mismatch:** safe BTC lending pays ~0–1.2%; anything paying meaningfully more is
  taking restaking/points/leverage risk.

### Recommendation for SPA
- **Build a read-only BTC adapter** (`spa_core/adapters/`) feeding **tBTC + cbBTC lending APY/TVL
  from DeFiLlama** (same pattern as existing adapters; APY-units normalization per our known gotcha).
  Prefer **tBTC** (decentralized, no single-custodian SPOF) and **cbBTC** (regulated) over WBTC.
  Apply the existing RiskPolicy gates: TVL ≥ $5M, smart-contract whitelist.
- **Add a BTC sleeve to the Strategy Lab** (a `Strategy` subclass like the engine wrappers): a
  *BTC-lending* book and, separately, a *hedged BTC-carry* candidate (long wrapped BTC + short
  BTC-perp), so we measure net APY / maxDD / β / beats-floor on equal footing — exactly the harness
  pattern in `STRATEGY_LAB.md`. Kill conditions: wrapper depeg > Y%, custodian/governance red flag.
- **Tier:** BTC lending = **T2**, advisory (`IS_ADVISORY=True`) until canary. **Reject** LBTC-restaking
  as a core building block (same logic as ETH-LRT below); allow advisory tracking only.
- **AVOID:** WBTC as primary collateral (governance/custody overhang), leverage looping on BTC,
  any "BTC yield > a few %" that is really points/airdrop farming.
- **Honest UX:** a "BTC deposit" in SPA should be framed as *"hold BTC exposure (your choice) +
  earn the lending floor on a decentralized wrapper"* — not as a high-yield product. The yield is
  low by design; the value is safety + composability.

---

## 2. ETH yield ("вклад ETH")

### Landscape & current numbers

**Plain ETH staking (LSTs) — the conservative path:**
- **Lido stETH** ≈ **2.5–2.6% APY** (10% fee).
- **Rocket Pool rETH** ≈ **2.2–3.5% APY** depending on methodology.
- ETH consensus base rate ≈ **2.84%**. (source: spotedcrypto, DeFiLlama, pistachio.fi)

**Restaking / LRTs — higher yield, higher risk:**
- eETH (ether.fi) dominates LRTs (~65% share); ezETH (Renzo) is L2-heavy.
- Stacked yield (ETH staking + AVS rewards + points) can be advertised as **10–15%+**, but a large
  share is **points/expected-airdrop value, not contractual yield**.

**LRT depeg history (corroborates our Lab finding):**
- **Renzo ezETH, 24 Apr 2024:** ezETH fell as low as **~$700 (−79% in under an hour)**, triggering a
  **liquidation cascade** — ~$56–60M+ liquidated across DeFi: Gearbox ~$33M (115 users, up to 10x
  leverage), Morpho ~$23M (146 users). Root cause: withdrawals were disabled, so the only exit was to
  **sell ezETH** into thin liquidity → feedback loop. (dlnews, protos, cryptoslate)
- Analysts: a DEX-pool imbalance or an EigenLayer upgrade could re-trigger LRT depegs at scale.

**Our own corroboration (Strategy Lab, real 2024-06-05 → 2026-06-24, 750-day window):**
| Strategy | Net APY % | MaxDD % | Sharpe | β(ETH) | Beats floor |
|---|---|---|---|---|---|
| variant_n (LRT + short ETH-perp hedge) | −0.84 | 10.79 | −0.04 | −0.02 | ❌ killed 2024-08-09 (LRT depeg 2.89%) |
| variant_d (pure LRT) | −15.42 | 30.05 | −1.03 | ~0 | ❌ killed 2024-08-05 (drawdown 30%) |
| engine_a/b/c (stable) | 4.60 / 8.33 / 8.87 | 0 | — | ~0 | ✅ |
| rwa_floor | 4.60 | 0 | — | 0 | benchmark |

So **both restaking candidates hit kill-switches in the real Aug-2024 ETH crash and fail to beat
the stable engines / RWA floor.** The external ezETH/Apr-2024 evidence is the same failure mode.

### Neutral (hedged) vs directional tradeoff
- **Neutral (β≈0, Variant N):** LST/LRT spot + short ETH-perp. Income = staking/restaking yield +
  points ± funding; price hedged out. Residual risk = **LST/LRT-vs-ETH depeg** and **negative
  funding**. This is the Ethena/basis structure (see §3). For LSTs (stETH/rETH) the depeg residual
  is far smaller than for LRTs.
- **Directional (β≈1, Variant D):** pure LST, full ETH price exposure. Only acceptable as an
  **isolated sleeve outside the stablecoin mandate** with an explicit drawdown kill.

### Recommendation for SPA
- **For the stable mandate:** offer ETH yield as **stETH/rETH staking, *hedged* (Variant-N style),
  using LSTs not LRTs.** Lower depeg tail than LRTs; ~2.5–3.5% base. Keep the existing Variant-N
  kill conditions (funding < X for N hours; depeg > Y%). Tier **T2**, advisory until canary.
- **For an ETH "directional deposit":** an **isolated, opt-in, clearly-labelled sleeve** (Variant D)
  outside the $100k stable book, with the drawdown kill — never commingled with go-live track equity.
- **AVOID as core:** eETH/ezETH and any restaking-points yield. Keep them **advisory-only**
  (`IS_ADVISORY=True`) for monitoring; do not let them earn live go-live equity. Our Lab is the
  receipt that this is the right call — keep it running and cite it publicly as a trust signal.
- **Architecture fit:** ETH staking/LST data already flows through the Strategy-Lab data layer
  (DeFiLlama coins for ETH/LST prices, Binance/Bybit median funding). Adding a stETH/rETH *staking*
  candidate is a new `Strategy` subclass + one config block — the harness does not change.

---

## 3. What else to add — competitive 2026 DeFi-yield product landscape

### A. RWA / tokenized T-bills (highest-priority addition)
- Tokenized US-Treasury market ≈ **$15.2B** across 76 products, ~58.7k holders, **7-day APY ≈ 3.36%**
  (May 2026); RWA-on-chain total crossed **$20B**. Leaders by AUM: **Circle USYC ($2.9B), BlackRock
  BUIDL ($2.6B), Ondo USDY ($2.1B), Franklin BENJI ($2.05B), Centrifuge JTRSY ($1.24B)**.
  Yields ~**3–5%**, daily redemptions, composable as collateral. (rwa.xyz, eco.com, financefeeds)
- **Fit:** SPA already has `rwa_floor` (4.5–4.6% benchmark) and an S74 RWA strategy. **Wire a real
  tokenized-T-bill APY feed** (BUIDL/USYC/USDY) so the "risk-free floor" is a *live* number, not a
  constant — and so a real **cash/RWA sleeve** can hold yield with near-zero vol. **Tier T1, quick win.**

### B. Delta-neutral funding (already partly built — formalize + cap)
- **Ethena sUSDe**: long staked ETH/LST + short ETH-perp; funding (10–13%) + staking (3–4%) → sUSDe
  7-day ≈ **9.4%**, 90-day ≈ **11.8%** (Apr 2026), >20% in high-funding regimes. Delta-neutral funds
  posted positive returns *every month of 2025* (0.43–1.42%/mo, maxDD 0.80%). **Risk:** sustained
  **negative funding** (Ethena pays), exchange counterparty risk, USDe depeg in stress, regulatory.
  The ~440bps premium over T-bills *is* the funding-vol/counterparty/cooldown compensation.
  (eco.com, docs.ethena.fi, coinmetrics)
- **Fit:** SPA already has `s71_delta_neutral`, `s72_basis_trade`, `delta_neutral_susde.py`, and an
  Ethena sUSDe adapter. **Quick win:** keep sUSDe as a **capped T2 sleeve** with an explicit
  **negative-funding kill** + per-protocol cap (existing 20% T2 cap). Don't chase the 20% spikes.

### C. Risk-tiered curated-vault structure (the 2026 standard)
- The market has converged on **curated vaults** (Morpho/Gauntlet/Bitwise; Kraken "DeFi Earn",
  Jan 2026, routes CEX deposits into curated on-chain vaults). Apollo bought up to 9% of Morpho;
  Bitwise runs ~6%-APY institutional Morpho vaults. Boards trust **Merkle-tree whitelists** that
  forbid moving funds outside pre-approved protocols. (rockawayx, defiprime, gauntlet.xyz)
- **Fit:** SPA's whitelisted-protocol RiskPolicy + risk-tiered packages (`PACKAGES.md`) *are* a
  curated-vault model. **Positioning win:** present SPA's products as **tiered curated strategies**
  (Conservative / Balanced / High-yield), each a config of whitelisted protocols + caps.

### D. Product/trust features the leaders ship
- **Auto-compounding** (have: `sleeve_yield.daily_yield` accrual).
- **Proof-of-reserves / verifiable NAV** — now baseline for institutional trust; Chainlink PoR
  becoming standard. SPA has `nav_proof` + hash-chain audit + run_manifest → **lean into this hard**;
  publish verifiable NAV as the headline trust signal.
- **Insurance / coverage** (Nexus-Mutual-style) — *not present*; a **bigger bet** to consider before
  external capital.
- **Multi-chain** (have: Aave on ETH/ARB/OP/POLY/BASE; tBTC/LBTC multi-chain).
- **"Invisible DeFi" / neobank UX** — abstract the chain away; deposit-button simplicity. SPA's
  family-fund cabinet + dashboard already aim here; borrow the framing.

### What separates the leaders
Curated/whitelisted risk, real-time PoR + reconciliation, institutional partnerships, and **honest,
risk-tiered products** — exactly the moat in `ARCHITECTURE_TIER1.md` (one operator, AI control-plane,
hard human gates on money movement). SPA's differentiator is the **auditable determinism + the Lab
that publishes when a strategy fails** — most products hide that.

---

## 4. Risk / regulatory context (toward external capital)

- **Custody is the gate, not the code.** 2026 institutional standard = **MPC + multisig** (key
  sharded, never reconstructed). `ARCHITECTURE_TIER1.md` already names this: full live requires
  **2-of-3 MPC custody + dual-control** (`ready_for_live=False` is honest). This is the #1 non-code
  blocker. (chainup, fireblocks, chain.link)
- **Proof-of-reserves + real-time reconciliation** have moved from nice-to-have to **baseline** for
  institutional trust — SPA's `nav_proof` / reconciliation / hash-chain audit are directly on-trend;
  finish + publish them.
- **Regulatory regimes hardening in 2026:** EU **MiCA** — CASP authorization hard deadline
  **1 Jul 2026** (regulated operations otherwise must cease); reserve segregation rules for
  ART/EMT. US — SEC/CFTC joint framework classifying assets into 5 categories; **yield-bearing
  tokens & DeFi yield products explicitly remain under scrutiny** (not auto-exempt). (weex,
  blockchain-council, tangem)
- **Implication for SPA's "not raising capital yet" stance:** **correct and protective.** Stay in
  research/paper, build the track record, and treat **custody + external audit + PoR + a legal
  wrapper/jurisdiction decision** as the gate *before* taking a dollar of external AUM. Yield-bearing
  + DeFi = exactly the products regulators are scrutinizing, so the conservative posture is an asset.

### Recommendation
- Keep the public stance: **research project, paper trading, not soliciting capital.**
- Pre-build (non-code, needs the operator): **MPC 2-of-3 custody, external smart-contract + ops
  audit, published proof-of-reserves/verifiable NAV, jurisdiction/legal-wrapper plan.** Make these
  the explicit **canary → full** promotion gate in the pipeline (which is `🔴 not built` today).
- Code-side now: finish **SSOT-manifest + fail-safe enforcement + canary stage** (already on the
  Tier-1 roadmap) so the moment custody/audit land, promotion is mechanical.

---

## Prioritized roadmap (quick wins → bigger bets)

**Quick wins (read-only adapters + Strategy-Lab candidates, advisory, this sprint):**
1. tBTC + cbBTC **lending** adapter (DeFiLlama feed) + BTC-lending Lab sleeve. *(BTC deposit, T2)*
2. Real tokenized-T-bill APY feed → live `rwa_floor` + RWA cash sleeve. *(T1)*
3. stETH/rETH **staking** Lab candidate (LST, not LRT), hedged Variant-N variant. *(ETH deposit, T2)*
4. Cap + negative-funding kill on the existing sUSDe delta-neutral sleeve. *(T2)*
5. Publish verifiable NAV / proof-of-reserves prominently (already built) as the trust headline.

**Medium:**
6. Isolated, opt-in directional ETH sleeve (Variant D) with drawdown kill, outside go-live track.
7. Risk-tiered "curated strategy" product framing (Conservative/Balanced/HY) + neobank-style UX.
8. Canary stage + SSOT-manifest + fail-safe enforcement (Tier-1 roadmap items).

**Bigger bets (pre-external-capital):**
9. MPC 2-of-3 custody + external audit + legal/jurisdiction wrapper.
10. Insurance/coverage layer; second host for HA (kill the single-host SPOF).

**Explicit AVOID list:**
- WBTC as primary BTC collateral (governance/custody overhang) — prefer tBTC/cbBTC.
- LRT restaking (eETH/ezETH) and BTC-restaking (LBTC restaked) as **core** building blocks — our Lab
  kills them and the ezETH depeg (-79%, ~$60M liquidations) is the real-world proof. Advisory-only.
- Any "BTC/ETH yield" that is really points/airdrop/leverage farming presented as base yield.
- Live deployment of any new asset class before canary + custody + audit.

---

## Sources

**BTC**
- BTCfi 2026 (yields/TVL): https://eco.com/support/en/articles/15220201-btcfi-2026-bitcoin-yield-lending-and-wrapped-btc-growth
- Wrapped BTC compared: https://eco.com/support/en/articles/15220191-wrapped-bitcoin-2026-cirbtc-wbtc-cbbtc-tbtc-fbtc-compared
- Lombard LBTC / Babylon: https://www.theblock.co/post/368511/bitcoin-staking-startup-lombard-launches-high-yield-lbtc-token-to-solana ; https://docs.lombard.finance/use/lbtc ; https://defillama.com/protocol/lombard
- WBTC/BitGo/BiT Global controversy: https://www.theblock.co/post/357379/justin-sun-connected-bit-global-drops-wbtc-related-legal-spat-with-coinbase ; https://decrypt.co/296540/bit-global-sues-coinbase-delisting-wrapped-bitcoin ; https://coinbureau.com/education/what-is-wrapped-bitcoin
- tBTC / Threshold Q1 2026: https://www.threshold.network/blog/threshold-q1-2026-benchmark-report ; https://defillama.com/protocol/tbtc

**ETH / restaking / LRT depeg**
- LST APYs: https://www.spotedcrypto.com/best-liquid-staking-protocols-2026-eth-sol-btc/ ; https://defillama.com/yields/pool/747c1d2a-c668-4682-b9f9-296708a3dd90 ; https://www.pistachio.fi/blog/ethereum-staking-yield
- Restaking / LRT yields & risk: https://www.dextools.io/tutorials/ethereum-yield-liquid-staking-restaking-2026 ; https://www.dlnews.com/articles/defi/renzo-boosts-share-of-the-lrt-market-with-layer-2-networks/
- ezETH depeg (Apr 2024): https://www.dlnews.com/articles/defi/renzos-ezeth-loses-ether-peg-drops-79-in-under-one-hour/ ; https://protos.com/depeg-of-3b-restaking-token-ezeth-causes-over-60m-in-defi-liquidations/ ; https://cryptoslate.com/renzos-ezeth-token-depeg-triggers-liquidations-across-defi-platforms/

**RWA / delta-neutral / products**
- Tokenized T-bills: https://app.rwa.xyz/treasuries ; https://eco.com/support/en/articles/15210582-top-tokenized-treasury-funds-2026-buidl-ousg-usdy-benji-compared ; https://financefeeds.com/tokenized-treasuries-explained-the-13-6b-institutional-guide/
- Ethena sUSDe delta-neutral: https://eco.com/support/en/articles/15254002-ethena-usde-and-susde-2026-delta-neutral-yield ; https://docs.ethena.fi/solution-overview/usde-overview ; https://www.tv-hub.org/guide/market-neutral-strategy-crypto
- DeFi vaults / neobanks / features: https://www.rockawayx.com/insights/defi-vaults-explained-2026-guide ; https://defiprime.com/defi-vaults-guide ; https://www.hhpty.com/the-future-of-vaults-neobanks-and-invisible-defi/ ; https://www.gauntlet.xyz/

**Regulatory / custody**
- MPC/multisig custody: https://www.chainup.com/blog/multi-sig-mpc-enterprise-crypto-custody-2026/ ; https://chain.link/article/institutional-digital-asset-custody ; https://www.fireblocks.com/blog/policy-changes-2025-outlook-2026
- MiCA / SEC-CFTC 2026: https://www.weex.com/news/detail/crypto-regulation-news-2026-sec-cftc-framework-genius-act-and-mica-2-coming-695837 ; https://www.blockchain-council.org/cryptocurrency/mica-sec-beyond-guide-us-vs-eu-crypto-regulation-traders-exchanges/

*Internal grounding: `CLAUDE.md`, `docs/ARCHITECTURE_TIER1.md`, `docs/STRATEGY_LAB.md`,
`spa_core/strategy_lab/`, `spa_core/strategies/` (s71/s72/s74, delta_neutral_susde.py).*
*Written 2026-06-25.*
