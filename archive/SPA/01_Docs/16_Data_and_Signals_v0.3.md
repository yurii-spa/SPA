# 16_Data_and_Signals

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01
Depends on: Context v0.3, Risk Policy v0.3, Monitoring & Alerts v0.3

Changelog from v0.2:
- Добавлен раздел 3.6 «Compliance Data» (OFAC/EU/UN).
- Добавлен раздел 4.4 «Кандидаты в provider stack» — конкретные провайдеры.
- Добавлен раздел 4.5 «Multi-chain rules».
- Добавлен раздел 4.6 «Cost considerations» ($50-150/месяц ориентир).
- Добавлен раздел 7.1 «Historical data» для paper trading.

---

## 1. Цель документа

Определяет источники данных, классы данных, приоритеты доверия и правила фолбэка.

**Данные всегда считаются потенциально ошибочными** — отказ от презумпции достоверности.

---

## 2. Классы данных

- **Market Data** — цены активов, peg-статусы
- **Protocol Data** — TVL, APY, utilization, governance
- **Execution Data** — gas, mempool, transaction status
- **Risk/Exposure Data** — наши позиции, доли, корреляции
- **Off-chain Signals** — Twitter security feeds, official protocol announcements
- **Compliance Data** — sanctions lists (см. 3.6)

---

## 3. Качество данных

Каждый источник имеет одно из состояний:
- **ok** — данные актуальны и согласованы;
- **degraded** — есть отклонение, но данные используемы с осторожностью;
- **broken** — данные не используемы → safe-mode на затронутую часть.

### Сигналы по off-chain
Off-chain сигналы **никогда не являются прямым триггером автоматических действий**. Только подтверждают контекст.

### 3.6. Compliance Data

- OFAC SDN list;
- EU restrictive measures;
- UN sanctions;
- внутренний blacklist.

Использование:
- проверка перед добавлением в whitelist (см. Whitelist Policy 4.1);
- ежедневная сверка адресов whitelisted-протоколов и Tail Risk Reserve.

При попадании whitelisted-адреса в санкционный список → **немедленный** алерт SEV-1.

---

## 4. Источники данных

### 4.1. On-chain
- Приоритет: собственные RPC > платные провайдеры > публичные RPC.
- Минимум 2 независимых RPC для каждой сети.

### 4.2. Oracle
- Chainlink (primary), Pyth (confirmation), RedStone (cross-check).
- Минимум 2 независимых oracle для critical price feeds.

### 4.3. Off-chain
- Официальные каналы протоколов;
- Security feeds (BlockSec, PeckShield, Cyvers);
- Минимум 3 независимых источника для подтверждения off-chain сигнала.

### 4.4. Provider stack (утверждён через ADR-003)

| Слой | Provider | Тип | Назначение |
|------|----------|-----|-----------|
| RPC primary | Alchemy | free tier → paid | основной on-chain |
| RPC backup | Ankr | freemium | fallback |
| RPC emergency | публичный node (ethereum.org) | free | аварийный |
| Oracle primary | Chainlink (on-chain) | free | основные цены |
| Oracle confirmation | Pyth (on-chain) | free | cross-check |
| Oracle tertiary | RedStone (on-chain) | free | verification |
| TVL/APY | DeFiLlama Pro API | ~$25/m | protocol data |
| Indexer | The Graph (subgraphs) | freemium | DeFi events |
| Block explorer | Etherscan API | freemium | tx history |
| Security feeds | BlockSec / PeckShield / Cyvers (X/Twitter) | free | early warnings |
| Compliance | OFAC SDN list (direct) | free | sanctions |

Бюджет ориентир: ~$110–125/месяц на старте.

### 4.5. Multi-chain rules
- Каждая поддерживаемая сеть имеет свой полный provider stack;
- cross-chain данные синхронизируются с пометкой блока, не времени;
- сравнение метрик across chains — только после явной нормализации;
- bridge между сетями — отдельный риск.

### 4.6. Cost considerations
- старт: free tiers где возможно;
- переход на paid: после 4 недель live или при превышении rate limits;
- бюджет потолок на Self-Capital: $200/месяц;
- на Fund — расширение до Chainalysis/TRM, dedicated infrastructure.

---

## 5. Refresh rates (нормальные)

| Класс | Refresh |
|-------|---------|
| Market data (Chainlink) | per block / heartbeat |
| Protocol TVL (DeFiLlama) | ~1 час |
| Sanctions lists | ежедневно |
| Security feeds | continuous |

Отклонения от нормальной refresh rate — degraded, не broken (если данные ещё свежие).

---

## 7. Paper trading and historical data

### 7.1. Historical data

Для paper trading требуется historical data:
- on-chain (через Dune Analytics, собственный archive RPC);
- APY history через DeFiLlama (период ≥ 12 месяцев);
- gas history через Etherscan gas tracker.

История baseline-данных используется для верификации paper trading simulation accuracy.

---

## 8. Условия выхода в v1.0

Data & Signals переходит в v1.0 после того как:
- provider stack успешно отработал 8 недель paper trading;
- проведена калибровка thresholds для degraded/broken;
- multi-chain rules проверены (после расширения на L2).

---

## 9. Статус и следующие шаги

Статус: Draft (целевой — Frozen после правок и ADR-003).
