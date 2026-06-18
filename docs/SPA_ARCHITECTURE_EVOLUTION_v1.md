# SPA Platform — Architecture Evolution v1.0
> **Тип:** Архитектурный дизайн-документ (ADR-уровень, не код)  
> **Автор:** Senior Solutions Architect  
> **Дата:** 2026-06-18  
> **Статус:** DRAFT для review  
> **Спринты:** ПАУЗИРОВАНЫ — только проектирование  
> **Контекст:** earn-defi.com зарегистрирован, Cloudflare Tunnel HEALTHY, go-live target 2026-08-01

---

## Содержание

1. [Архитектура инфраструктуры](#1-архитектура-инфраструктуры)
2. [Landing Page — концепция и структура](#2-landing-page)
3. [Admin Panel + User Cabinet](#3-admin-panel--user-cabinet)
4. [DevOps Pipeline](#4-devops-pipeline)
5. [Roadmap к Production](#5-roadmap-к-production)
6. [Deep Research Промпты](#6-deep-research-промпты)

---

## 1. Архитектура инфраструктуры

### 1.1 Принцип разделения ответственности

Ключевой вопрос: что должно жить на Mac Mini, а что выносить в облако?

**Правило:** Mac Mini — это мозг (исполнение стратегий, RiskPolicy, paper/live trading). Облако — это лицо (статика, CDN, публичные API). Разделение должно быть жёстким: никакой бизнес-логики в облаке, никакой публичной статики на Mac Mini.

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERNET / USERS                          │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────▼──────────────┐
          │      Cloudflare (Edge)       │
          │  DNS + WAF + DDoS + Cache    │
          │  earn-defi.com               │
          └──────┬───────────┬───────────┘
                 │           │
    ┌────────────▼──┐   ┌────▼──────────────────┐
    │ Cloudflare    │   │  Cloudflare Tunnel     │
    │ Pages         │   │  (cloudflared)          │
    │ (Static CDN)  │   │  Mac Mini ← → CF Edge  │
    │               │   │                         │
    │ earn-defi.com │   │ api.earn-defi.com       │
    │ (Landing)     │   │ dashboard.earn-defi.com │
    └───────────────┘   └────────────┬────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │       MAC MINI           │
                        │  (Primary Server)        │
                        │                          │
                        │  :8765 Family Fund API   │
                        │  :8766 Dashboard static  │
                        │  launchd 19 agents       │
                        │  cycle_runner (08:00)    │
                        │  data/ (state files)     │
                        └──────────────────────────┘
```

### 1.2 Что остаётся на Mac Mini (NEVER выносить)

| Компонент | Причина |
|-----------|---------|
| `cycle_runner.py` и все стратегии S0–S13 | Детерминированная бизнес-логика, LLM FORBIDDEN |
| `RiskPolicy` + `EmergencyBreakers` | Критический путь капитала, нельзя распределять |
| `data/` — все JSON state файлы | Single source of truth, атомарные записи |
| `spa_core/adapters/` — DeFi адаптеры | Runtime зависит от локального Python/stdlib |
| `spa_core/execution/` — execution домен | Gnosis Safe signing через локальный кошелёк |
| Telegram bot (long-poll) | Stateful процесс, требует persistent connection |
| launchd-агенты (19 шт.) | macOS-specific, привязаны к системе |
| Keychain secrets | Физически не может покинуть машину — это хорошо |

### 1.3 Что выносить в облако

| Сервис | Куда | Причина |
|--------|------|---------|
| Landing page (earn-defi.com) | **Cloudflare Pages** | Статика, глобальный CDN, 0 latency, бесплатно |
| Публичный дашборд (dashboard.earn-defi.com) | **Через Cloudflare Tunnel** к Mac Mini :8766 | Динамические данные из data/*.json, рендерится локально |
| API для инвесторов (api.earn-defi.com) | **Через Cloudflare Tunnel** к Mac Mini :8765 | Данные живут локально, туннель только проксирует |
| CI/CD логи и артефакты | **GitHub Actions** | Уже есть, расширять |
| Мониторинг uptime | **BetterStack** (free tier) | Внешняя проверка доступности тоннеля |
| Error tracking | **Sentry** (free tier, self-hosted SDK) | Исключения из Python без отправки данных наружу |

### 1.4 Cloudflare Pages vs Tunnel vs VPS — что для чего

**Cloudflare Pages** → Landing page earn-defi.com
- Плюсы: бесплатно, глобальный CDN, preview deployments, auto-deploy из GitHub
- Минусы: только статика (HTML/CSS/JS)
- Решение: Next.js или Astro с `output: 'static'` — генерируют статику, деплоятся в Pages

**Cloudflare Tunnel (уже есть, HEALTHY)** → dashboard.earn-defi.com + api.earn-defi.com
- Плюсы: уже работает, не нужен публичный IP, DDoS защита Cloudflare
- Минусы: зависит от Mac Mini uptime (RPO = время восстановления Mac)
- Решение: это приемлемо для текущей фазы (family fund, не публичный продукт)

**VPS** → НЕ нужен сейчас. Рассмотреть при:
- AUM > $500K (нужен 99.9% uptime, не зависящий от домашней сети)
- Публичный продукт (Investor Cabinet для внешних клиентов)
- Требование от инвесторов о независимой инфраструктуре

Рекомендация на Q3 2026: добавить **Hetzner CX21** (€4/мес) как cold standby — туда реплицируются data/*.json каждые 15 минут. При падении Mac Mini активируется вручную за 15 минут.

### 1.5 Разделение окружений

```
DEV (локальный Mac Mini)
├── порты: 8765, 8766 (как сейчас)
├── домен: localhost или dev.earn-defi.com (CF Pages Preview)
├── данные: data/ (реальные)
└── команды: python3 -m spa_core.paper_trading.cycle_runner --dry-run

STAGING (Mac Mini, другой набор портов)
├── порты: 8775 (API), 8776 (dashboard)
├── домен: staging.earn-defi.com → CF Tunnel к :8775/:8776
├── данные: data/staging/ (изолированы от prod)
└── запуск: отдельный launchd с суффиксом .staging

PROD (Mac Mini, основные порты)
├── порты: 8765 (API), 8766 (dashboard)
├── домен: dashboard.earn-defi.com, api.earn-defi.com
├── данные: data/ (prod state)
└── деплой: только через GitHub Actions + manual approval
```

**Критическое правило:** staging и prod — на одной машине, но с разными `data/` директориями и разными launchd plist файлами. Промышленные решения (отдельный VPS для staging) избыточны до $100K AUM.

### 1.6 Полная схема сервисов

```
earn-defi.com              → Cloudflare Pages  (Landing, статика)
dashboard.earn-defi.com    → CF Tunnel → Mac Mini :8766  (Dashboard index.html)
api.earn-defi.com          → CF Tunnel → Mac Mini :8765  (Family Fund API)
staging.earn-defi.com      → CF Tunnel → Mac Mini :8776  (Staging dashboard)
api-staging.earn-defi.com  → CF Tunnel → Mac Mini :8775  (Staging API)
status.earn-defi.com       → BetterStack status page     (Uptime публичная)
```

**Конфигурация Cloudflare Tunnel** (`config.yml`):
```yaml
ingress:
  - hostname: dashboard.earn-defi.com
    service: http://localhost:8766
  - hostname: api.earn-defi.com
    service: http://localhost:8765
  - hostname: staging.earn-defi.com
    service: http://localhost:8776
  - service: http_status:404
```

---

## 2. Landing Page

### 2.1 Позиционирование

**Что мы НЕ говорим:** "высокодоходные инвестиции", "гарантированная прибыль", "DeFi для всех".

**Что мы говорим:**

> **SPA — Autonomous DeFi Yield Infrastructure**
> Algorithmic yield optimization across battle-tested DeFi protocols.
> Currently in paper-trading mode. Track record since June 2026.

Тон: серьёзный, технически грамотный, прозрачный. Аудитория уровня — Enzyme Finance, Yearn Finance, не Binance Earn.

**Ключевые сообщения по секциям:**

1. "We optimize yield, not risk. Every position passes deterministic RiskPolicy before execution."
2. "Paper track record since Day 1 — full equity curve, no gaps, publicly verifiable."
3. "Built for family office scale first. External AUM by invitation only."
4. "Open-source core. Audited risk framework. No LLM in execution path."

### 2.2 Структура секций

```
┌─────────────────────────────────────────────┐
│  HERO                                        │
│  Headline: "Autonomous Yield. Verified Track."│
│  Subheadline: текущий APY + дней трека       │
│  CTA: "View Live Dashboard" + "Request Access"│
│  Live counter: Days tracking / Current APY   │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  LIVE STATS (real-time, pull from API)       │
│  • Track Record: N days, 0 gaps              │
│  • Current APY: 10.1% (paper)                │
│  • Protocols Active: 14                      │
│  • Virtual AUM: $100K                        │
│  • Strategy Tournament: S0–S13               │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  HOW IT WORKS (3 шага)                       │
│  1. Algorithm scans 14+ DeFi protocols       │
│  2. RiskPolicy validates every rebalance     │
│  3. Daily cycle executes optimal allocation  │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  PROTOCOLS (логотипы)                        │
│  Aave · Compound · Morpho · Pendle           │
│  Spark · Euler · Yearn · Maple · sFRAX       │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  RISK FRAMEWORK                              │
│  "Deterministic, not probabilistic"          │
│  • TVL floor: $5M minimum per pool           │
│  • Protocol cap: 40% T1 / 20% T2            │
│  • Kill-switch: 5% drawdown → close all      │
│  • Zero LLM in risk/execution path           │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  TEAM (минималистично)                       │
│  "Built by a quant with 10+ years..."        │
│  Ссылка на GitHub для технических            │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  CTA / WAITLIST                              │
│  "Join Family Fund Waitlist"                 │
│  Email форма (сохраняется локально или Airtable)│
│  Или: "For institutional inquiries: email"   │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  LEGAL FOOTER                                │
│  • "Paper trading only. Not financial advice."│
│  • Privacy Policy                            │
│  • "Not available to US persons"            │
│  • Юрисдикция                               │
└─────────────────────────────────────────────┘
```

### 2.3 Рекомендации по стеку

**Выбор: Astro + Tailwind CSS + деплой на Cloudflare Pages**

Почему Astro, а не Next.js / Webflow:

| Критерий | Astro | Next.js | Webflow |
|----------|-------|---------|---------|
| Bundle size | Минимальный (0 JS по умолчанию) | Больше | Большой |
| CF Pages deploy | Нативно | Требует адаптер | Нельзя (свой хостинг) |
| Live data из API | Islands (React/Svelte компонент) | SSR/ISR | Webhooks |
| Кривая обучения | Низкая | Средняя | Низкая (no-code) |
| Кастомизация | Полная | Полная | Ограниченная |
| Стоимость | $0 | $0 | $23–$39/мес |

Astro позволяет: статический сайт с "islands" — изолированными React/Svelte компонентами для live stats (они дёргают api.earn-defi.com каждые 60 секунд).

**Конкретные шаблоны на GitHub:**

1. **https://github.com/onwidget/astrowind** — AstroWind
   - Tailwind, тёмная тема, секции Hero/Features/Stats/CTA
   - Звёзды: 3.5K+, активно поддерживается
   - Идеально как базис — меняем контент, добавляем Live Stats island

2. **https://github.com/saadeghi/daisyui** — DaisyUI компонент-библиотека
   - Tailwind CSS компоненты, 35+ тем включая финансовые
   - Использовать для Stats карточек и таблиц протоколов

3. **https://github.com/cruip/open-react-template** — OpenReact
   - Если выбираем Next.js: dark theme, SaaS/fintech стиль
   - Секции: Hero, Features, Pricing, Testimonials

4. **https://github.com/shadcn-ui/ui** — shadcn/ui
   - Для Admin Panel и Investor Cabinet (не Landing)
   - Radix UI + Tailwind, продакшн-качество

**Финальная рекомендация стека:**
```
Landing: Astro + Tailwind + AstroWind шаблон → Cloudflare Pages
Admin/Cabinet: Next.js 14 App Router + shadcn/ui + Tailwind → CF Pages
API: FastAPI (Python) на Mac Mini :8765 → CF Tunnel
Данные: прямые запросы к data/*.json через API
```

---

## 3. Admin Panel + User Cabinet

### 3.1 Конкурентный анализ (что берём из опыта рынка)

**Nexo (nexo.io/account)**
- Берём: Clean portfolio overview, yield calculator, 1-click allocation
- Не берём: Кредитная линия, сложные продукты не нужны на старте

**Maple Finance (maplefinance.com)**
- Берём: Pool performance cards, borrower breakdown, detailed docs раздел
- Берём: Yield history chart (area chart, не line)
- Берём: Risk indicators в виде цветовых маркеров (зелёный/жёлтый/красный)

**Enzyme Finance (enzyme.finance)**
- Берём: Vault details page — полный breakdown активов, цена пая
- Берём: Policy enforcement visualization — показывать что именно ограничивает
- Берём: Public vault page (read-only для не-инвесторов)

**dHEDGE (dhedge.org)**
- Берём: Manager card с track record (Sharpe, DD, APY)
- Берём: Strategy Tournament view — чем-то похоже на наш tournament

**Yearn Finance (yearn.fi)**
- Берём: Vault cards с APY, TVL, risk badge
- Берём: Минимализм — не перегружать интерфейс

### 3.2 Иерархия ролей

```
SUPER_ADMIN (только Юрий)
├── Полный доступ ко всему
├── Управление ролями
├── Активация live trading (execute activate.py)
├── Просмотр сырых логов и state files
└── Emergency controls (kill-switch, EB-01..EB-05)

FUND_MANAGER (доверенный соратник)
├── Просмотр всех позиций и стратегий
├── Strategy tournament управление (promote/demote)
├── Risk limit review (не изменение)
└── Investor onboarding approval

INVESTOR (участник Family Fund)
├── Собственный портфель (P&L, доля, история)
├── Documents (договір, statements)
├── Notifications (Telegram-linked)
└── Referral link

OBSERVER (потенциальный инвестор, на review)
├── Публичная статистика (APY, track record)
├── Request access форма
└── НЕТ: финансовых данных
```

### 3.3 Investor Cabinet — экраны

#### Экран 1: Dashboard (главный)

```
┌────────────────────────────────────────────────────────┐
│  Добро пожаловать, [Имя]                  [Выход]      │
│                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Ваш баланс   │  │ Доход YTD    │  │ APY текущий  │ │
│  │ $25,000.00   │  │ +$1,847.32   │  │   10.1%      │ │
│  │ +2.3% за мес │  │ +7.4% годовых│  │  paper mode  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                        │
│  EQUITY CURVE (Area chart, 30 дней)                    │
│  ▁▂▃▄▅▆▇█  [1W] [1M] [3M] [All]                       │
│                                                        │
│  ТЕКУЩИЕ ПОЗИЦИИ                                       │
│  Protocol        Ваша доля   APY    % портфеля        │
│  Morpho          $8,200      6.5%   32.8%             │
│  Aave V3         $6,100      3.5%   24.4%             │
│  Compound V3     $4,900      4.8%   19.6%             │
│  ...                                                   │
└────────────────────────────────────────────────────────┘
```

#### Экран 2: Yield History (детальная история)

```
┌────────────────────────────────────────────────────────┐
│  История доходности                                    │
│                                                        │
│  [Месяц▼] [Квартал] [Год]  Экспорт CSV                │
│                                                        │
│  Дата       Начало       Конец        Yield    APY     │
│  2026-06-18  $25,000     $25,008.22   +$8.22   12.1%  │
│  2026-06-17  $24,991     $25,000.00   +$9.00   13.1%  │
│  ...                                                   │
│                                                        │
│  Итого за период: +$847.32 (+3.4%)                    │
│  Среднедневной yield: $28.24                          │
│  Лучший день: 2026-06-15 (+$41.20, Pendle rebalance)  │
└────────────────────────────────────────────────────────┘
```

#### Экран 3: Documents

```
┌────────────────────────────────────────────────────────┐
│  Документы                                             │
│                                                        │
│  ДОГОВОРЫ                                              │
│  📄 Договір інвестора v1.0 (подписан 2026-06-10) [PDF]│
│  📄 Risk Disclosure Statement [PDF]                    │
│                                                        │
│  ОТЧЁТЫ                                                │
│  📊 Monthly Statement — Июнь 2026 [PDF] [CSV]         │
│  📊 Monthly Statement — Май 2026 [PDF] [CSV]          │
│                                                        │
│  НАЛОГОВЫЕ ДОКУМЕНТЫ                                   │
│  📋 Transaction Log 2026 YTD [CSV]                    │
│  (Для самостоятельного расчёта налогов)               │
└────────────────────────────────────────────────────────┘
```

#### Экран 4: Notifications

```
┌────────────────────────────────────────────────────────┐
│  Уведомления                          Настройки ⚙️     │
│                                                        │
│  ✅ Подключен Telegram: @username                      │
│                                                        │
│  Типы уведомлений:                                     │
│  [✓] Ежедневный отчёт (09:00)                        │
│  [✓] Изменение APY > 1%                              │
│  [✓] Rebalance выполнен                              │
│  [ ] Drawdown alert (> 2%)                           │
│  [✓] Milestone achievements                          │
│                                                        │
│  История (последние 20):                              │
│  🔔 10:00 Дневной отчёт: APY 10.1%, balance $25,008  │
│  🔔 08:05 Rebalance: Morpho +$500, Aave -$300        │
└────────────────────────────────────────────────────────┘
```

#### Экран 5: Referral

```
┌────────────────────────────────────────────────────────┐
│  Реферальная программа                                 │
│                                                        │
│  Ваша реферальная ссылка:                             │
│  [earn-defi.com/join/abc123]  [Копировать]            │
│                                                        │
│  Приглашено: 2 человека                               │
│  Ваш бонус: 0.1% дополнительного yield на 12 месяцев │
│                                                        │
│  ⚠️ Программа активна только для family fund участников│
│  Новые участники проходят manual approval             │
└────────────────────────────────────────────────────────┘
```

### 3.4 Admin Panel — экраны

#### Экран A: System Overview

```
┌────────────────────────────────────────────────────────┐
│  SPA Admin Panel                    Super Admin        │
│                                                        │
│  СИСТЕМА                                               │
│  ✅ cycle_runner      Last run: 08:00:04 (+2.3 min)   │
│  ✅ autopush          Last push: 2h ago                │
│  ⚠️ httpserver        Status: UNKNOWN (check launchd)  │
│  ✅ cloudflared       HEALTHY                         │
│  ✅ telegram_bot      Connected, 3 users               │
│                                                        │
│  CAPITAL                                               │
│  Total AUM: $100,026.06 (virtual)                     │
│  Positions: 6 active                                  │
│  Cash buffer: 12.3% ✅                                 │
│  RiskPolicy: APPROVED (last cycle)                    │
│                                                        │
│  GO-LIVE STATUS                                        │
│  Progress: 26/26 criteria ✅                           │
│  Track days: 8 / 30 needed                            │
│  Target: 2026-08-01                                   │
│  [View Full GoLive Report]                            │
└────────────────────────────────────────────────────────┘
```

#### Экран B: Capital Allocation

```
┌────────────────────────────────────────────────────────┐
│  Распределение капитала                                │
│                                                        │
│  ТЕКУЩИЕ ПОЗИЦИИ                                       │
│  Protocol       Amount    APY    Tier   Risk   Delta   │
│  Morpho         $32,800   6.5%   T1     0.21   ——      │
│  Aave V3        $24,400   3.5%   T1     0.15   ↑+500  │
│  Compound       $19,600   4.8%   T1     0.18   ——      │
│  Cash/Buffer    $12,300   0%     —      —      ——      │
│  ...                                                   │
│                                                        │
│  RISK LIMITS STATUS                                    │
│  T1 cap (40%): 32.8% ✅                               │
│  T2 cap (20%): 0% ✅                                   │
│  T2 total cap (50%): 0% ✅                             │
│  Cash buffer (≥5%): 12.3% ✅                          │
│                                                        │
│  LAST REBALANCE                                        │
│  2026-06-18 08:00 — APPROVED (delta within threshold) │
│  [View Rebalance Log]  [Download JSON]                │
└────────────────────────────────────────────────────────┘
```

#### Экран C: Strategy Tournament

```
┌────────────────────────────────────────────────────────┐
│  Strategy Tournament (S0–S13)                          │
│                                                        │
│  Rank  Strategy          APY      Sharpe  Status       │
│  🥇 1  S7 Pendle YT+PT  10.115%  1.42    ACTIVE ✅    │
│  🥈 2  S11 Hybrid Max   15.6%*   —       ADVISORY ⚠️  │
│  🥉 3  S5 Pendle Enh.   8.5%     1.12    ACTIVE ✅    │
│  4     S8 Delta-Neutral  27.5%*  —       ADVISORY ⚠️  │
│  ...                                                   │
│  (*) Advisory only — не исполняется до go-live        │
│                                                        │
│  ACTIONS (Super Admin only)                           │
│  [Promote Strategy] [Suspend Strategy] [View ADR]    │
│                                                        │
│  TOURNAMENT CONFIG                                    │
│  auto_promote_enabled: false (until 2026-07-12)      │
│  Next auto-promote review: 2026-07-12                │
└────────────────────────────────────────────────────────┘
```

#### Экран D: Risk & Emergency Controls

```
┌────────────────────────────────────────────────────────┐
│  Risk Controls & Emergency Breakers        ⚠️ DANGER   │
│                                                        │
│  EMERGENCY BREAKERS (ADR-030)                         │
│  EB-01 ExploitProbe:   CLEAR ✅  Last: 08:00:01       │
│  EB-02 OracleCascade:  CLEAR ✅  Last: 08:00:01       │
│  EB-03 GasCrisis:      CLEAR ✅  Last: 08:00:01       │
│  EB-04 FlashCrash:     CLEAR ✅  Last: 08:00:01       │
│  EB-05 DataCorruption: CLEAR ✅  Last: 08:00:01       │
│                                                        │
│  MANUAL EMERGENCY CONTROLS                            │
│  [PAUSE rebalancing] — Skip next N cycles            │
│  [HALT all trading] — Requires confirmation text     │
│  [KILL SWITCH] — Close all positions (5% DD gate)   │
│                                                        │
│  RISK POLICY VERSION                                  │
│  Current: v1.0 (2026-05-20)                          │
│  Status: LOCKED during paper period (per ADR)        │
│  Changes require: new ADR + manual approval          │
│                                                        │
│  DRAWDOWN STATUS                                      │
│  Current: 0.00% (from $100,026.06 peak)              │
│  Kill-switch threshold: 5%                            │
│  Status: SAFE ✅                                      │
└────────────────────────────────────────────────────────┘
```

#### Экран E: Investor Management

```
┌────────────────────────────────────────────────────────┐
│  Управление инвесторами               Fund Manager     │
│                                                        │
│  АКТИВНЫЕ УЧАСТНИКИ                                    │
│  Name      Role     Balance    APY    Since            │
│  Юрий      Admin    $100K      10.1%  2026-06-10       │
│  [Name 2]  Investor $25K       10.1%  2026-06-15       │
│  ...                                                   │
│                                                        │
│  PENDING APPROVAL                                      │
│  • Ivan I. — заявка от 2026-06-17 [Approve] [Reject] │
│                                                        │
│  P&L ATTRIBUTION                                       │
│  Total fund yield today: $8.22                        │
│  Юрий (80%): $6.58                                    │
│  [Name 2] (20%): $1.64                                │
│  [Generate Monthly Statements]                        │
└────────────────────────────────────────────────────────┘
```

#### Экран F: Audit Log

```
┌────────────────────────────────────────────────────────┐
│  Audit Log (immutable)                                 │
│                                                        │
│  Фильтр: [All▼] [User▼] [Date▼]  [Export CSV]        │
│                                                        │
│  2026-06-18 08:00:04  SYSTEM    cycle_runner START    │
│  2026-06-18 08:00:11  SYSTEM    RiskPolicy APPROVED   │
│  2026-06-18 08:00:12  SYSTEM    Rebalance: 3 trades   │
│  2026-06-18 08:00:15  SYSTEM    cycle_runner END      │
│  2026-06-17 14:23:01  Юрий      LOGIN admin panel     │
│  2026-06-17 14:24:33  Юрий      APPROVED Ivan I.      │
│  ...                                                   │
│                                                        │
│  Лог хранится: data/audit_log.json (ring-buffer 1000) │
│  Push в GitHub: каждые 90 мин (autopush)              │
└────────────────────────────────────────────────────────┘
```

### 3.5 Data flows (ключевые)

```
INVESTOR LOGIN FLOW
Browser → api.earn-defi.com → CF Tunnel → Mac Mini :8765
         → Family Fund API → data/family_fund/registry.json
         → JWT token (HS256, secret in Keychain)
         → /dashboard, /history, /documents endpoints

DAILY REPORT FLOW
cycle_runner (08:00) → data/equity_curve_daily.json
                     → data/current_positions.json
                     → pnl_attribution.py → per-investor P&L
                     → telegram_blast.py → Telegram
                     → audit_log.json (atomic write)

ADMIN ACTION FLOW (HALT)
Admin Panel → POST /api/admin/halt → auth check (SUPER_ADMIN only)
           → write data/emergency_flags.json { halt: true }
           → next cycle_runner reads flag → aborts
           → audit_log: "Admin HALT triggered by [user]"
```

---

## 4. DevOps Pipeline

### 4.1 CI/CD — GitHub Actions → Mac Mini

**Проблема:** Mac Mini за NAT, нет публичного IP. Решение: self-hosted GitHub Actions runner.

**Архитектура:**
```
Developer → git push → GitHub repo
                    → GitHub Actions (облако)
                       ├── Unit tests (spa_core/tests/)
                       ├── Integration tests (tests/)
                       ├── Lint (pylint/flake8)
                       ├── Security scan (bandit)
                       └── [если все OK]
                              ↓
                    GitHub Actions → SSH → Mac Mini (self-hosted runner)
                       → git pull (main branch)
                       → python3 -m pytest (smoke test)
                       → launchd restart (если нужно)
                       → Telegram: "Deploy OK / FAILED"
```

**Установка self-hosted runner на Mac Mini:**
```bash
# Один раз: регистрация раннера
# Settings → Actions → Runners → New self-hosted runner
# macOS, архитектура Mac Mini
mkdir ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-osx-x64-2.x.x.tar.gz -L https://github.com/...
tar xzf ./actions-runner-osx-x64-2.x.x.tar.gz
./config.sh --url https://github.com/yurii-spa/SPA --token $TOKEN
./svc.sh install  # Установить как сервис (launchd)
./svc.sh start
```

**`.github/workflows/deploy.yml`:**
```yaml
name: Test + Deploy
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: python -m pytest spa_core/tests/ -v --tb=short
      - run: python -m pytest tests/ -v --tb=short

  deploy:
    needs: test
    runs-on: self-hosted  # Mac Mini runner
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    environment: production  # требует manual approval в GitHub
    steps:
      - uses: actions/checkout@v4
      - name: Smoke test
        run: python3 -m pytest spa_core/tests/ -v -x --tb=short -q
      - name: Reload changed launchd agents
        run: |
          if git diff HEAD~1 --name-only | grep -q "spa_core/"; then
            echo "Core changed — reload agents"
            # Только агенты, которые НЕ в середине цикла
          fi
      - name: Notify Telegram
        run: python3 scripts/notify_deploy.py --status success
```

**Важно: CI/CD не должен затрагивать живой цикл.** Деплой происходит через `git pull` + импорт новых модулей при следующем запуске цикла (в 08:00). Горячая перезагрузка launchd агентов — только для non-critical агентов (httpserver, autopush). `com.spa.daily_cycle` перезапускается только если нет активного цикла.

### 4.2 Secrets Management

**Текущее состояние:** Keychain macOS — хорошее решение для одной машины.

**Расширенная схема:**

```
TIER 1: macOS Keychain (оставить)
├── GITHUB_PAT_SPA — GitHub Personal Access Token
├── TELEGRAM_BOT_TOKEN_SPA — Telegram bot token
├── TELEGRAM_CHAT_ID_SPA — Chat ID
├── ALCHEMY_API_KEY — RPC ключ (когда получим)
└── JWT_SECRET — для Admin Panel (добавить)

TIER 2: GitHub Secrets (для CI/CD)
├── TELEGRAM_BOT_TOKEN — для notify_deploy.py в CI
├── SLACK_WEBHOOK — опционально, для CI alerts
└── Не хранить: PAT, RPC keys (они только в Keychain)

TIER 3: Файлы (ЗАПРЕЩЕНО — инцидент 2026-06-10)
└── НИКОГДА не писать секреты в файлы
```

**Ротация (TOKEN_ROTATION_RUNBOOK.md расширить):**
- PAT: каждые 90 дней (GitHub → Settings → Tokens → Regenerate)
- JWT_SECRET: при смене admin пользователей
- Telegram token: при компрометации только

### 4.3 Monitoring Stack

**Принцип:** внешнее наблюдение за внешними эндпоинтами, внутреннее — за внутренними процессами.

```
ВНЕШНИЙ МОНИТОРИНГ
├── BetterStack Uptime (бесплатно до 10 monitors)
│   ├── Монитор 1: https://dashboard.earn-defi.com (HTTP 200)
│   ├── Монитор 2: https://api.earn-defi.com/health (HTTP 200)
│   └── Алерт: Telegram если DOWN > 5 мин
│
└── Cloudflare Analytics (встроенный, бесплатно)
    ├── Requests, bandwidth, cache hit ratio
    └── Security events (DDoS, bot traffic)

ВНУТРЕННИЙ МОНИТОРИНГ (уже есть)
├── CycleHealthMonitor → data/health_report.json
├── EmergencyBreakers (EB-01..EB-05) → CLEAR/PAUSE/HALT
├── gap_monitor.json — непрерывность трека
└── com.spa.analytics_tier_c — ежедневно 05:00

МЕТРИКИ (собирать в data/metrics/)
├── cycle_latency.json — время выполнения цикла
├── api_response_times.json — latency Family Fund API
└── tunnel_health.json — CF Tunnel uptime
```

**Логирование:**
```
/tmp/spa_cycle.log       — stdout цикла (ротировать еженедельно)
/tmp/spa_cycle_err.log   — stderr цикла
data/audit_log.json      — бизнес-события (ring-buffer 1000)
~/Library/Logs/com.spa.* — launchd агенты

НЕ НУЖНО: Loki, Elasticsearch, Datadog — это overhead для текущей фазы.
При AUM > $500K → рассмотреть BetterStack Logs (от $29/мес).
```

### 4.4 Alerting — Telegram-first

**Severity уровни:**

```
P0 — CRITICAL (немедленно, 24/7)
├── EmergencyBreaker HALT activated
├── Kill-switch triggered (drawdown ≥ 5%)
├── cycle_runner FAILED (не запустился)
├── API DOWN > 5 мин
└── Gap in equity curve detected

P1 — HIGH (немедленно в рабочее время)
├── RiskPolicy blocked rebalance
├── APY drop > 2% в 1 день
├── Adapter失효 (adapter returns stale data)
└── GoLive criteria regression

P2 — MEDIUM (ежедневный дайджест)
├── Strategy promotion/demotion (ADR-029)
├── New protocol TVL warning
└── Deployment success/fail

P3 — LOW (еженедельный отчёт)
├── Test coverage изменилась
└── Dependency updates
```

**Telegram bot команды (расширить):**
```
/status      — системный статус
/apy         — текущий APY и позиции
/golive      — GoLive checklist статус
/halt        — (admin only) PAUSE цикла
/breakers    — статус EmergencyBreakers
/investors   — (admin only) список инвесторов
/deploy      — последний деплой статус
```

### 4.5 Backup & Recovery

**RPO (Recovery Point Objective):** 90 минут (autopush каждые 90 мин → GitHub)
**RTO (Recovery Time Objective):** 4 часа (восстановление Mac Mini из GitHub)

**Что бэкапить:**

```
TIER A: Critical (GitHub, каждые 90 мин — уже делается)
├── data/*.json — все state файлы
├── spa_core/**/*.py — весь код
└── docs/, config/ — конфигурация

TIER B: Important (еженедельно, offsite)
├── ~/Library/Keychains/ — Keychain backup (зашифрован)
├── ~/Library/LaunchAgents/com.spa.*.plist — launchd configs
└── data/audit_log.json — аудит лог

TIER C: Nice to have (ежемесячно)
└── Полный disk image Mac Mini (Time Machine или Carbon Copy Cloner)
    → внешний SSD или NAS
```

**Offsite backup (добавить):**
```bash
# Еженедельно: зашифрованный архив в Backblaze B2 ($0.006/GB)
# scripts/weekly_backup.sh
tar czf - data/ | \
  gpg --symmetric --cipher-algo AES256 | \
  b2 upload-file spa-backups - "backup-$(date +%Y%m%d).tar.gz.gpg"
```

**DR процедура (краткая):**
1. Получить новый Mac Mini / MacOS install
2. `git clone github.com/yurii-spa/SPA`
3. Восстановить Keychain (из TIER B backup)
4. `bash scripts/install_agents.sh`
5. Проверить последние данные из GitHub (autopush)
6. Запустить `python3 -m spa_core.paper_trading.cycle_runner --dry-run`

**Подробно:** `DR_PROCEDURE_v2.md` уже существует — дополнить разделом о Cloudflare Tunnel reconfiguration.

---

## 5. Roadmap к Production

### 5.1 Сейчас → 2026-08-01: Paper Track + Infrastructure

**Приоритет: не прерывать трек. Каждый день без gap — золото.**

| Неделя | Задачи | Критичность |
|--------|--------|-------------|
| W1 (до 25 июня) | Зарегистрировать self-hosted GitHub runner | P1 |
| W1 | Настроить BetterStack monitors (5 мин) | P2 |
| W1 | Создать `config.yml` для CF Tunnel с правильными роутами | P1 |
| W2 (до 2 июля) | Задеплоить Landing page v1 на CF Pages (минимальная версия) | P2 |
| W2 | Добавить `/health` endpoint в Family Fund API | P1 |
| W3 (до 9 июля) | Admin Panel MVP (только System Overview + Capital экраны) | P2 |
| W3 | JWT auth для Admin Panel | P1 |
| W4 (до 16 июля) | Investor Cabinet v1 (Dashboard + History экраны) | P2 |
| W4 | Получить Ledger/Trezor → настроить Gnosis Safe | **P0 блокер go-live** |

### 5.2 2026-08-01 → 2026-10-01: Go-Live + Live Trading

**Условие старта:** GoLive 26/26 + 30 дней трека + hardware wallets + manual review.

| Месяц | Задачи | Результат |
|-------|--------|-----------|
| Август 2026 | Transfer $10-50K реального капитала в Gnosis Safe | First live trades |
| Август 2026 | Mониторинг 24/7 первые 2 недели, ежедневный review | Confidence building |
| Сентябрь 2026 | Landing page v2 — live stats с реальными данными | Public presence |
| Сентябрь 2026 | Investor Cabinet v2 — полный набор экранов | Готов к внешним |
| Октябрь 2026 | Admin Panel v2 — полный набор + audit log | Operations ready |

### 5.3 2026-Q4 → 2027-Q1: External AUM + Vault

**Условие:** 90 дней реального трека без инцидентов + Sharpe ≥ 1.5.

| Период | Задачи |
|--------|--------|
| Q4 2026 | ERC-4626 vault дизайн (не деплой) |
| Q4 2026 | Первый внешний аудит (Spearbit / Trail of Bits) запустить |
| Q1 2027 | Vault деплой ПОСЛЕ аудита без критических находок |
| Q1 2027 | Первые DAO-пилоты ($1-3M AUM) |
| Q2 2027 | Mgmt fee 1.5% + perf fee 15% активированы |

### 5.4 Блокеры (требуют действий владельца)

| Блокер | Срок | Действие | Impact |
|--------|------|----------|--------|
| **Hardware wallets (Ledger/Trezor)** | До 2026-08-01 | Получить, настроить Gnosis Safe 2/3 | **Блокирует go-live** |
| **Regulatory review** | До Q4 2026 | Консультация юриста по юрисдикции | Блокирует внешний AUM |
| **Аудит smart contract** | До vault deploy | Запустить Trail of Bits / Spearbit | Блокирует ERC-4626 vault |
| **RPC ключи Alchemy** | НЕМЕДЛЕННО | Добавить в Keychain | Блокирует Pendle PT (+2-3% APY) |
| **GitHub Pages / CF Pages setup** | W1 | 15 мин настройки | Публичный landing |

### 5.5 Метрики готовности к запуску реального капитала

```
MUST HAVE (блокирующие):
☐ GoLive 26/26 criteria: PASS
☐ 30 дней трека без gap: подтверждено gap_monitor.json
☐ Sharpe ratio ≥ 1.0 (за 30 дней): calculated
☐ Max drawdown < 3% за весь period
☐ Gnosis Safe 2/3 multisig: deployed и tested
☐ Hardware wallets: configured и tested
☐ EmergencyBreakers: все 5 CLEAR
☐ Audit log: работает, пишет каждый цикл
☐ Kill-switch drill: выполнен, время < 1 мин

SHOULD HAVE:
☐ Landing page: запущен
☐ Admin Panel: System Overview + Capital + Emergency
☐ BetterStack monitors: настроены
☐ Weekly backup offsite: настроен
☐ Legal disclaimer: одобрен юристом
☐ DR Procedure: протестирован (restore drill)

NICE TO HAVE:
☐ Investor Cabinet v1
☐ Auto-reporting weekly statement
☐ Sentry error tracking
```

---

## 6. Deep Research Промпты

### Промпт 1: Конкурентный анализ DeFi yield platforms

```
Ты — аналитик DeFi. Сделай подробный конкурентный анализ следующих платформ 
управления yield-стратегиями: Enzyme Finance, dHEDGE, Yearn Finance v3, 
Idle Finance, Sommelier Finance, Vaultcraft. 

Для каждой платформы найди и опиши:
1. Бизнес-модель (fee структура, mgmt fee %, perf fee %)
2. Техническая архитектура (on-chain vs off-chain execution, multi-sig setup)
3. AUM в июне 2026 (или последние доступные данные)
4. Типичный клиент (retail/family office/DAO treasury)
5. Главные преимущества и слабые места
6. Требования к аудиту (сколько аудитов, какие компании)

Отдельно: сравни с позиционированием "autonomous yield infrastructure for family 
office with verifiable paper track record". Где незанятая ниша?

Формат: таблица сравнения + текстовые выводы, ~1000 слов.
```

### Промпт 2: Best practices DevOps для DeFi/финтех проектов

```
Ты — DevOps архитектор со специализацией в финтех и DeFi проектах.
Контекст: DeFi yield optimizer работает на одном Mac Mini (always-on), 
Cloudflare Tunnel для внешнего доступа, Python stdlib только, 
GitHub для хранения кода и state, launchd для cron-задач.

Какие конкретные best practices DevOps критически важны для такой системы?
Включи:
1. Self-hosted GitHub Actions runner на Mac — risks и mitigations
2. Управление секретами без внешних vault-систем (только macOS Keychain)
3. Zero-downtime deploy стратегии для critical financial processes
4. Rollback strategy когда нельзя прерывать работающий trading цикл
5. Log rotation и retention для финансовых данных (регуляторные требования)
6. Monitoring setup с минимальным бюджетом ($0-50/мес)
7. Incident response playbook для одного-двух человек команды

Конкретные инструменты с ценами, не абстрактные рекомендации. 
Учти, что система управляет реальным капиталом ($10-100K диапазон).
```

### Промпт 3: Landing page conversion для DeFi/fintech B2B

```
Ты — CRO специалист с опытом в fintech и DeFi. Проанализируй успешные 
landing pages: Maple Finance, Goldfinch, Clearpool, TrueFi, Notional Finance.

Для продукта "DeFi yield optimizer для family offices" (ticket size $25K-250K, 
аудитория: состоятельные технически-грамотные инвесторы, криптонативные 
family offices) разработай:

1. Hero section copy — 3 варианта headline + subheadline
2. Trust signals — что именно убеждает этот тип клиента (не retail!)
3. Social proof — что заменяет "testimonials" когда нет публичных клиентов
4. CTA иерархия — primary vs secondary, какие формулировки работают
5. Что НЕ писать (red flags для sophisticated investors)
6. Live stats block — какие метрики показывать (APY? Sharpe? Track days?)
7. Risk disclosure — как быть прозрачным не теряя конверсию

Дай конкретный пример копирайта для Hero section.
Учти: продукт в paper-trading режиме, реального AUM нет.
```

### Промпт 4: Investor Cabinet UX в fintech/wealth management

```
Исследуй UX паттерны investor cabinets в следующих продуктах:
Nexo (nexo.io), Maple Finance, Enzyme Finance, dHEDGE, Yearn Finance,
а также tradfi: Interactive Brokers, Schwab, Fidelity (их web apps).

Для DeFi yield fund с участниками ($25K-250K вклад, ежедневный yield) 
спроектируй UX investor cabinet:

1. Информационная архитектура (sitemap / page hierarchy)
2. Dashboard: какие 5 KPI показывать "first glance" (above the fold)
3. Yield history: как отображать (таблица? chart? оба? какой период дефолтный?)
4. Documents section: требования к форматам и доступу (PDF statements, CSV exports)
5. Notification preferences UX: email vs Telegram vs push
6. Mobile considerations: что обязательно работает на телефоне
7. Accessibility: минимум WCAG требований для финансовых продуктов

Оцени: что делают лучше tradfi vs DeFi в этой задаче?
Формат: wireframe-level описание каждого экрана (текстово, без картинок).
```

### Промпт 5: Regulatory considerations для DeFi yield platforms

```
Ты — юрист специализирующийся на DeFi и crypto regulation.

Контекст: DeFi yield optimizer, paper trading сейчас, план — управление 
реальным капиталом от family office ($100K-500K в 2026, внешний AUM в 2027).
Операционная юрисдикция: Украина (операционно), потенциальные инвесторы: 
Европа, СНГ, non-US. GitHub: публичный. Домен: earn-defi.com.

Вопросы:
1. Какая юридическая структура минимально-необходима для управления 
   чужими средствами в DeFi (SPV? фонд? ИП?) в Европе/Украине?
2. Требует ли DeFi yield fund лицензирования в EU (MiCA 2024)?
3. "Family fund" — есть ли юридические exemptions для close circle?
4. Что обязательно указывать в disclaimers на landing page?
5. AML requirements при onboarding инвесторов (что минимально-необходимо)?
6. Geo-blocking: какие юрисдикции блокировать обязательно (US persons)?
7. Смарт-контракт vault — требует ли регуляторного одобрения?
8. Какие документы (договор инвестора, risk disclosure) минимально необходимы?

Давай практические рекомендации, не только описание рисков.
Disclaimer: это информация для понимания, не юридическая консультация.
```

### Промпт 6: Cloudflare Pages + Tunnel архитектура для fullstack app

```
Архитектурный вопрос: есть Mac Mini за NAT как основной сервер (Python API),
домен earn-defi.com на Cloudflare, Cloudflare Tunnel (cloudflared) настроен.

Спроектируй оптимальную архитектуру:
1. Cloudflare Pages для static landing (Next.js/Astro) — как настроить 
   custom domain, preview deployments, cache headers?
2. Cloudflare Tunnel routing: одна конфигурация для нескольких 
   subdomains (dashboard, api, staging) — покажи config.yml
3. API security: как защитить api.earn-defi.com от нежелательных запросов
   через Cloudflare WAF rules без платного плана?
4. CORS: как правильно настроить между Pages (static) и Tunnel (API)?
5. WebSocket через CF Tunnel: работает ли? Как настроить?
6. Cache strategy: что кэшировать на CF Edge, что нет (финансовые данные)?
7. Rate limiting: CF настройки для API endpoints (бесплатный план)
8. SSL/TLS: как обеспечить end-to-end encryption через tunnel?
9. Health check endpoint: как мониторить tunnel availability?

Дай конкретные конфигурации (YAML/JSON), не абстрактные описания.
```

### Промпт 7: Python FastAPI для финансового API — best practices

```
Ты — Senior Python backend разработчик. Контекст: нужно создать 
Family Fund API на FastAPI (Mac Mini, Python 3.11, без внешних 
зависимостей в runtime кроме FastAPI).

Спроектируй production-ready API:
1. Authentication: JWT (HS256) без БД — сессии в памяти + Keychain для secret
2. Authorization: 4 роли (SUPER_ADMIN, FUND_MANAGER, INVESTOR, OBSERVER)
   — middleware pattern для FastAPI
3. Endpoints дизайн для:
   - GET /api/health
   - GET /api/portfolio/{investor_id}
   - GET /api/positions
   - GET /api/equity-curve?days=30
   - POST /api/admin/halt (SUPER_ADMIN only)
   - GET /api/tournament
4. Rate limiting без Redis (в памяти, TokenBucket)
5. CORS для Cloudflare Pages origin
6. Error handling: структура ответов, logging без утечки данных
7. File-based "database": как безопасно читать data/*.json (thread-safe?)
8. Request/Response models: Pydantic схемы для финансовых данных
9. Testing: pytest fixtures для FastAPI без мокирования файловой системы

Учти: код должен быть stdlib + FastAPI + Pydantic only (no SQLAlchemy, no Redis).
```

### Промпт 8: DeFi Smart Contract Vault — аудит и безопасность

```
Контекст: планируем ERC-4626 vault для внешнего капитала ($1-10M AUM в 2027).
Vault будет управляться off-chain optimizer (Python) через Gnosis Safe 2/3 multisig.

Вопросы по безопасности и аудиту:
1. ERC-4626 — типичные уязвимости: инфляционная атака, sandwich, re-entrancy
   — как защититься в дизайне?
2. Gnosis Safe + Zodiac Roles module: как ограничить права оператора 
   (только rebalance, не withdraw)?
3. Timelock: нужен ли для vault, какой минимальный period?
4. Bug bounty: Immunefi для проекта с $1-5M TVL — какой бюджет нормален?
5. Аудиторские компании: Spearbit vs Trail of Bits vs OpenZeppelin 
   для yield vault — цены, сроки, что проверяют?
6. Два аудита: достаточно ли, или нужно три? Best practice рынка?
7. Formal verification: нужна ли для vault этого размера?
8. On-chain Proof-of-Track: как реализовать Merkle root decision log 
   (каждое решение аллокатора → хеш → on-chain)?

Цель: понять scope работы и бюджет для Q4 2026 подготовки к аудиту.
```

### Промпт 9: Mac Mini как production server — reliability engineering

```
У нас Mac Mini (Apple Silicon) как primary production server для 
финансового приложения. Managed risk: hardware failure = trading stop.

Оцени риски и предложи mitigations:
1. Hardware failure probability: MTTF для Mac Mini M2/M4, 
   исторические данные отказов?
2. Power: UPS рекомендации для Mac Mini (мощность, runtime, бюджет)?
3. Network: как обеспечить uptime при проблемах ISP? 
   (4G failover router, dual ISP?)
4. Thermal: при 24/7 нагрузке — как мониторить, fan speed control?
5. Cold standby на Hetzner VPS: как синхронизировать state каждые 15 мин
   и активировать за < 30 мин? Конкретная архитектура.
6. macOS updates: как управлять ОС updates без downtime?
7. Remote access: если Mac Mini завис — как перезагрузить удалённо?
   (IP KVM, Smart PDU?)
8. Monitoring: какие macOS-specific метрики критичны 
   (memory pressure, SSD health, temps)?

Бюджет: $200-500 на reliability improvements.
```

### Промпт 10: Token economics и fee structure для DeFi yield fund

```
Исследуй fee structures успешных DeFi yield фондов и protocols:
Yearn Finance (Vaults), Enzyme Finance, Maple Finance, Ribbon Finance,
а также tradfi hedge funds (2/20 model).

Для DeFi yield fund (target APY 8-15%, USDC/stablecoins only):
1. Management fee: 1% vs 1.5% vs 2% — что стандарт для DeFi?
   Как считать: от AUM ежедневно или ежегодно?
2. Performance fee: 10% vs 15% vs 20%? High-watermark обязателен?
3. Deposit/withdrawal fee: нужна ли? Какой % нормален?
4. Early withdrawal penalty: есть ли lock-up periods в DeFi yield?
5. How to compete: чем оправдать fees если Yearn/Morpho дают comparable APY 
   без management fee?
6. Fee token vs direct fee: fee в USDC или ввести governance token?
7. На каком AUM стают важны: какие операционные расходы при $1M vs $10M vs $50M?
8. B2B white-label pricing: API access fees — rev share vs flat fee vs usage-based?

Цель: определить fee structure для launch в 2027.
```

### Промпт 11: Next.js vs Astro для fintech landing + dashboard

```
Технический выбор стека для двух сценариев:

СЦЕНАРИЙ A: Landing page earn-defi.com
- Полностью статический контент (маркетинг)
- Live stats блок обновляется каждые 60 сек (fetch от API)
- Деплой: Cloudflare Pages
- SEO критичен (Google индексация)
- Команда: 1 разработчик, не frontend-специалист

СЦЕНАРИЙ B: Admin Panel + Investor Cabinet  
- SPA приложение (много state, transitions)
- Auth (JWT), protected routes
- Реалтайм данные (WebSocket или polling)
- Деплой: Cloudflare Pages (статическая сборка) + API на Mac Mini
- Компоненты: таблицы, charts, формы

Для каждого сценария:
1. Astro 4 vs Next.js 14 — выбери один с обоснованием
2. UI Kit: shadcn/ui vs Radix vs Chakra vs MUI — для fintech
3. Charts: Recharts vs Chart.js vs TradingView Lightweight Charts
4. State management: Zustand vs Jotai vs React Query (для API data)
5. Auth: next-auth vs custom JWT vs Clerk для SPA
6. Конкретные GitHub repos как стартовые точки

Учти: backend — Python FastAPI, не Node.js. Нет BFF (Backend for Frontend).
```

### Промпт 12: Gnosis Safe + hardware wallets — операционный гайд

```
Практический гайд по операционной безопасности для DeFi fund manager.

Контекст: 
- Gnosis Safe 2/3 multisig на Ethereum mainnet (ADR-024)
- Hardware wallets: Ledger + Trezor (ещё не пришли)
- Сумма под управлением: $100K-500K (2026), до $5M (2027)
- Оператор: Python автоматизация через Safe API
- Governance: 2 из 3 подписей для любой транзакции

Ответь:
1. Как правильно настроить Gnosis Safe 2/3 (пошагово, Ethereum mainnet)?
2. Ledger + Trezor как 2 из 3 ключей — лучшая практика seed phrase storage?
3. Третий ключ: что использовать (hot wallet? другой hardware? multisig member)?
4. Zodiac Roles module: как настроить чтобы Python-оператор мог только 
   rebalance (call specific contracts), но не withdraw?
5. Safe Transaction Service API: как автоматизировать propose + мониторинг?
6. Timelock для critical ops: SafeGuard или отдельный timelock контракт?
7. Что тестировать на testnet перед mainnet (checklist)?
8. Incident response: если один hardware wallet потерян — что делать?
9. Gas management: как пополнять ETH для газа автоматически без риска?
10. Ключевые операционные риски при $100K+ AUM через Safe?

Дай конкретные шаги, не теоретические объяснения.
```

---

## Приложения

### Appendix A: Технологический стек финальный

```
ИНФРАСТРУКТУРА
├── Server: Mac Mini (основной) + Hetzner CX21 (cold standby, Q4 2026)
├── Domain: earn-defi.com (Cloudflare DNS)
├── CDN + WAF: Cloudflare (бесплатный план)
├── Tunnel: Cloudflare Tunnel (cloudflared, уже работает)
├── Landing hosting: Cloudflare Pages
└── CI/CD: GitHub Actions + self-hosted runner (Mac Mini)

FRONTEND
├── Landing: Astro 4 + Tailwind CSS + AstroWind template
├── Admin Panel: Next.js 14 + shadcn/ui + Tailwind
├── Charts: TradingView Lightweight Charts (equity curve) + Recharts (allocation)
└── Icons: Lucide React

BACKEND
├── Runtime: Python 3.11 (только stdlib в core)
├── API: FastAPI + Pydantic (не stdlib, но допустимо для API layer)
├── Auth: JWT (HS256), secret в Keychain
├── State: data/*.json (атомарные записи, ring-buffers)
└── Scheduler: launchd (macOS), 19 агентов

MONITORING
├── Uptime: BetterStack (бесплатно)
├── Errors: Sentry SDK (бесплатно, self-hosted)
├── Alerts: Telegram (уже есть)
├── Analytics: Cloudflare Web Analytics (встроено)
└── Internal: CycleHealthMonitor + data/health_report.json

SECURITY
├── Secrets: macOS Keychain + GitHub Secrets (только для CI)
├── Multisig: Gnosis Safe 2/3 (Q3 2026)
├── Hardware: Ledger + Trezor (ожидаются)
├── API auth: JWT Bearer tokens
└── Network: Cloudflare WAF + rate limiting
```

### Appendix B: Milestone Timeline

```
2026-06-18  Этот документ создан ✅
2026-06-19  7-day checkpoint (launchd 10:00) — first milestone
2026-06-25  CF Pages landing v0.1 (placeholder, earn-defi.com)
2026-07-01  ADR-031 Rebalancing Policy Phase 1 activation
2026-07-10  30 дней трека complete → evidence window закрыта
2026-07-12  auto_promote_enabled → может быть включён (ADR-029)
2026-07-15  Admin Panel MVP (System + Capital + Emergency screens)
2026-08-01  GO-LIVE TARGET (ADR-002: 26/26 + 30d + hardware wallets)
2026-09-01  Landing v1.0 (полный), Investor Cabinet v1
2026-10-01  90 дней live трека → внешний аудит переговоры
2026-12-01  ERC-4626 vault дизайн + Audit #1 запущен
2027-03-01  Vault деплой (после аудита) → external AUM
```

---

*Документ создан: 2026-06-18*  
*Следующий review: 2026-08-01 (post go-live)*  
*Автор: Senior Solutions Architect (Claude)*  
*Статус: Требует подтверждения Owner перед исполнением*
