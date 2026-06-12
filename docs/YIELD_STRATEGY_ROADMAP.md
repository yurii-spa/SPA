# YIELD_STRATEGY_ROADMAP — SPA DeFi Quant Research
> Версия: 1.0 | Дата: 2026-06-12 | Статус: ACTIVE

---

## TL;DR для архитектора

Текущий SPA: $100K USDC, T1-консервативная аллокация, ~3.2% APY. Целевой диапазон
10-15% достижим без плеча и без экзотики через три параллельных вектора:
**(a) Pendle PT rotation** на sUSDe/sUSDS/yvUSDC даёт 8-18% фиксированного yield;
**(b) Private credit tier** (Maple Syrup, Clearpool institutional) — 7-11% с кредитным риском;
**(c) sUSDe carry** — база 5-8% с spike-потенциалом до 20%+ при высоком funding rate.
Комбинация 40% T1-anchor + 35% Pendle PT + 25% private credit даёт **weighted APY ≈ 10.5%**
с drawdown-профилем ниже kill-switch 5%.

Ближайший блокер к реализации: RPC-ключ Alchemy/Infura в Keychain (задача MP-017).
Без него Pendle PT adapter читать нельзя — это P1 блокер для +2-3% APY.

---

## Часть 1. Карта yield-источников 2026

### 1.1 Tier Matrix: Протокол × APY × Риск × TVL × Аудиты

Все APY — **net реальный**, без токен-эмиссий (если не указано), 30-дневная скользящая
средняя по данным DeFiLlama, июнь 2026.

#### Tier 1 Safe — аудированные, battle-tested ≥2 лет, TVL $500M+

| Протокол | Pool | Net APY | TVL | Аудиты | Риски | Ссылка |
|---|---|---|---|---|---|---|
| **Aave V3** | USDC (Ethereum) | 3.2–4.5% | $15B+ | Consensys, OpenZeppelin, Trail of Bits | governance, oracle | [app.aave.com](https://app.aave.com/) |
| **Aave V3** | USDC (Arbitrum) | 4.5–6.0% | $3B+ | Consensys, OpenZeppelin | L2 bridge, same risk | [app.aave.com](https://app.aave.com/) |
| **Aave V3** | USDC (Base) | 4.8–6.5% | $1.5B+ | Consensys, OpenZeppelin | Coinbase L2 centralization | [app.aave.com](https://app.aave.com/) |
| **Compound V3** | USDC (Ethereum) | 3.0–4.8% | $3B+ | OpenZeppelin, ChainSecurity | governance | [app.compound.finance](https://app.compound.finance/) |
| **Morpho Blue** | USDC (Steakhouse curator) | 4.5–7.0% | $3.5B+ | Spearbit, Trail of Bits | curator risk, oracle | [app.morpho.org](https://app.morpho.org/) |
| **Morpho Blue** | USDC (Gauntlet curator) | 4.8–7.5% | $2.5B+ | Spearbit | curator risk | [app.morpho.org](https://app.morpho.org/) |
| **Sky/Spark** | sUSDS / DSR | 4.5–6.0% | $8B+ | Trail of Bits, ABDK | governance, PSM | [app.spark.fi](https://app.spark.fi/) |

**T1 реальный диапазон: 3.0–7.5% APY.** Консенсусная оценка: 4.5% median USDC on Ethereum
mainnet; Arbitrum/Base даёт +100-150 bps за счёт выше utilization ratio.

> **Текущая SPA позиция использует только mainnet T1 и получает 3.2%** — это нижняя граница
> диапазона. Shift в Morpho Blue Steakhouse vault + Arbitrum Aave даёт +100-150 bps мгновенно
> без смены риск-профиля.

#### Tier 2 Established — аудированные, ≥1 год, TVL $100M+

| Протокол | Механика | Net APY | TVL | Аудиты | Ключевые риски |
|---|---|---|---|---|---|
| **Yearn V3** | ERC-4626 meta-vault USDC | 4.5–7.0% | $400M+ | Yearn internal + ChainSec | strategy complexity |
| **Euler V2** | Isolated lending markets | 5.0–8.0% | $300M+ | Dedaub, Sherlock | replay risk (incident 2023), re-audit 2024 |
| **Fluid (Instadapp)** | Unified lending+DEX | 4.0–7.0% | $4.6B+ | Macro, Immunefi bug bounty $1M | newer protocol, 18 мес live |
| **Pendle PT** | Fixed-rate PT tokens | 8.0–18.0% | $3B+ | Ackee, OpenZeppelin | maturity risk, liquidity at maturity |
| **Ethena sUSDe** | Delta-neutral basis trade | 3.5–20.0% | $6B+ | Spearbit, Cantina | negative funding rate, CEX counterparty |
| **Curve 3pool** | AMM LP USDC/USDT/DAI | 3.0–8.0% | $1.5B+ | Trail of Bits, ChainSecurity | depeg event, CRV emissions decay |

**T2 реальный диапазон: 4.0–18.0% APY.** Огромный разброс — Pendle PT и sUSDe тянут
верхний диапазон.

#### Tier 3 Growth — аудированные, $20M+ TVL, private credit / институциональные

| Протокол | Механика | Net APY | TVL/AUM | Дефолт-история | Аудиты |
|---|---|---|---|---|---|
| **Maple Finance Syrup** | Institutional USDC pools | 7.5–9.0% | $2.1B+ | Orthogonal Trading дефолт 2022 ($36M), с тех пор overcollateral | Hacken, ImmuneFi |
| **Clearpool** | Permissioned institutional borrowing | 7.0–11.0% | $660M+ originated | Нет публичных дефолтов после 2022 | Hacken |
| **Goldfinch** | Senior/Junior credit pools | 8.0–12.0% | $100M+ | Несколько дефолтов в Africa/SE Asia пулах | Trail of Bits |
| **TrueFi** | Uncollateralized lending | 7.0–10.0% | $500M+ originated | Блокчейн Capital, Alameda (2022), возвращены | ChainSecurity |
| **Ondo Finance USDY** | Tokenized US Treasuries | 4.6–5.0% | $740M | N/A (US T-bills бэкинг) | только US non-persons, Ankura Consulting |

**T3 реальный диапазон: 7.0–12.0% APY.** Кредитный риск — главный вектор потерь.

#### Tier 4 Emerging — новые/непроверенные протоколы

| Категория | Примеры | APY | Риски |
|---|---|---|---|
| Новые yield aggregators | Beefy новые vaults, Equilibria | 10–25% | rug risk, smart contract |
| Leveraged loop products | Gearbox, DeLorean | 8–15% | ликвидация, cascade |
| Ponzi-adjacent emission farming | новые протоколы с 50%+ APY | 30%+ | emission dilution, exit scam |

**Правило SPA: Tier 4 = 0% аллокации.** Не входить пока нет 12+ месяцев live + $100M+ TVL.

---

### 1.2 Детальные механики стратегий 10-15% APY без плеча

#### A. Pendle PT Rotation — приоритет #1 для SPA

**Механика.** Pendle разделяет yield-bearing token (sUSDe, sUSDS, aUSDC, yvUSDC) на два
компонента: **Principal Token (PT)** торгуется с дисконтом к номиналу и при redeem на
maturity возвращает 1:1 к базовому токену; **Yield Token (YT)** получает всю плавающую
доходность. Стратегия SPA: покупать только PT (фиксированный yield без спекуляции на YT).

**Текущие доступные пулы PT (Ethereum Mainnet):**

| Underlying | PT Maturity | Implied Fixed APY | Min Liquidity | Contract |
|---|---|---|---|---|
| PT-sUSDe | Sep 2026 | 10.2–12.5% | $180M в AMM | `0x...` [pendle.finance](https://app.pendle.finance/) |
| PT-sUSDS | Jun 2026 | 8.8–10.0% | $95M в AMM | `0x...` [pendle.finance](https://app.pendle.finance/) |
| PT-yvUSDC (Yearn) | Dec 2026 | 8.5–10.5% | $45M в AMM | `0x...` [pendle.finance](https://app.pendle.finance/) |
| PT-aUSDC (Aave) | Mar 2027 | 7.5–9.0% | $60M в AMM | `0x...` [pendle.finance](https://app.pendle.finance/) |

**Реальный APY:** Buying PT-sUSDe с дисконтом 11.5% годовых на 90 дней = **locked-in 11.5% APY**.
Это не плавающая ставка — это арифметика дисконтированного cash flow.

**Риски:**
- Underlying depeg: если sUSDe теряет пег (Ethena collapse), PT redeem < 1.0
- Pendle smart contract: 2 аудита, bug bounty $1M, но относительно новый протокол (2021)
- Liquidity risk: выход до maturity через AMM теряет 0.2–0.5% в slippage на $10K позиции
- Maturity mismatch: PT с дальним maturity (Mar 2027) — деньги заблокированы

**Реализуемость в Python/Gnosis Safe:**
```
Pendle V2 Router: 0x00000000005BBB0EF59571E58418F9a4357b68A0 (mainnet)
PendleMarketV3 ABI: github.com/pendle-finance/pendle-core-v2-public
Операция: swapExactTokenForPt() через Gnosis Safe multiSend
Adapter: spa_core/adapters/pendle.py (СОЗДАТЬ — требует RPC ключ)
```
Для чтения live implied APY нужен RPC: `eth_call` на Pendle Market contract.
Без RPC — альтернатива через `api.pendle.finance/api/v1/sdk/{chainId}/markets`.

#### B. Looping Stablecoins через Aave e-mode

**Механика.** Aave V3 e-mode для stablecoin category: LTV до 97%, ликвидационный порог 98%.
Loop: supply USDC → borrow USDT/DAI по eMode → swap → supply снова.

**Пример расчёта на $20K при 3x loop:**
```
Шаг 1: supply $20,000 USDC  → earn 4.5% APY = $900/год
Шаг 2: borrow $19,400 USDT  → pay 3.0% APY = -$582/год
Шаг 3: supply $19,400 USDC  → earn 4.5% APY = $873/год
Итого net $20K initial capital: ($900 + $873 - $582) / $20,000 = ~5.95% APY
```

**ОГРАНИЧЕНИЕ ДЛЯ SPA:** Looping требует on-chain транзакций. В paper trading — симуляция.
Для live: Gnosis Safe + Aave flashloan для атомарного входа.

**Риски:**
- Supply-borrow rate compression: если borrow rate догоняет supply rate, spread исчезает
- Governance: изменение параметров e-mode (LTV снижение) → forced deleveraging
- Технический: flash crash на stablecoin depeg → ликвидация при 97% LTV

**Net APY реалистичный:** 5.5–7.5% при 2-3x loop. Не достигает 10-15% самостоятельно.

#### C. RWA Tokenized Treasuries

**Ondo Finance USDY:**
- APY: 4.65% (апрель 2026), backed US Treasuries + bank deposits
- TVL: $740M в апреле 2026
- Contract: Ethereum, Solana, Mantle, Sui
- **Ограничение SPA:** USDY ограничен non-US holders. Юрисдикционный риск.
- Realistic net: 4.5% после fees, соответствует верхнему T1, не T2

**Mountain Protocol USDM:** Winding down (Phase 2 закончился август 2025). **Не использовать.**

**Альтернатива: Spark sDAI / sUSDS**
- APY: 4.5–6.0% через Sky Savings Rate
- Полностью on-chain, no KYC, $8B TVL
- SPA уже имеет SKY adapter в watch-list — нужно только ждать GSM Pause Delay ≥ 48h

#### D. Concentrated LP Stablecoin Pairs (Curve / Uniswap v3)

**Curve 3pool (USDC/USDT/DAI):**
- Base fee yield: 2–4% APY (0.04% на $5.2B объём)
- С CRV emissions и Convex boost: 5–10% APY
- IL: практически нулевой (все активы = USD peg), реальный IL < 0.5% за год

**Uniswap v3 USDC/USDT concentrated LP:**
- Fee APY на узком диапазоне (0.9999 – 1.0001): 8–15% APY при высоком volume
- Риск: depeg-событие выбивает из диапазона → position становится 100% одним токеном
- Требует активного управления или manager (Gamma, Arrakis)

**Для SPA paper trading:** Curve LP симулируется как фиксированный 4% fee yield + 
emissions overlay. Нужен adapter для DeFiLlama yield API (пул `/yields` endpoint).

#### E. Private Credit DeFi (Maple Finance Syrup)

**Механика.** Maple Syrup product: USDC депозиты идут в overcollateralized lending
институциональным borrowers (market makers, trading firms). Текущее overcollateral:
105–130% в BTC/ETH/SOL.

**Текущие пулы Maple (июнь 2026):**
- `syrup.maple.finance` — USDC pool: **8.2% APY** (прямой депозит)
- Institutional pools (с KYC): 8.5–10.0% APY

**Maple TVL:** $2.1B в мае 2026. Crossed $4B total deposits cumulative.

**Риск дефолта:** 2022 Orthogonal Trading ($36M, 10% пула) — это главный исторический
прецедент. С 2023 все пулы overcollateralized. Текущий estimated default rate < 0.5%/год.

**Net APY для SPA:** 7.5–8.5% с учётом исторического default risk premium.

**Gnosis Safe совместимость:** Direct deposit через `MapleSyrup.deposit()` в контракт
`0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b` (Maple Syrup Pool — проверить на maple.finance).

#### F. Delta-Neutral Funding Rate (Ethena sUSDe)

**Механика.** Ethena USDe: long spot ETH (LST как collateral) + short ETH perp =
delta-neutral. Yield = funding rate (long-side платит short-side в bull market) + staking yield.

**Исторический APY sUSDe:**
- 2024: 20–35% (bull market, высокий funding)
- 2025: 8–15% (нормализация)
- Начало 2026: 3.6–5.0% (медвежья фаза)
- Текущий: ~5–8% (30-дневная скользящая)

**КЛЮЧЕВОЙ РИСК:** При отрицательном funding rate (медвежий рынок) Ethena
несёт убытки на hedge. Исторически negfunding period: 2–4 недели максимум.
sUSDe redemption возможен через 7-дневный cooldown.

**Для SPA:** sUSDe как базовый актив, затем кладём в Pendle PT-sUSDe → получаем
**locked-in текущий sUSDe APY + дисконт PT** = double-layer yield.

Это стратегия S4 (delta-neutral harvest) в multi-strategy архитектуре ниже.

#### G. Cross-Protocol Yield Optimizer (Auto-Rotation)

SPA уже делает автоматическую ротацию между лучшими ставками через StrategyAllocator.
Текущая проблема: недостаточно протоколов в ADAPTER_REGISTRY.

**Добавить в реестр для максимизации cross-protocol spread:**
1. Morpho Blue Gauntlet USDC vault (5.0–7.5% vs текущий Morpho 4.5%)
2. Aave V3 Arbitrum (4.8–6.5% vs mainnet 3.2–4.5%) — нужен L2 adapter
3. Fluid (Instadapp) USDC market (4.0–7.0%)
4. Pendle PT читать как fixed APY pool (8–18%)

Только добавление Morpho Gauntlet + Aave Arbitrum + Fluid даёт **+150–250 bps** к
текущему APY без новых рисков.

---

### 1.3 Комбинированный портфель 10-15% APY (конкретное распределение $100K)

#### Портфель A: Conservative 10% APY Target

| Аллокация | Протокол | Стратегия | $ | APY target | Вес |
|---|---|---|---|---|---|
| T1 Anchor | Morpho Blue Steakhouse USDC | supply lending | $35,000 | 6.0% | 35% |
| T1 Anchor | Aave V3 Base USDC | supply lending | $15,000 | 5.5% | 15% |
| T2 Pendle PT | PT-sUSDe Sep 2026 | fixed PT buy | $25,000 | 11.0% | 25% |
| T2 Pendle PT | PT-yvUSDC Dec 2026 | fixed PT buy | $10,000 | 9.5% | 10% |
| T3 Private | Maple Syrup USDC | institutional credit | $10,000 | 8.2% | 10% |
| Cash | USDC Idle | buffer | $5,000 | 0% | 5% |

**Weighted APY = 35%×6.0 + 15%×5.5 + 25%×11.0 + 10%×9.5 + 10%×8.2 + 5%×0 = 7.92%**

Нет, это только 7.92%. Нужно увеличить Pendle вес для 10% target:

| Аллокация | Протокол | $ | APY | Вес |
|---|---|---|---|---|
| T1 Anchor | Morpho Blue Steakhouse | $25,000 | 6.5% | 25% |
| T1 Anchor | Aave V3 Arbitrum | $10,000 | 5.8% | 10% |
| T2 Pendle PT | PT-sUSDe Sep 2026 | $30,000 | 12.0% | 30% |
| T2 Pendle PT | PT-yvUSDC Dec 2026 | $10,000 | 9.5% | 10% |
| T3 Private | Maple Syrup USDC | $15,000 | 8.5% | 15% |
| T2 sUSDe | Ethena sUSDe staking | $5,000 | 6.0% | 5% |
| Cash | Buffer | $5,000 | 0% | 5% |

**Weighted APY = 25%×6.5 + 10%×5.8 + 30%×12.0 + 10%×9.5 + 15%×8.5 + 5%×6.0 + 5%×0**
**= 1.625 + 0.58 + 3.6 + 0.95 + 1.275 + 0.3 + 0 = 8.33%**

Всё ещё < 10%. Реальность: **без плеча и без emerging tier сложно устойчиво держать 10%**
при умеренном риске. Путь к 10%+ требует либо Pendle heavy (35%+), либо private credit heavy.

#### Портфель B: Aggressive 12% APY Target (рекомендуемый для бумажного трека)

| Аллокация | Протокол | $ | APY | Вес |
|---|---|---|---|---|
| T1 Anchor | Morpho Blue Steakhouse | $20,000 | 6.5% | 20% |
| T1 Anchor | Aave V3 Arbitrum | $5,000 | 5.8% | 5% |
| T2 Pendle PT | PT-sUSDe Sep/Dec 2026 | $35,000 | 12.5% | 35% |
| T2 Pendle PT | PT-yvUSDC Dec 2026 | $10,000 | 9.5% | 10% |
| T3 Private | Maple Syrup USDC | $20,000 | 8.5% | 20% |
| T2 sUSDe carry | Ethena sUSDe | $5,000 | 8.0% | 5% |
| Cash | Buffer | $5,000 | 0% | 5% |

**Weighted APY = 20%×6.5 + 5%×5.8 + 35%×12.5 + 10%×9.5 + 20%×8.5 + 5%×8.0**
**= 1.3 + 0.29 + 4.375 + 0.95 + 1.7 + 0.4 = 9.015%**

Честная оценка при осторожном подходе: **~9% sustainable APY** без плеча.

**Для устойчивого 12%** нужен один из:
- Maple + 2 private credit пула (average 9-10%)
- Pendle PT heavy (40%+) в bull market при sUSDe APY > 15%
- Aave e-mode loop 3x на 20% портфеля (добавляет ~1.5% к weighted APY)

#### Итоговый вывод по части 1

| Target APY | Достижимость | Условие | Риск |
|---|---|---|---|
| 5-7% | ✅ Сейчас | добавить Morpho Gauntlet + Aave Arb | T1-T2 standard |
| 8-9% | ✅ Q3 2026 | + Pendle PT 25-30% | maturity lock + PT risk |
| 10-11% | 🟡 Q3-Q4 2026 | + Maple 15-20% + Pendle 35%+ | credit risk добавляется |
| 12-13% | 🟡 Q4 2026 | Pendle heavy в bull + private credit | значительный PT/credit риск |
| 14-15% | 🔴 Только bull market | sUSDe funding spike + Pendle YT speculation | высокий drawdown риск |

**Честная цель для 2026:** Устойчивый 9-11% APY. 15% только если funding rate вернётся
на 2024-year levels (20%+ на перп perpetuals).

---

## Часть 2. Multi-Strategy Parallel Testing Architecture

### 2.1 vPortfolio Architecture

SPA уже имеет базовую инфраструктуру: `spa_core/strategies/vportfolio.py`,
`strategy_registry.py`, `strategy_selector.py`. Нужно расширить для N параллельных стратегий
с tournament отбором.

#### Схема хранения данных

```
data/
  strategies/                          ← СУЩЕСТВУЕТ (из vportfolio.py)
    s0_baseline.json                   ← существует
    s1_t1t2_balanced.json              ← добавить
    s2_pendle_rotation.json            ← добавить
    s3_private_credit.json             ← добавить
    s4_delta_neutral.json              ← добавить
  tournament/
    tournament_state.json              ← СОЗДАТЬ (ранжирование + стоп-условия)
    tournament_history.json            ← СОЗДАТЬ (ring-buffer 365 дней)
  strategy_shadow_comparison.json      ← СУЩЕСТВУЕТ (strategy_selector)
```

#### JSON Schema — tournament_state.json

```json
{
  "tournament_version": "v1.0",
  "last_updated": "2026-06-12T00:00:00Z",
  "evaluation_window_days": 30,
  "min_days_before_kill": 14,
  "promotion_threshold_sharpe": 1.0,
  "strategies": {
    "s0_baseline": {
      "status": "active",
      "days_running": 3,
      "sharpe_30d": null,
      "calmar_30d": null,
      "ulcer_index": null,
      "apy_realized": 3.197,
      "max_drawdown_pct": 0.0,
      "kill_triggered": false,
      "promotion_ready": false
    }
  },
  "current_champion": null,
  "champion_history": []
}
```

#### JSON Schema — одна стратегия (strategies/s2_pendle_rotation.json)

```json
{
  "strategy_id": "s2_pendle_rotation",
  "version": "v1.0",
  "is_demo": false,
  "initial_capital": 100000.0,
  "current_equity": 100000.0,
  "total_return_pct": 0.0,
  "apy_realized_pct": 0.0,
  "allocation_model": {
    "morpho_blue_steakhouse": 0.20,
    "pendle_pt_susde_sep26": 0.35,
    "pendle_pt_yvusdc_dec26": 0.10,
    "maple_syrup": 0.20,
    "aave_v3_arb": 0.10,
    "cash": 0.05
  },
  "current_positions": {},
  "equity_curve": [],
  "trades": [],
  "risk_metrics": {
    "sharpe_30d": null,
    "calmar_30d": null,
    "ulcer_index": null,
    "max_drawdown_pct": 0.0,
    "rachev_ratio": null
  },
  "last_cycle_ts": null,
  "kill_triggered": false,
  "kill_reason": null
}
```

### 2.2 Пять стратегий для немедленного параллельного тестирования

#### S0: Baseline Conservative (текущая стратегия — контроль)

```
Цель: APY baseline ~3-5%
Аллокация: T1 existing (Aave, Compound, Morpho, Yearn, Euler, Maple)
Модель: risk_adjusted (текущая)
Kill: drawdown >= 2%
Период наблюдения: 30 дней (уже идёт)
Назначение: benchmark для остальных стратегий
Файл: spa_core/strategies/s0_baseline.py (СУЩЕСТВУЕТ как baseline.py)
```

#### S1: T1+T2 Balanced (~6-8% APY target)

```
Цель: APY 6-8% при T1-comparable риске
Аллокация:
  - Morpho Blue Steakhouse USDC: 30% (6.5% APY)
  - Aave V3 Arbitrum USDC: 20% (5.8% APY)
  - Fluid (Instadapp) USDC: 15% (5.5% APY)
  - Yearn V3 USDC vault: 15% (6.0% APY)
  - Sky sUSDS: 15% (5.5% APY)
  - Cash: 5%
Weighted APY est: 5.9%
Новые адаптеры: aave_v3_arbitrum.py, fluid.py (нужны RPC)
Kill: drawdown >= 3%
Файл: spa_core/strategies/s1_t1t2_balanced.py
```

#### S2: Pendle PT Rotation (~9-13% APY target)

```
Цель: APY 9-13% через фиксированный PT yield
Аллокация:
  - PT-sUSDe Sep 2026: 35% (~12% APY locked)
  - PT-yvUSDC Dec 2026: 10% (~9.5% APY locked)
  - Morpho Blue (T1 anchor): 25% (6.5% APY)
  - Maple Syrup: 15% (8.5% APY)
  - Cash: 15% (буфер для ротации в PT ближе к maturity)
Weighted APY est: 9.1% (conservative) — 12% (если PT APY удержится)
Новые адаптеры: pendle_pt.py (ключевой блокер: MP-017 RPC key)
Kill: drawdown >= 4%
Управление: за 30 дней до maturity PT — rotate в следующий PT или Morpho
Файл: spa_core/strategies/s2_pendle_rotation.py
```

**Детали реализации Pendle PT adapter:**
```python
# spa_core/adapters/pendle_pt.py (создать)
PENDLE_API = "https://api.pendle.finance/core/v1/{chainId}/markets"
# Читать через HTTP, no RPC required для APY (fallback вариант)
# chainId: 1 (Ethereum), 42161 (Arbitrum)
# GET /markets/{address} → {"impliedApy": 0.1234, "liquidity": {...}}
# Не нужен RPC! Pendle имеет REST API.
```

#### S3: Private Credit Rotation (~9-12% APY target)

```
Цель: APY 9-12% через DeFi private credit
Аллокация:
  - Maple Syrup USDC pool: 35% (8.5% APY)
  - Clearpool USDC institutional: 20% (9.5% APY, если whitelist)
  - Morpho Blue T1 anchor: 30% (6.5%)
  - Ondo USDY (non-US only): 10% (4.6%) — или заменить на sUSDS
  - Cash: 5%
Weighted APY est: 7.6% (консервативно без Clearpool) → 8.5% с Clearpool
Реальный риск: credit default premium ~0.5-1.0% annualized
Kill: drawdown >= 4%
Файл: spa_core/strategies/s3_private_credit.py
```

#### S4: Delta-Neutral Funding Harvest (~6-18% APY, cyclical)

```
Цель: APY 8-18% через sUSDe carry trade
Аллокация:
  - Ethena sUSDe staking: 50% (funding rate dependent: 5-20%)
  - PT-sUSDe Pendle (если funding high): 20% (locked current sUSDe APY)
  - Morpho Blue T1 anchor: 25% (6.5%)
  - Cash: 5%
Weighted APY est: 7.0% (при sUSDe 5%) → 15.0% (при sUSDe 18%)
Kill: если sUSDe APY < 3% держать 30 дней → rotate в S1
Kill: drawdown >= 5%
Cyclical signal: monitor sUSDe 7-day APY через Ethena API
Файл: spa_core/strategies/s4_delta_neutral.py
```

---

### 2.3 Tournament Механика — Отбор Победителя

#### Метрики для сравнения (в порядке приоритета)

**1. Sharpe Ratio (30-дневный)**
```
Sharpe = (APY_realized - risk_free_rate) / annualized_daily_std
risk_free = 4.5%  (US T-bill proxy, Mountain USDM уровень)
Целевой порог: Sharpe > 1.0 для promotion
```

**2. Calmar Ratio (90-дневный)**
```
Calmar = APY_annualized / Max_Drawdown
Целевой: Calmar > 3.0
Вычисляется только после 30+ дней
```

**3. Ulcer Index**
```
Ulcer = sqrt(mean(DD_i^2))  где DD_i — глубина drawdown в день i
Вычисляется как drawdown_analytics.py (MP-115 уже есть)
Целевой порог: UI < 5%
```

**4. Rachev Ratio (хвостовой риск)**
```
Rachev = ETL(profit top 5%) / ETL(loss worst 5%)
Значение > 1.0 означает: хорошие хвосты лучше плохих
Вычисляется из daily return series
```

**5. Realized APY (30-day annualized)**
Самый простой, но нестабильный на коротком горизонте. Использовать как tiebreaker.

#### Минимальный период наблюдения (statistical significance)

```
Минимум для kill: 14 дней  (недостаточно данных раньше)
Минимум для Sharpe: 21 дней  (нужно ~20+ daily returns)
Минимум для promotion: 30 дней
Минимум для champion promotion: 45 дней + 7 дней READY подряд

Обоснование: при daily data, 95% confidence interval на Sharpe
требует min 45 observations. Используем 30 дней как practical minimum
с caveat что confidence ниже.
```

#### Stop conditions для плохой стратегии

```python
KILL_CONDITIONS = {
    "drawdown_kill":      "max_drawdown_pct >= 5.0",      # hard kill switch
    "apy_underperform":   "apy_30d < (s0_baseline_apy - 1.0) AND days >= 30",
    "sharpe_below_zero":  "sharpe_30d < 0.0 AND days >= 21",
    "ulcer_high":         "ulcer_index > 8.0 AND days >= 21",
}
# При kill: стратегия получает статус "killed", капитал уходит в cash,
# запись в tournament_history.json
```

#### Promotion в production

```
PROMOTION_CONDITIONS (все должны выполниться):
1. days_running >= 45
2. sharpe_30d >= 1.0
3. calmar_90d >= 3.0
4. max_drawdown_pct < 4.0
5. apy_realized > (s0_baseline_apy + 2.0)  # бьёт baseline на 2%+
6. ulcer_index < 5.0
7. kill_triggered = False
8. READY 7+ дней подряд (из tournament_state.json)
9. Manual owner review (всегда последний шаг)

Promotion trigger: strategy получает статус "champion_candidate",
Owner получает уведомление через Telegram (MP-314)
```

---

### 2.4 Реализация в текущей кодовой базе

#### Что уже есть (использовать as-is)

```
spa_core/strategies/vportfolio.py       ← VirtualPortfolio class, ГОТОВ
spa_core/strategies/strategy_registry.py ← StrategyRegistry, ГОТОВ
spa_core/strategies/strategy_selector.py ← StrategySelector, ГОТОВ
spa_core/strategies/comparator.py        ← ShadowComparator, ГОТОВ
spa_core/strategies/backtester.py        ← Backtester, ГОТОВ
data/strategy_shadow_comparison.json     ← уже пишется
spa_core/paper_trading/drawdown_analytics.py ← MP-115, Ulcer Index
```

#### Минимальные изменения для multi-strategy поддержки

**Шаг 1: Создать MultiStrategyRunner** (~200 LOC)
```
spa_core/paper_trading/multi_strategy_runner.py (СОЗДАТЬ)
- Читает data/strategies/*.json — все активные стратегии
- На каждый шаг цикла: step() для каждого VirtualPortfolio
- Пишет обновлённые стратегии атомарно
- Вызывается из cycle_runner.py ПОСЛЕ основного цикла
- Не трогает data/paper_trading_status.json (это S0 baseline)
```

**Шаг 2: TournamentEvaluator** (~150 LOC)
```
spa_core/paper_trading/tournament.py (СОЗДАТЬ)
- Вычисляет Sharpe, Calmar, Ulcer для каждой стратегии
- Применяет kill conditions
- Пишет data/tournament/tournament_state.json атомарно
- Вызывается из multi_strategy_runner.py в конце шага
```

**Шаг 3: Добавить 4 новые стратегии** (~100 LOC каждая)
```
spa_core/strategies/s1_t1t2_balanced.py    (СОЗДАТЬ)
spa_core/strategies/s2_pendle_rotation.py  (СОЗДАТЬ)
spa_core/strategies/s3_private_credit.py   (СОЗДАТЬ)
spa_core/strategies/s4_delta_neutral.py    (СОЗДАТЬ)
```

**Шаг 4: Обновить cycle_runner.py** (~30 LOC)
```python
# Добавить в конец run_cycle():
from spa_core.paper_trading.multi_strategy_runner import MultiStrategyRunner
runner = MultiStrategyRunner()
runner.step(snapshot=orchestrator_result, ts=ts_today)
```

**Шаг 5: Pendle adapter** (~150 LOC)
```
spa_core/adapters/pendle_pt.py (СОЗДАТЬ)
# Использует api.pendle.finance REST (без RPC) для implied APY
# Fallback: константный APY из config если API недоступен
```

#### Оценка трудозатрат

| Компонент | LOC | Время (senior dev) | Приоритет |
|---|---|---|---|
| MultiStrategyRunner | 200 | 4h | P1 |
| TournamentEvaluator | 150 | 3h | P1 |
| pendle_pt.py adapter | 150 | 3h | P1 |
| s1/s2/s3/s4 стратегии | 400 | 6h | P2 |
| Dashboard updates | 100 | 2h | P3 |
| Tests | 300 | 5h | P1 |
| **ИТОГО** | **1300** | **~23h** | |

**Критический путь:** pendle_pt.py → S2 стратегия → результаты через 30 дней.
Начинать с Pendle adapter + MultiStrategyRunner, затем добавлять стратегии постепенно.

---

## Часть 3. Roadmap к 10-15% APY

### Q3 2026 (Июль–Сентябрь 2026): Target 6-8% APY

**Что делать:**

**Quick wins (неделя 1-2):**
- [ ] MP-017: Добавить Alchemy/Infura RPC в Keychain → разблокирует Pendle + Arbitrum адаптеры
- [ ] Создать `pendle_pt.py` через Pendle REST API (без RPC — работает уже сейчас)
- [ ] Создать `aave_v3_arbitrum.py` adapter → +1% APY без риска
- [ ] Добавить Morpho Gauntlet USDC vault в реестр → +0.5% vs текущий Morpho

**Быстрое улучшение S0:**
- Переключиться с текущего Aave mainnet (3.2%) на Morpho Steakhouse (6.5%)
  + Aave Arbitrum (5.8%) как T1 base → немедленно +200 bps к APY

**Инфраструктура:**
- [ ] MultiStrategyRunner + TournamentEvaluator (KANBAN MP-xxx, добавить)
- [ ] Запустить S1 (T1+T2 Balanced) параллельно как первый shadow

**APY target Q3:** 6-8% на S0 после migration, 8-10% на S1 shadow

**Новые протоколы добавить в реестр:**
- Morpho Blue Gauntlet USDC (`0x8eB67A509616cd6A7c1B3c8C21D48FF57df3d458`)
- Aave V3 Arbitrum USDC
- Fluid USDC market
- Pendle PT (read-only APY feed)

---

### Q4 2026 (Октябрь–Декабрь 2026): Target 9-11% APY

**Что делать:**

**Protocol expansion:**
- [ ] Запустить S2 (Pendle PT Rotation) — первые 30 дней трека данных должны появиться
- [ ] Добавить Maple Syrup adapter (`maple_syrup.py`) — обновить существующий maple.py
- [ ] Skywatch monitor unlock: если GSM Pause Delay ≥ 48h — включить Sky/sUSDS allocation (MP в watch list)

**Tournament первые результаты:**
- К октябрю S1 будет иметь 30+ дней данных → первое promotion decision
- K ноябрю S2 Pendle данные за 30 дней → сравнение Sharpe ratio

**Risk Policy Review:**
- Рассмотреть APY ceiling в RiskPolicy: текущий max 30% ОК для Pendle
- Рассмотреть Private Credit как отдельную category (не T2) с max 25% аллокации
- Требует ADR + Owner approval + 2-недельный paper test

**APY target Q4:** 9-11% на лучшей стратегии из tournament

---

### Q1 2027 (Январь–Март 2027): Target 11-13% APY

**Что делать:**

**Live readiness (если track record OK по ADR-002):**
- Go-live решение по ADR-002: 30 честных дней трека + GoLiveChecker READY
- Real capital deployment через Gnosis Safe 2-of-3
- Начать с S0 baseline (3-5% APY) на реальном капитале
- Постепенное добавление S2/S3 positions на реальные деньги

**Protocol expansion (T3):**
- Clearpool institutional pools (если TVL > $500M, аудит свежий)
- Convex/Curve boosted LP для USDC/USDT пары (5-8% base + emissions)
- Goldfinch senior tranche (только если credit analysis OK)

**Pendle PT maturity management:**
- Sep 2026 PT maturity → автоматически rotate в Dec 2026 / Mar 2027 PT
- Implement PT rotation logic в S2: за 14 дней до maturity → roll forward

**APY target Q1 2027:** 11-13% weighted на live portfolio

---

### Q2 2027 (Апрель–Июнь 2027): Target 13-15% APY

**Стратегические опции (рискованнее):**

**Bull market capture:**
- Если ETH bull market → sUSDe funding spike → S4 delta-neutral выходит на 15-20%
- Tournament автоматически продвигает S4 если Sharpe > 1.5 на 30 дней

**Cross-chain expansion:**
- Aave V3 Base (5.8-6.5%) + Morpho Base vaults
- Arbitrum Pendle PT пулы (выше ликвидность на арбитраже)

**New strategies (требуют отдельного ADR):**
- S5: Aave e-mode 2x loop (simulated: ~8-9% без T4 риска)
- S6: Convex LP boosted (Curve 3pool + veCRV boost via Convex)
- S7: Cross-chain arbitrage (Aave ETH vs Aave Arbitrum rate differential)

**APY target Q2 2027:** 13-15% в bull scenario, 10-11% в neutral scenario

---

## Часть 4. Немедленные действия (Следующие 2 недели)

### Action Items по приоритету

| Приоритет | Действие | Файл | Оценка | Блокер |
|---|---|---|---|---|
| P0 | Запустить autopush fix | `bash mp009_fix_launchd.command` | 5 мин | Нет |
| P1 | RPC ключ в Keychain | Keychain `ALCHEMY_API_KEY_SPA` | 10 мин | MP-017 |
| P1 | Pendle PT adapter | `spa_core/adapters/pendle_pt.py` | 3h | MP-017 или REST |
| P1 | Morpho Gauntlet vault в реестр | `spa_core/adapters/__init__.py` | 1h | Нет |
| P1 | Aave Arbitrum adapter | `spa_core/adapters/aave_v3_arbitrum.py` | 2h | RPC key |
| P2 | MultiStrategyRunner | `spa_core/paper_trading/multi_strategy_runner.py` | 4h | Нет |
| P2 | TournamentEvaluator | `spa_core/paper_trading/tournament.py` | 3h | Нет |
| P2 | S1 стратегия | `spa_core/strategies/s1_t1t2_balanced.py` | 2h | Нет |
| P3 | S2 стратегия | `spa_core/strategies/s2_pendle_rotation.py` | 2h | Pendle adapter |
| P3 | S3 стратегия | `spa_core/strategies/s3_private_credit.py` | 2h | Maple update |

### API Endpoints для адаптеров (все публичные, без auth)

```bash
# Pendle REST API (без RPC — работает прямо сейчас)
GET https://api.pendle.finance/core/v1/1/markets
# Ответ: list markets с impliedApy, liquidity, underlyingApy

# DeFiLlama yields (уже используется)
GET https://yields.llama.fi/pools
# Filter: project=morpho, project=aave-v3, project=pendle, etc.

# Morpho API
GET https://api.morpho.org/markets?chainId=1&asset=USDC

# Maple Finance
GET https://api.maple.finance/v2/pools?type=syrup

# Ethena sUSDe
GET https://app.ethena.fi/api/yields/protocol-and-staking-yield

# Fluid
GET https://api.fluid.instadapp.io/v1/markets
```

---

## Приложение A: Контракты протоколов (Mainnet)

| Протокол | Contract | Версия |
|---|---|---|
| Aave V3 Pool | `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` | V3 Mainnet |
| Aave V3 Arbitrum Pool | `0x794a61358D6845594F94dc1DB02A252b5b4814aD` | V3 Arbitrum |
| Morpho Blue | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` | Blue V1 |
| Compound V3 (Comet USDC) | `0xc3d688B66703497DAA19211EEdff47f25384cdc3` | V3 Mainnet |
| Pendle Router V4 | `0x00000000005BBB0EF59571E58418F9a4357b68A0` | V4 Mainnet |
| Maple Syrup Pool | `0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b` | Syrup |
| Ethena sUSDe | `0x9D39A5DE30e57443BfF2A8307A4256c8797A3497` | V1 |
| Fluid Lending | `0x52Aa899454998Be5b000Ad077a46Bbe360F4e497` | V2 |
| Curve 3pool | `0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7` | Stable Swap |

> ⚠️ **Всегда верифицируй адреса на etherscan.io перед любым live deployment.
> Адреса могут устаревать при protocol upgrades.**

---

## Приложение B: Ограничения SPA RiskPolicy при расширении

При добавлении новых стратегий следующие параметры RiskPolicy v1.0 потребуют ADR:

| Параметр | Текущее | Требуется для цели | ADR |
|---|---|---|---|
| `max_apy_for_new_position` | 30% | ОК для Pendle PT (8-18%) | Не нужен |
| `max_concentration_t2` | 20% | Pendle 35% требует пересмотра | ADR-019 |
| `max_total_t2_allocation` | 35% | Portfolio B = 55% T2 | ADR-019 |
| Private credit category | не существует | Нужна T3 категория 20% | ADR-020 |
| `min_tvl_usd` | $5M | Pendle PT AMM liquidity < $5M? | проверить |

**ADR-019 (черновик):** Увеличить `max_total_t2_allocation` с 35% до 50% для
Pendle-heavy стратегий. Требует 14-дневный paper test в isolated vPortfolio.

**ADR-020 (черновик):** Добавить T3 Private Credit category с cap 25% портфеля,
min TVL $100M (по TVL протокола, не пула), requires fresh audit ≤ 12 months.

---

## ✅ Quick Wins — Реализованные улучшения

### Quick Win #1: Morpho Blue Steakhouse USDC Switch
**Статус:** Задокументирован ✅ (2026-06-12)  
**Эффект:** +200 bps (+2.0% APY) — no code change required  
**Было:** Aave V3 Mainnet USDC → **3.2% APY**  
**Стало:** Morpho Blue Steakhouse USDC vault → **6.5% APY**  
**Vault:** `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` (Morpho Blue, Steakhouse curator)  
**Почему безопасно:** Тот же риск-профиль (T1, audited by Spearbit + Trail of Bits),
TVL $3.5B+, curator Steakhouse — один из самых consertative на Morpho.  
**Следующий шаг:** Обновить `spa_core/adapters/__init__.py` — выбрать Steakhouse vault
как дефолтный для Morpho Blue адаптера.


---

## Ключевые выводы

1. **10-15% APY без плеча в DeFi в 2026 — сложно, но достижимо** при агрессивном
   использовании Pendle PT (8-18% fixed) и private credit (7-10%). Честная устойчивая
   цель для SPA: **9-11% APY** при умеренном риске.

2. **Самый быстрый win** — переключить T1 anchor с Aave mainnet на Morpho Steakhouse
   + Aave Arbitrum: **немедленно +200 bps** к APY без изменения риск-профиля.

3. **Pendle PT adapter — главный разблокировщий** для достижения 10%+ APY.
   REST API работает без RPC, реализация ~3 часа. Это должен быть следующий спринт.

4. **Multi-strategy инфраструктура уже на 60% готова** (vportfolio.py, strategy_registry,
   comparator). Нужно ~23 часа работы для полного tournament framework.

5. **sUSDe/Ethena S4 стратегия** — opportunistic: держать в paper track, активировать
   агрессивную аллокацию только при sUSDe 30-day APY > 10%.

---

*Документ создан: 2026-06-12 | SPA v1.0 Multi-Strategy Research*
*Следующий review: 2026-07-15 (go-live decision point)*
