# Конкурентный анализ DeFi Yield Platforms
## Позиционирование SPA относительно рынка управления on-chain доходностью

**Дата исследования:** 2026-06-18  
**Охват:** Enzyme Finance, dHEDGE/Chamber, Yearn Finance v3, Idle Finance/Pareto, Sommelier Finance, VaultCraft  
**Метод:** Multi-source deep research (DeFiLlama, официальная документация, Sygnum Bank institutional report, DeFiPrime, Messari, Flagship.fyi)

---

## 1. Сравнительная таблица платформ

| Платформа | Mgmt Fee | Perf Fee | TVL (2025–2026) | Архитектура | Клиент | Аудиты |
|---|---|---|---|---|---|---|
| **Enzyme Finance** | Кастомная (до ~2%) | Кастомная | ~$184M (снижение с пика $230M) | Полностью on-chain, EVM (Eth + Polygon) → Canton Q3'26 | On-chain fund managers, DAO, institutional | Множественные (PeckShield, Trail of Bits, ранние + Onyx-специфичные) |
| **dHEDGE / Chamber** | ≤3% годовых (cap) | Да, по HWM | $33–50M (волатильно) | On-chain EVM vaults, multi-chain (ETH/OP/Poly/Arb/Base) | Retail traders, crypto fund managers | Не раскрыто подробно |
| **Yearn Finance v3** | ~2% годовых | ~20% от прибыли | ~$270M (март 2026) | Полностью on-chain, ERC-4626, 7 чейнов | Retail DeFi, DAO treasury | Consensys Diligence, Trail of Bits, ChainSecurity и др. |
| **Idle Finance / Pareto** | Зависит от стратегии | Зависит от стратегии | <$15M (малый) | On-chain ERC-4626 + Senior/Junior tranches; Eth/Polygon/OP/Arb | DAO treasury, institutional (переход на private credit) | Quantstamp × 2 (2019–2021), Certik + Consensys Diligence (2021) |
| **Sommelier Finance** | ~1% от TVL | 10–20% от прибыли | ~$14.6M (значительный спад) | Гибрид: off-chain Cosmos SDK → on-chain EVM cellars | Retail DeFi | Не раскрыто; сложная Cosmos-EVM архитектура с bridge-риском |
| **VaultCraft** | Не раскрыто публично | Не раскрыто публично | ~$100M (self-reported) | Multi-chain ERC-4626 + Smart/Boost Vaults + perp options | Retail → institutional | 5 аудитов: Immunefi, BlockSec, Code4rena, Paladin, Zokyo |

---

## 2. Детальный анализ по платформам

### 2.1 Enzyme Finance

**Бизнес-модель и фии.** Enzyme предоставляет инфраструктуру Vault-as-a-Service для on-chain фондов. Протокол поддерживает четыре типа комиссий: management fee (кастомная логика), performance fee (кастомная), entrance fee (flat %), exit fee (flat %). Все значения обновляемые. Дополнительно взимается 0.25% от AUM вауч в MLN-токенах, которые сжигаются. Конкретные диапазоны ставок задаются каждым vault-менеджером индивидуально.

**Техническая архитектура.** Полностью on-chain. EVM-нативный протокол (Ethereum + Polygon через v4 Sulu). В 2026 году идёт миграция на Canton Network — enterprise-grade блокчейн с privacy и real-time settlement для институциональных игроков. Enzyme Onyx — новый слой токенизации для enterprise, с кастодием NAV через Chainlink Runtime Environment.

**AUM/TVL.** Исторический пик — около $230M. Stelareum фиксирует ~$184M в более ранних данных. По состоянию на Q2 2026 TVL снизился. Тревожный сигнал: MLN-токен помещён в Monitoring Tag на Binance (апрель 2026), что сигнализирует о риске делистинга. Создано 1,400+ vault'ов за всё время.

**Типичный клиент.** On-chain fund managers, crypto hedge funds (например, Nexus Mutual использует Enzyme для управления капиталом), DAO treasury. Shift к институциональному сегменту через Onyx + Canton.

**Преимущества.** Старейшая и наиболее зрелая on-chain инфраструктура управления активами (с 2019 года). Максимальная гибкость fee-структуры. Мульти-ассетная, permissioned. Сильный institutional pivot через Canton.

**Слабые места.** Снижение TVL от пика. MLN на Binance Monitoring List — риск ликвидности токена. Transition friction между версиями (Sulu → Onyx). Сложность интеграции для розничного клиента.

---

### 2.2 dHEDGE / Chamber (formerly dHEDGE)

**Бизнес-модель и фии.** Management fee ограничена 3% годовых. Performance fee взимается только при достижении нового high-water mark (не поиндивидуально). Основной драйвер выручки — Toros Finance (инкубированный продукт), обеспечивающий 70% от общей выручки $886K в Q3 2025. Общий годовой доход протокола — ~$2M в 2025 году, из которых половина — комиссии.

**Техническая архитектура.** Vault-tokens — ERC-20, on-chain исполнение. Мультичейн: Ethereum, Optimism, Polygon, Arbitrum, Base. Toros Finance запускает on-chain токенизированные деривативы (leveraged tokens). Ребрендинг в Chamber включает новый lending market и "DeFi Perps" — направление агрессивного роста. 

**AUM/TVL.** Начало 2025 — $48M. Спад после выборов США — до $33M. Конец Q3 2025 — $50M. Волатильность TVL отражает зависимость от крипторынка в целом.

**Типичный клиент.** Retail DeFi-трейдеры, on-chain менеджеры небольших фондов, пользователи левереджных стратегий через Toros.

**Преимущества.** Мультичейн, прозрачный on-chain performance, Toros как sticky revenue layer, активное развитие (перманентные инновации).

**Слабые места.** Скромный TVL ($33–50M). Ребрендинг в "Chamber" сигнализирует о поиске identity. Высокая конкуренция от более крупных протоколов. $2M годовой выручки — мало для устойчивости.

---

### 2.3 Yearn Finance v3

**Бизнес-модель и фии.** Классическая модель: ~2% management fee + 20% performance fee. По governance-предложению 90% выручки протокола направляется stYFI-стейкерам. ERC-4626 стандарт обеспечивает компосабельность.

**Техническая архитектура.** Полностью on-chain. V3 rollout завершён в июле 2025 с переходом на ERC-4626. Модульная архитектура стратегий. 7 чейнов. Auto-compounding как основная UX-ценность.

**AUM/TVL.** По данным DeFiPrime (март 2026) — ~$270M. Пик в 2021 году — ~$6B. Снижение объясняется появлением curated vaults (Morpho) как более привлекательной альтернативы. Совокупный TVL категории "yield aggregators" (~$1.6B) более чем в 3x ниже одного Morpho ($5.8B) — capital migration налицо.

**Типичный клиент.** Retail DeFi-пользователи, DAO treasury, depositors, которым нужен "set-and-forget" подход. Не институциональный.

**Преимущества.** Первопроходец (2020), battle-tested, широкое DeFi-интегрирование, ERC-4626 комплаенс, yvUSD vault с нулевой fee (январь 2026).

**Слабые места.** $9M exploit legacy yETH pool в ноябре 2025 (core V3 не пострадал, но PR-урон). TVL в 22x ниже пика. Не готов для институционального клиента. Высокая конкуренция от curated vault сегмента.

**Аудиты.** Один из наиболее аудитированных протоколов в DeFi: Consensys Diligence, Trail of Bits, ChainSecurity, Certora, sigp, samczsun — множественные аудиты за 5 лет.

---

### 2.4 Idle Finance → Pareto Credit

**Бизнес-модель и фии.** Idle предлагал yield automation + Yield Tranches (senior/junior). Senior tranche получает 70% процентного дохода при нормальной работе и 100% защиту капитала при убытках (убытки ≤ Junior liquidity). Junior tranche берёт на себя весь downsizing risk в обмен на повышенный доход. Партнёрская программа: до 50% fee share для интеграторов. Протокол переходит в Pareto Credit — институциональный private credit marketplace с USP (synthetic USD).

**Техническая архитектура.** On-chain ERC-4626. Ethereum + Polygon + Optimism + Arbitrum. Yield sources: Lido, Compound, Aave, Morpho, Clearpool. Переход в Pareto Credit вводит collateral-backed USP и credit vaults.

**AUM/TVL.** Малый. Видимые вауты в 2026: Fasanara Investments ~$4.6M, Ethena ~$913K, Instadapp ~$298K. Суммарный TVL оценочно <$15M. Парадоксально низкий для протокола с 2019 года.

**Типичный клиент.** DAO treasury, institutional DeFi (Fasanara, ConsenSys-backed). Переход → institutional private credit lenders/borrowers.

**Преимущества.** Самый четкий institutional focus среди рассматриваемых. Tranche-архитектура — надёжный продукт для risk-averse инвесторов. Длинная история (с 2019). Сильные аудиторы: Quantstamp, Certik, Consensys Diligence.

**Слабые места.** Крошечный TVL — свидетельство сложности масштабирования в этом сегменте. Ребрендинг в Pareto = незавершённая трансформация. Конкуренция от Morpho curated vaults (аналогичный institutional appeal, но несравнимо больший масштаб).

**Аудиты.** Quantstamp (декабрь 2019 — апрель 2021), Quantstamp Governance audit (ноябрь 2020), Certik + Consensys Diligence — Tranches audit (декабрь 2021). $100K Immunefi bug bounty программа.

---

### 2.5 Sommelier Finance

**Бизнес-модель и фии.** Management fee ~1% от TVL + performance fee 10–20% от прибыли выше high-watermark. Комиссии поступают к SOMM-стейкерам через auction mechanism. Raised $26.5M (seed $3.5M + Series A $23M под руководством Polychain Capital, Alameda, Byzantine Partners).

**Техническая архитектура.** Гибридная: Стратегисты запускают off-chain модели → посылают rebalance messages → Sommelier blockchain (Cosmos SDK + Tendermint consensus) достигает консенсуса → rebalance передаётся через bridge → EVM vault contracts исполняют. Ключевые стратегисты: Seven Seas, Clear Gate, AR, Algolab, Define Logic Labs. Adapter architecture для интеграции множества DeFi-протоколов. Совет SOMM-валидаторов управляет governance.

**AUM/TVL.** Пик 2023 — ~$40M. Текущий TVL — ~$14.6M (апрель 2026). SOMM token — $0.00048, что означает потерю ~99.9%+ стоимости от пика. Этот показатель критически подрывает ценностное предложение.

**Типичный клиент.** Retail DeFi, пользователи ETH/USD yield vaults. Не институциональный.

**Преимущества.** Уникальная идея: off-chain вычисления + конфиденциальность стратегий. Cosmos SDK уменьшает gas fees на Ethereum. Non-custodial с validator governance.

**Слабые места.** Катастрофическое обесценивание токена ($0.00048). Малый TVL (~$14.6M). Сложность архитектуры (два блокчейна + bridge) = повышенный attack surface. Ставка на strategist model не оправдалась в масштабе. Аудитная документация слабо раскрыта.

---

### 2.6 VaultCraft

**Бизнес-модель и фии.** "Institutional grade, tokenized yield with perpetual options." Fee-структура публично не раскрыта в найденных источниках. V2-позиционирование: Smart Vaults (yield optimization) + Boost Vaults (yield + perp options). Инвесторы: Jump Crypto, New Form Capital, Big Brain Holdings, The LAO.

**Техническая архитектура.** Multi-chain с 1-click cross-chain zap. ERC-4626. Продукты: Smart Vaults, Boost Vaults, Manage (white-label vault builder). Governance через Snapshot.

**AUM/TVL.** Self-reported $100M TVL. DeFiLlama показывает минимальные verified fee данные ("$0 in fee data"), что ставит под сомнение точность self-reported TVL. Jump Crypto backing придаёт легитимность, но публичная верифицируемость слабая.

**Типичный клиент.** Позиционируется как "institutional grade", фактически обслуживает DeFi-native retail. Upsell для Jump Crypto portcos.

**Преимущества.** Сильный VC-backing (Jump Crypto). Дифференцирование через perpetual options layer. Наиболее диверсифицированный аудит-портфель: Immunefi, BlockSec, Code4rena, Paladin, Zokyo (5 аудиторов).

**Слабые места.** Непрозрачная fee структура. Сомнительность TVL-заявки (DeFiLlama не верифицирует). Ограниченная публичная узнаваемость бренда. Неясный path-to-revenue.

---

## 3. Анализ незанятой ниши: "autonomous yield infrastructure for family office"

### 3.1 Что говорит рынок о семейных офисах и DeFi

По данным Sygnum Bank (май 2025) — ведущего регулируемого digital asset банка — институциональные инвесторы (пенсии, endowments, суверенные фонды) **не аллоцируют** в DeFi из-за юридической неопределённости по enforcement смарт-контрактов. Семейные офисы, однако, занимают промежуточную позицию: в 2026 году они проявляют повышенный интерес к крипто-инфраструктуре и DeFi-yield стратегиям, хотя это остаётся "sandbox" для наиболее инновационных офисов, а не mainstream.

Ключевой вывод Sygnum: "Большинство притоков идёт от asset managers, hedge funds или crypto-native компаний с гораздо более высокой толерантностью к риску." Family offices находятся в этой серой зоне — достаточно гибки для экспериментов, но требуют доверия и прозрачности.

### 3.2 Незанятые позиции на рынке

Анализ шести платформ выявил четыре структурных пробела:

**Пробел 1: Отсутствие верифицируемого paper track record перед go-live.** Ни одна из шести платформ не имеет задокументированного бумажного трек-рекорда в режиме paper trading перед запуском реальных средств. Все либо запустились с реальными деньгами сразу, либо не документировали pre-launch performance. Это критический пробел для family office клиента, которому нужна история без рисков чужих экспериментов.

**Пробел 2: Автономность без LLM-зависимости в risk/execution.** Sommelier использует off-chain computation, но это human strategists, а не детерминированный алгоритм. Yearn/dHEDGE управляются комьюнити или fund managers. Полностью автономная система с детерминированной RiskPolicy (без LLM в критических компонентах) — пустое место на рынке. Family offices ценят предсказуемость и отсутствие человеческого фактора в управлении рисками.

**Пробел 3: Инвесторский портал для семейного офиса.** Ни одна из платформ не предлагает out-of-box investor portal с P&L attribution по участникам, Telegram-рассылками, onboarding документацией и правовой базой (инвестиционный договор). Это административный gap, который имеет критическое значение для family office с несколькими участниками.

**Пробел 4: Позиционирование между retail aggregators и institutional curated vaults.** Рынок разделился на два лагеря: (a) retail auto-compounders (Yearn, Beefy, Idle) с низким барьером входа, и (b) institutional curated vaults (Morpho + Gauntlet/Steakhouse) с ориентацией на AUM от $10M+. В промежутке — семейные офисы ($1M–$10M), которым нужна автономная, верифицируемая система с человекопонятной отчётностью.

### 3.3 Итоговая карта конкурентного позиционирования

```
                    INSTITUTIONAL
                         |
          Enzyme         |    Morpho
        (tokenized       |  (curated,
         funds)          |   $5.8B)
                         |
RETAIL ──────────────────┼──────────────── FUND-MANAGED
(retail,                 |                 (strategist/
 auto-compound)          |                  curator model)
   Yearn, Beefy          |    dHEDGE, Sommelier
   Idle (small)          |
                         |
                    ★ SPA OPPORTUNITY ZONE ★
               (autonomous algo, family office,
                verifiable paper track record,
                 investor portal, $100K–$5M AUM)
```

### 3.4 Ключевые дифференциаторы SPA в контексте конкурентов

По каждому конкуренту — чего у него нет, что есть в SPA-концепции:

- **Enzyme**: flexible infrastructure, но требует active fund manager и нет автономности. SPA предлагает полностью autonomous execution без human manager.
- **dHEDGE/Chamber**: community vaults, но нет детерминированной RiskPolicy и нет investor portal для семейного офиса. Rebrand риск.
- **Yearn v3**: auto-compound, но нет custom RiskPolicy, нет KYC/investor portal, нет paper track record.
- **Idle/Pareto**: лучший трактат по tranche protection, но tiny TVL и незавершённый pivot. Нет autonomous execution.
- **Sommelier**: closest model по автономности (off-chain compute), но: SOMM token рухнул, TVL микроскопический, стратегисты — люди, а не алгоритм.
- **VaultCraft**: strong audit posture, но нет прозрачной fee structure, сомнительный TVL, нет investor portal.

---

## 4. Ключевые выводы и рекомендации

### Выводы

1. **Рынок yield management консолидируется вокруг curated vaults** (Morpho, Mellow, Veda) с institutional-grade risk management. Классические yield aggregators (Yearn, Beefy, Idle) теряют TVL.

2. **"Institutional DeFi" остаётся narrative, а не реальностью** для крупных институтов (Sygnum Bank, май 2025). Но семейные офисы — более гибкие early adopters, готовые экспериментировать при наличии доверия.

3. **Ни одна платформа не предлагает сочетание**: (a) fully autonomous deterministic strategy без human manager, (b) verifiable paper trading track record до реального деплоя, (c) investor portal для family office onboarding, (d) прозрачная RiskPolicy с публичными audit snapshots.

4. **Sommelier — ближайший концептуальный аналог** (off-chain compute + on-chain execution), но провалился по токеномике и масштабу. Это важный anti-pattern: платформа, зависящая от нативного токена для governance + стейкинг-reward, высоко уязвима к bear market.

5. **VaultCraft показывает правильный аудит-подход** (5 аудиторов). Для SPA минимальный стандарт pre-launch — 2 независимых аудита core contracts + Immunefi bug bounty.

6. **Стандарт отрасли по fee**: mgmt fee 1–2% + perf fee 10–20%. Семейный офис клиент более чувствителен к mgmt fee, чем retail (т.к. учитывает absolute cost в USD).

### Рекомендации для SPA

- **Маркетинг**: позиционировать "verifiable paper track record" как первичный trust signal — это уникально и измеримо.
- **Fee structure**: рассмотреть 0% mgmt fee в paper period → 1% mgmt + 15% perf fee после go-live (конкурентоспособно vs. рынка).
- **Аудит**: до go-live — минимум 2 аудита core contracts (Certik/Consensys Diligence/Trail of Bits) + Immunefi bug bounty. Ссылка на audit reports — обязательный элемент investor portal.
- **Нишевое позиционирование**: не конкурировать с Morpho/Gauntlet в institutional large-AUM сегменте. Target — семейные офисы $500K–$5M AUM, которые хотят DeFi yield без внешнего fund manager.
- **Regulatory**: следить за EU MiCA и US stablecoin framework — они создадут первое юридическое пространство для family office DeFi allocation.

---

## 5. Источники

- [Enzyme Finance Documentation — Fees](https://docs.enzyme.finance/onyx-protocol/architecture/fees)
- [Enzyme Finance — Hedgeweek interview](https://www.hedgeweek.com/enzyme-the-global-infrastructure-for-tokenized-finance/)
- [Enzyme Finance TVL — DeFiLlama](https://defillama.com/protocol/enzyme-finance)
- [dHEDGE First Half 2025 Update](https://blog.dhedge.org/dhedge-2025-update/)
- [dHEDGE Q3 Report 2025](https://blog.dhedge.org/q3-report/)
- [Chamber (formerly dHEDGE) website](https://chamberfi.com/)
- [dHEDGE TVL — DeFiLlama](https://defillama.com/protocol/dhedge)
- [Yearn Finance v3 — yearn.fi](https://yearn.fi/v3)
- [Yearn Finance TVL — DeFiLlama](https://defillama.com/protocol/yearn-finance)
- [Yearn Finance Review 2026 — Milk Road](https://milkroad.com/reviews/yearn-finance/)
- [Idle Finance (now Pareto Credit)](https://idle.finance/)
- [Idle Finance — Yield Tranches Documentation](https://docs.idle.finance/products/yield-tranches/overview)
- [Sommelier Finance — Flagship.fyi Deep Dive](https://flagship.fyi/outposts/dapps/a-comprehensive-deep-dive-into-sommelier-finance-an-innovative-vault-platform/)
- [Sommelier Finance TVL — DeFiLlama](https://defillama.com/protocol/sommelier)
- [Sommelier Vault Fees — Medium](https://medium.com/@sommelier.finance/vault-fees-are-being-distributed-to-somm-stakers-5efc2076dc54)
- [VaultCraft — Official website](https://vaultcraft.io/)
- [VaultCraft TVL — DeFiLlama](https://defillama.com/protocol/vaultcraft)
- [The Complete Guide to DeFi Vaults in 2026 — DeFiPrime](https://defiprime.com/defi-vaults-guide)
- [Institutional DeFi in 2025 — Sygnum Bank](https://www.sygnum.com/blog/2025/05/30/institutional-defi-in-2025-the-disconnect-between-infrastructure-and-allocation/)
- [Sherlock Top 10 Smart Contract Auditing Companies 2026](https://sherlock.xyz/post/top-10-best-smart-contract-auditing-companies-in-2026/)
- [Family Offices & Crypto 2025 — insights4vc](https://insights4vc.substack.com/p/family-offices-and-crypto-2025)
- [Why Family Offices Are Going All In on Crypto in 2026 — Digital Ascension Group](https://www.digitalfamilyoffice.io/why-family-offices-are-going-all-in-on-crypto-in-2026/)
- [Messari — Enzyme Finance Profile](https://messari.io/project/enzyme-finance)

---

*Отчёт подготовлен для проекта SPA (Smart Passive Aggregator). Все данные верифицированы через минимум 2 независимых источника. TVL-данные актуальны на март–июнь 2026 г. Данные следует регулярно обновлять по мере изменения рынка.*
