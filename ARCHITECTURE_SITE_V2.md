# ARCHITECTURE_SITE_V2 — earn-defi.com Product Site Redesign

> **Автор:** SPA Product Architecture  
> **Дата:** 2026-06-19  
> **Статус:** DRAFT v1.0  
> **Целевой дедлайн MVP:** 2026-08-01 (go-live date)  
> **Текущий стек:** Astro 4 SSG → Cloudflare Pages

---

## 0. Контекст и исходная точка

### Текущее состояние сайта
earn-defi.com — one-page landing на Astro 4, задеплоен на Cloudflare Pages. Содержит базовую информацию о продукте без структурированного контента о стратегиях, методологии и доказательной базе.

### Что изменилось в продукте (что должен отражать новый сайт)
- Paper trading запущен 2026-06-10 (реальный трек: с 2026-06-18)
- 14 стратегий (S0–S13) в tournament, текущий лидер S7 (10.115% APY target)
- 16 адаптеров в ADAPTER_REGISTRY
- GoLiveChecker 20/26 pass (на 2026-06-19) → go-live 2026-08-01
- Три продуктовых стратегии для позиционирования: Preserve / Core / Max Yield

### Целевая аудитория
Family offices, allocators, private investors: $25K–$250K в DeFi stablecoins. Это люди, которые:
- **знают** что такое DeFi, но хотят **управляемый** риск
- принимают решения медленно — им нужна доказательная база, а не хайп
- читают методологию и смотрят на gates, а не на APY заголовок

### Ключевое позиционирование
> "Мы показываем, как управляется риск, что именно проверяется, и что именно заблокировано."

SPA занимает нишу между retail auto-compounders (Yearn, Beefy) и institutional vaults (Goldfinch, Maple). Главные конкурентные преимущества для сайта:
- **Deterministic risk policy** — не «мы стараемся», а «вот конкретные gates»
- **Paper track record** — публичные логи, equity curve, GoLiveChecker 26 критериев
- **Transparency** — trade logs, risk blocks, method описание

---

## 1. Sitemap с приоритетами

### Легенда приоритетов
- 🔴 **MVP** — обязательно к 2026-08-01 (дата go-live)
- 🟡 **Post-MVP** — в течение 30 дней после go-live
- 🟢 **Phase 2** — через 60–90 дней

```
earn-defi.com/
├── /                           🔴 MVP  — Landing: hero + strategy selector + track record
├── /strategies                 🔴 MVP  — Обзор трёх стратегий
│   ├── /strategies/preserve    🔴 MVP  — Tier 1 only, ~6% APY
│   ├── /strategies/core        🔴 MVP  — Tier 1+2, ~10% APY (текущая LIVE стратегия)
│   └── /strategies/max-yield   🟡 Post — Looping + leverage, ~15% APY (target)
├── /methodology                🔴 MVP  — Как работает SPA под капотом
├── /risk                       🔴 MVP  — Risk philosophy, gates, stress scenarios
├── /trust                      🔴 MVP  — Custody, multisig, kill switch, incident response
├── /due-diligence              🔴 MVP  — Proof layer: paper status, GoLiveChecker, logs
├── /dashboard                  🔴 MVP  — Multi-strategy live dashboard (client-side JSON)
├── /fees                       🟡 Post — Fee structure, HWM, FAQ
├── /security                   🟡 Post — Frontend + domain + contract security
├── /emergency-withdrawal       🟡 Post — Прямой вывод без frontend
├── /risk-disclosure            🔴 MVP  — Уже есть, перенести/обновить
└── /changelog                  🟢 Phase2 — История изменений стратегий/политики
```

### Обоснование приоритетов

**К MVP (Aug 1)** нужен минимальный пакет для due diligence аллокатора:
1. Landing с proof of track record
2. Стратегии Preserve и Core (то, во что реально можно войти на go-live)
3. Methodology — без этого нет доверия
4. Risk — это ядро дифференциации
5. Trust — custody + kill switch
6. Due Diligence — живые данные из JSON
7. Dashboard — live window в систему

**Max Yield** — post-MVP, потому что S8/S11 на go-live только advisory, реальных позиций нет.  
**Fees** — post-MVP, структура комиссий уточняется.  
**Emergency Withdrawal** — post-MVP (зависит от finalised custodial setup к go-live).

---

## 2. Компонентная архитектура для Astro 4

### 2.1 Архитектурный принцип: Islands of Interactivity

```
Astro 4 SSG
│
├── Static pages  (все /strategies/*, /methodology, /risk, /trust, /fees, /security)
│   └── Полностью рендерятся на build time — данные из JSON через import или getStaticPaths
│
├── Hybrid pages  (/, /due-diligence, /strategies/core, /strategies/preserve)
│   └── Статический HTML + "islands" компоненты с client:load для live данных
│       └── Данные: fetch(PUBLIC_JSON_ENDPOINT) в браузере
│
└── /dashboard
    └── Полностью client-side (React/Preact island или vanilla JS)
        └── Все данные через клиентский fetch из публичного JSON-эндпоинта
```

### 2.2 Shared компоненты (src/components/)

#### Атомарные компоненты

| Компонент | Файл | Описание | Данные |
|---|---|---|---|
| `StatusBadge` | `StatusBadge.astro` | LIVE / PAPER / COMING_SOON / SUSPENDED бейдж | prop: status |
| `RiskBadge` | `RiskBadge.astro` | Conservative / Moderate / Aggressive | prop: level |
| `APYDisplay` | `APYDisplay.astro` | Форматированный APY с тарget/actual | props: target, actual, isLive |
| `TierBadge` | `TierBadge.astro` | T1 / T2 / T3-SPEC индикатор протокола | prop: tier |
| `GoLiveProgress` | `GoLiveProgress.astro` | Прогресс-бар N/26 criteria | data: golive_status.json |
| `TrackRecord` | `TrackRecord.astro` | Дней трека / equity / start date | data: paper_trading_status.json |
| `KillSwitchAlert` | `KillSwitchAlert.astro` | Баннер при активном kill switch | data: paper_trading_status.json |
| `RiskGateIndicator` | `RiskGateIndicator.astro` | Иконка APPROVED / BLOCKED | data: risk_limits_check.json |
| `MetricCard` | `MetricCard.astro` | Универсальная карточка метрики (label + value + delta) | props |

#### Составные компоненты

| Компонент | Файл | Описание | Данные |
|---|---|---|---|
| `StrategyCard` | `StrategyCard.astro` | Карточка стратегии для списка | strategy_config.json |
| `StrategyHero` | `StrategyHero.astro` | Hero-секция страницы стратегии | strategy_config.json |
| `MetricsPanel` | `MetricsPanel.astro` | Панель из нескольких MetricCard | paper_trading_status.json |
| `ProtocolTable` | `ProtocolTable.astro` | Таблица протоколов (название, тир, APY, TVL, статус) | adapter_status.json |
| `RiskGatesSnapshot` | `RiskGatesSnapshot.astro` | Snapshot последних risk блокировок | risk_limits_check.json |
| `GoLiveCheckerPanel` | `GoLiveCheckerPanel.astro` | 26 критериев с pass/fail статусом | golive_status.json |
| `EquityCurveChart` | `EquityCurve.tsx` | Chart.js equity curve (island client:load) | equity_curve_daily.json |
| `TradesLog` | `TradesLog.tsx` | Таблица последних N трейдов (island) | trades.json |
| `AllocationPie` | `AllocationPie.tsx` | Пай-чарт текущих позиций (island) | current_positions.json |
| `TournamentTable` | `TournamentTable.tsx` | Рейтинг стратегий (island) | tournament_ranking.json |
| `DailyStatusBanner` | `DailyStatusBanner.tsx` | Live статус из paper_trading_status (island) | paper_trading_status.json |

#### Секции страниц (layouts/sections)

| Компонент | Файл | Используется на |
|---|---|---|
| `SiteHeader` | `SiteHeader.astro` | Все страницы |
| `SiteFooter` | `SiteFooter.astro` | Все страницы |
| `HowItWorksStepper` | `HowItWorksStepper.astro` | / (main), /methodology |
| `TrustSignals` | `TrustSignals.astro` | /, /trust |
| `RiskWarningBox` | `RiskWarningBox.astro` | /, все /strategies/* |
| `CTABlock` | `CTABlock.astro` | /, /strategies/*, /due-diligence |
| `FAQAccordion` | `FAQAccordion.astro` | /strategies/*, /fees |
| `StressScenarioTable` | `StressScenarioTable.astro` | /risk |

### 2.3 Layouts

```
src/layouts/
├── BaseLayout.astro          — <html>, SEO meta, fonts, global CSS vars
├── PageLayout.astro          — BaseLayout + SiteHeader + SiteFooter + prose container
├── StrategyLayout.astro      — PageLayout + 15-section strategy template
└── DashboardLayout.astro     — BaseLayout + minimal chrome, max-width = full
```

### 2.4 Страницы (src/pages/)

```
src/pages/
├── index.astro                      — /
├── strategies/
│   ├── index.astro                  — /strategies
│   ├── preserve.astro               — /strategies/preserve
│   ├── core.astro                   — /strategies/core
│   └── max-yield.astro              — /strategies/max-yield
├── methodology.astro                — /methodology
├── risk.astro                       — /risk
├── trust.astro                      — /trust
├── security.astro                   — /security
├── emergency-withdrawal.astro       — /emergency-withdrawal
├── fees.astro                       — /fees
├── due-diligence.astro              — /due-diligence
├── dashboard.astro                  — /dashboard
└── risk-disclosure.astro            — /risk-disclosure (существующая, обновить)
```

### 2.5 Маппинг продуктовых стратегий → внутренние стратегии SPA

| Продуктовая стратегия | Внутренние стратегии | Tier | APY Target | Статус на go-live |
|---|---|---|---|---|
| **Preserve** | S0 (Aave V3) + S4 (Conservative) | T1 only | ~6% | LIVE (paper verified) |
| **Core** | S7 (Pendle YT+PT) + аллокатор T1+T2 | T1 + T2 | ~10% | LIVE (текущая активная) |
| **Max Yield** | S8 (Delta-Neutral sUSDe) + S11 (Hybrid) | T2 + T3-SPEC | ~15% | ADVISORY (post-launch) |

---

## 3. Data Contracts

### 3.1 Принцип: два слоя данных

```
Layer 1: Build-time data (статические конфиги, версии)
└── src/data/*.json — импортируются в Astro на build time
    ├── strategy_config.json    — конфиг трёх стратегий
    ├── protocol_metadata.json  — статические описания протоколов
    └── faq_content.json        — FAQ для страниц стратегий

Layer 2: Runtime data (live данные, меняются ежедневно)
└── public/data/*.json — публично доступны по URL, fetched client-side
    ├── site_metrics.json       — агрегированные метрики для landing и dashboard
    ├── golive_status.json      → symlink/copy из SPA_Claude/data/golive_status.json
    ├── equity_curve_daily.json → symlink/copy из SPA_Claude/data/equity_curve_daily.json
    ├── trades.json             → symlink/copy из SPA_Claude/data/trades.json
    ├── current_positions.json  → symlink/copy из SPA_Claude/data/current_positions.json
    ├── tournament_ranking.json → symlink/copy из SPA_Claude/data/tournament_ranking.json
    └── risk_limits_check.json → symlink/copy из SPA_Claude/data/risk_limits_check.json
```

**Важно:** Runtime данные в `public/data/` обновляются через auto_push (каждые 90 мин) — Cloudflare Pages перестраивает сайт при новом коммите в main.

### 3.2 strategy_config.json (build-time)

```json
{
  "version": "1.0",
  "updated_at": "2026-06-19",
  "strategies": {
    "preserve": {
      "id": "preserve",
      "name": "Preserve",
      "tagline": "Capital-first yield on Tier 1 protocols",
      "target_apy_pct": 6.0,
      "apy_range": [4.5, 7.5],
      "risk_level": "conservative",
      "status": "paper_tracking",
      "go_live_date": "2026-08-01",
      "min_deposit_usd": 25000,
      "allowed_tiers": ["T1"],
      "protocols": ["aave_v3", "compound_v3", "morpho_steakhouse", "spark_susds"],
      "rebalance_threshold_pct": 5.0,
      "max_single_protocol_pct": 40.0,
      "cash_buffer_pct": 5.0,
      "internal_strategies": ["S0", "S4"],
      "apy_floor_pct": 1.0,
      "apy_ceiling_pct": 12.0,
      "tvl_floor_usd": 5000000,
      "color": "#185FA5",
      "icon": "shield"
    },
    "core": {
      "id": "core",
      "name": "Core",
      "tagline": "Optimized yield across Tier 1 + Tier 2 protocols",
      "target_apy_pct": 10.0,
      "apy_range": [7.0, 13.0],
      "risk_level": "moderate",
      "status": "paper_tracking",
      "go_live_date": "2026-08-01",
      "min_deposit_usd": 25000,
      "allowed_tiers": ["T1", "T2"],
      "protocols": [
        "aave_v3", "compound_v3", "morpho_steakhouse", "morpho_blue",
        "yearn_v3", "euler_v2", "maple", "spark_susds", "fluid_fusdc", "sfrax"
      ],
      "rebalance_threshold_pct": 5.0,
      "max_t1_single_pct": 40.0,
      "max_t2_single_pct": 20.0,
      "max_t2_total_pct": 50.0,
      "cash_buffer_pct": 5.0,
      "internal_strategies": ["S7", "S1", "S2", "S3"],
      "apy_floor_pct": 1.0,
      "apy_ceiling_pct": 30.0,
      "tvl_floor_usd": 5000000,
      "is_active_live_strategy": true,
      "color": "#3B6D11",
      "icon": "target"
    },
    "max-yield": {
      "id": "max-yield",
      "name": "Max Yield",
      "tagline": "Structured leverage and delta-neutral for higher APY",
      "target_apy_pct": 15.0,
      "apy_range": [12.0, 25.0],
      "risk_level": "aggressive",
      "status": "advisory_only",
      "go_live_date": null,
      "min_deposit_usd": 100000,
      "allowed_tiers": ["T1", "T2", "T3-SPEC"],
      "protocols": ["pendle_pt", "pendle_yt", "euler_v2", "morpho_blue"],
      "internal_strategies": ["S8", "S11", "S10"],
      "uses_leverage": true,
      "max_leverage_ratio": 2.5,
      "advisory_note": "ADR-021 — advisory-only until live track record ≥ 60 days",
      "color": "#BA7517",
      "icon": "flame"
    }
  }
}
```

### 3.3 site_metrics.json (runtime — генерируется скриптом)

Этот файл агрегирует данные из нескольких data/*.json в единый документ для сайта. Должен генерироваться ежедневно в конце cycle_runner и пушиться через auto_push.

```json
{
  "generated_at": "2026-06-19T06:00:05Z",
  "source": "cycle_runner_site_exporter",
  "is_demo": false,

  "paper_track": {
    "start_date": "2026-06-10",
    "honest_start_date": "2026-06-18",
    "days_running": 31,
    "honest_days": 1,
    "capital_usd": 100000,
    "current_equity": 100021.69,
    "total_return_pct": 0.0217,
    "apy_today_pct": 3.96,
    "max_drawdown_pct": 0.0,
    "positive_days": 1,
    "kill_switch_active": false,
    "market_regime": "STABLE"
  },

  "go_live": {
    "target_date": "2026-08-01",
    "criteria_passed": 20,        // актуально на 2026-06-19
    "criteria_total": 26,
    "is_ready": false,
    "consecutive_ready_days": 0,
    "blockers_count": 6,          // adapter_status keys, telegram, 30d track
    "days_until_30d_track": 29
  },

  "active_strategy": {
    "id": "core",
    "name": "Core",
    "current_apy_pct": 3.96,
    "target_apy_pct": 10.0,
    "positions_count": 5,
    "deployed_usd": 94999.99,
    "cash_buffer_pct": 5.0,
    "risk_policy_approved": true,
    "last_rebalance_ts": "2026-06-18T20:16:29Z"
  },

  "risk_gates": {
    "emergency_breakers_status": "CLEAR",
    "risk_policy_approved": true,
    "kill_switch_active": false,
    "last_block_ts": null,
    "blocks_last_7d": 0,
    "gap_detected": false
  },

  "protocols_live": {
    "count": 16,
    "tier1_count": 6,
    "tier2_count": 8,
    "tier3_count": 2,
    "suspended_count": 1
  },

  "tournament": {
    "strategies_count": 14,
    "leading_strategy": "S7",
    "leading_apy_pct": 10.115,
    "days_running": 1
  }
}
```

### 3.4 Существующие JSON-файлы в SPA_Claude/data/ → использование на сайте

| Файл | Страница сайта | Секция |
|---|---|---|
| `paper_trading_status.json` | /, /due-diligence, /dashboard | Track record, live metrics |
| `equity_curve_daily.json` | /due-diligence, /dashboard | Equity curve chart |
| `trades.json` | /due-diligence, /dashboard | Trade log |
| `current_positions.json` | /dashboard | Allocation pie |
| `golive_status.json` | /, /due-diligence | GoLiveChecker panel |
| `tournament_ranking.json` | /dashboard | Tournament tab |
| `risk_limits_check.json` | /risk, /dashboard | Risk gates DL-01..DL-05 snapshot |
| `analytics_signals_blocking.json` | /risk, /dashboard | Blocking analytics signals |
| `gap_monitor.json` | /due-diligence | Track continuity indicator |
| `adapter_status.json` | /methodology, /dashboard | Protocol status table |
| `market_regime.json` | /dashboard | Market regime indicator |
| `strategy_summary.json` | /, /dashboard | Strategy selector |
| `emergency_status.json` | /dashboard | Emergency breakers panel |
| `chain_concentration.json` | /risk | Chain concentration chart |
| `daily_report_*.json` | /dashboard | Daily digest |

### 3.5 Новые JSON-файлы, которые нужно создать

| Файл | Кто генерирует | Когда | Назначение |
|---|---|---|---|
| `public/data/site_metrics.json` | `scripts/export_site_metrics.py` | Ежедневно после cycle_runner | Агрегированные метрики для landing |
| `src/data/strategy_config.json` | Вручную (редактируется при изменении стратегий) | По мере изменений | Конфиг стратегий (build-time) |
| `src/data/protocol_metadata.json` | Вручную | По мере изменений | Статические описания протоколов (auditors, founded, tvl_usd) |
| `src/data/faq_content.json` | Вручную | По мере изменений | FAQ для страниц стратегий |

---

## 4. Связь статических страниц с live data

### 4.1 Схема data flow

```
SPA_Claude/data/*.json                  (ежедневно обновляется cycle_runner)
        │
        │  auto_push.sh (каждые 90 мин)
        ▼
GitHub repo: /public/data/*.json        (commit в main)
        │
        │  Cloudflare Pages webhook
        ▼
Cloudflare Pages Build (Astro SSG)
        │
        ├── Build-time: import JSON → статические страницы
        │
        └── Deploy: /public/* → CDN edge
                        │
                        │  Client browser
                        ▼
              fetch('/data/site_metrics.json')  → live widgets (islands)
```

### 4.2 Правило: что статично, что динамично

| Контент | Тип | Обновление |
|---|---|---|
| Описание стратегий, секции "How It Works" | Статичный | При изменении стратегии (ручной commit) |
| APY targets, risk levels | Статичный | При изменении политики (ручной commit) |
| Текущая equity, APY today | Live (island) | Каждые 90 мин (auto_push) |
| GoLiveChecker status | Live (island) | Ежедневно после cycle_runner |
| Trade log | Live (island) | Ежедневно |
| Allocation chart | Live (island) | Ежедневно |
| Risk gates (блокировки) | Live (island) | Ежедневно |
| Tournament ranking | Live (island) | Ежедневно |

### 4.3 Реализация live islands

```typescript
// src/components/LiveMetrics.tsx (Preact/React island)
import { useEffect, useState } from 'preact/hooks';

export default function LiveMetrics() {
  const [metrics, setMetrics] = useState(null);
  
  useEffect(() => {
    fetch('/data/site_metrics.json')
      .then(r => r.json())
      .then(setMetrics)
      .catch(() => {}); // fail silently — static fallback visible
  }, []);

  if (!metrics) return <StaticFallback />;  // SSR fallback из пропов
  return <MetricsDisplay data={metrics} />;
}

// В .astro странице:
// <LiveMetrics client:load staticFallback={staticData} />
```

**Ключевое правило:** каждый live island должен получать `staticFallback` данные через props (из build-time import JSON). Если `fetch` упадёт — пользователь увидит последние данные на момент деплоя, не пустой экран.

---

## 5. Страницы детально: структура контента

### 5.1 / (главная)

**Секции (порядок сверху вниз):**
1. **Hero** — главный message + три стратегии (selector) + CTA "Explore Strategies"
2. **Paper Track Record** (live island) — equity $100K+, дней трека, APY today, GoLive progress bar
3. **How It Works** — 4 шага: Daily Scan → Risk Gate → Rebalance → Yield Accrual
4. **Trust Signals** — 5 блоков: Deterministic Policy / No LLM in Execution / Kill Switch / Multisig / Audit Trail
5. **Risk Gates Snapshot** (live island) — последние 3 решения Risk Policy (APPROVED/BLOCKED + причина)
6. **Strategy Preview** — три карточки StrategyCard с кнопками "Learn More"
7. **Fees Preview** — кратко (Management 0% paper period / Performance TBD)
8. **Due Diligence CTA** — ссылки на /due-diligence, /methodology, /risk
9. **Risk Warning** — обязательный дисклеймер (regulatory)

### 5.2 /strategies/* (template 15 секций)

Для каждой стратегии (Preserve / Core / Max Yield):

1. **Hero** — название, tagline, status badge (PAPER TRACKING / ADVISORY)
2. **Target APY** — target range + caveat (paper period, no guarantees)
3. **Risk Level** — RiskBadge + 2-3 предложения
4. **Current Status** — StatusBadge + live данные (equity, days, GoLive)
5. **Who It's For** — профиль инвестора (capital range, time horizon, risk tolerance)
6. **What's Inside** — протоколы по тирам (ProtocolTable)
7. **Yield Sources** — как именно генерируется APY (lending rates, PT/YT, базовые yield)
8. **What It Does NOT Do** — важный раздел: нет leverage (для Preserve), нет unaudited protocols, нет позиций при BLOCKED gate
9. **Risk Controls** — специфичные gates для стратегии (T1 cap 40%, TVL floor $5M, kill switch drawdown 5%)
10. **Performance / Validation** — EquityCurveChart (island) + ссылка на /due-diligence
11. **Strategy-Specific Risks** — 3-5 рисков специфичных для этой стратегии
12. **Emergency Behavior** — что происходит при kill switch / gap / emergency breaker
13. **Fees** — fee structure для этой стратегии
14. **FAQ** — FAQAccordion (5-7 вопросов)
15. **CTA** — Due Diligence / Contact / Waitlist

### 5.3 /methodology

Секции:
1. **Overview** — три слоя: Read-Only Adapters → Risk Gate → Paper Execution
2. **Daily Scan** — как работает DeFiLlama feed, Protocol Direct Feed (ADR-028), 16 адаптеров
3. **Risk-Gated Rebalancing** — RiskPolicy v1.0 детерминированный (не LLM), все параметры
4. **Tournament** — S0-S13, metrics: Sharpe/Calmar/Ulcer/Rachev, как выбирается аллокация
5. **Oracle Hierarchy** — ADR-028: Protocol Direct → DeFiLlama → Static
6. **No LLM in Execution** — объяснение почему LLM_FORBIDDEN_AGENTS (prompt injection риск)
7. **Emergency Breakers** — EB-01..EB-05 (ADR-030): ExploitProbe / OracleCascade / GasCrisis / FlashCrash / DataCorruption
8. **Atomic Writes** — как гарантируется integrity data (tmp + os.replace)

### 5.4 /risk

Секции:
1. **Risk Philosophy** — deterministic policy vs discretionary, transparencia
2. **Strategy Risk Matrix** — таблица: стратегия × риск-факторы (liquidation / peg / oracle / smart contract)
3. **Concrete Gates** — таблица всех limit параметров из RiskPolicy v1.0
4. **Stress Scenarios** — 5 сценариев: Protocol exploit / Stablecoin depeg / Oracle failure / Gas crisis / Market crash
5. **What Gets Blocked** — примеры из реальных risk_policy_blocks (анонимизированные даты)
6. **Kill Switch Mechanics** — drawdown ≥ 5% → close all, ссылка на /emergency-withdrawal
7. **Audit Trail** — как логируются решения (audit_trail.jsonl)

### 5.5 /trust

Секции:
1. **Custody Model** — paper period: виртуальный капитал; live: Gnosis Safe 2/3 multisig (ADR-024)
2. **Admin Roles** — Owner / Operator / Viewer матрица доступов
3. **Multisig** — ADR-024: Gnosis Safe 2/3, адреса (после finalize)
4. **Kill Switch** — механизм, кто может активировать, время исполнения
5. **Incident Response** — DR_PROCEDURE_v2.md summary: levels, response times
6. **Logs** — что логируется (trades.json, risk_limits_check.json, audit_trail.jsonl), retention
7. **Upgrade Policy** — RiskPolicy изменение → ADR + snapshot + changelog

### 5.6 /due-diligence

Proof layer — самая важная страница для allocators.

Секции:
1. **Paper Trading Status** (live island) — GoLiveChecker 20/26 pass, checklist
2. **Track Record** (live island) — equity curve chart, days running, total return
3. **Trade Log** (live island) — последние 10 трейдов с деталями
4. **Risk Blocks Log** (live island) — последние блокировки (если есть)
5. **Gap Monitor** (live island) — track continuity status
6. **GoLiveChecker 26 Criteria** — полный checklist с pass/fail
7. **Links** — прямые ссылки на raw JSON файлы (GitHub raw или Cloudflare Pages URL)
8. **ADR Index** — список всех принятых ADR с датами

### 5.7 /dashboard

Multi-panel live dashboard. Вкладки:

| Вкладка | Данные | Компоненты |
|---|---|---|
| **Overview** | site_metrics.json | MetricsPanel, GoLiveProgress, DailyStatusBanner |
| **Core** | paper_trading_status + equity_curve | EquityCurveChart, AllocationPie, TradesLog |
| **Preserve** | strategy mock (paper) | StrategyMetricsPanel |
| **Max Yield** | strategy mock (advisory) | AdvisoryPanel |
| **Allocations** | current_positions.json | AllocationPie, ProtocolTable |
| **Trades** | trades.json | TradesLog full |
| **Risk Blocks** | risk_limits_check.json | RiskGatesSnapshot full |
| **GoLiveChecker** | golive_status.json | GoLiveCheckerPanel full |
| **Tournament** | tournament_ranking.json | TournamentTable |
| **Protocol Status** | adapter_status.json | ProtocolTable detailed |
| **Changelog** | manual (build-time) | ChangelogList |

---

## 6. Технические риски и рекомендации

### 6.1 Не сломать текущий earn-defi.com

**Стратегия: feature branch + preview URL до слияния**

```
Workflow:
main branch → earn-defi.com (текущий сайт — не трогать)
feature/v2-redesign → earn-v2.earn-defi.com (Cloudflare Pages preview)
                              │
                    Тестирование, QA, stakeholder review
                              │
                    Merge → earn-defi.com (cutover за 1 коммит)
```

**Конкретные шаги:**
1. Создать ветку `feature/site-v2` от текущего main
2. В Cloudflare Pages настроить preview deployment для этой ветки
3. Разрабатывать полностью в ветке
4. Merge в main только когда MVP полностью готов (≈ за 1-2 недели до Aug 1)

### 6.2 Деплой: рекомендация

**Рекомендую:** один репо, feature branch, Cloudflare Pages preview.  
**Не рекомендую:** отдельный проект/домен — сложнее управлять DNS и Cloudflare конфигами.

Cloudflare Pages нативно поддерживает preview deployments для каждого PR/branch. Preview URL вида `feature-site-v2.earn-defi-com.pages.dev` — идеально для review.

### 6.3 CLS / Performance для Astro SSG

**Проблемы и решения:**

| Проблема | Риск | Решение |
|---|---|---|
| Live islands без skeleton | Высокий CLS при загрузке JSON | Использовать staticFallback props + CSS min-height на island-контейнерах |
| Chart.js без данных | Пустой канвас при медленном fetch | Показывать skeleton loader, Chart.js только после данных |
| Fonts FOUT | Сдвиг текста при загрузке Inter | `font-display: swap` + preconnect в `<head>` (уже есть в index.html) |
| JSON fetch latency | Медленный first contentful paint для live данных | Cloudflare edge caching для /data/*.json с Cache-Control: max-age=90 |
| Большой bundle dashboard | /dashboard может быть heavy | Lazy import компонентов, `client:visible` вместо `client:load` для ниже-fold |

**Принцип:** любой island компонент получает `staticFallback` из build-time данных. CLS = 0 при медленном fetch.

```astro
---
// При build: import последних данных из public/data/ 
const staticMetrics = await fetch('...').then(r => r.json())
  .catch(() => DEFAULT_METRICS);
---
<LiveMetrics client:load staticFallback={staticMetrics} />
```

### 6.4 public/data/ pipeline риски

**Риск:** auto_push упадёт → данные на сайте устареют.  
**Митигация:** 
- `generated_at` в каждом JSON → показывать "Data as of: X hours ago" в UI
- Если `generated_at` > 48h — показывать `KillSwitchAlert` вместо live данных
- Dashboard показывать freshness indicator

**Риск:** Cloudflare Pages build fail при merge в main.  
**Митигация:** Проверить что `public/data/*.json` валидны перед push. Добавить `scripts/validate_site_json.py`.

### 6.5 SEO и метаданные

Для аудитории (family offices) SEO не критичен, но:
- Каждая страница должна иметь уникальный `<title>` и `<meta description>`
- `robots.txt` — закрыть `/dashboard` от индексации (live данные, не нужно)
- Open Graph теги для /due-diligence (поделиться со-инвесторам)
- Не индексировать параметры APY — они меняются, хотим canonical content

### 6.6 Regulatory / Legal риски

- Risk Warning обязателен на главной и каждой странице стратегии
- Не писать "guaranteed returns" — только "target APY (paper period)"
- `status: "paper_tracking"` должен быть виден без клика — не скрывать за fold
- `/risk-disclosure` ссылка в footer и в CTA на всех страницах стратегий

---

## 7. Порядок реализации к Aug 1, 2026

### 7.1 Временна́я шкала

```
СЕЙЧАС → Jun 30     [1.5 недели] — Foundation Sprint
Jul 1  → Jul 14     [2 недели]   — Content Sprint
Jul 15 → Jul 25     [1.5 недели] — Polish + Data Pipeline
Jul 25 → Aug 1      [1 неделя]   — QA + Cutover
```

### 7.2 Foundation Sprint (до Jun 30)

**Цель:** инфраструктура, компоненты-атомы, data pipeline.

**День 1-2: Setup**
- [ ] Создать ветку `feature/site-v2`
- [ ] Настроить Cloudflare Pages preview для ветки
- [ ] Структура папок: `src/components/`, `src/layouts/`, `src/data/`, `public/data/`
- [ ] BaseLayout.astro + SiteHeader + SiteFooter
- [ ] CSS design tokens (цвета, типографика — из текущего index.html)

**День 3-4: Data Pipeline**
- [ ] Написать `scripts/export_site_metrics.py` → `public/data/site_metrics.json`
- [ ] Настроить symlink/copy из `SPA_Claude/data/` → `public/data/` в auto_push.sh
- [ ] Написать `scripts/validate_site_json.py` — валидация перед push
- [ ] Интегрировать export_site_metrics.py в конец cycle_runner (или отдельный launchd)
- [ ] Создать `src/data/strategy_config.json`

**День 5-7: Атомарные компоненты**
- [ ] StatusBadge, RiskBadge, APYDisplay, TierBadge
- [ ] MetricCard, StrategyCard
- [ ] GoLiveProgress, TrackRecord
- [ ] LiveMetrics island (с staticFallback pattern)
- [ ] EquityCurveChart island (Chart.js)

### 7.3 Content Sprint (Jul 1-14)

**Цель:** все MVP страницы с контентом.

**Неделя 1 (Jul 1-7): Core pages**
- [ ] `/` — главная (все 9 секций)
- [ ] `/strategies` — обзор
- [ ] `/strategies/preserve` — полный 15-секционный template
- [ ] `/strategies/core` — полный 15-секционный template

**Неделя 2 (Jul 7-14): Trust + Proof pages**
- [ ] `/methodology` — 8 секций
- [ ] `/risk` — 7 секций
- [ ] `/trust` — 7 секций
- [ ] `/due-diligence` — 8 секций (наибольшая работа по live islands)
- [ ] `/risk-disclosure` — обновить существующую

### 7.4 Polish + Data Pipeline (Jul 15-25)

**Цель:** живые данные работают, dashboard функционирует, производительность ОК.

- [ ] `/dashboard` — все вкладки с live данными
- [ ] Проверить все live islands с реальными JSON данными
- [ ] CLS аудит (Lighthouse) — исправить skeleton/fallback где нужно
- [ ] Mobile responsiveness — все MVP страницы
- [ ] `src/data/protocol_metadata.json` — написать описания 16 протоколов
- [ ] `src/data/faq_content.json` — написать FAQ для Preserve + Core
- [ ] SEO: title/description для всех страниц
- [ ] robots.txt, sitemap.xml

### 7.5 QA + Cutover (Jul 25-Aug 1)

- [ ] Full review с аллокатором (если есть) или внутренний review
- [ ] Проверить все ссылки (dead links check)
- [ ] Проверить live data freshness на preview URL
- [ ] Performance: Lighthouse ≥ 90 на всех MVP страницах
- [ ] Merge `feature/site-v2` → main → автодеплой на earn-defi.com
- [ ] Verify: earn-defi.com загружается корректно после cutover
- [ ] Анонс go-live через Telegram Family Fund blast

---

## 8. Scripts, которые нужно написать

| Скрипт | Путь | Когда запускается | Что делает |
|---|---|---|---|
| `export_site_metrics.py` | `scripts/export_site_metrics.py` | После cycle_runner (ежедневно) | Агрегирует данные из data/*.json → `public/data/site_metrics.json` |
| `sync_public_data.py` | `scripts/sync_public_data.py` | auto_push.sh (каждые 90 мин) | Копирует нужные data/*.json → `public/data/` |
| `validate_site_json.py` | `scripts/validate_site_json.py` | Перед push | Проверяет что public/data/*.json валидны и не устарели >48h |

### export_site_metrics.py — минимальная спецификация

```python
# Читает из:
#   data/paper_trading_status.json
#   data/golive_status.json
#   data/gap_monitor.json
#   data/emergency_status.json
#   data/tournament_ranking.json
#   data/risk_limits_check.json
# Пишет в: public/data/site_metrics.json (атомарно)
# Только stdlib, exit 0 всегда, read-only домен
```

### sync_public_data.py — файлы для синхронизации

```python
FILES_TO_SYNC = [
    "golive_status.json",
    "equity_curve_daily.json",
    "trades.json",
    "current_positions.json",
    "tournament_ranking.json",
    "risk_limits_check.json",
    "gap_monitor.json",
    "paper_trading_status.json",
    "adapter_status.json",
    "market_regime.json",
    "emergency_status.json",
    "site_metrics.json",  # генерируется export_site_metrics.py
]
# src: SPA_Claude/data/{file}
# dst: SPA_Claude/earn-defi-site/public/data/{file}
# атомарно (tmp + os.replace)
```

---

## 9. Технический стек для Astro проекта

```
earn-defi-site/
├── astro.config.mjs
├── package.json
├── tsconfig.json
├── public/
│   ├── data/          ← live JSON (sync из SPA_Claude/data/)
│   ├── fonts/
│   └── favicon.ico
└── src/
    ├── components/    ← атомарные + составные
    │   ├── atoms/
    │   ├── composed/
    │   └── islands/   ← client:* компоненты (React/Preact)
    ├── data/           ← build-time JSON
    ├── layouts/
    ├── pages/
    └── styles/
        └── tokens.css  ← design tokens (из index.html)
```

**Зависимости:**
```json
{
  "@astrojs/preact": "^3.x",  ← для islands
  "preact": "^10.x",
  "chart.js": "^4.4.x",       ← equity curve (уже используется в index.html)
  "@astrojs/sitemap": "^3.x"  ← автогенерация sitemap
}
```

**Нет внешних CSS фреймворков** — токены из текущего index.html, custom CSS. Меньше зависимостей → меньше build time, меньше bundle.

---

## 10. Определения успеха MVP

К 2026-08-01 сайт должен позволять аллокатору:

1. **За 5 минут** понять три стратегии, их риски и текущий статус
2. **За 10 минут** прочитать методологию и убедиться что нет LLM в исполнении
3. **За 15 минут** пройти /due-diligence и увидеть живые данные (equity, trades, GoLiveChecker)
4. **В любой момент** проверить dashboard и увидеть актуальный статус (данные не старше 90 мин)

**Acceptance criteria:**
- [ ] Все MVP страницы загружаются без ошибок
- [ ] Live islands показывают данные не старше 90 мин или статичный fallback
- [ ] GoLiveChecker panel отображает актуальный статус (connected to golive_status.json)
- [ ] Equity curve chart работает с реальными данными из equity_curve_daily.json
- [ ] Risk Warning виден без скролла на главной и страницах стратегий
- [ ] Lighthouse Performance ≥ 90, CLS < 0.1 на всех MVP страницах
- [ ] `is_demo: false` верифицировано на /due-diligence (из paper_trading_status.json)

---

*Документ: ARCHITECTURE_SITE_V2.md | Версия: 1.0 | 2026-06-19*  
*Следующий шаг: создать `feature/site-v2` ветку и начать Foundation Sprint*
