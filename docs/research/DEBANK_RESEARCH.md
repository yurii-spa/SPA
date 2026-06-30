# DeBank — Deep Research & DFB ("DeFi Board") Adaptation Map

> **Type:** READ-ONLY research deliverable (no code edits, no push).
> **Author scope:** Study DeBank in depth, map what is adaptable to SPA as a new sub-project
> (working name **DFB / "DeFi Board"**), grounded in SPA's *real* existing code
> (`spa_core/adapters/`, `spa_core/strategy_lab/rates_desk/`, FastAPI + Astro).
> **Date:** 2026-06-30. All external claims web-grounded + cited (Sources at end).
>
> **Bottom line up front:** DeBank is the market-leading EVM portfolio tracker — it shows you
> *what you hold and what it yields*. SPA already owns the harder, scarcer half of that picture:
> *the risk behind the yield, proven*. DFB is **not** "clone DeBank." DFB is the **risk-first,
> provable, no-custody analytics layer** SPA can ship from data it already produces — a public
> pool/yield explorer where every row carries its **A/B/C/D risk class, exit-liquidity-by-size,
> and a would-the-desk-refuse-it verdict**, with a "don't trust us, check us" proof hash. That is
> a surface no incumbent (DeBank, DefiLlama, Vaults.fyi, Exponential, APY.vision) publishes in full.

---

## 1. What DeBank IS

**DeBank** is the dominant **multi-chain DeFi portfolio tracker** for EVM ecosystems — often
described as the "Bloomberg terminal for a DeFi wallet." You paste in (or connect) a wallet
address and DeBank reads public on-chain state and renders, in one readable place: total
net worth, token holdings, per-protocol DeFi positions (lending, LP, vaults, staking
derivatives, accrued rewards), NFTs, and transaction history — across many chains at once.

- **Founded** 2018 in Shanghai by Tang Hongbo and Xu Yong; the original product was a clean
  dashboard reading public on-chain data to surface DeFi positions/balances/yield. [PitchBook;
  cryptoadventure]
- **Funding/scale:** raised ~$25M at a ~$200M valuation (Dec 2021, led by Sequoia China; with
  Coinbase Ventures, Circle, Crypto.com, Ledger, Dragonfly); ~$36M total raised. ~2.6M monthly
  visits (Jan 2026); effectively the EVM-portfolio-dashboard market leader. A 2025 ecosystem
  report cites ~3.2M "Hi!" social users (single-source). Small team (~14 employees). [Crunchbase;
  cryptoadventure]
- **Coverage:** advertised **200+ chains** and **800+ DeFi protocols** (Ethereum, BNB, Polygon,
  Arbitrum, Optimism, Avalanche, Solana, etc.), integrating Uniswap, Aave, Compound, MakerDAO,
  Yearn, and more. [cryptoadventure; DEXTools]
- **Evolution:** the dashboard is still the public face, but DeBank is now a *layered platform*:
  a wallet (**Rabby**), a Web3 social product (**Hi! / Stream / DeBank ID**), an **L2 chain**
  (DeBank Chain, OP Stack, mainnet live 2024-07-19), and a paid developer API (**DeBank Cloud**).
  [decrypt; blockchainreporter; cryptoadventure]

**Who uses it:** retail DeFi users monitoring their own wallets daily; on-chain researchers /
"smart-money" watchers inspecting *other* wallets; and (via Cloud) wallets/apps/fintechs that
need normalized multi-chain portfolio data.

**Honest limitations (per a 2026 review):** DeBank does **not** track centralized-exchange
balances, does **not** do tax accounting / filing-ready exports, and does **not** do cost-basis /
lot tracking. It answers *"what happened"* and *"what does this wallet hold"* — not *why*.
[cryptoadventure]

---

## 2. Full feature surface (grouped honestly)

### A) Portfolio tracking (the core)
- **Multi-chain net-worth** roll-up across 200+ chains in one view.
- **Token holdings** per chain with USD pricing.
- **Per-protocol DeFi positions** — value sits inside lending, LPs, vaults, staking derivatives,
  reward flows; DeBank's protocol view makes those readable (involved assets, current value,
  accrued rewards). [cryptoadventure; bitget]
- **NFT holdings**, **transaction history**, real-time balance refresh.
- **Wallet research** — inspect *any* address: its holdings, positions, activity.

### B) Market & pool analytics
- **Protocol explorer + rankings** (TVL, the protocols DeBank indexes).
- **Yield/APY discovery** at the protocol/pool level (what positions earn).
- **Liquidity-pool details** (the Cloud **Pool API** exposes pool-level data — see §5).
- Note: DeBank's *market* analytics are thinner than DefiLlama's; DeBank's edge is the
  *wallet-centric* lens, not a pure pool screener.

### C) Safety tools
- **Token approvals / revoke** — see and revoke risky ERC-20/NFT allowances (a standard wallet-
  hygiene feature in the DeBank/Rabby surface).
- **Gas tracker** / network info.
- *(DeBank's safety tooling is utility-grade — approvals + activity visibility — not a risk-rating
  engine. There is no per-pool A–F risk grade. This is precisely SPA's opening — see §6.)*

### D) Social (Web3 layer — off-identity for SPA)
- **DeBank ID** — a mintable on-chain Web3 identity tied to a wallet (custom username; mint fee
  ~$96), the basis of the social graph. [cryptoadventure; chainslab]
- **Hi!** — wallet-to-wallet encrypted on-chain messaging; "Attention-as-a-Service" (bidders pay
  to message high-value wallets; DeBank takes a fee). [chainslab; chaincatcher]
- **Stream** — a Twitter-like posting feed where accounts are linked to on-chain asset stats;
  follow wallets, feed, leaderboards, whale discovery. [chainslab; cryptoadventure]

### E) Data API (DeBank Cloud)
- A paid, consumption-metered developer API exposing the same data DeBank itself aggregates:
  **User / Token / Protocol / Pool / Chain / Wallet** APIs (see §3, §4).

---

## 3. Data model & how it works (conceptually)

DeBank's product is fundamentally a **multi-chain on-chain indexer + normalization layer**:

1. **Ingest public chain state** — for a given address, read balances and contract state across
   every supported chain. No custody, no private keys to read a portfolio (read-only address
   lookups); wallet-connect adds convenience, not custody.
2. **Protocol adapters** — per-protocol logic that maps raw contract storage into human positions
   (e.g. an Aave aToken balance → "supplied X USDC earning Y%"; a Uniswap LP NFT → pool share +
   fees + IL exposure). This is the same *adapter* pattern SPA uses (`spa_core/adapters/`), just
   pointed at *user balances* instead of *protocol-level APY/TVL*.
3. **Pricing** — token USD pricing layered on top to produce net-worth and position values.
4. **Normalization → API model objects** — the Cloud API exposes structured objects:
   **`PortfolioItemObject`** (a position), **`ActionObject`**, **`TransactionObject`**, plus
   token/protocol/pool/chain shapes. [docs.cloud.debank.com]
5. **Cloud API for developers** — consumption-metered ("Units Usage", pay-as-you-go units;
   Pro plan up to ~100 req/s). [docs.cloud.debank.com]

**Data sources that power it:** public chain RPC/node state (the on-chain truth), protocol
contract ABIs/adapters, and token price feeds. The differentiator vs. a raw node is the
*breadth of protocol adapters* + *normalization* — the unglamorous integration moat.

---

## 4. Business model

DeBank is **free at the front** (the dashboard) and monetizes around it:

- **DeBank Cloud / Data API** — selling refined, normalized on-chain data to third-party devs and
  institutional researchers. ~**$522k gross protocol revenue in Q4 2025**. Consumption-metered
  units; "fees based on Services purchased, not actual usage," non-cancellable terms.
  [DefiLlama: debank-cloud; docs.cloud.debank.com]
- **DeBank Chain (L2)** — recurring network transaction fees (350k+ unique wallets cited).
- **Web3 ID mint** — one-time ~$96 fee per identity (converts users → paying customers).
- **Hi! attention market** — bidders pay to message; DeBank takes a platform fee.
- **Wallet swap fees** (Rabby) + on-chain USDC/USDT top-up deposits.
- Mentioned/forward: tiered subscriptions for AI investment tools (personalized risk scoring,
  automated tax reporting). [businessmodelcanvas; cryptoadventure]

**What's monetizable for an SPA-style player:** the **Data API** is the clean, identity-aligned
monetization path (sell normalized + *risk-graded* data). The chain/social/wallet plays are
off-identity for SPA (they require custody, an own-chain, or a social product). The "AI risk
scoring" line item is exactly the space SPA's deterministic, refusal-first engine already occupies
— but *provably* and *without an LLM in the risk path*.

---

## 5. Liquidity-pool analytics — the state of the art (the owner's immediate interest)

DeBank's own pool surface is wallet-centric (your LP position's value + rewards) plus a Cloud
**Pool API**. The *richer* pool analytics live with peers; a good LP-analytics view, synthesized
across **DeBank, DefiLlama, Vaults.fyi, Exponential, APY.vision**, contains:

| Dimension | What a good LP view shows | Who does it well |
|---|---|---|
| **APY breakdown** | total = **base** (real: swap fees / lending interest / staking) + **reward** (token emissions/incentives) — *separated*, because reward APY is mercenary and decays | DefiLlama splits `apyBase` / `apyReward`; Vaults.fyi breaks base/reward/total per vault [DefiLlama yields; Vaults.fyi] |
| **TVL / pool depth** | pool size in USD; your share | DefiLlama, all |
| **Volume & fees** | 1d/7d USD volume → fee revenue (drives base APY) | DefiLlama, APY.vision |
| **Impermanent loss / divergence loss** | estimated IL from price divergence of paired assets; **net** LP gain = fees − IL | **APY.vision** (strongest IL+fee analytics); DefiLlama flags **IL risk** (yes/no) [APY.vision; DefiLlama] |
| **Pool composition** | the assets + weights; reserves; reward tokens; exposure type (single vs multi) | DefiLlama (`exposure`, `rewardTokens`), APY.vision |
| **Historical charts** | APY / TVL / fees over time; P&L over time | APY.vision (LP P&L reports), DefiLlama charts |
| **APY trend / outlook** | 1d/7d/30d APY change; 30d-mean; a prediction class + probability + σ (stddev) | DefiLlama yields (`apyPct1D/7D/30D`, `apyMean30d`, prediction `predictedClass`/probability, `sigma`) [DefiLlama yields] |
| **Risk indicators** | the scarce part — see below | **Exponential.fi** A–F |

**Exponential.fi — the closest precedent to SPA's identity.** Exponential publishes an
institutional-grade **A–F letter-grade risk rating** per pool, decomposed into **asset / protocol
/ chain / pool** risk (pool risk = leverage, complexity, dependency on external integrations),
built on a dependency graph ("Exponential DeFi Graph"). Backtested: A-rated protocols (Aave,
Yearn, Morpho) had **zero defaults / zero user losses** across major DeFi events; F-rated (Terra/
UST) had ~80% default rate. They present **yield alongside the risk grade** so you weigh one
against the other. [Exponential risk-rating; DL News]

> **The gap the whole field leaves open:** *nobody* publishes, per pool, a **conservative
> exit-liquidity-by-size schedule** ("if you need $1M / $5M / $10M OUT, what do you actually get
> back and how long does it take") **tied to validated contemporaneous depth**, alongside a
> **deterministic would-I-refuse-this verdict** and a **reproducible proof hash**. DefiLlama gives
> you a yes/no IL flag and a prediction; Exponential gives you a letter grade; Vaults.fyi gives a
> reputation score. SPA already *computes* the exit-by-size bound and the refusal verdict (§6).

---

## 6. What's ADAPTABLE to SPA — the key section

SPA's identity (from `CLAUDE.md` + the real code): **no-custody, READ-ONLY, refusal-first,
risk-honest** DeFi yield+risk desk in paper trading. What it *already* has, grounded in code:

- **35-adapter live APY/TVL feed** — `ADAPTER_REGISTRY` in `spa_core/adapters/__init__.py`
  (Aave/Compound/Morpho/Yearn/Euler/Maple/Fluid/Spark/Ethena/Pendle/Aerodrome/… across ETH +
  Arbitrum/Optimism/Polygon/Base L2s), all read-only via `defillama_feed.py`.
- **A/B/C/D + T1/T2/T3 risk taxonomy** — tier tags in the registry; RiskPolicy
  (`spa_core/risk/policy.py`) deterministic, **LLM-forbidden** (TVL ≥ $5M floor, per-protocol
  caps, APY 1–30% bounds, two-tier kill-switch).
- **The Rates Desk** — `spa_core/strategy_lab/rates_desk/`:
  - `exit_nav.py` — the flagship **liquidation-NAV-by-size** surface (per-ticket exit schedule
    $100k/$250k/$1M/$5M/$10M; conservative lower bound; fail-closed; **per-row `proof_hash`**).
  - `depth_at_size.py` — per-market **depth-at-size** feed (absorbable fraction at each ticket).
  - `rate_policy.py` — the **refusal-first gate** (tail-veto / depeg / oracle-stale / funding-flip
    / economics / size), `evaluate_entry` / `evaluate_hold`; composes *under* the global RiskPolicy.
  - `proof_chain.py` — tamper-evident **hash chain** (entries *and* refusals).
- **Public proof surfaces already shipped** — FastAPI routers (`spa_core/api/routers/`:
  `rates_desk.py`, `live.py`, `redteam.py`, `underwriting.py`, `competitive_watch.py`) and Astro
  pages (`landing/src/pages/`: `exit-nav.astro`, `refusals.astro`, `proof-of-reserves.astro`,
  `verify.astro`, `rates-desk.astro`, `methodology.astro`, `due-diligence.astro`).
- **A standalone verifier** (`scripts/verify_spa.py`, per MEMORY) — "don't trust us, check us."

### Map: BUILD / SHOULD-NOT / DIFFERENTIATOR

| DeBank capability | DFB verdict | Why |
|---|---|---|
| Multi-chain **pool/yield explorer** | ✅ **BUILD (Phase 1)** | SPA already produces the live APY/TVL feed; add the risk overlay it uniquely owns. On-identity. |
| **APY base/reward breakdown + TVL/volume/IL** | ✅ **BUILD** | DefiLlama feed already carries `apyBase`/`apyReward`/`ilRisk`/`exposure`; SPA just surfaces them honestly. |
| Per-pool **risk grade (A/B/C/D)** | ✅ **BUILD — the core** | SPA's tier taxonomy + RiskPolicy + refusal gate already produce this deterministically. This is *the* differentiator vs DefiLlama (no grade) and parity-plus vs Exponential (theirs is opaque; SPA's is reproducible). |
| Per-pool **exit-liquidity-by-size** | ✅ **BUILD — nobody else has it** | `exit_nav.py` / `depth_at_size.py` already compute the conservative bound. Generalize from the desk's *own* book to *any* followed market. |
| **"Would the desk refuse it?" verdict + proof hash** | ✅ **BUILD — flagship** | `rate_policy.evaluate_entry` + `proof_chain.py` already exist. "Don't trust us, check us" is SPA's whole brand. |
| **Watchlists / alerts** on pools (APY collapse, TVL drain, IL spike, refusal-state flip) | ✅ **BUILD (Phase 2/3)** | Deterministic, keyless; reuses `evaluate_hold` kill signals as alert triggers. |
| **Portfolio lens** (paste a read-only address → its positions, each risk-graded) | ◐ **BUILD LATER (read-only addr only)** | Read-only address lookup is on-identity (no custody). Needs per-protocol *balance* adapters (new work) + token pricing; bigger lift. |
| **Whale / smart-money / flow tracking** | ◐ **OPTIONAL LATER** | Possible read-only, but data-heavy; lower fit with SPA's risk-desk identity. Defer. |
| **Data API** (sell normalized + *risk-graded* pool data) | ◐ **LATER (owner infra)** | Strong identity-aligned monetization (risk-graded data is scarcer than raw data). Needs API-key infra, SLAs, billing — owner decision. |
| **Token approvals / revoke** | ❌ **DO NOT** | Requires a connected signing wallet → off SPA's no-custody, read-only identity. |
| **Own L2 chain (DeBank Chain)** | ❌ **DO NOT** | Massively off-identity; SPA is a measurement/underwriting desk, not infra. |
| **Social layer (ID / Hi! / Stream)** | ❌ **DO NOT** | Off-identity; attention-market + social graph are a different company. |
| **Wallet (Rabby) / swap fees / custody** | ❌ **DO NOT** | Custody/execution — explicitly forbidden by SPA's read-only, no-custody, paper-only stance. |

### SPA's differentiator (the one sentence)

> **DeBank (and DefiLlama) show you the yield. DFB shows you the RISK behind the yield —
> per pool, with its A/B/C/D class, its exit-liquidity-by-size, and a deterministic
> would-the-desk-refuse-it verdict, each row carrying a reproducible proof hash so you don't
> have to trust us — you can check us.**

This is *defensible* because (a) it's built from data SPA already produces, (b) the risk engine
is deterministic + LLM-free + fail-closed (auditable, unlike a black-box "AI risk score"), and
(c) the exit-by-size + refusal surfaces are things **no incumbent publishes**.

---

## 7. Concrete DFB feature recommendations (prioritized)

### Phase 1 — **The LP / yield risk-explorer dashboard** (buildable NOW, read-only / keyless)
*Scope: a public pool explorer where every row is risk-first. All data already flows from
`ADAPTER_REGISTRY` + `defillama_feed.py` + the rates-desk modules. New work is presentation + a
thin generalization layer, not new data sources.*

1. **Pool table** — one row per followed pool/market, columns:
   - protocol · chain · symbol · TVL
   - **APY breakdown**: base vs reward (separated — flag reward-heavy pools)
   - **Risk class A/B/C/D** (from tier taxonomy + RiskPolicy result)
   - **IL risk** flag + exposure type (from DeFiLlama feed)
   - **Exit-liquidity-by-size** mini-cell ("$1M/$5M/$10M out → net %, days") from
     `depth_at_size.py`
   - **Refusal verdict** badge: ✅ desk would enter / ⛔ desk refuses (+ reason code) from
     `rate_policy.evaluate_entry`
   - **proof_hash** link (per-row, from `proof_chain.py`)
2. **Pool detail page** — APY/TVL history, the full exit-NAV-by-size schedule, the refusal
   decomposition (the 5 structural haircuts), and the "reproduce" block (verify the hash yourself).
3. **Honest empty-state / fail-closed** — pools with thin/stale depth show a visible hole
   ("insufficient_contemporaneous_depth"), never a fabricated fill (already the `exit_nav` rule).
4. **Surface via existing infra** — new FastAPI router `dfb.py` reusing `_shared` + rates-desk
   readers; new Astro page `landing/src/pages/dfb.astro` (or `/board`) reusing the design system.

*Phase-1 honesty note:* this is a **screener of the markets SPA's adapters already follow** (~35
markets/L2s), not a 10,000-pool DefiLlama clone. The pitch is **depth + risk-truth on a curated
whitelist**, not breadth. Breadth can grow later by adding read-only DeFiLlama pools behind the
same risk overlay (keyless).

### Phase 2 — **Alerts & watchlists** (still keyless / deterministic)
- Per-pool alert rules driven by `evaluate_hold` kill signals: APY collapse, TVL drain, IL/peg
  spike, funding flip, **refusal-state flip** (a pool that *was* enter-able becoming refused).
- Delivery via SPA's existing channels; deterministic triggers, no LLM.

### Phase 3 — **Portfolio lens (read-only address)**
- Paste a read-only wallet address → DFB shows its positions, **each risk-graded by DFB's engine**
  ("DeBank tells you what you hold; DFB tells you how risky what you hold is, and whether the desk
  would hold it").
- **Needs new work:** per-protocol *balance* adapters (read user positions, not just protocol APY)
  + token pricing. Read-only address only — **no wallet-connect, no signing, no custody.**

### Later / owner-infra-gated
- **Public pool explorer at breadth** (ingest read-only DeFiLlama pools under the risk overlay).
- **DFB Data API** — sell *risk-graded* normalized pool data (the identity-aligned monetization).
  Requires owner infra: API-key/billing, SLAs. The product wedge: risk-graded data is scarcer and
  more defensible than raw data.
- **Whale/flow tracking** — optional, data-heavy, weakest identity fit. Defer.

### Buildable-now vs owner-infra (honest split)
- **Now, read-only/keyless:** Phase 1 (pool risk-explorer), Phase 2 (alerts) — *all from existing
  SPA data + modules.*
- **Needs new (still no-custody) code:** Phase 3 portfolio lens (balance adapters + pricing).
- **Needs owner infra / decision:** breadth ingestion at scale, the paid Data API (keys, billing,
  SLA), any wallet-connect (which DFB should **not** do for signing — read-only address only).

---

## Sources

- DeBank product/scale/history/limitations — CryptoAdventure "DeBank Review 2026"
  https://cryptoadventure.com/debank-review-2026-defi-portfolio-tracking-wallet-research-and-web3-social-features/
- DeBank homepage — https://debank.com/
- DeBank tutorial / chains+protocols — DEXTools
  https://www.dextools.io/tutorials/debank-defi-portfolio-tutorial-track-wallets-2026
- Why on-chain traders use DeBank — Bitget Wallet
  https://web3.bitget.com/crypto-news/why-every-serious-on-chain-trader-uses-debank-defi-portfolio-tracker-now
- DeBank Cloud API docs (endpoints, model objects, units) — https://docs.cloud.debank.com/en
- DeBank Cloud revenue/fees — DefiLlama https://defillama.com/protocol/debank-cloud
- DeBank business model — businessmodelcanvastemplate.com
  https://businessmodelcanvastemplate.com/blogs/how-it-works/debank-how-it-works
- DeBank funding/valuation/founders — PitchBook https://pitchbook.com/profiles/company/471828-07 ;
  Crunchbase https://www.crunchbase.com/organization/debank
- DeBank Chain (L2 on OP Stack) — Decrypt
  https://decrypt.co/152202/ethereum-defi-dashboard-debank-launches-layer-2-on-optimisms-op-stack ;
  BlockchainReporter https://blockchainreporter.net/debank-unveils-news-chain-merging-web3-social-and-asset-layers/
- DeBank social (ID/Hi!/Stream) — Chainslab
  https://research.chainslab.io/debank-shifting-the-social-paradigm-with-web3-integration ;
  ChainCatcher https://www.chaincatcher.com/en/article/2101163
- DefiLlama yields (APY base/reward, IL risk, predictions) — https://defillama.com/yields ;
  yield-server schema https://github.com/DefiLlama/yield-server
- Vaults.fyi (base/reward/total + reputation scores) — https://vaults.fyi/
- Exponential.fi A–F risk rating (asset/protocol/chain/pool) — https://exponential.fi/learn/risk-rating
  (redirects to https://yo.xyz/risk) ; whitepaper https://exponential.fi/whitepaper ;
  DL News https://www.dlnews.com/research/internal/exponentialfi-report-evaluating-risk-in-defi/
- APY.vision (IL + fee analytics, LP P&L) — https://blog.apy.vision/impermanent-loss-uniswap-v3/ ;
  Alchemy https://www.alchemy.com/dapps/apy-vision

### SPA grounding (real code referenced — not web)
- `spa_core/adapters/__init__.py` (`ADAPTER_REGISTRY`, ~35 read-only adapters, T1/T2/T3 tiers)
- `spa_core/strategy_lab/rates_desk/exit_nav.py` (liquidation-NAV-by-size + proof_hash)
- `spa_core/strategy_lab/rates_desk/depth_at_size.py` (per-market depth-at-size)
- `spa_core/strategy_lab/rates_desk/rate_policy.py` (refusal-first gate)
- `spa_core/strategy_lab/rates_desk/proof_chain.py` (tamper-evident hash chain)
- `spa_core/risk/policy.py` (deterministic RiskPolicy, LLM-forbidden)
- `spa_core/api/routers/` (rates_desk.py, live.py, redteam.py, underwriting.py)
- `landing/src/pages/` (exit-nav, refusals, proof-of-reserves, verify, methodology — existing
  public proof pages to extend)
