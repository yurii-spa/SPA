# Deep Research — DeFi Protocols May 2026

Отчёт по deep research, проведённому в chat (ID `10beb301-...`) 2026-05-02. Источники: DefiLlama, документация протоколов, audit reports, governance forums (Aave Governance, Sky Forum, Morpho Forum).

---

## 1. Provider stack для SPA операций

### Recommended stack

| Сервис | Тариф | Цена/мес | Назначение |
|---|---|---|---|
| **Alchemy** или **QuickNode** | Growth/Build | $49 | RPC node, archive data |
| **DefiLlama Pro** | API | $25 | TVL data, yield rankings, protocol metadata |
| **Zapper** | Pro | $30 | Portfolio aggregation, position tracking |
| **Tenderly** | Free / Developer | $0–50 | Tx simulation, monitoring alerts |
| **Koinly** | Pro | $9–15 | Tax accounting, cost basis tracking |
| **Total** | | **$113–169/мес** | |

Baseline: **~$110–125/мес.**

### Альтернативы (рассмотрены, не выбраны)

- **Infura** — RPC, $50/мес. Equivalent Alchemy, но менее богатые archive features.
- **Etherscan API Pro** — $50/мес. Покрыт Alchemy.
- **Dune** — $399/мес для team. Overkill для retail/SMB размеров portfolio.
- **Chainalysis Reactor** — enterprise pricing. Out of scope.

---

## 2. Daily / Weekly / Monthly monitoring signals

### Daily

- **TVL deltas** для каждого whitelist protocol — DefiLlama API.
- **APY deltas** — DefiLlama Yields + protocol-native frontends.
- **Oracle freshness** для критических pairs (USDC/USD, USDS/USD, sUSDe/USD) — Chainlink + alternative oracles (Pyth, Redstone).
- **Governance proposal monitoring** — Tally + Snapshot для Aave, Sky, Morpho.

### Weekly

- **Tracking error** vs ожидаемый APY (paper trading metric).
- **Effective underlying concentration** (для yvUSDC и Morpho meta-vaults).
- **Operational cost rolling 30-day** в bps от capital.
- **Gas costs aggregate** + bridge usage report.

### Monthly

- **Whitelist re-validation** — каждый protocol проходит full criteria check (TVL ≥$300M, audit status, оracle independence).
- **Tier 2 rotation review** — Pendle PT maturity calendar для next 60 дней.
- **Sky/Morpho/Yearn governance changes** retrospective.

---

## 3. Tier 1 allocation analysis (v0.4)

Two scenarios предложено в research:

### Scenario A (Conservative within Aggressive)

| Protocol | Allocation T1 |
|---|---|
| Aave V3 USDC | 30% |
| Sky sUSDS | 35% |
| Morpho Steakhouse | 25% |
| Compound V3 USDC | 10% |

### Scenario B (Yield-tilted)

| Protocol | Allocation T1 |
|---|---|
| Aave V3 USDC | 35% |
| Sky sUSDS | 40% |
| Morpho Steakhouse | 25% |
| Compound V3 USDC | 0% |

### Recommended (eventually adopted в v0.4)

Гибрид с Aave 25%, Morpho 15%, Compound 10%, Sky 10% (Sky консервативно из-за GSM Pause Delay caveat). Total T1 = 60% working capital.

---

## 4. Morpho immutable core caveat

**Critical observation:** Morpho Blue ядро (markets) — immutable. Но MetaMorpho vaults — managed.

- **Increasing caps** на vault — **timelocked (24h)**.
- **Decreasing caps** на vault — **NOT timelocked** — instant execution.

Что это значит:

- Curator (Steakhouse, Gauntlet, Block Analitica) может моментально снять капитал из markets через decrease cap.
- Это **feature**, не bug — позволяет быстро ответить на crisis.
- Но это означает: если curator решит, что один из markets compromised, наш capital может быть rebalanced **без нашего согласия**.

**Mitigation:**

- Whitelist только три проверенных curator (Steakhouse Financial, Gauntlet, Block Analitica).
- Monitor curator vault metadata daily.
- При curator change announcement (через Morpho governance) — exit position до подтверждения.

---

## 5. Oracle concentration risk

### Chainlink dominance

Среди whitelist v0.4.5:

- Aave V3: **Chainlink** primary
- Compound V3: **Chainlink** primary
- Morpho Blue: **Chainlink** для большинства markets
- Yearn V3 yvUSDC: наследует от underlying (Chainlink)
- Sky sUSDS: внутренний oracle (no external dependency)

**Conclusion:** ~80%+ working capital зависит от Chainlink price feeds.

### Alternative oracles ecosystem

- **Pyth** — push-based, низкая latency. Используется на Solana primarily, expansion на EVM.
- **Redstone** — modular oracle, off-chain by default, on-chain on demand. Используется Morpho для некоторых markets.
- **Chronicle** — Sky/MakerDAO origin, используется для Sky internals.

### Risk scenarios

- **Chainlink price feed manipulation** (low probability, high impact): coordinated reporter compromise → wrong USDC price → потенциальная liquidation cascade.
- **Chainlink feed deprecation** (medium probability, low impact): отдельный feed может быть deprecated с migration period.

### Mitigation в whitelist v0.4.5

- При **stale price feed** alert (>30 min) — auto-pause new positions.
- При **price deviation >50 bps** между Chainlink и alternative source (Pyth или Redstone, если доступен) — manual review.

---

## 6. November 2025 Stream xUSD contagion

**Event:** ноябрь 2025, Stream xUSD (synthetic stablecoin от Stream Finance) potential exploit / governance compromise (точное определение event типа disputed).

**Impact на Morpho:**

- Permissionless Morpho markets с Stream xUSD как collateral or loan asset experienced bad debt.
- Несколько curator vaults, которые держали Stream xUSD exposure (не Steakhouse/Gauntlet/Block Analitica) — lost user funds.

**Why Steakhouse/Gauntlet/Block Analitica vaults were safe:**

- Conservative curator policy: только blue-chip stablecoins + ETH/wBTC collateral.
- Active risk management: regularly review market additions.

**Lesson для SPA:**

- Permissionless Morpho markets — НЕ Tier 1 candidate.
- Curator choice — critical risk dimension.
- Continuous curator vetting > one-time onboarding decision.

---

## 7. Open questions / future research

- **Pendle на L2** (Arbitrum/Base): TVL ramp, ожидаем $300M threshold для inclusion в whitelist.
- **Spark Lend** — после миграции Sky → Spark spinoff, нужен новый assessment.
- **Aladdin fxUSD** — новый stablecoin, ETH-backed, требуется ≥6 мес. operation.
- **Athena USDe risk** — Pendle PT-sUSDe expose нас на Ethena. Funding-rate scenario где negative funding > 30 дней — что происходит с PT pricing.

---

## Ссылки

- DefiLlama Yields: https://defillama.com/yields
- Aave Governance forum
- Sky Forum
- Morpho Forum + Documentation
- Yearn V3 documentation
- Pendle Documentation
- Trail of Bits audit repository
- ChainSecurity audit repository
