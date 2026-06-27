# DeFi Yield Strategy Research — 2025–2026

> Составлено: 2026-06-22 | Источник: WebSearch + WebFetch, ~15 источников  
> Цель: Обзор реальных стратегий для SPA expansion roadmap

---

## Содержание

1. [Tier 1 — Минимальный риск (3–7% APY)](#tier-1)
2. [Tier 2 — Средний риск (7–15% APY)](#tier-2)
3. [Tier 3 — Повышенный риск (15–30% APY)](#tier-3)
4. [Ecosystem: Gauntlet / Chaos Labs / Block Analitica](#ecosystem)
5. [DeFi Hedge Fund стратегии](#hedge-funds)
6. [Backtest фреймворки для DeFi](#backtest)
7. [Новинки DeFi lending 2025–2026](#innovations)
8. [Совместимость с SPA (USDC/USDT, Ethereum/Base/Arbitrum)](#compatibility)
9. [Источники](#sources)

---

## <a name="tier-1"></a>TIER 1 — Минимальный риск (3–7% APY)

### 1.1 Aave V3 — Simple Stablecoin Lending

| Параметр | Значение |
|---|---|
| **Протокол** | Aave V3 (Ethereum, Arbitrum, Base) |
| **APY (июнь 2026)** | 3.8–5.2% (30-дневный trailing); диапазон 3–6% в зависимости от утилизации |
| **Механизм** | Поставляешь USDC в пул → заёмщики платят проценты → доходность определяется utilization rate пула |
| **Главный риск** | Smart contract risk; резкое падение спроса на заёмные средства снижает ставку |
| **TVL** | ~$20B+ (Aave V3 суммарно по чейнам) |
| **Совместимость** | ✅ USDC/USDT, Ethereum + Arbitrum + Base |
| **Статус в SPA** | ✅ T1, адаптер `aave_v3.py` активен (и `aave_v3_arbitrum.py` в разработке) |

**Вывод:** Надёжный базовый блок. APY ниже Morpho, но ликвидность мгновенная.

---

### 1.2 Compound V3 (Comet) — USDC Market

| Параметр | Значение |
|---|---|
| **Протокол** | Compound V3 Comet, Ethereum + Arbitrum |
| **APY (июнь 2026)** | 3–5% base APY; исторический mean 3.78%, диапазон 2.3–11.7% |
| **Механизм** | Упрощённая монолитная архитектура: один базовый актив (USDC) + несколько коллатералей; более консервативная модель рисков |
| **Главный риск** | Smart contract risk; ставка ниже Morpho и Aave |
| **TVL** | ~$3–5B (Ethereum Comet USDC) |
| **Совместимость** | ✅ USDC, Ethereum + Arbitrum |
| **Статус в SPA** | ✅ T1, адаптер `compound_v3.py` активен |

**Вывод:** Консервативный вариант, исторически немного уступает Aave по ставке. Gauntlet активно оптимизирует параметры через контракт с Compound до сентября 2026.

---

### 1.3 Morpho Blue / Curated Vaults

| Параметр | Значение |
|---|---|
| **Протокол** | Morpho Blue + MetaMorpho Vaults (Ethereum, Base) |
| **APY (июнь 2026)** | 4–8% USDC (curated vaults); выше Aave/Compound за счёт активной ребалансировки |
| **Механизм** | Изолированные lending-рынки с permissionless created парами + кураторы (Gauntlet, Block Analitica, Steakhouse Financial) активно маршрутизируют ликвидность в наиболее доходные пары |
| **Главный риск** | Smart contract + curator risk; ошибка куратора может привести к потере принципала |
| **TVL** | $10B+ (Q4 2025, рост с $2B в начале 2025) |
| **Совместимость** | ✅ USDC, Ethereum + Base |
| **Статус в SPA** | ✅ T1, адаптер `morpho_steakhouse_adapter.py` и `morpho_blue.py` активны |

**Вывод:** Лучшая ставка в Tier 1. Morpho стал модульной lending-инфраструктурой DeFi к 2026. Tranches: Prime (низкий риск) / Core (средний) / Frontier (высокий yield).

---

### 1.4 Spark Protocol (sUSDS / USDS)

| Параметр | Значение |
|---|---|
| **Протокол** | Spark (Sky/MakerDAO экосистема) |
| **APY (июнь 2026)** | 4.5–6% на USDS через Sky Savings Rate (SSR) |
| **Механизм** | Governance-managed savings rate на USDS (преемник DAI Savings Rate); параметры устанавливаются Sky governance |
| **Главный риск** | Governance risk; зависимость от Sky DAO; ставка может быть снижена без notice |
| **TVL** | Часть более широкой Sky/Maker экосистемы |
| **Совместимость** | ⚠️ USDS (не USDC), конвертация USDC→USDS через Spark |
| **Статус в SPA** | KANBAN: watch list; ADR для Sky/sUSDS — 0% аллокации до подтверждённого GSM Pause Delay ≥ 48h |

**Вывод:** Интересная ставка, но требует выполнения условий ADR-002. Pendle PT-stUSDS предлагает фиксированный доступ к SSR (~16.8% в Pendle пуле).

---

### 1.5 Pendle PT — Fixed Yield (Фиксированная доходность)

| Параметр | Значение |
|---|---|
| **Протокол** | Pendle Finance v2 (Ethereum, Arbitrum, Base) |
| **APY — PT-USDe** | ~8.8% фиксированная (Zero Coupon Bond: купить PT-USDe за $0.917 → $1 при погашении) |
| **APY — PT-stETH** | 4–5% фиксированная (с премией к нативному стейкингу ~3.3%) |
| **APY — PT-stUSDS** | exposure на Sky SSR ~16.8% в фиксированной PT-форме |
| **Механизм** | Pendle разделяет yield-bearing token на PT (principal) и YT (yield). PT = zero-coupon bond, выкупается 1:1 к базовому активу при истечении срока |
| **Главный риск** | Smart contract risk Pendle; ранняя продажа PT на вторичном рынке может быть по дисконту |
| **TVL Pendle** | ~$5B (Q2 2026); пик $13B в Q1 2026 |
| **Совместимость** | ✅ PT-USDe — через USDe (USDC→USDe swap); Ethereum + Arbitrum |
| **Статус в SPA** | Pendle PT — рассматривается для включения; `pendle_pt_rest.py` в разработке (T3-SPEC) |

**Вывод:** PT-USDe при 8.8% фиксированной доходности — привлекательная Tier 1/Tier 2 граничная стратегия для «lock-in» доходности на квартал вперёд.

---

### 1.6 RWA Yield — Ondo Finance (USDY / OUSG)

| Параметр | Значение |
|---|---|
| **Протокол** | Ondo Finance |
| **APY — USDY** | 4.65% (апрель 2026); backed by short-duration US Treasuries + bank demand deposits |
| **APY — OUSG** | ~3.49% (январь 2026); tokenized US T-bills / government money market funds |
| **Механизм** | Токенизированные краткосрочные US Treasuries. Delaware bankruptcy-remote structure. USDY $740M supply через Ethereum, Solana, Mantle, Sui, Aptos |
| **Главный риск** | Регуляторный/кастодиальный риск (централизованный эмитент); доступно только аккредитованным инвесторам |
| **TVL** | $2.75B+ TVL Ondo (доминирует в tokenized Treasury рынке) |
| **Совместимость** | ⚠️ Требует KYC/accredited investor; USDC вход через swap |
| **Статус в SPA** | Не используется (требует KYC gate) |

**Вывод:** Привлекательно для институционального трека, но не для автономного DeFi цикла без KYC.

---

### 1.7 Maple Finance — syrupUSDC (Institutional Credit)

| Параметр | Значение |
|---|---|
| **Протокол** | Maple Finance (Ethereum + Solana) |
| **APY — syrupUSDC** | 4.35% средний; institutional book (крупные заёмщики) 9–14% |
| **Механизм** | On-chain кредитный рынок: institutional borrowers (trading firms, market makers) берут USDC; профессиональные андеррайтеры управляют пулами. syrupUSDC — permissionless токен без KYC |
| **Главный риск** | Undercollateralized lending credit risk; дефолт крупного заёмщика может повредить пулу |
| **TVL** | ~$2.1B (май 2026); активные займы $1.85B |
| **Совместимость** | ✅ USDC, Ethereum |
| **Статус в SPA** | ⚠️ T2 кандидат; отслеживается |

**Вывод:** Умеренно привлекательная ставка (~4.35% без KYC через syrupUSDC). Риск дефолта заёмщика нужно мониторить. SYRUP листинг на Revolut (апрель 2026) — признак mainstream роста.

---

### 1.8 Yearn V3 — Yield Aggregator

| Параметр | Значение |
|---|---|
| **Протокол** | Yearn Finance V3 |
| **APY** | 3–6% USDC (mix Aave V3 + Curve crvUSD/USDC + Convex boost) |
| **Механизм** | Автоматически аллоцирует USDC между лучшими лендинговыми протоколами; стратегии пишутся community-driven |
| **Главный риск** | Smart contract stack risk (несколько протоколов); crvUSD vault показывает всего 0.25% при $3M TVL |
| **TVL** | Меньше исторических пиков; конкуренция со стороны Morpho Vaults |
| **Совместимость** | ✅ USDC, Ethereum |
| **Статус в SPA** | `yearn_v3.py` активен (T2) |

**Вывод:** Yearn V3 для USDC — безопасный агрегатор, но конкурентное давление со стороны Morpho curated vaults сильнее. APY Yearn USDC vault ~4.93% historical mean.

---

### 1.9 Centrifuge — RWA Structured Credit

| Параметр | Значение |
|---|---|
| **Протокол** | Centrifuge (Ethereum + нативная Centrifuge chain) |
| **APY** | Варьируется по пулу (trade receivables, mortgages, consumer loans); типично 6–12% |
| **Механизм** | Реальные долговые активы (инвойсы, ипотека, structured credit) токенизируются в NFT → пулятся в tranches DROP/TIN; USDC вход, yield в USDC |
| **Главный риск** | Private credit default risk; требует KYC/accredited investor для большинства пулов |
| **TVL** | ~$1.6B (июнь 2026) |
| **Совместимость** | ⚠️ Требует KYC для большинства пулов; USDC yes |
| **Статус в SPA** | Не используется (KYC gate) |

---

## <a name="tier-2"></a>TIER 2 — Средний риск (7–15% APY)

### 2.1 Ethena sUSDe — Delta-Neutral Basis Trade ⭐

| Параметр | Значение |
|---|---|
| **Протокол** | Ethena Protocol |
| **APY (апрель 2026)** | 7-day trailing: **9.4%**; 90-day trailing: **11.8%**; пик при запуске 2024: 27% |
| **Механизм** | Long staked ETH (коллатераль) + short ETH perpetual futures (hedge) = delta-neutral позиция. Доходность = стейкинговый yield ETH + funding rate от шорта |
| **Главный риск** | Funding rate flip (ставка становится отрицательной); counterparty risk (централизованные биржи для перпов); collateral risk (stETH); smart contract risk |
| **Reserve Fund** | $61M (март 2026) против $5.6B supply (~1.1%) |
| **TVL** | ~$5.6B USDe в обращении |
| **Совместимость** | ✅ USDC→USDe swap; Ethereum |
| **Статус в SPA** | `delta_neutral_susde.py` (S8) — paper-only до go-live; ~27.5% bull mode APY в бэктесте |

**Механизм детально:**
1. Пользователь вносит ETH/stETH → Ethena держит коллатераль
2. Ethena открывает шорт ETH perpetual на CEX (Binance, Bybit, OKX)
3. Когда funding позитивный (лонги платят шортам) → доход для sUSDe holders
4. Доход распределяется: stakers получают sUSDe (rebasing/yield-bearing)

**Риск детально:**
- Funding rate исторически ~3 недели в году отрицательный → Reserve Fund поглощает
- Counterparty: $5.6B перп-позиции на CEX — системный риск при биржевом коллапсе
- Депег USDe возможен при mass-withdrawal + low liquidity

---

### 2.2 Basis Trade / Funding Rate Arbitrage (Hyperliquid)

| Параметр | Значение |
|---|---|
| **Протокол** | Hyperliquid DEX (L1 perp DEX, $3B+ daily volume) |
| **APY** | 20–50% во время высоких funding периодов; **несистематический** — зависит от рыночного сентимента |
| **Механизм** | Spot long ETH/BTC + short perpetual на Hyperliquid = delta-neutral. Funding settlement hourly. Когда funding позитивный (bull market) → шорт получает выплаты |
| **Главный риск** | Funding flip — при медвежьем рынке лонги получают выплаты, шортам надо платить; execution complexity; нет withdrawals в USDC напрямую |
| **Совместимость** | ⚠️ Требует ETH/BTC позицию; не pure USDC |
| **Статус в SPA** | Не реализовано; требует execution на Hyperliquid |

**Вывод:** Этот APY реальный, но **непостоянный**. Среднегодовой yield ближе к 10–15% при правильном timing. Ethena по сути автоматизирует эту стратегию.

---

### 2.3 Pendle YT — Yield Token Speculation

| Параметр | Значение |
|---|---|
| **Протокол** | Pendle Finance v2 |
| **APY — YT-sUSDe** | Leverage на Ethena: пул платил 8–25% APY Q4 2025/Q1 2026 + Ethena/Ethereal points (167% points boost) |
| **APY — YT-stUSDS** | Leverage на Sky SSR ~16.8% |
| **Механизм** | YT даёт право на весь yield underlying asset до maturity. Покупая YT по дешёвой цене (discounted), получаешь leveraged yield exposure. YT = 0 при maturity. |
| **Главный риск** | Theta decay: YT теряет ценность к дате погашения; yield compression убивает YT доходность; Pendle TVL волатильно |
| **TVL Pendle** | $5B (Q2 2026), пик $13B в Q1 2026 |
| **Совместимость** | ✅ USDC вход через YT пулы; Ethereum + Arbitrum |
| **Статус в SPA** | `pendle_yt.py` (S10) — paper-only, ADR-021 (advisory only, не открывает позиции автоматически) |

**Вывод:** YT — спекулятивный инструмент для активного управления. PT — консервативный для lock-in yield.

---

### 2.4 Liquid Restaking Tokens (LRT) + EigenLayer

| Параметр | Значение |
|---|---|
| **Протоколы** | Ether.fi (eETH), Renzo (ezETH), Kelp DAO (rsETH) + EigenLayer |
| **APY реальный** | 4–7% (3–4% ETH staking + 1–2% AVS rewards); без ETH-деноминации неприменимо для USDC |
| **APY с рекурсивным рестейкингом** | 10–20% (3-loop setup) |
| **Механизм** | Стейкаешь ETH → получаешь LRT (eETH/ezETH/rsETH) → EigenLayer рестейкает на AVS сети → получаешь AVS rewards поверх staking yield |
| **Главный риск** | Slashing на ETH + slashing на каждом AVS + смарт-контракт стек; исторический пример: Kelp DAO exploit апрель 2026 ($300M потери, $5.4B sector withdrawals) |
| **TVL EigenLayer** | $15B+ (февраль 2026), 93.9% доля restaking рынка |
| **Совместимость** | ❌ ETH-деноминированная стратегия; USDC inapplicable напрямую |
| **Статус в SPA** | Не в скоупе (USDC-only политика) |

---

### 2.5 Concentrated Liquidity — Uniswap V3 / Aerodrome (USDC/USDT Pairs)

| Параметр | Значение |
|---|---|
| **Протоколы** | Uniswap V3 (Ethereum), Aerodrome (Base), Curve (Ethereum) |
| **APY — Uniswap V3 USDC/USDT 0.01%** | Типично 3–10%; исключительные условия до 117% |
| **APY — Aerodrome msUSD/USDC (Base)** | ~86% base + 2.5% rewards (при высоком объёме) |
| **Механизм** | LP предоставляет ликвидность в узком ценовом диапазоне ($0.9999–$1.0001 для стейблкоин пары) → получает пропорциональную долю swap fees с высокой эффективностью капитала |
| **Главный риск** | Out-of-range риск: если цена выходит за диапазон — zero fees; impermanent loss для стейблов минимален |
| **Совместимость** | ✅ USDC/USDT, Ethereum + Base (Aerodrome) |
| **Статус в SPA** | Не реализовано; требует активного управления диапазоном |

**Вывод:** При активном управлении и высоком объёме — сильная стратегия. Aerodrome на Base показывает хороший APY за счёт AERO emissions.

---

### 2.6 Points Farming — Активные программы 2026

| Протокол | Программа | Механизм | Статус |
|---|---|---|---|
| **Ethena** | sUSDe staking → Shards → ENA airdrop | Накопление points пропорционально размеру позиции | Активно, buybacks $890M в 2025 |
| **Pendle YT** | YT holders → 160% Ethereal points + 167% Ethena points | Покупка YT даёт multiplied points farming | Активно |
| **Ethereal DEX** | Ethereal points → airdrop (Ethena L3 perp DEX) | Depositing/trading на Ethereal платформе | Был airdrop май 2025; продолжение |
| **Hyperliquid** | HYPE ecosystem farming | Торговля/лирование на Hyperliquid | Активно |
| **EigenLayer era** | ❌ Завершена | Mainnet launch 2024, restaking booms прошли | Завершено |

**Вывод:** Основная эпоха EigenLayer points закончилась. Активные программы 2026 — Ethena ecosystem (ENA, Converge, Ethereal) + Pendle multipliers.

---

## <a name="tier-3"></a>TIER 3 — Повышенный риск (15–30% APY)

### 3.1 Leverage Looping / Recursive Lending

| Параметр | Значение |
|---|---|
| **Протоколы** | Instadapp Fluid Lite, DeFi Saver, Contango; Gearbox переходит на RWA Credit Lines |
| **APY** | 12–15% при 2–3x leverage (базовая доходность stETH 3–4% → 12%+) |
| **Механизм** | Supply stETH → borrow ETH (Aave/Morpho) → swap borrowed ETH → stETH → re-supply → repeat. Leverage усиливает staking yield, но и borrowing costs |
| **Главный риск** | Liquidation risk если stETH depeg; borrowing rate > staking rate → отрицательный spread; gas costs |
| **Совместимость** | ❌ ETH-деноминированная стратегия |
| **Статус в SPA** | `emode_looping.py` (S9) — paper-only; ~5.84% APY (консервативный 1.5x) |
| **Gearbox note** | Gearbox официально завершает looping и переходит к RWA Credit Lines (2026) |

**Instadapp Fluid Lite stETH Vault:** берёт stETH → суплает в lending протоколы → борет ETH → покупает ещё stETH → leveraged position. Автоматизирован, нет ручного rebalancing.

---

### 3.2 Recursive Restaking Loop

| Параметр | Значение |
|---|---|
| **Механизм** | wstETH → supply на Morpho → borrow ETH → swap ETH→stETH → wstETH → restake через EigenLayer → loop |
| **APY** | 10–20% при 3-loop setup (5% base → 12–15% эффективный) |
| **Главный риск** | Двойной slashing (ETH + AVS), liquidation cascade, smart contract stack (5+ протоколов) |
| **Совместимость** | ❌ ETH only |
| **Статус в SPA** | Не в скоупе |

---

### 3.3 Synthetic Dollar Strategies

#### Ethena USDe / sUSDe (детальнее см. Tier 2)

**sUSDe стал Tier 2 стратегией** в 2026 после компрессии с 27% → 9–11%. В bull mode по-прежнему может давать 20–27%.

#### Frax sfrxUSD — Benchmark-Rate Synthetic Dollar

| Параметр | Значение |
|---|---|
| **Протокол** | Frax Finance |
| **APY** | 5–8% (benchmark-rate strategy) |
| **Механизм** | ERC4626 wrapper для frxUSD (fully collateralized USD stablecoin). Yield routing: лучшее из трёх governance-approved стратегий — carry-trade, AMO (algorithmic market operations), IORB/T-bill rate. FIP-444 (апрель 2026): добавлены Aave sGHO и USCC Treasury fund |
| **Главный риск** | Governance risk (Frax DAO), smart contract risk; AMO стратегии могут underperform |
| **Совместимость** | ✅ Ethereum + Arbitrum + Fraxtal; интеграция с Aave V4 и Morpho vaults |
| **Статус в SPA** | Не реализовано; потенциальный кандидат |

#### f(x) Protocol

| Параметр | Значение |
|---|---|
| **Протокол** | f(x) Protocol (Aladdin DAO) |
| **Механизм** | Разделяет ETH на fETH (стабильный) + xETH (leveraged). Synthetic dollar через risk rebalancing между stablecoins и leveraged tranches |
| **APY** | Переменный; зависит от ETH волатильности |
| **Статус** | Нишевый, меньше данных в 2026 |

---

### 3.4 Protocol Incentive Farming (Aggressive Token Emissions)

| Протокол | Стратегия | APY токенами | Примечание |
|---|---|---|---|
| **Aerodrome (Base)** | LP в ключевых пулах + ve(AERO) voting | 50–200%+ | Gauge emission, сильная механика veAERO |
| **Morpho Frontier vaults** | Высокорисковые curated vaults | 10–20% | Frontier = max yield, max risk |
| **Hyperliquid HLP** | Provide liquidity to HLP Vault | 10–25% | Protocol fee sharing + funding |
| **Ethena Converge** | New Ethena blockchain (EVM) ecosystem | TBD | Converge ecosystem incentives |

---

## <a name="ecosystem"></a>Ecosystem: Gauntlet / Chaos Labs / Block Analitica

### Gauntlet — DeFi's Risk Brain

**Что делает:** Simulation-based risk modeling и quantitative research. Ключевые продукты:

- **Parameter Optimization:** 24/7 мониторинг и оптимизация параметров (borrow/liquidation collateral factors, supply caps, interest rate curves) для Compound (контракт до сентября 2026, 50 Comet deployments) и Aave
- **Curated Vaults on Morpho:** 30+ вольтов, $2B+ TVL. Tranches: Prime / Core / Frontier
- **Armitage (Wintermute's new vault service):** запущен май 2026 — Gauntlet-inspired approach от крупнейшего маркет-мейкера

**Методология:** Monte Carlo stress-testing, adverse scenario simulation, continuous parameter adjustment.

**2025 Recap:** Ключевые партнёрства — Compound, Morpho, Drift, Kamino. Расширение в RWA оптимизацию.

---

### Chaos Labs — Risk Oracles

**Что делает:** Real-time risk management для DeFi протоколов через Risk Oracles.

- **Risk Oracles:** Combines risk expertise с protocol-level automation — параметры автоматически корректируются on-chain на основе live market data
- **Reviews:** frxUSD Token Review (для Frax); параметры для Aave, Compound, других протоколов
- **Innovation:** Переход от off-chain advisory к on-chain automated risk parameters

---

### Block Analitica — Long-Horizon Risk Intelligence

**Что делает:** Risk intelligence с фокусом на Sky/MakerDAO экосистему и long-horizon collateral risk.

- **История:** С 2019 года поддерживает Sky (MakerDAO), Spark, Morpho, Summer.fi
- **Flagship Vaults:** USDC на Spark + Morpho mainnet; APY 4.5–6.5% с 15% fees
- **Методология:** Tail-risk behavior specific collateral types (LSTs, LRTs, tokenized treasuries) через multi-year cycles — отличие от Gauntlet (short-term volatility modeling)

**Вывод для SPA:** Эти три фирмы — ключевые risk infrastructure providers. Morpho Vaults с кураторами Gauntlet/Block Analitica — наиболее изощрённые USDC yield vehicles в Tier 1–2.

---

## <a name="hedge-funds"></a>DeFi Hedge Fund стратегии

### Wintermute — Market Maker → Vault Curator

**Публичные данные 2025–2026:**
- $2.24B daily trading volume; ликвидность на 50+ бирж
- **Armitage (май 2026):** два USDC vault на Morpho — institutional-grade risk management + trading intelligence для DeFi lending
- OTC options activity удвоилась в 2025 YoY; доминируют **systematic yield и risk-management strategies** (не directional bets)

**Стратегия:** Options-based yield (selling volatility) + market-neutral lending через Morpho.

### Amber Group (NASDAQ: AMBR с 2025)

- $5B+ daily market making volumes; 2000+ institutional investors
- CeFi/DeFi unified operations: market making + structured products + yield strategies
- Публично не раскрывает конкретные DeFi yield playbooks

**Вывод:** Крупные игроки в 2026 идут в vault curation (Morpho) и structured yield products. Wintermute Armitage — показательный сигнал, что institutionals видят Morpho curated vaults как primary DeFi yield venue.

---

## <a name="backtest"></a>Backtest фреймворки для DeFi Yield

### Специфично DeFi-ориентированные (2025–2026)

| Фреймворк | Тип | DeFi-специфика | Ссылка |
|---|---|---|---|
| **PFund** | Python; vectorized + event-driven | TradFi/CeFi/DeFi unified; поддерживает tick data | GitHub (Python) |
| **Jesse** | Python; algo-trading framework | Multi-timeframe, crypto-native | jessepy.io |
| **Dune Analytics** | SQL; on-chain data analytics | DeFi-специфично через on-chain queries | dune.com |
| **Messari Subgraphs** | GraphQL | Protocol-level DeFi data | messari.io |

### Generic (не DeFi-специфичные)

- **Backtrader** — de facto для retail Python traders
- **Backtesting.py** — лёгкий, candlestick-based
- **hftbacktest** — high-frequency, full tick data

### Вывод: Нет готового open-source DeFi yield backtest фреймворка

Специализированного open-source фреймворка именно для **DeFi yield стратегий** (не price trading) в 2026 не существует как отдельного продукта. Команды строят своё поверх:
- DeFiLlama API (исторические APY данных)
- Dune Analytics (on-chain исторические данные)
- Python + pandas/numpy (custom simulation)

**Для SPA:** Текущий подход (custom Python + DeFiLlama feed) соответствует industry best practice. BACKTEST_METHODOLOGY.md в репо — правильный путь.

---

## <a name="innovations"></a>Новинки DeFi Lending 2025–2026

### Aave V4 (март 2026 — mainnet)

- **Модульная архитектура (hub-and-spoke):** единый ликвидный хаб с изолированными "спицами" для разных рынков
- **Плавные процентные кривые:** устраняет cliff-effect в utilization rate
- **Unified Liquidity Layer:** один пул ликвидности для всех chain deployments
- **GHO Cross-Chain:** нативный стейблкоин Aave расширяется через chains
- frxUSD интеграция (FIP-444, апрель 2026): frxUSD как core borrowable stablecoin в Aave V4

### Morpho V2 (2026 roadmap)

- **Externalized rate pricing:** рыночно-определённые ставки вместо protocol-defined formulas
- **Fixed-rate lending:** defined maturities — новый product line (как рынок облигаций)
- **Cross-chain expansion:** Base, Optimism, Cronos, Flare + growing
- **TVL:** $10B+ (Q4 2025), рост с $2B в начале 2025

### Fluid Protocol (Instadapp)

- **Dual-use collateral:** collateral одновременно = lending position + DEX liquidity → пользователь зарабатывает и lending interest, и swap fees
- **SmartDebt/SmartCol:** позиции активны в DEX пока не используются как collateral
- **Unified Liquidity Layer:** одна ликвидность для лендинга и DEX — улучшает capital efficiency

### Рыночная динамика

- **Aggregate DeFi lending TVL:** ~$75–80B в апрель 2026 (рост с $50B в начале 2025)
- **Morpho:** $2B → $10B за год (институциональное принятие)
- **Основная борьба:** Morpho vs Aave V4 за title "DeFi lending infrastructure layer"
- **RWA интеграция:** tokenized treasuries (Ondo, Centrifuge) становятся acceptable collateral в Aave/Morpho

---

## <a name="compatibility"></a>Совместимость с SPA (USDC/USDT, Ethereum/Base/Arbitrum)

| Стратегия | USDC/USDT | ETH | Base | Arbitrum | Статус SPA |
|---|---|---|---|---|---|
| Aave V3 Lending | ✅ | — | ✅ | ✅ | ✅ Активно |
| Compound V3 | ✅ | — | — | ✅ | ✅ Активно |
| Morpho Blue/Vaults | ✅ | — | ✅ | — | ✅ Активно |
| Spark/sUSDS | ⚠️ USDS | — | — | — | Заморожено (ADR) |
| Pendle PT | ✅ via swap | — | — | ✅ | В разработке |
| Ethena sUSDe | ✅ via swap | — | — | ✅ | Paper-only (S8) |
| Pendle YT | ✅ via swap | — | — | ✅ | Paper-only (S10, ADR-021) |
| Maple syrupUSDC | ✅ | — | — | — | Кандидат T2 |
| Aerodrome CL | ✅ | — | ✅ Base | — | Не реализовано |
| Uniswap V3 CL | ✅ | — | — | ✅ | Не реализовано |
| Frax sfrxUSD | ✅ via swap | — | — | ✅ | Не реализовано |
| Ondo USDY | ⚠️ KYC | — | — | — | Недоступно (KYC) |
| LRT Restaking | ❌ ETH only | ✅ | — | — | Out of scope |
| Leverage Loop | ❌ ETH only | ✅ | — | — | Paper-only (S9) |

---

## Ключевые выводы для SPA Roadmap

**Tier 1 оптимизация (ближайший квартал):**
1. Morpho curated vaults — лучший USDC yield в Tier 1 (4–8%); расширение аллокации разумно
2. Pendle PT-USDe (8.8% fixed) — рассмотреть как "фиксированный блок" для части аллокации
3. Fluid Protocol adapter — двойной доход (lending + DEX fees)

**Tier 2 расширение (после go-live):**
1. Ethena sUSDe (9–11% trailing) — самый сильный risk-adjusted yield в T2 для USDC-совместимых стратегий
2. Concentrated liquidity Aerodrome/Uniswap V3 на стейблкоин парах — активное управление диапазоном
3. Maple syrupUSDC — институциональный кредитный yield без KYC

**Инфраструктура:**
1. Gauntlet Armitage vaults на Morpho — отслеживать как потенциальный managed vehicle
2. Aave V4 integration — по мере зрелости (март 2026 launch)
3. Frax sfrxUSD — benchmark-rate strategy (5–8%) как консервативный T1.5 вариант

---

## <a name="sources"></a>Источники

- [Aave vs Morpho vs Spark vs Fluid 2026 — eco.com](https://eco.com/support/en/articles/15253994-aave-vs-morpho-vs-spark-vs-fluid-2026-lending-protocol-comparison)
- [Ethena USDe Q1 2026 Report — Stablecoin Insider](https://stablecoininsider.org/ethena-usde-q1-2026-report/)
- [Ethena Docs: How USDe Works](https://docs.ethena.fi/how-usde-works)
- [Ethena Docs: Funding Risk](https://docs.ethena.fi/solution-overview/risks/funding-risk)
- [What Is Pendle Finance 2026 — EarnPark](https://earnpark.com/en/posts/what-is-pendle-finance-the-complete-2026-guide-to-yield-tokenisation-pt-yt-mechanics-and-boros/)
- [Ondo Finance USDY — RWA.xyz](https://app.rwa.xyz/assets/USDY)
- [Top RWA Crypto Projects 2026 — Bitcoin Foundation](https://bitcoinfoundation.org/news/defi/top-rwa-crypto-projects-2026-ondo-maple-centrifuge/)
- [Maple Finance TVL — DeFiLlama](https://defillama.com/protocol/maple-finance)
- [Gauntlet 2025 Research Recap](https://www.gauntlet.xyz/resources/gauntlet-applied-research-2025-recap-leading-growth-optimization-and-risk-management-in-defi)
- [Chaos Labs Risk Oracles](https://chaoslabs.xyz/posts/risk-oracles-real-time-risk-management-for-defi)
- [Block Analitica — Risk Intelligence for DeFi](https://blockanalitica.com/)
- [EigenLayer Restaking Guide 2026 — PistachioFi](https://www.pistachio.fi/blog/eigenlayer-restaking-guide-2026)
- [Financial Dynamics of Liquid Restaking — arXiv](https://arxiv.org/html/2604.03274)
- [Wintermute Launches Armitage — PR Newswire](https://www.prnewswire.com/news-releases/wintermute-launches-armitage-bringing-its-defi-and-trading-expertise-to-vault-curation-302776176.html)
- [2026 DeFi Outlook — The Block](https://www.theblock.co/post/383120/2026-defi-outlook)
- [DeFi Lending Is Modularizing — Tiger Research](https://reports.tiger-research.com/p/defi-lending-is-modularizing-the-eng)
- [Hyperliquid Funding Rate Strategy 2026 — MEXC](https://www.mexc.com/learn/article/hyperliquid-funding-rate-strategy-earning-passive-income-in-2026/1)
- [Best Liquidity Pools Stablecoin Pairs 2026 — StablecoinInsider](https://stablecoininsider.org/liquidity-pools-for-stablecoin-pairs-in-2026/)
- [frxUSD 2026 Report — StablecoinInsider](https://stablecoininsider.org/frxusd-report-2026/)
- [Centrifuge RWA Guide 2026 — DEXTools](https://www.dextools.io/tutorials/what-is-centrifuge-cfg-rwa-tokenization-protocol-guide-2026)
- [Aave V3 TVL — DeFiLlama](https://defillama.com/protocol/aave-v3)

---

*Документ подготовлен: 2026-06-22. Данные актуальны на июнь 2026 (некоторые APY могут меняться ежедневно — проверять через DeFiLlama / протокол-дашборды).*
