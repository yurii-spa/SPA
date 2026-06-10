# SPA ARCHITECTURE v2.0 — Институциональная машина

> Целевая архитектура для пути, описанного в `GRAND_VISION_v1.md`.
> Дата: 2026-06-10. Статус: проект (требует ADR для принятия).
> Принцип документа: каждый компонент помечен [ЕСТЬ] / [ЧАСТИЧНО] / [НЕТ],
> чтобы не путать целевое состояние с текущим.

---

## 1. Конституция системы (инварианты)

Эти правила не меняются ни на одной фазе. Они — продукт, а не ограничение.

1. **LLM FORBIDDEN на пути капитала.** Любой код, который строит, подписывает
   или отправляет транзакцию, а также вычисляет лимиты риска — строго
   детерминированный. LLM-агенты производят *предложения* (proposals),
   детерминированное ядро их *валидирует и исполняет*. [ЕСТЬ как принцип,
   ЧАСТИЧНО как enforcement]
2. **Risk Policy стоит на пути каждого доллара.** Ни один таргет аллокации не
   становится сделкой, не пройдя `RiskPolicy.check()`. [СЕЙЧАС НАРУШЕНО —
   аллокатор не вызывает policy; фикс — первый приоритет]
3. **Полная воспроизводимость.** Каждое решение восстанавливается из
   decision log: входные данные (snapshot id) → модель → результат → причина.
   [ЧАСТИЧНО — decision logger есть, snapshot-связность неполная]
4. **Капитал следует за треком.** Лимиты AUM повышаются только после
   выполнения объективных критериев (см. §8 Capital Ladder). [НЕТ — формализовать]
5. **Деградация — всегда в сторону безопасности.** Отказ данных/RPC/агента →
   система не делает ничего нового (freeze), а при пробое стопов → выходит в
   USDC. Никогда «не уверен — всё равно ребалансирую». [ЧАСТИЧНО]

---

## 2. Пять слоёв

```
                  ┌──────────────────────────────────────────────────┐
   ВНЕШНИЙ МИР    │  L5  CAPITAL & PRODUCT                           │
   (депозиторы,   │  ERC-4626 Vaults · Fee Module · White-label API  │
   фонды, DAO)    └───────────────────────┬──────────────────────────┘
                  ┌───────────────────────┴──────────────────────────┐
   ДОВЕРИЕ        │  L4  GOVERNANCE & TRUST                          │
                  │  Decision Audit Trail · Investor Reporting ·     │
                  │  Proof-of-Track · ADR-процесс · Compliance       │
                  └───────────────────────┬──────────────────────────┘
                  ┌───────────────────────┴──────────────────────────┐
   ДЕНЬГИ         │  L3  EXECUTION (детерминированный)               │
   (детерм. зона) │  Tx Builder · Simulation-before-send · MEV-      │
                  │  protect · Gnosis Safe + timelock · Nonce mgmt   │
                  ├──────────────────────────────────────────────────┤
                  │  L2  RISK (детерминированный)                    │
                  │  Risk Policy v2 · Оси риска · Exit-latency ·     │
                  │  Стресс-движок · Kill-switch · Capacity limits   │
                  └───────────────────────┬──────────────────────────┘
                  ┌───────────────────────┴──────────────────────────┐
   ИНТЕЛЛЕКТ      │  L1  INTELLIGENCE (LLM разрешён)                 │
   (LLM-зона)     │  Adapter SDK · Protocol Discovery · Cross-chain  │
                  │  Data · Allocator · Agents (CEO/Alpha/Research)  │
                  └──────────────────────────────────────────────────┘
```

Граница «LLM-зона / детерминированная зона» проходит между L1 и L2 и
оформляется кодом: L2/L3 не импортируют ни одного LLM-клиента (проверяется
CI-линтом: запрет import anthropic/google.generativeai в risk/, execution/,
allocator/). [НЕТ — добавить CI-гейт]

---

## 3. L1 — Intelligence Layer

### 3.1 Adapter SDK (5 → 50 → 100+ протоколов)

Сейчас каждый адаптер — рукописный файл [ЕСТЬ: 5 шт.]. Для масштаба нужен SDK:

```python
class ProtocolAdapter(ABC):           # единый контракт
    meta: AdapterMeta                 # protocol_id, tier, chains, risk_axes
    def fetch_pools(self) -> list[PoolSnapshot]      # APY, TVL, util, liquidity
    def exit_latency(self) -> ExitProfile            # мгновенно / очередь / срок
    def health(self) -> HealthReport                 # свежесть, аномалии
```

- **Декларативные адаптеры:** для 80% протоколов хватает YAML-манифеста
  (DeFiLlama pool ids + параметры качества) — кодовый адаптер нужен только
  для нестандартных (Pendle PT discount-кривая, Maple очереди). Это
  единственный способ дойти до 100+ без 100 файлов. [НЕТ]
- **Candidate-tier pipeline** (расширение SPA-V417): автоскан DeFiLlama по
  quality-gates (TVL ≥ $5M, возраст ≥ 6 мес, аудиты, листинг-чеклист) →
  реестр кандидатов → Protocol Research Agent готовит досье → человек (позже
  governance) промоутит в whitelist. Автодискавери НЕ добавляет протоколы в
  аллокацию сам — только в кандидаты. [НЕТ]
- **Домены не смешиваются:** read-only фиды живут в `spa_core/adapters/`,
  исполнение — в `spa_core/execution/` (действующее правило, сохранить).

### 3.2 Cross-chain data

- Цель Phase 3: Ethereum + Arbitrum + Base (где реально живёт stable-ликвидность);
  Phase 4: + Optimism, Polygon, Avalanche по мере ёмкости. [ЧАСТИЧНО — пайплайн
  знает про сети, аллокация фактически single-chain]
- Каждый PoolSnapshot несёт `chain`, Risk Policy ограничивает per-chain
  (`max_single_chain_allocation` уже есть) и учитывает bridge-риск как ось.

### 3.3 Allocator v2

[ЕСТЬ v1: risk-adjusted + tier caps + T1-якорь.] Развитие:

- Вход: candidate pools (после RiskPolicy-префильтра!), ковариации (есть
  модуль), exit-профили, utilization.
- Модели: текущие (equal/best_apy/risk_parity/risk_adjusted) + CVaR-оптимизация
  и capacity-aware веса (вес ограничен долей от TVL пула, напр. ≤ 1–2% TVL —
  критично при AUM $10M+). [НЕТ capacity-логики]
- Выход — `AllocationProposal`, который L2 либо одобряет, либо режет. Аллокатор
  никогда не пишет финальный таргет в обход Risk.

---

## 4. L2 — Risk Layer (детерминированный)

### 4.1 Risk Policy v2 — оси риска вместо одних тиров

Текущие tier-caps [ЕСТЬ] не различают ПРИРОДУ риска (вывод ANALYST_REPORT:
Maple credit-риск тарифицируется как Aave). Вводим оси:

| Ось | Примеры | Лимит (старт) |
|---|---|---|
| smart_contract | все | suммарно 100%, но per-protocol по тирам |
| credit (недообеспеченные) | Maple | ≤ 15% портфеля |
| peg/synthetic | Ethena sUSDe, agEUR | ≤ 10%, мониторинг funding/peg |
| duration/fixed-term | Pendle PT, Notional | ≤ 30%, ladder по maturity |
| bridge/chain | всё вне Ethereum | ≤ 50% L2 (есть), per-bridge cap |

### 4.2 Ликвидность выхода

Каждый адаптер обязан декларировать `exit_latency_h` (Aave ~0ч, Maple —
очередь дни/недели, Pendle PT — до maturity либо рынок с дисконтом).
Жёсткое правило: **доля портфеля с exit_latency > 72ч ≤ 25%**, и kill-switch
исполняет сначала ликвидную часть. [НЕТ — критично до live]

### 4.3 Стресс-движок и defensive mode

- Сценарии: депег стейбла −2%, одновременный отток TVL −40% в 3 протоколах,
  дефолт Maple-пула, APY-коллапс до 1%. Прогон еженедельно на текущем портфеле,
  результат — в go-live/health гейты. [НЕТ]
- Defensive mode: drawdown > 3% → выход в чистый USDC (не в «следующий пул»),
  re-entry только по правилу (N дней стабильности). [НЕТ]

### 4.4 Capacity limits (институциональное требование)

При AUM $10M+: позиция ≤ X% TVL пула, ≤ Y% дневного объёма выхода. Без этого
стратегия, дающая 7% на $100K, даст 5% на $10M — модель доходности обязана
это показывать честно (capacity-adjusted APY в отчётах). [НЕТ]

---

## 5. L3 — Execution Layer (детерминированный)

[ЧАСТИЧНО: eth_signer + Flashbots MEV-protect написаны, не тестированы в сети.]

Целевой pipeline исполнения:

```
AllocationTarget (одобрен L2)
  → DiffPlanner: текущие позиции vs таргет → список операций
  → TxBuilder: calldata per протокол (execution-адаптеры)
  → Simulator: eth_call / Tenderly-fork симуляция КАЖДОЙ tx → ожидаемый результат
  → SafetyChecks: slippage-бюджет, gas-бюджет, балансы, allowances, лимиты L2
  → Signer: EIP-1559, Flashbots Protect (mainnet) / private RPC
  → Confirmer: ожидание включения, re-org защита, ретраи
  → Reconciler: фактические балансы on-chain == ожидаемые? Расхождение → freeze + алерт
```

- **Custody:** Gnosis Safe как владелец средств; hot-key — только executor-роль
  с модулем ограничений (Zodiac Roles: только whitelisted-контракты, только
  whitelisted-методы, лимиты сумм). Человеческие подписи нужны для: смены
  whitelist, поднятия лимитов, вывода за пределы Safe. [НЕТ — обязательный
  компонент до первого внешнего доллара]
- **Timelock** на изменения whitelist/policy в проде. [НЕТ]
- **Live E2E harness** (SPA-V384, anvil/mainnet-fork) — обязательный CI-гейт
  для каждого релиза execution-кода. [ready в backlog]

---

## 6. L4 — Governance & Trust Layer

Это слой, который продаёт систему институционалам. Технически прост, ценностно — главный.

- **Decision Audit Trail** [ЧАСТИЧНО]: связать в одну цепочку snapshot_id →
  proposal → risk-вердикт → tx hash. Экспорт: подписанный JSONL + периодический
  Merkle-root этого лога, публикуемый on-chain → **Proof-of-Track: трек
  невозможно переписать задним числом**. Дёшево (~1 tx/день), а в pitch'ах —
  убойный аргумент. [НЕТ]
- **Investor Reporting** [ЧАСТИЧНО — PDF есть]: месячный tear sheet (APY net,
  Sharpe/Sortino/PSR, drawdown, exposure по осям риска, инциденты), авто-рассылка.
- **ADR-процесс** [ЕСТЬ] — сохранить; любые изменения Risk Policy / whitelist /
  fee — только через ADR.
- **Compliance-заготовки:** гео-ограничения на vault-депозиты, AML-скрининг
  адресов депозиторов (Chainalysis/TRM API), отчётность по юрисдикции фонда. [НЕТ]

---

## 7. L5 — Capital & Product Layer

- **ERC-4626 Vaults** — стандартный интерфейс = автоматическая совместимость
  с агрегаторами, казначейскими платформами, DeBank/Zapper. Три профиля:
  - `spaUSD-C` Conservative: T1-only + Pendle PT ≤ 20%, цель 4.5–6%;
  - `spaUSD-B` Balanced: текущий профиль политики, цель 6–8%;
  - `spaUSD-A` Aggressive: + capped Ethena/credit, цель 8–12%.
  Контрактный минимализм: vault хранит и учитывает; решения по аллокации
  приходят из off-chain ядра через executor-модуль с ограничениями. [НЕТ]
- **Fee Module:** mgmt fee стримится с TVL, performance fee — high-watermark.
  Прозрачные on-chain начисления. [НЕТ]
- **White-label API** (B2B, Phase 4): `POST /v1/portfolio/analyze` (их позиции →
  наш риск-скоринг), `GET /v1/allocations/recommended` (наш таргет под их
  мандат), webhook-сигналы ребаланса. Это монетизация мозга без кастоди —
  ниже регуляторный риск, выше маржа. [НЕТ; FastAPI-каркас ЕСТЬ]

---

## 8. Capital Ladder (формализация «капитал следует за треком»)

| Ступень | AUM cap | Условие подъёма на ступень |
|---|---|---|
| L0 paper | $100K virtual | — (текущая) |
| L1 pilot | $50K real (own) | 30 дней живого paper-трека, E2E harness зелёный, Safe настроен |
| L2 own | $1M (own) | 90 дней live без инцидентов, APY ≥ benchmark+1пп, drill kill-switch пройден |
| L3 friends | $5M (own+близкие) | аудит #1 пройден, юр. структура, страховой буфер 0.5% AUM |
| L4 external | $25M | 12 мес трека, аудит #2, bug bounty, Proof-of-Track on-chain |
| L5 institutional | $100M+ | 24 мес трека, 3 аудита, команда 5+, SOC-подобные процедуры |

Подъём по ступени — ADR + Owner approval. Автоматический спуск: инцидент
≥ 1% AUM → минус одна ступень немедленно.

---

## 9. Суб-агентная архитектура (целевая)

Принцип: агенты = аналитики и операторы, ядро = исполнитель. Каждый агент
имеет письменный мандат, бюджет токенов и список того, что ему ЗАПРЕЩЕНО.

| Агент | Модель (класс) | Мандат | Запрещено |
|---|---|---|---|
| **CEO** | топ-модель (Sonnet/Opus-класс) | синтез недельной картины, эскалации Owner'у, приоритизация бэклога, ответы депозиторам | менять policy, инициировать tx |
| **Alpha** | средняя модель | скан новых источников доходности (Pendle-рынки, новые пулы), оценка ёмкости и устойчивости APY, предложения в candidate-tier | добавлять в whitelist напрямую |
| **Protocol Research** | топ-модель, редкие вызовы | due-diligence досье кандидата: аудиты, команда, инциденты, TVL-история, governance-риски → структурированный отчёт к ADR | финальное решение о листинге |
| **Risk Sentinel** | — (детерминированный) + малая модель для классификации алертов | мониторинг лимитов, drawdown, depeg-фиды, аномалии APY/TVL; классификация: «шум / деградация / инцидент» | переопределять policy (вердикт policy финален) |
| **Execution** | — (строго детерминированный) | diff-план → simulate → sign → confirm → reconcile | любая LLM-логика |
| **Reporting** | средняя модель | tear sheets, investor updates, объяснение решений человеческим языком из decision log | искажать цифры (источник — только данные, шаблонная валидация) |
| **Incident Commander** | средняя модель | при инциденте: сбор контекста, таймлайн, черновик post-mortem, чеклист реагирования | исполнять «исправляющие» транзакции |

Координация: текущий LangGraph-граф [ЕСТЬ] эволюционирует в event-driven
шину [ЕСТЬ SQLite pub/sub] с тремя контурами:

- **Fast loop (4ч, без LLM):** data → risk → allocator → execution. Работает
  даже если все LLM недоступны. Это требование автономности 95%.
- **Slow loop (ежедневно, LLM):** Alpha + Risk Sentinel анализ, Reporting.
- **Strategic loop (еженедельно, LLM):** CEO-синтез, Protocol Research,
  предложения изменений через ADR.

Деградация: недоступен LLM → fast loop продолжает с последней одобренной
конфигурацией; ничего нового не листится, лимиты не меняются.

---

## 10. Инфраструктура и миграции

| Компонент | Сейчас | Phase 3 | Phase 4 |
|---|---|---|---|
| Планировщик | GH Actions 4ч + ручное | launchd/systemd на выделенном сервере (V413) + GH Actions как резерв | k8s/Nomad, мультирегион, leader election |
| Хранилище | SQLite + JSON | Postgres (сделки, решения, снапшоты); JSON остаётся для дашборда | + TimescaleDB для тайм-серий, S3-архив |
| Секреты | env/Keychain | Vault/SOPS, отдельные ключи per-окружение | HSM/MPC (Fireblocks/Turnkey) для подписи |
| RPC | публичные + fallback | платные (Alchemy/Infura) ×2 провайдера | + собственная нода для критичных чтений |
| Мониторинг | health JSON + Telegram | Grafana/Prometheus, PagerDuty-стиль алерты | 24/7 on-call ротация, Hypernative/Forta security-фиды |
| CI-гейты | pytest | + LLM-import линт (L2/L3), E2E fork-harness, anti-demo гейты | + формальная верификация инвариантов vault |

---

## 11. Безопасность (сводный чеклист до внешнего капитала)

1. Два независимых аудита execution + vault (Spearbit/Cantina/ToB-класс).
2. Bug bounty (Immunefi), стартовый пул $50–250K.
3. Zodiac Roles на Safe: hot-key умеет ТОЛЬКО whitelisted методы.
4. Timelock 24–48ч на изменения whitelist/policy/fee.
5. Rate-limits исполнения: ≤ X% AUM перемещается за 24ч без доп. подписи.
6. Prompt-injection поверхность: LLM-агенты не имеют tool'ов записи в
   policy/whitelist/execution-конфиги (только PR/proposal-артефакты).
7. Страховой буфер 0.5–1% AUM + рассмотреть Nexus Mutual-класс покрытие.
8. Регулярные kill-switch drills (V416) — с измеряемым временем выхода в USDC.

---

## 12. Что строим в первую очередь (мост от сегодня к этой архитектуре)

Порядок важнее полноты. Первые 5 шагов:

1. **RiskPolicy в allocation-путь** (инвариант №2 сейчас нарушен) — ~30 строк,
   закрывает governance gap из ANALYST_REPORT.
2. **Расписание трека** (V413) + anti-demo гейты (V412) — трек = главный актив компании.
3. **Pendle PT + Sky read-фиды** (V409/V410) — без них APY-потолок 4.7% и
   продукт нечего продавать.
4. **E2E fork-harness** (SPA-V384) → live-пилот $10–50K через Safe — первый
   реальный доллар важнее десятого аналитического модуля.
5. **Exit-latency атрибут в адаптерах** — дешёво сейчас, невозможно дорого потом.

---

*Связано: `GRAND_VISION_v1.md` (зачем), `ROADMAP_v2.md` (когда), действующее
правило разделения доменов адаптеров (read-only vs execution).*
