# Token Economics & Fee Structure для DeFi Yield Fund
## Deep Research Report — SPA Launch 2027

> **Дата:** 2026-06-18  
> **Автор:** Deep Research Agent (Claude Sonnet 4.6)  
> **Версия:** 1.0  
> **Контекст:** SPA — автономный DeFi yield optimizer, paper trading с 2026-06-10, target go-live 2026-08-01, внешний AUM с 2027.

---

## Содержание

1. [Executive Summary](#executive-summary)
2. [Benchmark: Fee Structures конкурентов](#benchmark-fee-structures-конкурентов)
3. [TradFi Reference: 2/20 Model и его эволюция](#tradfi-reference-220-model-и-его-эволюция)
4. [Ответы на 8 ключевых вопросов](#ответы-на-8-ключевых-вопросов)
5. [Конкурентный ландшафт: как соперничать с бесплатными протоколами](#конкурентный-ландшафт)
6. [AUM Economics & Operational Costs](#aum-economics--operational-costs)
7. [B2B White-Label Pricing Models](#b2b-white-label-pricing-models)
8. [Adversarial Verification](#adversarial-verification)
9. [Рекомендуемый Fee Schedule для SPA (2027)](#рекомендуемый-fee-schedule-для-spa-2027)
10. [Sources](#sources)

---

## Executive Summary

На основании анализа 5 ведущих DeFi-протоколов, 300+ крипто-хедж-фондов и текущих TradFi-бенчмарков сложилась следующая картина:

**Стандарт рынка (2025–2026):** DeFi yield фонды дрейфуют от исторического 2/20 к структуре **1–1.5% management + 10–15% performance + high-watermark**. Полностью "бесплатные" протоколы (Morpho, Yearn V3 с отключёнными fees) создают жёсткое конкурентное давление снизу.

**Главный вывод:** Fee-структура не является конкурентным преимуществом сама по себе — это скорее вопрос доверия и позиционирования. Фонд должен отвечать на вопрос не "почему мы берём 1.5%", а "почему наши 12% net > 12% от Morpho без риска человеческой ошибки". Ответ — **track record, risk framework, compliance, верифицируемая автоматизация**.

**Рекомендация для SPA:** Трёхфазный подход:
- **Фаза 0 (Family Fund, < $2M):** 0% management, 10% performance с HWM, hurdle 5%
- **Фаза 1 (Seed External, $2–20M):** 1% management, 15% performance с HWM
- **Фаза 2 (Institutional, $20M+):** 0.75% management, 15–20% performance, volume discounts

---

## Benchmark: Fee Structures конкурентов

### Yearn Finance (Vaults)

**Исторически (V2):** 2% management fee + 20% performance fee — был стандартом DeFi.

**Текущее состояние (2025–2026):**
- YIP-51 установил 2/20 как базовую структуру для V2
- YIP-69 ввёл динамический fee через yRates — factory vaults: **10% performance fee** (не 20%)
- Одно-активные vaults (single asset): **без management fee**
- **YIP-85 (май 2025):** протокольные fees в V3 полностью отключены — temporary, для стимулирования роста и adoption
- Пользователи видят **net APY** (после всех fees и компаундинга)
- Fee распределение V2: management fee (2%) → 100% governance; performance fee (20%) → 19.5% governance + 0.5% strategist

**Вывод:** Yearn сейчас работает фактически без fees на новых V3 vaults. Это значит, что они жертвуют краткосрочным revenue ради роста TVL. **Конкурент с нулевыми fees существует.**

---

### Enzyme Finance (V4 — Sulu)

Enzyme — это on-chain инфраструктура для asset management, а не yield-протокол напрямую. Vault managers настраивают свой fee-schedule самостоятельно:

| Тип fee | Параметры | Особенности |
|---------|-----------|-------------|
| Management fee | % от AUM, периодический | Независим от доходности |
| Performance fee | % от прибыли за период | Benchmarked против denomination asset |
| Entry fee (entrance) | % от вложения | Дополнительная защита от арбитражистов |
| Exit fee | % при редемпшне | Введён в V4 (Sulu) |

**Ключевые детали:**
- **High Water Mark:** стандартно встроен. После crystallisation period → HWM = GAV на момент выплаты. Подписчики ниже HWM не платят performance fee пока GAV не вернётся выше.
- **V4 изменение:** убран crystallisation period → performance fee начисляется непрерывно (continuous accrual). Это выгоднее для менеджера, т.к. он получает fees раньше, а не ждёт квартала/года.
- **Fee currency:** новые shares (dilution-based), а не прямой transfer USDC
- **Изменение fees:** только при миграции на новую версию протокола — нельзя менять произвольно

**Практические диапазоны для Enzyme vaults:** менеджеры устанавливают индивидуально, типичный диапазон — management 1–2%, performance 10–20%.

---

### Ribbon Finance (теперь Aevo)

Ribbon Finance была pioneers опционных yield vaults (Theta Vaults — продажа OTM options):

| Параметр | Значение |
|----------|----------|
| Management fee | **2% годовых** (начисляется еженедельно) |
| Performance fee | **10% от премий** (если стратегия прибыльна) |
| Условие | Если неделя убыточна → никакие fees не берутся |

**Детали начисления:**
- Fees считаются **еженедельно**, пропорционально неделе (2% / 52)
- Performance fee — только на заработанные option premiums, не на общий NAV
- При убыточной неделе — полное освобождение от fees (это необычно и user-friendly)

**Контекст:** В июле 2023 Ribbon Finance был объединён с Aevo (L2 derivatives DEX). Theta Vaults продолжают работать, но фокус сместился. Важно: **структура 2/10 (management/performance) стала де-факто стандартом для опционных yield vaults**.

---

### Maple Finance (syrupUSDC/syrupUSDT)

Maple — институциональный on-chain credit fund. **Принципиально другая модель:**

| Метрика | Значение |
|---------|----------|
| All-in fee | **70–90 bps** (0.70–0.90% годовых) |
| Maple Direct: management fee | **12% от процентных платежей по займам** |
| Token buybacks | 25% protocol revenue → buyback SYRUP |
| AUM (конец 2025) | $4.59B (+767% за год) |
| ARR (Q4 2025 run-rate) | >$100M |
| Target APY | 6–10% USDC/USDT |

**Ключевое отличие:** Maple конкурирует с TradFi private credit (типичный 2/20) и берёт в 5–10x меньше. Это **B2B/institutional positioning** — не retail. Yield у них real (от займов институциональным заёмщикам), не token emissions. Repayment rate > 99%.

**Вывод:** Maple установил новый стандарт для institutional on-chain credit: <1% all-in вместо TradFi 2/20. Если SPA будет позиционироваться как institutional → нужно смотреть на этот benchmark.

---

### Morpho (MetaMorpho Vaults / Curated Markets)

**Morpho — самый опасный конкурент с точки зрения fees:**

- **Протокольный fee: 0%** — Morpho как протокол не берёт management/performance fee
- **Curator fee:** curators (риск-менеджеры вроде Steakhouse Financial) могут устанавливать свой performance fee за управление vault'ом
- TVL: >$10B (Q4 2025), лидер рынка automated yield
- USDC rates на Morpho: на 0.5–2% выше, чем на Aave/Compound
- Coinbase через Morpho vault (Steakhouse curator) — USDC lending для US retail (сентябрь 2025)

**Бизнес-модель конкурентов на Morpho:** curator зарабатывает performance fee за отбор рынков. Это именно то, что делает SPA — но Morpho-curator не несёт overhead фонда (compliance, legal, investor relations).

---

## TradFi Reference: 2/20 Model и его эволюция

### Классическая структура

**"2 and 20"** — 2% management fee + 20% performance fee на прибыль — был стандартом хедж-фондов десятилетиями.

| Компонент | Классика | 2025 Тренд | Crypto Funds (2025) |
|-----------|----------|------------|---------------------|
| Management fee | 2.0% | 1.3–1.7% avg | 1.5–2.0% (avg 1.70%) |
| Performance fee | 20% | 16–18% avg | ~20% (avg, SMA ~22%) |
| HWM | Стандарт | Стандарт | Стандарт |
| Hurdle rate | Реже | Чаще (инвест. давление) | Редко |

### Тренды (данные Crypto Insights Group, июль 2025)

Анализ 300+ liquid crypto funds и SMAs:

- **Среднее management fee, open-ended fund:** 1.70%
- **Среднее management fee, SMA:** 1.79%
- **Среднее incentive fee, open-ended:** ~20%
- **Среднее incentive fee, SMA:** ~22%
- **Кристаллизация:** 77% считают annually, 21% — quarterly (open-ended)
- **Начисление:** assessment monthly — стандарт

### Fee Compression

- Традиционный хедж-фонд 2/20 → уже не норма, exception
- Новые запуски: часто **1.5 and 15** или ниже
- Institutional investors выбивают side letters со скидками при крупных вложениях
- Для DeFi/Yield стратегий (наиболее близких к SPA) — fee ниже из-за автоматизации

---

## Ответы на 8 ключевых вопросов

### 1. Management Fee: 1% vs 1.5% vs 2%? Как считать?

**Стандарт для DeFi yield фондов (2025–2026):**

| Тип фонда | Management fee | Логика |
|-----------|---------------|--------|
| Автоматизированный on-chain yield | 0–0.5% | Yearn V3 (0%), Morpho curators (0–0.3%) |
| Опционный vault (Ribbon) | 2.0% | Юстифицируется активным риском стратегии |
| Crypto hedge fund (avg) | 1.5–1.7% | Crypto Insights Group benchmark |
| Institutional DeFi credit (Maple) | 0.7–0.9% | Vs TradFi private credit (намного ниже) |
| Рекомендация для SPA | **1.0%** | Компромисс между auto-yield протоколами и TradFi |

**Как считать:** Стандарт — **ежедневное начисление, ежеквартальная/ежегодная выплата**.

Формула: `Daily_fee = AUM × (management_rate / 365)`

- Это fair для инвестора (не платит за cash, которого нет в управлении)
- Начисляется на daily NAV — учитывает притоки/оттоки
- Выплата ежеквартально или ежегодно (отдельный vault share или USDC)

**Вывод:** Начинать с **1%** — это конкурентно на фоне традиционных 1.5–2%, но выше auto-yield протоколов. Оправдание — риск-менеджмент, track record, compliance.

---

### 2. Performance Fee: 10% vs 15% vs 20%? High-watermark обязателен?

**High-watermark: ДА, обязателен.** Без HWM институциональные инвесторы откажутся. Это базовая investor protection — manager не получает fees на "возврат" потерянного.

**Сравнение уровней:**

| Performance fee | Когда уместно |
|----------------|---------------|
| 10% | Низкорисковые стратегии (стейблкоин-only), высокий AUM, конкуренция с auto-yield |
| 15% | Оптимальный баланс для DeFi yield фонда. Рыночный компромисс. |
| 20% | Традиционный TradFi стандарт; оправдан при уникальной стратегии или alpha |

**Ribbon Finance прецедент:** 10% performance fee при 2% management — модель для опционных vaults, где стратегия хорошо известна рынку.

**Crypto Fund benchmark:** средний performance fee ~20% (open-ended), 22% (SMA). Но для low-volatility yield стратегий (как SPA — USDC-only) — **15% является психологически приемлемым и конкурентным**.

**Hurdle rate (не обязателен, но желателен):** Soft hurdle 5% — означает, что performance fee берётся только с дохода сверх 5% APY. При target 8–15% это разумно и защищает инвестора при "boring" рынке.

**Рекомендация:** **15% performance fee + HWM + soft hurdle 5%**

---

### 3. Deposit/Withdrawal Fee: нужна ли? Какой % нормален?

**Deposit fee (entrance fee):**
- Enzyme позволяет её устанавливать — обычно 0% для yield фондов
- Maple: нет deposit fee
- Yearn: нет deposit fee
- **Для SPA: 0% deposit fee** — любой барьер на входе снижает AUM

**Withdrawal fee (exit fee):**
- Enzyme V4 ввёл exit fee как опцию — направлена против арбитражистов (flash loan + vault drain)
- Ribbon: нет withdrawal fee, но weekly lock (вышел на следующий roll)
- Для стейблкоин yield фондов: обычно 0%

**Контекст:** В DeFi withdrawal fees редки для stablecoin vaults (т.к. депозиты/выводы не влияют на других так сильно, как в AMM с IL). Они чаще встречаются в governance-locked протоколах (Curve: нет withdrawal fee, но lock на token, не на капитал).

**Рекомендация для SPA:** **0% deposit, 0% withdrawal** для стандартных условий. Можно ввести **0.05–0.1% withdrawal fee при выходе в течение 30 дней** как soft deterrent против hot money — но это secondary.

---

### 4. Early Withdrawal Penalty: есть ли lock-up periods в DeFi yield?

**Lock-up в DeFi yield: есть, но не как в TradFi фондах (quarterly/annually).**

| Протокол | Lock-up | Механизм |
|----------|---------|-----------|
| Curve (veCRV) | 1 неделя — 4 года | Token lock, не капитал; для governance power |
| Ribbon Finance | 1 неделя (soft) | Выход только на следующий weekly roll |
| Maple Finance | Гибко | Некоторые пулы — instant, некоторые — notice period |
| Yearn | Нет lock-up | Instant withdrawal |
| Morpho | Нет lock-up | Instant (limited by liquidity) |

**Данные:** Протоколы с lock-up механизмами показали удержание ликвидности на 40%+ выше, чем без них.

**Для institutional DeFi yield фондов:** lock-up редко превышает 30 дней (в отличие от TradFi private credit с 1+ годом). Более типичны **notice periods** (7–30 дней) вместо жёстких lock-up.

**Рекомендация для SPA:**
- **Стандарт:** No lock-up, instant withdrawal
- **Опционально:** 7-дневный notice period для выводов > $100K (institutional tranche) — даёт time for position management
- **Incentive:** bonus APY за voluntary 30/90/180-day lock (как Curve модель)

---

### 5. Как конкурировать с бесплатными протоколами (Yearn/Morpho)?

Это главный вызов. Yearn V3 сейчас без fees. Morpho даёт 0.5–2% premium к Aave/Compound без management fee.

**Почему инвестор заплатит fees:**

| Дифференциатор | Как это работает | Ценность |
|---------------|-----------------|----------|
| **Верифицируемый track record** | 30+ дней реального трека, публичные данные | Единственный объективный измеримый показатель |
| **Risk curation** | RiskPolicy gate, TVL floor, drawdown kill-switch | Инвестор не следит 24/7 — он платит за это |
| **Strategy tournament** | S0–S10 competition, best strategy wins allocation | Alpha capture сверх passive APY |
| **Compliance & legal** | Договір інвестора, investor portal, KYC | Institutional требование |
| **Multi-protocol optimization** | Автоматическая ребалансировка по APY/TVL | Active vs passive management |
| **Downside protection** | 5% drawdown kill-switch vs Morpho (нет) | Insurance value |
| **Transparency** | Полная публичность data через GitHub | Trust premium |

**Ключевое наблюдение (из DL News research):** "Высококачественные curator'ы ведут себя как performance-fee фонды — монетизируют active risk-taking и proprietary analytics". SPA — именно это.

**Tesis:** Morpho даёт 8% USDC yield. SPA должен показывать 9–12% net после всех своих fees, при этом с более жёстким risk framework. Тогда fees оправданы. Если SPA не может outperform net-of-fees — не стоит запускаться как fee-bearing fund.

---

### 6. Fee Token vs Direct Fee: USDC или governance token?

**Аргументы за прямые fees в USDC:**

- Простота и прозрачность
- Нет необходимости в токеномике с нуля
- Инвесторы знают что платят
- Регуляторно безопаснее (governance tokens = securities risk в многих юрисдикциях)
- Maple берёт fees в USDC, реинвестирует 25% в buyback SYRUP — гибридная модель
- Yearn: fees в shares vault'а (dilution model)

**Аргументы за governance token:**

- Alignment of interests (owner = stakeholder)
- Protocol value capture
- Fee distribution как staking rewards
- Более сложно реализовать, особенно при старте

**Вывод для SPA в 2027:**

Не вводить governance token на launch. Причины:
1. Юридически сложно (securities laws в USA, EU MiCA)
2. Distraction от core yield-generation задачи
3. Market cap token требует ликвидности — нечем обеспечить при малом AUM
4. TradFi investors не хотят governance tokens — хотят yield in USDC

**Рекомендация:** **Direct fees в USDC** (или USDC-equivalent stablecoin). Governance token — возможность через 2–3 года при $50M+ AUM и DAO-формате. Если хочется token exposure для team — выпустить простой revenue-sharing NFT или profit-sharing agreement.

---

### 7. На каком AUM важны операционные расходы?

**Расчёт breakeven для разных AUM уровней:**

| AUM | Management fee (1%) | Performance fee (15% × 10% net yield) | Total Revenue/год | Breakeven |
|-----|--------------------|-----------------------------------------|-------------------|-----------|
| $500K | $5,000 | $7,500 | $12,500 | ❌ Невозможно |
| $1M | $10,000 | $15,000 | $25,000 | ❌ 1 part-time |
| $2M | $20,000 | $30,000 | $50,000 | ⚠️ Min viable (1 FTE) |
| $5M | $50,000 | $75,000 | $125,000 | ✅ 1–2 FTE |
| $10M | $100,000 | $150,000 | $250,000 | ✅ Small team (2–3 FTE) |
| $20M | $200,000 | $300,000 | $500,000 | ✅ Real business (4–5 FTE) |
| $50M | $500,000 | $750,000 | $1,250,000 | ✅ Full team + compliance |
| $100M | $1,000,000 | $1,500,000 | $2,500,000 | ✅ Institutional fund |

*Допущения: target gross APY = 10%, performance fee база = net yield 10%, management fee 1%*

**Ориентиры операционных расходов:**

- **Минимальный overhead (solo founder, автоматизированный):** ~$30–60K/год (VPS, инфраструктура, юридический минимум)
- **Малая команда (2 человека + аутсорс аудит):** ~$150–250K/год
- **Полноценный фонд (compliance officer, legal, ops):** ~$500K–1M+/год
- **API platform overhead (Финансовая модель лаб данные):** ~$70K/мес fixed на операционную платформу монетизации API

**Ключевые выводы:**
- При **$1M AUM**: управление обходится слишком дорого — стоит делать это как hobby/track record builder, не как бизнес
- При **$5–10M AUM**: min viable для small automated operation (1–2 FTE + infra)
- При **$20–50M AUM**: можно строить настоящую команду
- При **$50M+ AUM**: full-scale institutional fund с compliance

**Для SPA контекст:** Family Fund сейчас — это track record builder, не revenue center. Внешний AUM имеет смысл начинать при $2M+, target $10M+ для первого year external.

---

### 8. B2B White-Label Pricing: rev share vs flat fee vs usage-based?

**Текущий рынок DeFi B2B/White-Label (2026):**

Специфических данных по DeFi yield fund white-label API немного, но паттерны из смежных рынков:

**Модели B2B DeFi pricing:**

| Модель | Примеры | Плюсы | Минусы |
|--------|---------|-------|--------|
| Revenue share | 20–30% от fees | Aligns incentives, низкий barrer | Зависимость от AUM партнёра |
| Flat subscription | $500–5000/мес | Предсказуемость | Невыгодно при малом AUM |
| AUM-based fee | 0.1–0.3% от white-label AUM | Scales с ростом | Сложно контролировать |
| Usage-based (API calls) | $0.001–0.01/call | Fair для exploratory | Непредсказуемый revenue |

**Конкретные данные:**
- White-label crypto exchange: $899/мес (basic) → $5,000+/мес (enterprise)
- Breakeven на white-label exchange: 3–6 месяцев при активных пользователях
- API monetization platform: $70K/мес fixed costs → требует $434K cash buffer до breakeven

**Рекомендуемая модель для SPA B2B:**

**Revenue share + minimum:** 
- 25–30% от management fee (т.е. 0.25% от AUM партнёра при 1% management fee SPA)
- Минимум $500/мес — покрывает инфраструктурные расходы
- Enterprise (>$5M AUM) → negotiated flat fee + rev share

**Альтернатива — стратегический partner:** вместо white-label API, sub-advisory arrangement — SPA управляет капиталом под брендом партнёра за fixed advisory fee (20–30% от management fee партнёра).

---

## Конкурентный Ландшафт

### Матрица конкурентов

| Протокол/Фонд | APY (USDC) | Management | Performance | Lock-up | Дифференциация |
|--------------|------------|------------|-------------|---------|----------------|
| Morpho (Steakhouse) | 6–8% | 0% | 0–small | None | Scale, институц. доверие |
| Yearn V3 | 5–8% | 0% | 0% | None | Бренд, автоматизация |
| Maple syrupUSDC | 6–10% | 0.7–0.9% | — | Гибко | Реальные займы, $4.5B AUM |
| Ribbon/Aevo Theta | 10–25% (ETH vol) | 2% | 10% | 1 week | Опционная premium |
| **SPA (target)** | **8–12% net** | **1%** | **15%** | **None** | **Track record + risk mgmt** |

### Как SPA оправдывает fees

Суть value proposition — **not the fee level, but the risk-adjusted net yield**.

Если Morpho даёт 8% без риска менеджерской ошибки, SPA должен давать 10–12% net с лучшим downside protection. При target gross 12–15% и fees 1% + 15% performance:

```
Gross APY:        12.0%
Management fee:   -1.0%
Performance fee:  -1.65% (15% × 11% after mgmt)
Net to investor:  ~9.35%
```

Vs Morpho: 8%. Delta = +1.35% — это и есть alpha, за которую платит инвестор.

---

## AUM Economics & Operational Costs

### Автоматизированный DeFi yield рынок (2025)

| Протокол | AUM | Model |
|----------|-----|-------|
| Morpho | ~$10B+ | Curator-based, near-zero fees |
| Yearn | ~$750M | DAO-managed, fees отключены |
| Maple | ~$4.6B | Institutional credit, 0.7-0.9% all-in |
| Total auto-yield | ~$17.5B | — |

Net yields рынка 2025: 6.45% (avg) vs 7.95% gross → spread на fees и slippage: 1.5%.

### Breakeven Calculator для SPA

При launch с Family Fund ($500K virtual) + external seed $2M:

```
Год 1: AUM $2M external + $500K demo = ~$2.5M managed
Revenue: $20K (mgmt) + $30K (perf) = $50K
Costs: $40K (infra + legal minimum)
Net: $10K — barely viable, но track record растёт

Год 2: AUM $10M external  
Revenue: $100K (mgmt) + $150K (perf) = $250K
Costs: $150K (2 FTE equiv. + infra + compliance)
Net: $100K — profitable small operation

Год 3: AUM $50M external
Revenue: $500K + $750K = $1.25M
Costs: $500K (team, compliance, legal)
Net: $750K — healthy business
```

---

## B2B White-Label Pricing Models

### Структура B2B для SPA

**Tier 1: API Access (exploratory)**
- $500/мес flat fee
- Доступ к read-only data endpoints (APY, positions, risk metrics)
- Лимит: 10,000 API calls/мес
- Без управления капиталом

**Tier 2: Sub-Advisory White-Label ($1M–$10M AUM)**
- Revenue share: 25% от management fee партнёра
- То есть: если партнёр берёт 1.5% с клиентов, SPA получает 0.375% от AUM
- Minimum $1,000/мес
- SPA управляет capital, партнёр держит relationship

**Tier 3: Enterprise ($10M+ AUM)**
- Negotiated: flat fee $5,000–20,000/мес + 15–20% rev share
- Custom risk parameters
- Dedicated support
- SLA на uptime и reporting

**Revenue projections (B2B channel):**

| Partners | Avg AUM/partner | SPA rev share | Monthly B2B Revenue |
|----------|----------------|---------------|---------------------|
| 2 Tier 2 | $3M | 0.375% | $1,875/мес |
| 5 Tier 2 | $5M | 0.375% | $7,813/мес |
| 2 Tier 3 | $15M | 0.4% | $10,000/мес |
| Mix (mature) | — | — | $30–50K/мес = $360–600K/год |

---

## Adversarial Verification

Следующие ключевые claims были проверены против опровержений:

### Claim 1: "Yearn V3 работает без fees (YIP-85, май 2025)"
- **Подтверждение:** Мессарь и несколько источников подтверждают отключение fees для роста
- **Контраргумент:** Это временная мера — Yearn может вернуть fees при достижении TVL targets
- **Вердикт:** ✅ Подтверждено, но volatile — SPA не должен строить pitch исключительно на "мы дешевле Yearn"

### Claim 2: "Maple All-in fee 70–90 bps"
- **Источник:** Genfinity (2026-06-04) цитирует 70-90 bps как Maple pricing vs TradFi 2/20
- **Контраргумент:** Maple Direct берёт 12% management fee на loan interest — это другой продукт (institutional lending), не retail yield
- **Вердикт:** ✅ Частично — 70-90 bps all-in для syrup retail; 12% management fee для Maple Direct institutional

### Claim 3: "Средний crypto fund management fee 1.70% (Crypto Insights Group, июль 2025)"
- **Источник:** CIG database 300+ funds, COO report
- **Контраргумент:** Данные могут быть biased к larger, more established funds — новые запуски могут быть ниже
- **Вердикт:** ✅ Надёжный источник, но SPA как yield-specific strategy может ориентироваться на нижний диапазон (1.0–1.5%)

### Claim 4: "Ribbon 2% management + 10% performance"
- **Источник:** Официальная документация docs.ribbon.finance (первичный источник)
- **Контраргумент:** Ribbon мигрировал в Aevo, старые Theta Vaults депрекированы
- **Вердикт:** ✅ Исторический прецедент, но не текущий живой продукт

### Claim 5: "Performance fee lock-up повышает retention на 40%+"
- **Источник:** ecos.am анализ Curve/Balancer incentive structures
- **Контраргумент:** Данные по liquid stablecoin vaults (не токен-локи) могут отличаться
- **Вердикт:** ⚠️ Применимо к токен-локам (veCRV), не обязательно к capital lock-up в yield fund

---

## Рекомендуемый Fee Schedule для SPA (2027)

### Итоговая рекомендация: трёхфазная структура

---

### Фаза 0: Family Fund / Track Record (сейчас — до external AUM)

| Параметр | Значение |
|----------|----------|
| Management fee | **0%** |
| Performance fee | **10%** с HWM |
| Hurdle rate | Нет |
| Deposit fee | 0% |
| Withdrawal fee | 0% |
| Lock-up | None |
| Fee currency | USDC |
| Crystallization | Ежеквартально |

**Ратionale:** Нет смысла брать fees с себя / family fund. Track record строится, не revenue. 10% performance fee documenting что мы используем industry standard от начала.

---

### Фаза 1: Seed External Investors (launch 2027, $0–20M AUM)

| Параметр | Значение |
|----------|----------|
| Management fee | **1.0% годовых** (daily accrual, quarterly payment) |
| Performance fee | **15%** с HWM + soft hurdle 5% |
| Deposit fee | 0% |
| Withdrawal fee | 0% (или 0.10% при выводе в течение 30 дней — anti-hot-money) |
| Lock-up | None mandatory; 7-day notice для выводов > $50K |
| Fee currency | USDC |
| Crystallization | Ежегодно (31 декабря) |
| HWM reset | Ежегодная кристаллизация |
| Governance token | Нет |

**Math для инвестора:**
```
Target gross APY:       12%
Hurdle (free):          5%
Excess above hurdle:    7%
Performance fee (15%):  -1.05%
Management fee:         -1.0%
Net APY to investor:    ~9.95%

Vs Morpho USDC:         ~7.5%
SPA premium:            +2.45% — оправдывает fees
```

---

### Фаза 2: Institutional ($20M+ AUM)

| Параметр | Значение |
|----------|----------|
| Management fee | **0.75%** (volume discount) |
| Performance fee | **15–20%** (negotiated per investor) |
| Hurdle rate | SOFR + 1% или 5% fixed |
| Deposit fee | 0% |
| Withdrawal fee | 0% |
| Lock-up | 30-day notice period for > $500K |
| Minimum investment | $100K |
| Side letters | Доступны при > $5M commitment |
| Fee currency | USDC |
| Crystallization | Quarterly (для SMAs) / Annual (для commingled) |

---

### B2B / White-Label Channel

| Tier | AUM Range | SPA Revenue |
|------|-----------|-------------|
| API Read-only | Any | $500/мес |
| Sub-Advisory | $1M–$10M | 25% от партнёрского management fee |
| Enterprise | $10M+ | $5K–20K/мес + 15% rev share |

---

### Governance Token: рекомендация — отложить

**Условия для введения token (2028–2029 horizon):**
- AUM > $50M
- 2+ года верифицированного track record
- DAO-формат принят юридически
- Regulatory clarity в целевых юрисдикциях (EU MiCA, US)
- Utility четко определена (не securities)

---

## Итоговая сводка: 8 вопросов → 8 ответов

| Вопрос | Ответ |
|--------|-------|
| Management fee: сколько? | **1.0%** (competitive vs 1.5–2% TradFi, premium vs 0% Morpho/Yearn) |
| Management fee: как считать? | **Daily accrual** (AUM × rate/365), **quarterly payment** |
| Performance fee: сколько? | **15%** с HWM + soft hurdle 5% |
| HWM обязателен? | **Да, абсолютно.** Без HWM — не institutional-grade |
| Deposit/withdrawal fee? | **0%** (deposit), **0%** standard (опционально 0.1% early exit < 30 дней) |
| Lock-up periods? | **Нет жёстких.** 7-day notice > $50K; optional voluntary lock с APY bonus |
| Как конкурировать с free? | **Net yield > Morpho + risk framework + track record + compliance** |
| Fee token или USDC? | **USDC.** Governance token — только при $50M AUM + DAO stage |
| Operational AUM breakeven? | **$5M** (min viable), **$20M** (comfortable), **$50M** (full team) |
| B2B pricing? | **Rev share (25% from mgmt fee) + minimum $1K/мес** |

---

## Sources

- [Yearn Finance Docs — yVaults Overview](https://docs.yearn.fi/getting-started/products/yvaults/overview)
- [YIP-51: Set Vault v2 fee structure](https://yips.yearn.finance/YIPS/yip-51)
- [YIP-69: Reduce and cap fees through yRates](https://gov.yearn.finance/t/yip-69-reduce-and-cap-fees-through-yrates/12588)
- [Yearn Vaults V3 — Token Terminal](https://tokenterminal.com/resources/interview/yearn-vaults-v3)
- [Enzyme Finance V4 — Fees (User Docs)](https://userdocs.enzyme.finance/managers/setup/fees)
- [Performance Fee | Enzyme General Spec (v4)](https://specs.enzyme.finance/fee-formulas/performance-fee)
- [Enzyme Finance: Monetising your Vaults (Medium)](https://medium.com/enzymefinance/monetising-your-vaults-the-inner-workings-of-fees-on-enzyme-d5b275e7b9f5)
- [Ribbon Finance — Fees (Official Docs)](https://docs.ribbon.finance/theta-vault/theta-vault/fees)
- [Maple Finance — syrupUSDC Built for Scale](https://maple.finance/insights/syrupusdc-and-syrupusdc-built-for-scale)
- [Maple Finance: Onchain Asset Management (Tiger Research)](https://reports.tiger-research.com/p/maple-finance-onchain-asset-management-eng)
- [Maple Finance Is Pulling Institutional Credit On-Chain (Genfinity, 2026-06-04)](https://genfinity.io/2026/06/04/maple-finance-institutional-credit-on-chain-fee-compression/)
- [Morpho vs Aave 2026 Comparison (Fensory)](https://fensory.com/insights/compare/morpho-vs-aave)
- [DeFi Lending Is Growing Up: Aave, Morpho, Institutional Credit 2026 (VaaSBlock)](https://www.vaasblock.com/news/defi-lending-aave-morpho-institutional-credit-2026/)
- [Benchmarking Crypto Fund Fees and Expenses (Crypto Insights Group, July 2025)](https://www.cryptoinsightsgroup.com/insights/benchmarking-crypto-fund-fees-and-expenses)
- [Decoding Performance Fee Structure in Crypto Hedge Funds (21e6 Capital, Medium)](https://21e6.medium.com/decoding-the-performance-fee-structure-in-crypto-hedge-funds-a-detailed-analysis-from-the-21e6-909e59cb11c8)
- [Hedge Fund Fee Structures: 2-and-20, HWM, Hurdle Rates (Ryan O'Connell, CFA)](https://ryanoconnellfinance.com/hedge-fund-fee-structures/)
- [Fee Structures Demystified (O-CFO)](https://o-cfo.com/blog/structures-demystified-how-hedge-funds-calculate-management-performance-fee)
- [Solving the DeFi Yield Maze: Gen 3 Optimizers (DL News)](https://www.dlnews.com/research/internal/yo-report-solving-the-defi-yield-maze-rise-of-gen-3-optimizers/)
- [Institutionalizing Risk Curation in Decentralized Credit (arXiv, Dec 2025)](https://arxiv.org/html/2512.11976v1)
- [State of DeFi 2025 (DL News)](https://www.dlnews.com/research/internal/state-of-defi-2025/)
- [White Label Crypto Exchange Cost 2026 (Tronix Technologies)](https://www.troniextechnologies.com/blog/white-label-crypto-exchange-cost)
- [Trends in Hedge Fund Fee Structures (Hedge Fund Buyer)](https://hedgefundbuyer.com/blog/b/trends-in-hedge-fund-fee-structures)
- [Performance Fee — Wikipedia](https://en.wikipedia.org/wiki/Performance_fee)

---

*Отчёт подготовлен: 2026-06-18. Следующий review рекомендован: перед привлечением первого внешнего инвестора (~2027 Q1).*
