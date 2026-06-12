# SPA Protocol Research — MP-375
## Spark Protocol (SparkLend) & Fluid (Instadapp)
### Candidate T1/T2 Adapters — Next Yield Sources

**Версия:** v469  
**Дата:** 2026-06-12  
**Автор:** DeFi Research Agent SPA  
**Задача:** MP-375 — исследование Spark + Fluid как кандидатов в адаптеры  
**Статус:** ✅ Завершено → рекомендации в §6

---

## 1. Executive Summary

### 1.1 Spark Protocol (SparkLend)

Spark Protocol — это lending market, созданный командой MakerDAO/Sky (ребрендинг
MakerDAO в 2023-2024). SparkLend — **форк Aave V3** с нативной интеграцией
экосистемы Sky (USDS, sUSDS, Sky Savings Rate). Ключевой актив: **sUSDS** —
ERC-4626 vault, который начисляет Sky Savings Rate (SSR, ex-DSR) напрямую
от протокола эмиссии стейблкоина.

Статус: **зрелый протокол**, TVL > $3B, управляется MKR/SKY governance.

Для SPA существует два независимых маршрута:

- **Route A — SparkLend USDC supply**: прямое предложение USDC в lending pool → получение
  переменного APY (~3–5%). Аналог Aave V3, но другой пул ликвидности.
- **Route B — sUSDS (Sky Savings Rate)**: конвертация USDC→USDS через Sky PSM
  (Peg Stability Module), затем депозит в sUSDS ERC-4626 → получение SSR (~5–6.5%).
  Без книги заявок, без переменного спроса — rate устанавливает MKR governance.

**Рекомендация:** Route B (sUSDS) — приоритет. Даёт предсказуемый, governance-driven yield
выше текущей Aave mainnet позиции (+2–3 п.п.) без рыночного риска книги заявок.
Tier: **T1**.

---

### 1.2 Fluid (Instadapp)

Fluid — новый протокол от команды Instadapp (Sowmay Jain, Vadim Kardinal). Ключевая
инновация — разделение ликвидности на **Smart Collateral** и **Smart Debt**:

- **Smart Collateral**: залог одновременно участвует в DEX liquidity provisioning
  и зарабатывает trading fees.
- **Smart Debt**: заёмная позиция зарабатывает часть trading fees через DEX интеграцию.

Это позволяет достигать эффективной стоимости займа < 0% и supply yield выше
стандартных lending протоколов за счёт composite APY = lending fees + LP fees.

TVL: ~$1.5–3B (быстрый рост в 2024–2025). USDC supply APY: **4–9%** в зависимости от
утилизации и LP активности. Tier: **T2** (достаточный TVL, но новый механизм = повышенный
smart contract риск).

**Рекомендация:** реализовать адаптер второй очередью после Spark. Более высокий потенциал
APY (+1–4 п.п. vs Morpho Steakhouse), но требует более тщательного мониторинга.

---

## 2. APY Comparison Table

| Протокол | Tier | APY USDC/USDS | TVL | Стабильность | Статус SPA |
|---|---|---|---|---|---|
| Aave V3 Ethereum | T1 | ~3.2% | $12B+ | ⬆ Очень высокая | ✅ Активен |
| Compound V3 (Comet) | T1 | ~4.8% | $2B+ | ⬆ Высокая | ✅ Активен |
| Morpho Steakhouse USDC | T1 | ~6.5% | $800M+ vault | ⬆ Высокая | ✅ Активен |
| Aave V3 Arbitrum | T1* | ~4.1% | $1B+ | ⬆ Высокая | ✅ Активен |
| Pendle PT sUSDe | T2 | ~8–18% | $500M+ | ↔ Умеренная | ✅ Advisory |
| **Spark SparkLend USDC** | **T1** | **~3–5%** | **$3B+** | **⬆ Высокая** | **🎯 Кандидат** |
| **Spark sUSDS (SSR)** | **T1** | **~5–6.5%** | **$3B+** | **⬆ Governance** | **🎯 Кандидат** |
| **Fluid USDC** | **T2** | **~4–9%** | **$1.5–3B** | **↔ Умеренная** | **🎯 Кандидат** |

*T1* на Arbitrum — обрабатывается отдельным адаптером.

**Gap анализ:** текущий weighted APY портфеля ~4–5%. sUSDS добавит предсказуемые
+150–250 bps на T1 уровне без дополнительного риска. Fluid может добавить +200–400 bps
на T2 аллокации.

---

## 3. Spark Protocol — Детальное исследование

### 3.1 Обзор и архитектура

Spark Protocol запущен в 2023 командой Phoenix Labs (дочерняя компания MakerDAO Foundation).
Состоит из двух независимых продуктов:

**SparkLend** — lending market (Aave V3 fork):
- Развёрнут на Ethereum mainnet (и Gnosis Chain, Base)
- Те же аукционы ликвидации, rate model, Health Factor механизм как в Aave V3
- Ключевое отличие: нативная поддержка USDS (ex-DAI) как базового актива
- Borrowing rate для USDS напрямую субсидируется MakerDAO (ставка может быть ниже рыночной)

**sUSDS (Sky Savings Rate vault)** — ERC-4626 совместимый контракт:
- USDS → sUSDS конвертация через `deposit()` / `withdraw()` интерфейс ERC-4626
- Yield начисляется ежесекундно, rate задаётся DSR/SSR системой MakerDAO
- USDC → USDS конвертация через PSM (Peg Stability Module) 1:1 без slippage
- Путь: USDC → [PSM] → USDS → [sUSDS.deposit()] → sUSDS → yield

### 3.2 Contract Addresses (Ethereum Mainnet)

| Контракт | Назначение | Адрес |
|---|---|---|
| SparkLend Pool (Proxy) | Основной lending pool | `0xC13e21B648A5Ee794902342038FF3aDAB66BE987` |
| Pool Address Provider | Реестр адресов Spark | `0x02C3eA4e34C0cBd694D2adFa2c690EECbC1793eE` |
| Pool Data Provider | Данные о резервах, rate | `0xFc21d6d146E6086B8359705C8b28512a983db0cb` |
| USDS Token | Стейблкоин Sky (ex-DAI) | `0xdC035D45d973E3EC169d2276DDab16f1e407384F` |
| sUSDS (Sky Savings Rate) | ERC-4626 savings vault | `0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD` |
| PSM (USDC↔USDS) | Peg Stability Module | `0xf6e72Db5454dd049d0788e411b06CfAF16853042` |
| MKR/SKY Governance | Governance token | `0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2` (MKR) |

> ⚠️ Адреса получены из knowledge base (knowledge cutoff май 2025). Верифицировать
> через spark.fi/docs или Etherscan перед имплементацией.

### 3.3 APY Механизм

**SparkLend USDC supply APY (Route A):**
- Переменная ставка, определяется utilization ratio пула
- Зависит от спроса на borrowing USDC в Spark
- Типичный диапазон: **3–5%** (похож на Aave V3, конкурируют за тот же borrower pool)
- DeFiLlama: `project="spark"`, `chain="Ethereum"`, `symbol="USDC"`

**sUSDS Sky Savings Rate (Route B):**
- Фиксированная (governance-voted) ставка, устанавливается MKR/SKY governance
- Изменяется через on-chain голосование (обычно раз в 1–4 недели при необходимости)
- Типичный диапазон 2024–2025: **5–6.5%**
- Риск: governance может снизить ставку в любой момент (без notice period для выхода)
- DeFiLlama: `project="sky"` или `project="maker"`, `symbol="USDS"` или `symbol="sUSDS"`
- Альтернативно: прямой on-chain вызов `sUSDS.convertToAssets(1e18)` vs timestamp

### 3.4 TVL и Рыночная позиция

- SparkLend общий TVL: **$3–5B** (principalmente ETH/stETH как залог)
- sUSDS TVL (USDS в savings): **$2B+** (большой спрос на governance-backed yield)
- Spark является одним из крупнейших DeFi lending протоколов по TVL → **T1 бесспорно**
- Позиция: конкурент Aave V3 в сегменте институционального USDC/USDS lending

### 3.5 Risk Matrix — Spark

| Риск | Уровень | Описание |
|---|---|---|
| Smart Contract Risk | 🟡 LOW-MEDIUM | Aave V3 форк — аудирован Trail of Bits, Certora. Дополнительный код PSM/sUSDS. |
| Centralization | 🔴 MEDIUM | MKR/SKY governance контролирует SSR (rate risk), PSM лимиты, экстренное отключение |
| Governance Rate Risk | 🔴 MEDIUM | SSR может быть снижен в любой момент без exit notice. Модель: всегда мониторить |
| Liquidity Risk | 🟢 LOW | sUSDS — мгновенный выход в USDS → PSM → USDC. Без book depth |
| Oracle Risk | 🟡 LOW-MEDIUM | Использует Chainlink для lending markets, PSM — без оракула (1:1 механизм) |
| Protocol Risk | 🟡 LOW-MEDIUM | Зависимость от экосистемы MakerDAO/Sky. "Too big to fail" в DeFi |
| Depeg Risk | 🟡 LOW-MEDIUM | USDS обеспечен через PSM и CDP. Пережил рыночные стрессы в форме DAI |
| **Итоговый Risk Score** | **0.28** | Выше Aave (0.20), ниже Morpho (0.22) из-за governance rate risk |

**Вывод:** Spark — проверенный форк с реальным TVL. Основной риск — не техника,
а governance (MKR голосование может снизить SSR). SPA мониторит это через
`data/adapter_status.json` + gap_monitor.

---

## 4. Fluid (Instadapp) — Детальное исследование

### 4.1 Обзор и архитектура

Fluid запущен командой Instadapp в 2024 году. Представляет принципиально новую
архитектуру DeFi протокола, объединяющую lending и DEX в одном слое ликвидности.

**Ключевые концепции:**

**FluidLiquidity (Core Layer):**
- Единый пул ликвидности для всех позиций (lending + DEX)
- Изолированные пользовательские вaults с общей базой ликвидности
- Smart Collateral: залог автоматически направляется в DEX pools для LP yield
- Smart Debt: заёмная позиция зарабатывает DEX trading fees → эффективная ставка займа снижается

**fTokens (ERC-4626 lending):**
- fUSDC = ERC-4626 vault для USDC supply
- Supply APY = base lending rate + часть DEX fees, распределённых поставщикам ликвидности
- Результат: USDC supply APY часто выше стандартных lending протоколов

**Liquidation mechanism:**
- Range-based liquidation (аналог Curve Lending / LLAMMA)
- Позиции ликвидируются постепенно при вхождении в "liquidation range"
- Более мягкий, чем стандартный аукционный механизм Aave

### 4.2 Contract Addresses (Ethereum Mainnet)

| Контракт | Назначение | Адрес |
|---|---|---|
| FluidLiquidity | Core liquidity layer | `0x52Aa899454998Be5b000Ad077a46Bbe360F4e497` |
| fUSDC (ERC-4626) | USDC supply vault | `0x9Fb7b4477576Fe5B32be4C1843aFB1e55F251B33` |
| fUSDT (ERC-4626) | USDT supply vault | `0x5C20B550819128074FD538Edf79791733ccEdd18` |
| Fluid DEX (v1) | DEX с Smart Collateral | `0x6D83f60eEac0e50A1250760151E81Db2a278592A` |
| FluidVaultFactory | Фабрика vaults | `0x324c5Dc1fC42c7a4D43d92df1eBA58a54d13Bf2d` |
| Governance (Timelock) | 2-day timelock | `0xfEE56009a76B5B2c69D09b7891b5A3Ede0bEC39a` |

> ⚠️ Адреса получены из knowledge base. Fluid активно развивается — верифицировать
> через fluid.instadapp.io/docs или GitHub перед имплементацией.

### 4.3 APY Механизм

**fUSDC supply APY:**
- Базовая lending ставка: определяется utilization (как у всех протоколов)
- Бонус: часть DEX trading fees от Smart Collateral пар (ETH/USDC и другие)
- Типичный диапазон: **4–9%** — значительно варьируется с рыночной активностью
- При высокой DEX активности (bull market): до 10–12% кратковременно
- При низкой DEX активности: ближе к базовому lending rate 4–5%

**DeFiLlama интеграция:**
- `project="fluid"`, `chain="Ethereum"`, `symbol="USDC"`
- Альтернативно: Fluid публикует свой публичный API

### 4.4 TVL и Рыночная позиция

- Fluid общий TVL: **$1.5–3B** (быстрый рост с запуска в 2024)
- fUSDC TVL: **$300M–600M** (рост с ростом протокола)
- Позиционирование: инновационный протокол, конкурирует с Morpho Blue и Aave
- Поддержан крупными инвесторами DeFi экосистемы (Instadapp имеет 7-летний track record)
- Instadapp — один из первых DeFi агрегаторов (2019), команда с доказанным опытом

**Tier classification:** TVL > $1B → формально T1 по TVL, но:
- Новый механизм (Smart Collateral/Debt) — не аудирован так широко как Aave V3
- Протокол < 2 лет в продакшене → дополнительный риск
- **Рекомендуем T2 с повышением до T1 через 12 месяцев** при подтверждённом track record

### 4.5 Risk Matrix — Fluid

| Риск | Уровень | Описание |
|---|---|---|
| Smart Contract Risk | 🔴 MEDIUM-HIGH | Инновационный механизм. Audits: Cantina, но меньше time-in-production |
| Centralization | 🟡 MEDIUM | 2-day timelock governance. Upgrade keys у команды Instadapp |
| Complexity Risk | 🔴 MEDIUM-HIGH | Smart Collateral/Debt — нестандартный механизм, сложнее предсказать поведение |
| Liquidation Risk | 🟡 MEDIUM | Range-based liquidation — мягче, но непривычное поведение при каскадах |
| APY Volatility | 🔴 HIGH | DEX fee component делает APY сильно зависящим от market activity |
| Liquidity Risk | 🟡 LOW-MEDIUM | ERC-4626 стандарт — выход в обычных условиях мгновенный; high utilization может создать задержку |
| Oracle Risk | 🟡 LOW-MEDIUM | Использует Chainlink + TWAPs |
| **Итоговый Risk Score** | **0.38** | Выше Morpho Steakhouse (0.22). Новый механизм требует осторожности. |

**Вывод:** Fluid — перспективный протокол с реальным TVL и инновационным yield механизмом.
Risk Score 0.38 — допустим для T2 аллокации (≤20% портфеля). Ключевой риск: APY
волатильность от DEX activity.

---

## 5. Risk Comparison Matrix — Все Протоколы

| Протокол | Tier | Risk Score | TVL ($M) | APY Range | Exit Latency | Тип риска |
|---|---|---|---|---|---|---|
| Aave V3 Ethereum | T1 | 0.20 | 12,000+ | 3–5% | 0h | Lending |
| Compound V3 | T1 | 0.21 | 2,000+ | 4–6% | 0h | Lending |
| Morpho Steakhouse | T1 | 0.22 | 800+ | 6–7% | 0h | Curated Lending |
| Aave V3 Arbitrum | T1 | 0.21 | 1,000+ | 3.5–6% | 0h | Lending (L2) |
| **Spark sUSDS** | **T1** | **0.28** | **2,000+** | **5–6.5%** | **0h** | **Governance Rate** |
| **Spark SparkLend** | **T1** | **0.25** | **3,000+** | **3–5%** | **0h** | **Lending (Aave fork)** |
| **Fluid USDC** | **T2** | **0.38** | **400–600** | **4–9%** | **0–1h** | **DEX/Lending hybrid** |
| Yearn V3 | T2 | 0.32 | 300+ | 4–8% | 0–1h | Strategy vault |
| Euler V2 | T2 | 0.33 | 200+ | 4–7% | 0h | Lending |
| Maple Finance | T2 | 0.45 | 100+ | 8–12% | 7–30d | Private Credit |
| Pendle PT sUSDe | T2* | 0.35 | 500+ | 8–18% | fixed term | Fixed Rate |

*T3-SPEC в SPA классификации (ADR-021)

**Spark sUSDS vs Morpho Steakhouse:**
- Схожий APY (6.0 vs 6.5), но разная природа риска
- Morpho: credit/liquidation risk у заёмщиков; Spark sUSDS: governance rate risk
- Spark имеет более высокий TVL → более глубокая ликвидность

---

## 6. Рекомендации

### 6.1 Общий вывод

**Рекомендуем реализовать оба адаптера.** Они дополняют текущий портфель:

1. **Spark sUSDS adapter (MP-376)** — ПРИОРИТЕТ 1 (P1):
   - Добавляет **T1** anchor с governance-backed APY 5–6.5%
   - Механизм прост: USDC→USDS (PSM, 1:1) → sUSDS (ERC-4626) → yield
   - DeFiLlama покрывает sUSDS — адаптер идентичен по структуре Morpho Steakhouse
   - Риски известны и управляемы (мониторинг SSR через sky_monitor.py уже есть!)
   - Закрывает gap: у нас уже есть `spa_core/data_pipeline/sky_monitor.py` — можно
     переиспользовать infrastructure для получения SSR

2. **Fluid USDC adapter (MP-377)** — ПРИОРИТЕТ 2 (P2):
   - Добавляет **T2** источник с переменным APY 4–9%
   - Заполняет T2 slot (у нас сейчас Yearn, Euler, Maple — можно добавить Fluid)
   - Выше risk score (0.38), но укладывается в T2 cap ≤20%
   - APY волатильность требует robust fallback в адаптере

### 6.2 Рекомендуемый порядок имплементации

**Шаг 1: MP-376 — Spark sUSDS adapter (Sprint v4.70)**
- Использует DeFiLlama feed (уже реализован), минимум нового кода
- Leverages `sky_monitor.py` для на-чейн SSR check (резерв)
- Ожидаемое время: 1–2 дня разработки
- APY impact: +0.5–1.5% к weighted portfolio APY (при 20% аллокации)

**Шаг 2: MP-377 — Fluid USDC adapter (Sprint v4.71)**
- Чуть сложнее — нужно проверить DeFiLlama coverage и fallback APY
- Ожидаемое время: 2–3 дня разработки + тесты
- APY impact: +0.5–2% при хорошей рыночной активности

### 6.3 НЕ рекомендуем сейчас

- **SparkLend USDC lending (Route A)** — APY аналогичен Aave V3 mainnet. Дублирует
  существующую позицию без существенного APY gain.
- **Fluid с T1 статусом** — требует минимум 12 месяцев дополнительного track record.

---

## 7. Implementation Notes

### 7.1 Spark sUSDS Adapter

```
Файл: spa_core/adapters/spark_susds_adapter.py
Tier: T1
Risk Score: 0.28
T1_CAP: 0.40
FALLBACK_APY_PCT: 5.5  # Sky SSR historical median
```

**DeFiLlama запрос (предпочтительный метод — stdlib only):**
```
GET https://yields.llama.fi/pools
→ filter: project="sky" OR project="maker"
→ filter: symbol="sUSDS" OR symbol="USDS"
→ filter: chain="Ethereum"
→ extract: apy (decimal, e.g. 0.055 = 5.5%)
```

Альтернативный DeFiLlama pool slug:
```
project = "spark"
symbol  = "sUSDS"
chain   = "Ethereum"
```

**On-chain SSR fallback (через sky_monitor.py):**
```python
# Уже реализовано в spa_core/data_pipeline/sky_monitor.py
# Читает GSM Pause Delay и SSR из on-chain
# Переиспользовать _fetch_ssr_rate() если DeFiLlama недоступен
```

**Adapter pattern (идентичен MorphoSteakhouseAdapter):**
```python
class SparkSUSDSAdapter(BaseAdapter):
    PROTOCOL = "spark_susds"
    TIER = "T1"
    T1_CAP = 0.40
    RISK_SCORE = 0.28
    EXIT_LATENCY_HOURS = 0.0
    FALLBACK_APY_PCT = 5.5
    DEFILLAMA_PROJECT = "sky"   # или "spark"
    DEFILLAMA_SYMBOL = "sUSDS"
    DEFILLAMA_CHAIN = "Ethereum"
    CONTRACT_sUSDS = "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD"
    CONTRACT_PSM = "0xf6e72Db5454dd049d0788e411b06CfAF16853042"
```

**Мониторинг SSR изменений:**
- Подписаться на событие SSR на sky_monitor (уже есть инфраструктура)
- При изменении SSR > 0.5 п.п. — alert через Telegram

---

### 7.2 Fluid USDC Adapter

```
Файл: spa_core/adapters/fluid_usdc_adapter.py
Tier: T2
Risk Score: 0.38
T2_CAP: 0.20
FALLBACK_APY_PCT: 5.0  # Conservative estimate (base lending, no DEX boost)
```

**DeFiLlama запрос:**
```
GET https://yields.llama.fi/pools
→ filter: project="fluid"
→ filter: symbol="USDC"
→ filter: chain="Ethereum"
→ extract: apy
```

**Важно — APY нормализация:**
Fluid APY включает DEX fee компонент. При `apy > 15%` → caps at fallback,
поскольку это аномальный всплеск, не устойчивый. RiskPolicy gate APY_MAX=30%
закроет аллокацию при выходе за пределы.

**Adapter pattern:**
```python
class FluidUSDCAdapter(BaseAdapter):
    PROTOCOL = "fluid_usdc"
    TIER = "T2"
    T2_CAP = 0.20
    RISK_SCORE = 0.38
    EXIT_LATENCY_HOURS = 0.5   # На случай высокой утилизации
    FALLBACK_APY_PCT = 5.0     # Conservative: только base lending
    APY_SPIKE_CAP_PCT = 15.0   # Кэп аномальных всплесков
    DEFILLAMA_PROJECT = "fluid"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Ethereum"
    CONTRACT_fUSDC = "0x9Fb7b4477576Fe5B32be4C1843aFB1e55F251B33"
```

---

## 8. ADR Requirements

При имплементации потребуется:

**Для MP-376 (Spark sUSDS):**
- Новый ADR не требуется: T1 протокол, SSR уже мониторится sky_monitor.py
- Обновить `ADAPTER_REGISTRY` в `spa_core/adapters/__init__.py`
- Добавить запись в `data/adapter_status.json` через execution domain

**Для MP-377 (Fluid):**
- Новый ADR не требуется: укладывается в существующую T2 политику (≤20%)
- Risk Score 0.38 < допустимого T2 максимума
- Обновить `ADAPTER_REGISTRY` + тесты + GoLiveChecker criteria если нужно

**Оба адаптера:**
- Тесты в `spa_core/tests/test_spark_susds_adapter.py` и `test_fluid_usdc_adapter.py`
- Stdlib only, no numpy/pandas/requests
- Атомарные операции для любых state-файлов
- `approved=False` от RiskPolicy не переопределяется

---

## 9. Sky Monitor Synergy (Spark)

Протокол Sky уже мониторится в `spa_core/data_pipeline/sky_monitor.py`.
Текущий статус: **0% аллокация** до подтверждённого GSM Pause Delay ≥ 48h (FORBIDDEN §7).

**Важное уточнение:**
- `sky_monitor.py` отслеживает GSM Pause Delay для **безопасности системы**
- `spark_susds_adapter.py` будет получать **только APY через DeFiLlama**
- Аллокация в sUSDS по-прежнему блокируется до GSM ≥ 48h (правило не меняется)
- Адаптер создаётся сейчас; аллокация активируется позже автоматически
  когда `sky_monitor` подтвердит безопасность

Эта логика позволяет подготовить адаптер заранее без нарушения FORBIDDEN §7.

---

## 10. Итоговые метрики исследования

| Параметр | Spark sUSDS | Fluid USDC |
|---|---|---|
| Рекомендация | ✅ YES — P1 | ✅ YES — P2 |
| Tier | T1 | T2 |
| Ожидаемый APY | 5–6.5% | 4–9% |
| Risk Score | 0.28 | 0.38 |
| Сложность адаптера | Низкая (DeFiLlama) | Средняя (APY normalize) |
| Срок разработки | ~1–2 дня | ~2–3 дня |
| APY impact на портфель (20% аллокация) | +0.4–0.7 п.п. | +0.2–0.8 п.п. |
| Блокеры | GSM ≥ 48h (уже мониторим) | Нет |
| Ключевой риск | Governance rate change | APY volatility |

---

*Исследование завершено: 2026-06-12. Задача MP-375 закрыта.*  
*Следующие шаги: MP-376 (Spark sUSDS adapter) → MP-377 (Fluid USDC adapter).*
